# SR-07 — 同源样片 runner 只读设计交接

- **Status:** historical design；runner与技术样片已交付，最终状态见SR-07，不再是待实现清单。
- **Owner:** sample_dev；最终验收由技术负责人执行。
- **依赖:** [SR-07](SR-07-real-sample-acceptance.md)、ADR-0006 第 20.2 节及已验收生产 composition。
- **本次只读核对:** 2026-10-24。未运行 handler、FFmpeg、ASR/provider 或 SRT planner；未写 output。

## 1. 已确认 fixture

规范 asset 为 `cnbc:2000:morning`，使用 `build_asset_workspace()`：

- 原始来源：`output/transcription-integration/cnbc_2000_morning/`，现有 33 文件。
- v3：`output/cue-evaluation/20261023-candidate-v3/workspaces/cnbc_2000_morning/`，现有 25 文件。
- v3 的 `video.mp4`、`audio.wav` 是指向原始来源的绝对 symlink；其余输入已复制，transcription
  manifest 的 record 路径重定位已有 `preparation.v1.json` 明示证据，不能再改写它。
- 2 sections、97 sentences、1564 words、163 cues；媒体基线 623000ms，首 cue 从 1427ms 开始，
  末 cue 在 622972ms 结束。完整视频必须编码，不能加 `-ss` / `-t`。
- alignment SHA-256：`99f36287d28d0581ae039f64eeea55c14bef044dbb87fdca2f9c8d26ad7fbf91`。
- translation SHA-256：`0862d8759a3bb0cec59bf2d3531fd2301a37b889d2499135c46ea24a608d1dfb`。
- video：46297605 bytes，SHA-256 `364d6cc6b2fd164d972344b42bbb9019b6d55a838257d0cc243c54ddca5b59e0`。
- 五份 rendering 正式输出均不存在；生成前必须再次核对，不能依赖这次静态 inventory。
- 固定字体与 `/opt/homebrew/opt/ffmpeg-full/bin/{ffmpeg,ffprobe}` 路径存在；这不代表版本、
  glyph、像素、可解码性或成片已验收，必须交给真实生产适配器重新证明。

## 2. 实现文件和入口

拟新增 `tests/subtitle_rendering/sample_runner.py`、`test_sample_runner.py` 与
`test_integration_local.py`。测试/runner 只 import 本模块公共入口和 `archive_core` 公共契约，
不 import 上游功能模块私有代码、不调用其他阶段 runner。

- sample runner 需要显式 `--run`；不带参数输出 `opt_in_required`、非零，且零文件/工具操作。
- pytest 仅在 `RUN_SUBTITLE_RENDERING_INTEGRATION=1` 开启；未开启 skip，明确开启后缺产物
  必须失败，不能 skip。真实 FFmpeg 不是网络 `live`。
- 默认固定现有 v3 root。不得提供 overwrite 或“自动准备上游”选项。
- 主模式调用真实 production composition/handler；创建一次 handler，同一 command 连续执行。
- 内部显式 reuse-only 模式供独立 Python 进程使用：先确认完整五件套存在，再调用同一生产
  composition，并要求 `reused`、零 stage/publish/pixel/full-content-encode。不能递归启动子进程。
- 使用当前 Python 和共享 `run_process()` 启动独立进程，不经 shell；明确仓库 cwd 和 `src`
  import path，读取子进程结构化结果并核验返回码/状态，不能把退出 0 当成复用证据。

具体 injection 参数以 SR-05 accepted 接口为准；不为 runner 修改生产 API 或添加测试分支。

## 3. 前置条件和只读来源证明

先列出缺失的规范输入及必需来源/重定位证据；存在悬空 symlink 也按缺前置报告其 lexical
path。`precondition_missing` 返回完整绝对路径清单、非零；不构造 handler、不补跑任何阶段。
损坏、基线不符或不同源属于失败，不以合成 fixture 顶替。

生产 input gate 负责 ADR 第 7 节整套显式证据链和公共 DTO；runner 另证明：

1. 原始和 v3 alignment / translation / video 同字节，与 SP-08A 来源一致；全部资产身份一致。
2. `preparation.v1.json` 的来源/目标路径及媒体链接仍匹配，transcription manifest 仅记录了
   已批准的 record 路径重定位，不因 rendering 改写任何 input。
3. 2/97/1564/163/623000 是该 fixture 的回归断言，不进入生产模块通用限制。
4. `meta.json` / `transcript.txt` / `media_ref.json` 等未被 acquisition 成功 SHA manifest 锚定
   的上下文只能称“快照未变”，不能冒称其已获生产 provenance 逐项验证。

## 4. 快照、调用观察和验收

保护原始 33 文件、SP-09 139 文件、v2 111 文件、偏好 15 文件及全部既有 v3 文件。只排除
当前 v3 workspace 下将新增的五份 rendering 正式输出；不按相同 basename 排除其他历史文件。

每个文件快照记录 lexical 绝对路径、类型和 lstat mtime；普通文件记录 size/hash/mtime。
symlink 额外记录 readlink 字符串、resolved target path 及目标实际 size/hash/mtime，避免重指到
同字节另一路径被漏检。不以 atime 为不变门禁；读取本身可改变它。快照捕获全部文件/链接，
不把正常发布五文件引起的 workspace 目录 mtime 变化误报成上游修改。

观察器继承真实 local store / renderer，仅计数再转发真实调用，不替换实际文件或媒体行为：
stage/create-staging、publish、逐 cue transparent frame、完整内容 `render()` 分开计数。
工具 identity 的零帧内存 libx264 探针不是完整内容编码，必须在证据中区分，不伪称零外部进程。

运行顺序：

1. 确认首次五份全无，保存保护集 before；真实 handler 返回 `succeeded`，编码覆盖完整样本。
2. 读公共 render plan/report/manifest，验证 actual evidence、全部 163 PixelResult、媒体 QA、
   cue 数/时间/安全区域/字体身份；保存五份 bytes/mtime 基线和第一次真实编码计数。
3. 同 handler 再调 `reused`；独立进程 reuse-only 再调 `reused`；逐次核对正式输出 size/hash/
   mtime 与字节，stage/publish/pixel/full-content-encode 增量必须为 0。
4. 所有保护文件/链接目标与 before 完全一致，含历史参考。已有完整同身份结果可未来复用，
   但不能用未来的 reused 结果替代首次 `succeeded` 的持久证据。
5. JSON 结果提供绝对样片/manifest/report 路径、大小/hash/时长、来源输入指纹、前后快照、
   首次/复用调用计数、工具/字体身份与 agent/human 审看边界。首次结果需由调用方以 exclusive
   新文件保留到 workspace 之外，不能仅保留 pytest stdout 或覆盖既有验收证据。

失败时结果应保留原 error category 和 staging/report 路径，所有残留保留，不删除、重命名或
擅自 overwrite；完整/部分正式结果变化立即交负责人决定，不通过重复生成掩盖首次失败。

## 5. 离线测试和视觉交付

离线 runner 测试不调用真实字体或工具：覆盖 opt-in 零操作、所有 required input 缺失路径、
显式 integration 缺前置不 skip、基线错配、symlink 被重指、目标内容/mtime 修改、首轮失败、
同进程/子进程复用状态或计数异常、outputs/upstream 改动、子进程非零/坏 JSON、已存在完整
结果不谎称首次生成。fixture 端口只用于 runner 单元测试；真实集成入口不能传 fake。

真实样片交付后选择首尾、最长中英、四行、专名/数字、复杂底部及 S17/S22/S48/S74/S88
对应 cue 抽帧。抽帧仅为 agent 视觉证据，使用实际成片，保留时间与 cue 映射，不能冒称
人类播放或完整音画审阅。负责人另向用户请求人工播放；未获确认时该项明确未通过。

当前没有 fixture 文件缺失阻断；唯一实施前置仍是 SR-06 accepted 和负责人明确放行。
