# media_download AGENTS.md

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

- `yt-dlp` 为默认适配器，隔离在端口之后；`ffprobe` 仅用于校验元数据，不作为业务规则依赖。
- 跳过/续传/覆盖决策必须由 manifest 与 `DownloadPolicy` 显式驱动，**不得以"文件存在"作为完成判据**。
- 媒体文件的覆盖必须显式；下载 manifest 属廉价元数据，允许覆写。

## 测试方向

- 离线测试：fake downloader/resolver/checksum，不触网、不执行 yt-dlp。
- 注册顺序、dry-run、覆盖策略、manifest 往返必须有用例覆盖。
