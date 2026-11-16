# 文档导航

## 从哪里开始

1. **[总方案入口：ADR-0008](archive/decisions/0008-local-orchestration-and-integration-tests.md)**：当前流水线、模块分工、契约替换及逐阶段审核。
2. [ADR 导航](decisions/README.md)：当前仅0006/0013；已实施契约按归档0008 → 0009 → 0010（当前修订0013）→ 0011 → 0012阅读，仍生效。
3. [当前任务](tasks/README.md)：仅NB-12质量迭代仍开放；policy v8/真实165块与cached v9完整一致、166cue诊断样片已交付，整体语义/出版NOT PASSED，未核听。NB-00～NB-10及已实施技术方案见[归档](archive/README.md)，归档不撤销现行契约或抹去未通过结论。

新实现只保留一套契约及生产流程，不做旧版兼容；旧集成产物已按用户授权删除；编排完成后从空产物工作区完整生成。
编排集成测试产物须由实施 agent 逐阶段审核，并实际检查最终样片的字幕和声音；另有独立 agent 回归。
这些是交付责任，不新增运行时语义发布门禁。

## 需要追溯原因时再读

- [业界字幕流水线调研](reviews/2026-10-28-industry-bilingual-subtitle-pipelines.md)：当前方案的参考依据，不再作为实施入口。
- [渲染技术验收与用户语义反馈](reviews/2026-10-24-rendering-technical-and-semantic-review.md)：旧片已知问题。
- [旧语义同步研究](reviews/2026-10-24-bilingual-semantic-alignment-design.md)：保留诊断证据；独立语义模块路线已被替代。
- [历史探索 prompt](prompts/bilingual-semantic-alignment-exploration.md)：原探索范围，不是当前实施指令。
- [归档 ADR 与任务](archive/README.md)：实现记录与历史依据，不是待办清单。

当前代码状态以根和模块 AGENTS.md 为准。已接受设计不代表已实施、质量通过或昂贵调用已获授权。
