# orchestration AGENTS.md

2026-11-07 NB-09：全新真实upstream及下游编辑生成已实跑，最终623秒/163 cue；集中editorial_refresh
runner先只读核验、完整保全，依公开verify复用或显式更新下游，不删旧资产。最终同/新进程九阶段0昂贵调用/
0阶段改写、84项保护集不变。文本/视觉和未核听范围见NB-09负责人及独立报告，不能把技术复用写成出版签字。

2026-11-06：已实现ADR-0008单机同步公开编排，支持正式媒体派生或直接完整资产、授权/阶段预算、
plan/run/resume/verify、父子工作区OS锁、阶段证据与运行回执。静态verify只读不执行工具；
真实 CNBC 已从空根经恢复发布，九阶段同进程/新进程均复用、阶段零写/零昂贵调用；技术验证与真实样片质量分别记录。实跑与验收看[NB-08](../../docs/archive/tasks/NB-08-full-fresh-acceptance.md)。
总方案入口为 ADR-0008；实施 agent 还必须逐阶段审核实际产物并检查样片字幕与声音，不能只看测试摘要。

## 模块定位

`orchestration` 负责多步骤工作流组装、依赖排序、可恢复性与故障恢复策略。

## 职责

- 组合 acquisition、download/可选派生、transcription、英文chunking、初译、修订排时、SRT和rendering；不含Web。
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
