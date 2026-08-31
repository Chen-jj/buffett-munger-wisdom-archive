# subtitle_rendering AGENTS.md

## 模块定位

`subtitle_rendering` 负责字幕样式、ASS 生成、烧录计划、ffmpeg 执行，以及渲染工件元数据。

## 职责

- 把校验通过的字幕文档转换为带样式的 ASS 或可渲染资产。
- 规划硬字幕输出的 ffmpeg 命令，不隐藏影响用户观感的质量参数。
- 采集渲染设置、输入哈希、输出路径与评审 sidecar。
- 视觉样式决策与 SRT 文本处理保持分离。

## 分层规则

- `domain/`：渲染 profile、字幕样式、渲染输入集、渲染计划、渲染工件等概念。
- `application/`：build-ass、render-video、verify-render-inputs、generate-render-manifest 用例。
- `infrastructure/`：`pysubs2` ASS 适配器、ffmpeg 进程执行器、字体发现、文件系统输出。
- `interfaces/`：CLI 处理器、渲染进度消息、面向评审/orchestration 的摘要。

## 技术方向

- ASS/样式生成与 ffmpeg 执行分离，各自可独立测试。
- 烧录渲染通过适配器使用 `ffmpeg`/libass。
- CRF、preset、分辨率、字幕样式等质量设置作为显式 profile 管理。
- 优先支持 dry-run 命令规划，便于调试与评审。
