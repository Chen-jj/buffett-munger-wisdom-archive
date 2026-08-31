# orchestration AGENTS.md

## 模块定位

`orchestration` 负责多步骤工作流组装、依赖排序、可恢复性与故障恢复策略。

## 职责

- 组合 acquisition、download、transcription、translation、rendering 与 Web 目录工作流。
- 基于 manifest 与输入，决定哪些阶段可跳过、续跑、重试或失效。
- 提供可由 CLI 或未来自动化执行的管线计划。
- orchestration 本身不携带提供方特定的实现细节。

## 分层规则

- `domain/`：管线阶段、任务依赖、执行计划、工件需求、恢复策略等概念。
- `application/`：run-year、run-session、resume-pipeline、plan-pipeline、verify-readiness 用例。
- `infrastructure/`：本地锁文件、manifest 持久化、可选的进程调度辅助。
- `interfaces/`：面向 CLI 的计划摘要与机器可读的工作流报告。

## 技术方向

- 先做同步本地执行；不过早引入队列或服务。
- 每个阶段在执行前保持显式且可检视。
- 优先 manifest 驱动的决策，而非只检查文件是否存在。
- 爬虫注册顺序等来源特定策略见 `src/acquisition/AGENTS.md`。
