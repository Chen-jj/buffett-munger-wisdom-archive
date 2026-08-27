# AI 工作流重构规划（脑暴稿）

> 范围：`爬取 → 下载 → ASR 对齐 → LLM 翻译 → 字幕烧录 → 人工评审` 这条 AI 密集管线的重构规划。
> 现状基线：`legacy-src/run.py` + `step0~4` + `tools_project_cli.py`（约 2600 行）为在跑实现；
> `src/` 下 13 个模块脚手架已就位，`archive_core` / `acquisition` / `media_download` 已完成分层迁移并有离线测试。

---

## 1. 现状诊断：Legacy AI 工作流的痛点

| # | 痛点 | 证据（legacy 代码） | 后果 |
|---|------|--------------------|------|
| P1 | **顺序单进程、以"年份"为粒度**，失败后只能靠 `--step N` 手工重试 | `run.py` 的 `STEPS` 字典顺序循环 | 长任务（数小时 ASR/翻译）中断后恢复粒度粗，容易整段重跑 |
| P2 | **用"文件存在"判断完成** | `step3` 的 `chinese.srt.exists()` 跳过；`step4` 的渲染产物跳过 | 半成品/损坏文件被误判为完成，违反 AGENTS 的 manifest 驱动约束 |
| P3 | **翻译不可断点续翻、失败静默降级** | `step3_translate.translate_srt`：批失败时把英文原文当 fallback 写进 `chinese.srt` | 昂贵产物被污染且无标记；长会议翻到一半失败全部重来 |
| P4 | **无 provenance**：不知道某个 SRT 是哪个 model/prompt/参数产出 | prompt 硬编码在 `step3`；`step2` 的模型参数只在 config.yaml | 无法回答"这版字幕怎么来的"，无法做失效传播与复现 |
| P5 | **API key 明文入库** | `config.yaml` 的 `translation.openai.api_key` | 安全风险 |
| P6 | **质量门禁缺失** | 无 cue 数一致性校验、时间轴单调性校验、术语强制、翻译抽检 | 坏字幕直接流入烧录（烧录是最贵的下游步骤） |
| P7 | **昂贵计算无缓存** | ASR、翻译重跑即重花钱/花时间 | 调整 prompt 或参数后无法只重算受影响部分 |
| P8 | **CLI 巨石** | `tools_project_cli.py` 1335 行，混杂 listing/翻译辅助/剪辑/烧录/review 服务/catalog/favorites | 无法测试、无法复用 |
| P9 | **无结构化日志与指标** | 全程 print + emoji | 无法事后分析各 stage 耗时、成本、失败率 |
| P10 | **网页 transcript 资产被浪费** | `timing_source: asr` 直接用 ASR 文本 | CNBC 官方逐字稿语义更准（人名/术语），目前只做归档不参与字幕 |

---

## 2. 目标与原则：业界实践 → 本项目落法

不引入 Airflow/Prefect/数据库/后台 worker（AGENTS 红线），借鉴其**思想**而非**设施**：

| 业界实践 | 本项目落法 |
|----------|-----------|
| Build system 思维（Make/Bazel）：以产物为中心的 DAG、内容哈希增量 | `orchestration` 产出显式 `PipelinePlan`（stage DAG），每个 stage 声明输入/输出 ArtifactType；用 manifest+checksum 判断"新鲜"，而非文件存在 |
| Data/ML lineage（W3C PROV、MLflow run） | 扩展现有 `archive_core.manifest.v1`：每个 stage 运行写 `run` 记录（tool、version、params、输入哈希、输出哈希、耗时、token/成本） |
| 幂等 + 原子写 | 一律写 `*.tmp` 后 rename；canonical 文件只在 stage 校验通过后落地；状态机 `pending → running → done/failed(+verified)` |
| LLM 工程：prompt 版本化、结构化输出、校验重试、批级缓存 | prompt 作为带版本号的资源文件；翻译返回按编号对齐并校验 cue 数；`(model, prompt_version, input_hash)` 为缓存键的批级 checkpoint |
| HITL（human-in-the-loop） | `review` 模块产出评审报告 + `webui` 本地评审页，评审通过才允许"发布"级烧录 |
| Strangler 模式迁移 | legacy 与新 CLI 并存；每迁一个 stage 做 golden 对比（同输入下新旧产物 diff 为空或差异可解释） |
| 可观测性 | 结构化 JSONL 事件日志 + 每个 session 一份 `pipeline_report.json`（人读摘要 + 机读明细） |
| 配置分层 | `默认值 → config.yaml → 环境变量（密钥）→ CLI 覆盖`；密钥只走 env（`ARCHIVE_OPENAI_API_KEY`） |

---

## 3. 目标架构总览

```
                    ┌─────────────────────────────────────────────┐
                    │                cli (thin)                    │
                    │  archive run / plan / status / review / ...  │
                    └──────────────────────┬──────────────────────┘
                                           │ 调用 application services
                    ┌──────────────────────▼──────────────────────┐
                    │             orchestration                    │
                    │  plan(会话×stage DAG) → verify → execute     │
                    │  → record(run manifest) → report             │
                    │  恢复策略 / 失效传播 / 覆盖策略               │
                    └───┬─────────┬─────────┬─────────┬────────────┘
                        │         │         │         │
        acquisition  media_download transcription translation  subtitle_rendering ...
        （已迁移）    （已迁移）    │ ASR/对齐 │ LLM 翻译   │ ASS/ffmpeg
                                    │          │            │
                                    └────┬─────┴─────┬──────┘
                                         ▼           ▼
                              archive_core（ArtifactType/AssetId/
                              manifest.v1/provenance/路径契约）
                                         │
                              infrastructure（config/process/http/tools）
```

### 3.1 管线数据流（每 session 工作区 `output/<year>/<session>/`）

```
source_meta ──► source_video ──► source_audio ──► alignment(word timings json)
                                                    │
                             web transcript ────────┤（可选融合）
                                                    ▼
                                              english_srt ──► chinese_srt ──► rendered_video
                                                    │                │
                                             (QA: 单调性/覆盖)   (QA: cue 一致/术语)
```

每个产物 = `ArtifactType` + canonical 文件名 + `manifest.json` 里的 ref + checksum + provenance。

### 3.2 Stage 状态推导规则（替代 P2 的文件存在性检查）

```
stage 状态 = f(输入产物状态, 本 stage run manifest)
- inputs missing/failed        → blocked
- run done + outputs verified  → done（跳过）
- run 参数/输入哈希变化          → stale（需重跑，且下游级联 stale）
- 无 run 记录                  → pending
```

---

## 4. 核心机制设计

### 4.1 Pipeline Plan（orchestration/domain）
- `StageId`、`StageSpec(stage, requires: [ArtifactType], produces: [ArtifactType], service 引用)`。
- 计划可序列化为 JSON，`archive plan --year 1994 --only translate --dry-run` 先看后跑。
- 短期固定拓扑（上面数据流），DAG 结构留扩展位但不做通用图引擎。

### 4.2 Run Manifest（archive_core 扩展）
```jsonc
// output/1994/cnbc_1994_morning/manifest.json（节选）
{
  "schema": "archive-core.manifest.v1",
  "artifacts": {
    "chinese_srt": {
      "path": "chinese.srt", "checksum": {"algorithm": "sha256", "value": "..."},
      "state": "verified",
      "run": {
        "stage": "translate",
        "tool": "openai-chat", "tool_version": "gpt-4o",
        "prompt_version": "zh-v2",
        "parameters": {"temperature": 0.1, "batch_size": 15},
        "input_hashes": {"english_srt": "sha256:..."},
        "metrics": {"prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0,
                     "batches_total": 40, "batches_cached": 12, "duration_s": 380}
      }
    }
  }
}
```

### 4.3 昂贵计算缓存（翻译批级 checkpoint + ASR）
- 翻译：`cache/translation/<sha256(model|prompt_version|batch_input)>/response.json`；命中即免调用。断点续翻 = 重放已缓存批次。
- ASR：持久化**词级时间戳 JSON**（而非只有 SRT），SRT 视为其投影；改分段/样式策略不重跑模型。
- 缓存与产物分离：缓存可随时删除，产物有 manifest。

### 4.4 QA 门禁（每个 stage 的 verify）
| Stage | 门禁 |
|-------|------|
| transcription | cue 序号连续、时间轴单调不重叠、覆盖率（静音间隙报告）、文本规范化 |
| translation | cue 数一致、时间轴逐条相等、说话人标记保留、术语表命中、行长（≤20 汉字）抽检 |
| rendering | ffprobe 校验输出时长≈源视频、字幕流存在、文件完整性 |
- 门禁失败 → `state=failed`，canonical 产物不落/标废，禁止 fallback 原文混入（修 P3）。

### 4.5 观测与成本
- JSONL 事件流：`stage_start/stage_done/batch_done/qa_failed/...`。
- 每 session 汇总 `pipeline_report.json`：各 stage 耗时、重试数、token/费用（翻译）、ASR 设备与实时率。
- 这是后续决定"用哪个模型/批大小"的数据依据。

---

## 5. AI 能力专项增强（脑暴区）

1. **Prompt 资源化**：`translation/prompts/zh-v2.md` + 术语表 `glossary.yaml`（人名/公司/口头禅），随 provenance 记录版本；diff prompt = 失效翻译缓存。
2. **翻译记忆（TM）**：跨年份复用完全相同 cue 的译文（开场白、常见段子公司介绍重复率极高），再省一截成本。
3. **LLM-as-judge 抽检**：翻译完成后按比例抽 N 条做"信达雅+术语"评分，低于阈值标记进 review 报告，不阻塞管线。
4. **网页 transcript × ASR 融合（可选后期）**：用 ASR 词级时间戳对官方 transcript 做 forced alignment 式映射，得到"官方文本 + 精确时间轴"的英文字幕，修复 P10。作为 transcription 的对齐策略之一，而非硬编码。
5. **说话人标注**：WhisperX 已有对齐能力，diarization 作为可选 provider，反哺翻译的说话人标记规则。
6. **成本预估 dry-run**：`archive plan` 顺带估算 token 与时长（按历史 metrics），跑前知道要花多少钱、多久。

---

## 6. 分阶段路线图（每阶段可独立验证、legacy 不中断）

### Phase 0 — 地基（infrastructure / archive_core）
- config 分层加载 + env 密钥覆盖；结构化日志；原子写工具；`tools.py` 外部工具发现（ffmpeg/ffprobe/yt-dlp）。
- 验收：单测覆盖；`ARCHIVE_OPENAI_API_KEY` 生效；无密钥泄漏进 git。

### Phase 1 — transcription 迁移
- `domain`: AsrSegment/WordTiming/TimingPolicy；`application`: extract-audio/transcribe/emit-english-srt/verify；`infrastructure`: ffmpeg adapter、faster-whisper/whisperx adapter（可 mock）。
- 持久化词级 JSON；修 P3 同源的"半成品 SRT"问题。
- 验收：与 legacy `step2` 同输入 golden 对比；QA 单调性测试；离线 mock 测试。

### Phase 2 — srt_processing 迁移
- 把散落在 step2/step3/tools_cli 的解析、规范化、分段、双语合并收拢为纯函数库。
- 验收：纯函数 100% 可离线测试；legacy 产物 round-trip 一致。

### Phase 3 — translation 迁移（收益最大）
- prompt 版本化 + 术语表；批级 checkpoint 缓存与断点续翻；cue 一致性校验；失败不写 fallback；token/成本 metrics。
- 验收：中途 kill 进程后重跑只补缺失批次；坏响应被拒绝并重试；metrics 进 run manifest。

### Phase 4 — subtitle_rendering 迁移
- ASS 转换、ffmpeg 命令计划化（可 dry-run 打印命令）、渲染后 ffprobe 验证、字体解析。
- 验收：命令计划单测；渲染产物验证；重复渲染被 stale 检测拦截。

### Phase 5 — orchestration + cli 合流（legacy 退役点）
- `archive run/plan/status/resume/report` 命令族；stage 状态推导 + 失效传播；拆解 `tools_project_cli.py` 到各模块 interfaces。
- 验收：`run.py --year X` 全流程可在新 CLI 复现并产出等价 manifest 化产物；`--step` 语义被 `resume` 取代。

### Phase 6 — review + webui
- catalog 契约（承袭 legacy-weapp）、评审报告（含 judge 抽检结果）、favorites、清理建议 dry-run。
- 验收：本地评审页可用；报告能定位到具体 cue。

---

## 7. 开放问题（需要拍板）

1. **并行度**：session 级并行（同一年 morning/afternoon）几乎无风险，是否 Phase 5 就开？年份级并行受 crawl 礼貌间隔与 API 限流约束，建议后置。
2. **翻译 provider**：主力 OpenAI 兼容 + 本地 Ollama 备选，缓存键已含 model，切换无损。是否需要多 provider A/B？
3. **ASR 硬件路径**：macOS CPU（int8）目前可用但慢；是否预留 remote worker adapter（只在 infrastructure 层）？
4. **web transcript 融合**（§5.4）做不做、何时做。
5. **旧产物回收**：存量 `output/` 如何补登 manifest（一次性 backfill 工具 vs 只管新产物）。

---

## 8. 与 AGENTS 约束的符合性自查

- 无云持久化/数据库/后台 worker：✅ 全本地文件 + manifest。
- provider 逻辑只在 infrastructure：✅ 各 stage adapter 隔离，domain/application 纯净。
- 不静默覆盖昂贵产物：✅ 状态机 + stale 检测 + 显式 overwrite 策略。
- 字幕非权威 until 验证：✅ QA 门禁是 stage 完成的一部分。
- 迁移粒度小、可验证：✅ 每 Phase 有 golden 对比或离线测试。
