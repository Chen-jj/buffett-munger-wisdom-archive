# infrastructure AGENTS.md

## 模块定位

`infrastructure` 持有不够具体、不足以归属某个功能模块的共享技术适配器。

## 职责

- 提供配置加载、日志、文件系统辅助、进程执行、HTTP 基础客户端、外部工具发现。
- 保证横切技术行为在各模块间一致。
- 避免沦落为业务逻辑的垃圾场。

## 分层规则

- `domain/`：通常为空；若某概念有业务含义，应放入 `archive_core` 或对应功能模块。
- `application/`：通常最小化；仅当服务真正是技术性且横切时才允许共享应用服务。
- `infrastructure/`：配置、日志、文件系统、subprocess、HTTP、工具探测的具体实现。
- `interfaces/`：多模块需要的小型适配器协议或 DTO。

## 技术方向

- 依赖保持轻量且显式。
- subprocess 执行可注入，使 ffmpeg/yt-dlp 调用无需运行真实二进制即可测试。
- 集中配置解析，但功能特定配置的含义归各功能模块所有。

## 当前实现状态（2026-10-16）

- 共享 YAML loader 只返回原始 mapping，不解释 `translation` 字段；严格 provider 配置解析与
  production composition 归 `translation.infrastructure` 所有。
- 共享 process adapter 支持可注入的 stdin 文本，Codex CLI adapter 的命令与 prompt 可离线测试。
- TA-16 已通过共享 process adapter 真实运行两次 `codex exec`，并验证第二次正式工件复用没有新增
  provider/process call。
