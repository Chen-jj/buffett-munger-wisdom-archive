# AGENTS.md

巴菲特与芒格智慧档案的离线媒体资产管线：抓取元数据 → 下载视频 → ASR 转写 → 翻译 → 双语字幕 → 烧录渲染 → 人工评审。完全本地运行。这是一条可复现的长视频处理管线，不是视频平台、CMS 或云服务。

## 当前状态（先读这里）

仓库正处于迁移中期。动手前先核实现实，不要假设某个模块能用。

> 状态最后核对：2026-10-24 21:02 CST。**每次完成编码任务后，若实现状态或本文件中的事实发生变化，必须在同一次提交中更新本节（含核对时间）。**

> 文档已整理：[导航](docs/README.md)。ADR-0001..0005、TA/SP历史任务和已验收SR-01..06
> 已归档；TA-10仍为superseded而非通过。归档不撤销未被替代的公共契约，也不把候选质量写成定版。
> ADR-0006、SR-00及SR-07仍进行中。SR-01..06已accepted，渲染公共契约、纯布局、字体/ASS/
> 像素/媒体适配器、工作流与独立对抗测试均已实现。完整离线最近验收为2580 passed / 6 skipped。
> 同源623秒/163-cue双语样片已持久交付，succeeded→reused→reused、逐cue像素、媒体QA与零写/
> 上游不变通过；负责人另独立复用和20帧审图，**不是完整听音或人类质量签字**。
> 用户实际播放发现中文与英语讲话的语义不同步，故SR-07最终验收未通过，ADR-0006不归档为完成。
> 用户进一步确认其观察中音轨/英文单词时间准确，当前重点是中文优先切分+比例分配的语义错位；
> 保留transcription与全部旧资产，先探索新方案，不重跑ASR、不直接调DP权重或改时间掩盖问题。
> [复审证据](docs/reviews/2026-10-24-rendering-technical-and-semantic-review.md)与
> [新agent探索prompt](docs/prompts/bilingual-semantic-alignment-exploration.md)记录当前事实和边界。
> 用户批准的ASS百分秒投影、U+2060可逆显示控制及发布顺序修订仍以ADR-0006为准。
> 本次整理后复验：2580 passed / 6 skipped，84份Markdown本地链接0断链；未新增语义修复算法。
> 后续顺序仍为rendering→orchestration→CLI→Web UI；不能把技术样片交付写成语义或出版质量通过。

> 用户另要求简化阅读稿，已新增[全97句v3/agent两方对照](output/cue-evaluation/20261023-candidate-v3/two_way_v1/all_97_sentences.md)。
> 仅投影已冻结正文/时间并标明跨句共用关系，不重切或新增质量评价；负责人独立重算MD/JSONL字节一致。
> 两方展示回归9项，当时完整离线 **1404 passed / 5 deselected**；以下1395为此前v3实施验收时点结果。

> 2026-10-23补记：当前默认已是候选v3，SP-13/14已通过负责人技术验收，完整离线
> **1395 passed / 5 deselected**。中文只在停顿标点/句末切；16单位/7秒/9CPS均软目标，
> 不另设10秒硬上限；英文实际2×42及覆盖/时间/溯源门禁保留。独立CNBC生成163 cues，
> 负责人再次`reused → reused`，六输出bytes/mtime不变、复用0写；原正式33、SP-09 139、
> v2 111及只读偏好测量15文件未变，没有重跑ASR/translation/provider。
> 中文非停顿cut0、短cue0；中文长度/7秒/CPS告警81/9/18，不能把软目标告警当硬错误。
> S17节奏/中英错位、S22未保留已认可切法及S48/S74/S88等残余仍在；SP-15全97句/33偏好
> 对照已交付并由负责人独立复算、审读验收。中文偏好23满足/4允许变体/5部分/1未满足，
> 双语节奏总体18/2/12/1；**不建议质量定版**，非音画/像素/出版签字通过。
> [本轮报告](docs/reviews/2026-10-23-cue-candidate-v3.md)包含逐句入口、失败与成本原因。
> 下文v1/v2数字是历史结果，旧资产不覆盖。

| 状态 | 模块 |
|---|---|
| 已实现 + 离线测试 | `archive_core`、`acquisition`、`media_download`、`infrastructure` |
| 已实现 + 离线测试 + CNBC 真实集成测试 | `transcription` |
| 已实现 + 离线测试；Codex CLI 真实集成在本次 prompt 修正前已通过 | `translation` |
| 已实现 + 离线跨层验收 + CNBC 真实技术集成（非出版级质量背书） | `srt_processing` |
| 技术实现/真实样片已交付；用户发现双语语义同步问题，最终验收未通过 | `subtitle_rendering` |
| 仅脚手架（分层目录 + AGENTS.md，无代码） | `cli`、`orchestration`、`webui` |

- 遗留管线（`run.py` step0–4 + Web 评审应用）已在提交 `cc9df50` 中删除。目前**没有 CLI 入口，管线无法端到端运行**。ADR-0001 与其实现任务已完成并归档到 `docs/archive/`。
- 文档入口为`docs/README.md`；进行中ADR在`docs/decisions/`，已实现ADR/任务在`docs/archive/`。
  归档不自动使决策失效，但历史任务不再作为现行路线图；此前两份路线图已由用户删除，不得恢复。
- 尚无 lint/typecheck/CI。离线 pytest 套件是唯一的验证门槛；另有少量 `live` 标记测试，包括
  acquisition→media_download 真实网络测试，以及 `RUN_TRANSCRIPTION_INTEGRATION=1` 门控的真实
  WhisperX 集成测试。本地 CNBC 2000 上午场连续第 6、7 节样本可从空 `output/` 自动准备，并在
  唯一的 integration workspace 跑通至含两个 section 的 `source_alignment.json`；第二次运行按
  manifest 复用全部 transcription 工件。translation 的 provider-neutral workflow、OpenAI
  Responses adapter、Codex CLI ChatGPT adapter 及显式 provider composition 已通过离线 fake/mock
  测试；仓库配置默认选择 `codex-cli-chatgpt`，保留 OpenAI 作为显式备选且绝不自动 fallback。
  TA-10 OpenAI live gate 已被 ADR-0005 取代且未运行；TA-16 已使用 ChatGPT 登录和
  `codex-cli 0.154.0` 完成真实双 section 翻译、人工质量检查及第二次零调用正式复用验收。
  当前 `translation.zh-hans.v1` prompt 已直接修正 `go— ahead` 被机械翻成“请——继续”的问题
  并加入 live fixture 回归门禁；修改后已通过离线测试，尚未重跑真实 gate，历史工件由 prompt
  SHA-256 与当前内容区分。
  transcription 不再提供 reference-based Golden Live 入口；未来全管线连通性由 orchestration
  集成测试负责。
- ADR-0003 的公共字幕契约、确定性双语 planner、双链输入门禁、本地适配器、三份 SRT 投影、
  manifest 驱动复用与 manifest-last 发布已实现，SP-01..08（含 SP-08A）已完成历史v1技术验收；当时完整离线套件为
  **1220 passed / 5 deselected**。历史缺译文阻断已由用户明确授权的 SP-08A 解决：现有 Codex
  CLI translation 流程完成97句/2 sections、2次生成调用，正式译文持久保留、第二次零调用；
  未重跑 ASR。CNBC 字幕真实入口生成242 cues并立即复用，独立新进程再次复用；六输出
  bytes/mtime 不变、0写入，19份上游文件未变。SRT 本身完全不调用 provider。
- 负责人/agent 已完成 CNBC 文本内容审读，但**不是人类签字、语义对齐或出版级字幕质量通过**，
  未观看音画或验证像素/烧录。c3/c4 人物地名错位、c183“风/险”语义提前、c142–147“认/为”
  及破折号/专名拆分等已知比例/应急限制保留，详见 [SP-08](docs/archive/tasks/SP-08-real-sample-and-final-status.md)。
  在当时v1代码环境中，保留规范工件后可独立运行字幕样本入口复用，无需 ASR/translation 或其他模块 live 测试；当前候选路径/冲突说明见下文。
  完整离线 pytest 仍是代码改动门槛。
- 用户于2026-10-22授权先修一版再审阅，该轮规则为**历史候选v2，不是最终质量定版**（当前v3见上文）：
  中文一逻辑行16单位、中文内Latin word计1；英文最多两行各42，真实按word排布而非仅总容量84。
  固定`jieba==0.42.1`随包词典/HMM=False，词典hash进入profile；新边界/D39/codec身份均版本化，
  旧v1 profile/codec仍可读但受控冲突，绝不静默复用或覆盖。完整离线已为**1329 passed / 5 deselected**。
- 候选隔离工作区`output/cue-evaluation/20261022-candidate-v2/workspaces/cnbc_2000_morning/`
  真实生成224 cues，194.410s；随后复用及负责人独立`reused → reused`均0写、bytes/mtime不变。
  原正式33文件与SP-09的139份参考/证据文件未变，没有重跑ASR/translation/provider。
  全97句三方对照见[SP-12](docs/archive/tasks/SP-12-candidate-v2-comparison.md)；候选短cue从旧2增至9，
  中文CPS按统一新口径从旧11增至17，且有s30/s32等新语义错位，**不得宣称质量全面改善**。
- 旧CNBC规范目录保留v1字幕；当前v3代码对其直接运行原sample_runner应受控冲突，不再承诺
  原地直接复用。候选复跑用`tests.srt_processing.candidate_runner --run`并指定从未存在的
  `--result-name`；需要三方对照时加`--compare --comparison-name`唯一新目录。旧SP-09脚本动态
  import当前rules，无v1代码环境隔离不能复现历史计数；历史工件原样保留，新比较显式按v2重审。
- 当前v3独立工作区为`output/cue-evaluation/20261023-candidate-v3/workspaces/cnbc_2000_morning/`，
  复跑用`tests.srt_processing.candidate_v3_runner --run --result-name <唯一新文件>`；四方比较按
  v3硬/软政策明确重审，不能混用历史v1/v2容量指标或把153参考当合法golden。阶段本身仍只消费
  已有正式alignment/译文，不依赖先跑其他模块集成测试。
- `webapp/app.db` 是已被 gitignore 的遗留残留，忽略它。

## 开工规则

1. 动某个模块前，先读该模块的 `src/<module>/AGENTS.md`；大型任务前再读相关 ADR 与任务文档。
2. 说"做完了"之前必须跑质检（见「构建、测试与验证」），离线测试套件全绿才算完成；没跑测试不得声称完成。
3. 一次只做一小块可验证的改动，不同时大范围修改多个模块，不顺手重构无关代码。

## 环境与工具链（已知的坑）

- **仅支持 Python 3.11**（3.12 可接受）。WhisperX/PyTorch 技术栈不能可靠支持 Python 3.13+。
- **用 `ffmpeg-full`，不是 `ffmpeg`**（Homebrew）。字幕烧录需要 libass 支持的 `ass`/`subtitles` 视频滤镜。`ffmpeg-full` 是 keg-only：
  ```bash
  export PATH="/opt/homebrew/opt/ffmpeg-full/bin:$PATH"
  ```
- 做媒体工作前先验证外部工具：
  ```bash
  ffmpeg -hide_banner -filters | awk '$2 == "ass" || $2 == "subtitles"'   # 必须两个都列出
  yt-dlp --version && ffprobe -version
  ```
- 首次真实使用 ASR 会下载 Whisper 模型文件（按配置为 `large-v3`）——很慢，缓存它，别跟它较劲。
- `config.yaml` 存放非敏感运行时配置（包括翻译 API key 的环境变量名、下载、字幕样式、WhisperX、抓取礼貌性）。**绝不提交真实 API key**。

## 管线数据流（目标态）

```text
acquisition ─→ media_download ─→ transcription ── source_alignment.json ─┬─→ translation
（网页抓取/         （yt-dlp）      （WhisperX + 词级对齐/句界）             │   （句级翻译）
 结构化逐字稿）                                                         │        │
                                                                        │        ▼
                                                                        └─→ srt_processing
                                                         translation_result.json ─┘
                                                                                │
                                                                                ▼
                                                               subtitle_rendering（libass/ffmpeg）

archive_core：资产身份、路径、公共 schema、manifest、溯源
orchestration：可恢复任务计划 · cli/webui：薄接口 · infrastructure：共享适配器
```

各阶段状态：实现到 `srt_processing` 为止；transcription 已通过离线测试与当前 CNBC 真实集成
验收，translation 已通过离线测试与 Codex CLI ChatGPT 真实集成验收。srt_processing 已通过
离线跨层与 CNBC 真实技术集成，已知字幕内容质量限制见 SP-08；rendering技术实现/样片已交付，
最终语义质量验收未通过，后续模块仍为脚手架。

## 模块地图

- `src/archive_core/` —— 共享领域原语：资产身份、规范文件名、路径策略、`manifest.v1`、溯源。
- `src/acquisition/` —— 网页分析、爬虫、逐字稿提取、元数据规范化、抓取礼貌性规则。
- `src/media_download/` —— 媒体 URL 解析、yt-dlp 下载编排、校验和/溯源采集。
- `src/transcription/` —— 音频提取、VAD、ASR、词级对齐、逐字稿融合、英文句界。*（已实现 +
  离线测试 + CNBC 真实集成测试）*
- `src/srt_processing/` —— 确定性双语 cue 规划、三份 SRT 投影/解析、QA 与可恢复发布。*（已实现 + 离线跨层验收 + CNBC 真实技术集成，非出版级质量背书）*
- `src/translation/` —— 完整英文句子/section 翻译、checkpoint、术语/风格策略、服务适配器、结果
  校验与原子发布。*（已实现 + 离线测试 + Codex CLI 真实集成测试）*
- `src/subtitle_rendering/` —— SRT/ASS 样式、烧录渲染、ffmpeg 命令规划、渲染元数据。*（SR-01..06已验收，真实样片已交付，最终验收未通过）*
- `src/webui/` —— 本地评审 UI 边界、目录契约。*（脚手架）*
- `src/cli/` —— 命令解析、面向人的命令、进度显示。*（脚手架）*
- `src/orchestration/` —— 管线组装、可恢复工作流、依赖排序、故障恢复。*（脚手架）*
- `src/infrastructure/` —— 共享技术适配器：配置、文件系统、进程执行、HTTP、日志、工具发现。

跨模块 import 规则：`archive_core`（领域契约）与 `infrastructure`（技术适配器）是仅有的两个允许被其他模块 import 的模块；功能模块的内部实现不得被跨模块 import。

## 架构

- 按能力组织，不按步骤编号组织。步骤式命名（如 `step3_translate`）禁止出现，临时迁移 shim 除外。
- 每个模块分四层：
  - `domain/` —— 纯概念与规则。禁止网络客户端、CLI 框架、`subprocess`、重文件系统操作、UI 代码。
  - `application/` —— 用例与模块内工作流协调。可依赖 `domain/` 和抽象端口；绝不直接依赖具体外部服务。
  - `infrastructure/` —— HTTP、ffmpeg、yt-dlp、ASR 库、翻译服务、文件系统等外部系统的适配器。
  - `interfaces/` —— CLI/Web/orchestration 使用的 DTO、命令处理器、展示器、序列化器。
- 跨模块只能通过契约 import：
  - ✅ `from src.archive_core.interfaces.manifest import ...`
  - ❌ `from src.acquisition.infrastructure.http_client import ...`（在 `media_download` 中这样写）
- 资产工作区契约由 `archive_core.application.build_asset_workspace()` 唯一定义，别处不得自创路径规则。规范文件名与 manifest schema 定义在 `src/archive_core/domain/artifacts.py` 和 `src/archive_core/interfaces/manifest.py` —— 同样以代码为唯一事实来源。任何写文件的模块必须定义期望的文件名、元数据和幂等行为。
- 每个昂贵阶段（抓取、下载、ASR、翻译、渲染）必须可恢复且由 manifest/溯源驱动。**绝不用"文件存在"当作完成判据。**
- CLI 和 Web UI 保持薄：校验输入、调用 application 服务、渲染结果。业务规则（媒体处理、爬虫逻辑）不得放进去。
- 外部工具/API 一律隔离在适配器之后，保证测试套件离线可跑（无网络、无 yt-dlp、无 ffmpeg）。
- 优先小步可验证的迁移，不做大规模重写。当某次改动改变了模块的架构意图、公开契约或阶段目标时，必须在同一次改动中更新该模块的 `AGENTS.md`。

## 构建、测试与验证

```bash
# 安装（Python 3.11）
python3.11 -m venv .venv && . .venv/bin/activate
python -m pip install -r requirements.txt -r requirements-dev.txt

# 完整离线套件（验证门槛）
python -m pytest tests/ -q

# 单个模块的测试
python -m pytest tests/test_acquisition_domain_application.py -q

# 标记为 `live` 的测试需要真实网络 —— 除非明确要求，否则跳过
python -m pytest tests/ -q -m "not live"

# 架构健全性检查：实现前确认模块指南存在
fd '^AGENTS\.md$' src --max-depth 3 | sort
```

## 关键约束

- 不引入云持久化、后台 worker、Web 框架或数据库，除非某个具体工作流确实需要。
- `domain/` 和 `application/` 层不得包含 OpenAI/Whisper/yt-dlp/ffmpeg 的特定厂商逻辑。
- CLI 和 Web UI 不得持有业务规则。
- 未校验 cue 数量一致性、时间轴单调性和文件溯源前，不得将生成字幕视为权威。
- 绝不静默覆盖昂贵的生成资产（ASR/翻译/渲染）。必须有显式覆盖策略或工件版本化。
- 绝不在没有用户明确确认的情况下删除生成资产或源媒体资产（`input/`、`output/`）。
- 实现某个模块切片时，不要顺手重构无关代码。

## 补充文档

- 模块指南：`src/<module>/AGENTS.md`（11 份）—— 动某个模块前先读对应那份。
- 已接受决策：`docs/decisions/`；已完成的 ADR 与任务：`docs/archive/`。
- `README.md` 是面向人的快速上手（安装、工具链设置）；架构规则在本文件和各模块指南中。
- 规则冲突时的优先级：`src/<module>/AGENTS.md` > 本文件 > `docs/` 规划文档。但本文件「关键约束」中的安全规则始终有效，模块指南不得覆盖。
