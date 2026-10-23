# SP-07 — 跨层回归与可复现本地样本入口

- **Status:** accepted
- **Owner:** contracts 子开发 agent；仅技术负责人标记accepted
- **Module:** srt_processing tests + acceptance runner
- **Decision coverage:** ADR-0003 §14全部
- **Depends on:** SP-06
- **Depended on by:** SP-08

## 范围与验收标准

- 独立检查前序覆盖，补足跨层不变量、损坏/故障注入、Unicode/转义/范围错配、确定性及非贪心回归；发现缺陷回派责任开发agent。

- 提供显式opt-in本地样本入口：只消费现有canonical transcription/translation/video，不下载、不重跑ASR/翻译、不伪造正式译文。记录初次生成/第二次byte-identical复用、双链hash、三份投影、全文时间覆盖、上游未变、统计与人工挑样。

- 现有CNBC alignment/video在output/transcription-integration/cnbc_2000_morning，缺少匹配的translation_result/manifest。前置条件缺失清楚报告，不弱化门禁。本任务通过不等于真实样本通过。

## 验证与交接

```bash
.venv/bin/python -m pytest tests/ -q -m "not live"
git diff --check
```

记录实际命令/结果、API与未解决问题，再交负责人复验。先读根与模块AGENTS，保留用户已有ADR/指南修改；不得删除文件/资产，不作无关重构。

## 技术负责人验收（2026-10-21 09:05 CST）

已审查真实local/pysubs2跨层测试和显式样本入口，回派修复相对output_root与上游绝对canonical记录路径不一致的问题，并复验其生成/复用回归。独立定向 **52 passed**，完整离线 **1220 passed / 5 deselected**，diff check通过。

负责人实际执行 `PYTHONPATH=src .venv/bin/python -m tests.srt_processing.sample_runner --run`，退出2，`precondition_missing`：CNBC工作区仍缺translation_manifest.json和translation_result.json，未调用workflow/probe或上游生成。SP-07开发与离线集成验收通过，不代表SP-08真实样本通过。

## 开发交接（2026-10-21）

### 文件与边界

- 新增 `tests/srt_processing/sample_runner.py`、`acceptance_fakes.py`、
  `test_sample_runner.py`、`test_cross_layer.py`。后 3 份仅使用临时目录的合成离线输入，
  不接触真实 CNBC 工件；新测试均禁止真实 `subprocess.run` 与网络连接。
- 未修改 production 实现、旧测试、根/模块指南或 ADR，未删除资产，未作 Git 提交。

### 可复现入口与 API

在仓库目录、Python 3.11 虚拟环境中执行：

```bash
PYTHONPATH=src .venv/bin/python -m tests.srt_processing.sample_runner --run
```

- 默认资产 `cnbc:2000:morning`、根 `output/transcription-integration`；支持 `--asset-id`、
  `--output-root`、`--ffprobe-executable`。根先 `resolve()` 为绝对路径，再使用公共 workspace
  builder，兼容真实 transcription manifest 的绝对 record 路径。
- 无 `--run` 返回 `opt_in_required` / exit 2；五输入缺失返回 `precondition_missing` / exit 2，
  列出规范缺失路径；两者均不构造 workflow/probe、不创建文件、不下载、不生成上游工件。
- 不提供 overwrite、ASR/翻译、provider 或绕过门禁开关。完整输入存在才调用生产 composition；
  第 1 次默认不覆盖，第 2 次新建 handler 且必须 `reused`、零 stage/publish、六输出 bytes 与
  mtime 完全不变。已有完整输出则如实报告 `generated_now=false`，残缺输出保持 conflict。
- stdout JSON 包含双链/五输入/六输出证据、profile/rules、probe/codec 身份、fps/G、耗时、
  word/sentence/section 数、cue/告警统计和最长/最短/null/合并/比例片段示例；仅打印，不新增
  canonical 工件。现有 audio/ASR 等非字幕文件的 hash/size/mtime 也检查未变。
- `run_local_sample(*, asset_id, output_root, ffprobe_executable="ffprobe", probe=None, clock=None)`
  允许离线测试注入 fake probe/clock；正式 CLI 不提供该注入。样本摘要明确仍需人工检查比例映射，
  不代表语义、像素、ASS 或烧录验收。

### 独立补充覆盖

- 真实 local+pysubs2+fake probe 的双链指纹、公共 plan/manifest 交叉校验、三份实际 SRT
  cue/编号/time/text、独立生成确定性、第二次 bytes/mtime 不变且 clock 不再调用。
- 组合标记/ZWJ/布局空白范围守恒、极端 CPS 仅 warning、非贪心路径经门禁/codec/落盘/复用、
  已知/null/不同已知 speaker 不串联。
- 重新签署大小/hash 不能掩盖范围、speaker、section、源锚点/方法或实际 SRT BOM/CRLF/编号/
  时间/正文/HTML 损坏；冲突完全只读。真实 lossy codec 失败不能发布成功 bundle。
- 实际 Path.replace 故障、暂存字节改变、残留、显式覆盖中断造成混合代次均不可误判成功，
  不自动回滚或删除；runner 独立拒绝复用后暗改上游或输出 mtime。
- 负责人预审指出的相对根/绝对 record 不一致已仅在 runner 修复并补回归；无 production 缺陷。

### 实际验证及剩余前置条件

- 定向两份新增测试：**52 passed**。
- `.venv/bin/python -m pytest tests/ -q -m "not live"`：**1220 passed, 5 deselected**。
- `git diff --check` 通过。实际默认 `--run` 精确报告缺失 CNBC `translation_manifest.json`、
  `translation_result.json`；工作区未生成字幕输出。无标志实际运行返回 `opt_in_required`。
- **真实 CNBC 生成/正式复用与人工评审未执行，SP-08 仍待匹配正式译文及 manifest。**
  临时合成样本通过不替代此项，不得据此宣称 ADR-0003 真实样本验收完成。
