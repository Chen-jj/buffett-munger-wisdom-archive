# cli AGENTS.md

## 模块定位

`cli` 负责面向人的命令结构，把用户命令连接到各模块的应用用例。

## 职责

- 解析命令行选项，校验用户意图。
- 调用各模块的 application 服务，不内嵌业务规则。
- 为长时本地任务提供合适的进度、dry-run、确认与错误消息。

## 分层规则

- `domain/`：通常为空，除非需要 CLI 特有的命令概念。
- `application/`：跨单个用户动作的命令组合，业务工作委托给功能模块。
- `infrastructure/`：终端输出、提示/确认辅助、环境发现。
- `interfaces/`：argparse/Typer/click 命令定义与命令 DTO 映射。

## 技术方向

- 近期 `argparse` 即可；仅当命令复杂度增长时再考虑 Typer。
- CLI 只能依赖 application 服务，不得直接依赖解析器/下载器/ffmpeg 等提供方实现。
- 长时命令应支持 dry-run 与显式的覆盖/续跑策略。
