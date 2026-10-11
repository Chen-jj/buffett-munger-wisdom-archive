# 技术任务：transcription 结构化事件、详细日志与报告

- 任务 ID：`TR-01`
- 优先级：`P0`
- 影响模块：`transcription`、`infrastructure` 日志适配器
- 依赖：`AC-01`
- 被依赖：`TR-02`～`TR-06`
- 对应决策：[ADR-0001](../decision.md) §11
- 状态：已实现

## 目标

在实现各处理阶段前固定可注入的事件契约，使每个匹配、调整、冲突和失败从第一天起可
观测，而不是最后补散落的 `print()`。

## 实现范围

- 在 transcription application 定义 `TranscriptionEvent`、severity、稳定 event code 和
  `TranscriptionEventSink` 端口。
- 实现写入 `transcription.log` 的全级别结构化日志适配器；日志至少包含 asset、stage、
  code、severity、相关 ID、文本摘录、原视频时间范围、动作和原因。
- 实现 `transcription_report.json` 聚合器，记录计数、WARNING/ERROR findings、QA 和状态。
- 实现 interfaces 层的用户展示器：只显示 WARNING、ERROR 和阶段汇总；INFO/DEBUG 只落盘。
- 失败时仍尽力 flush log/report；不得因日志失败掩盖原始业务错误。
- 测试使用内存 sink，不依赖终端或真实文件。

## 非目标

- 不实现具体 VAD、ASR、alignment、融合或句界规则。
- 不建立全仓日志平台或数据库。
- 不把业务事件分类规则放进 CLI。

## 验收标准

- INFO/DEBUG 事件写入详细日志但不出现在默认用户输出。
- WARNING/ERROR 同时进入详细日志、report 和用户输出。
- 阶段汇总始终可展示 aligned/interpolated/conflict/warning/error 等计数。
- event code 和必需字段缺失时构造失败；敏感配置不得进入事件。
- 失败路径仍保存可解析 report，canonical 工件发布由后续工作流任务控制。
- 更新相关模块 `AGENTS.md` 中新增的事件边界。
- `python -m pytest tests/ -q -m "not live"` 全绿。
