# media_download AGENTS.md

2026-11-06：media_download.interfaces 提供公开download/媒体派生命令与factory。
派生从已验证的完整父资产按显式时间和章节选择，保父媒体，记录父hash/时间映射、
子媒体验证及真实PTS；派生AAC是明确裁切行为，非最终渲染的音轨转码。直接资产可同阶段
产生媒体边界；样本的360p限定不是通用规则。媒体边界验证ffprobe的v:0单流响应及原始duration字符串，
不接受整数或布尔值。真实网络/文件集成归编排。

## 模块定位

`media_download` 负责媒体 URL 解析、视频/音频下载工作流，以及下载工件的溯源。

## 架构

- 应用服务是两段式：先 `plan()` 产出可检视的下载计划（action 与 reason），再 `execute()` 按计划执行；dry-run 只出计划不落盘。
- 媒体 URL 解析经 resolver registry 选择：特定解析器在前，宽匹配解析器在后，registry 选第一个接受者——与 acquisition 的爬虫注册是同一条策略。
- 下载、校验和计算、工件存取均为注入端口；`yt-dlp` 只是默认下载适配器。

## 依赖规则

- 依赖只能向内指：infrastructure 依赖 application/domain 契约；application 依赖 domain 与 Protocol 端口；domain 只 import 纯原语与共享的 `archive_core` 身份值。
- 输出路径与文件名一律经 `archive_core` 的 workspace 与 `canonical_filename()` 解析，不得自创。

## 技术方向

- `yt-dlp` 为默认适配器，隔离在端口之后。`ffprobe` 为 `media_boundary.json` 收集实际解码帧时间，供下游排时复用。全帧扫描等待工具退出，再按现有规则校验工件。见 [ADR-0014](../../docs/archive/decisions/0014-pipeline-timeouts.md)。
- 跳过/续传/覆盖决策必须由 manifest 与 `DownloadPolicy` 显式驱动，**不得以"文件存在"作为完成判据**。
- 已有视频只有在 manifest 的身份、媒体引用、成功状态、canonical 路径、大小与 SHA-256 全部验证通过后才能返回 `SKIP`；否则抛出带稳定 `category` 的 `ExistingDownloadConflict`。
- 媒体文件的覆盖必须显式；下载 manifest 属廉价元数据，允许覆写。

## 测试方向

- 离线测试：fake downloader/resolver/checksum，不触网、不执行 yt-dlp。
- 注册顺序、dry-run、覆盖策略、manifest 往返必须有用例覆盖。
