# 当前任务入口

唯一行为总方案仍是已实施归档的[ADR-0008：新双语流水线总方案、编排与集成验收](../archive/decisions/0008-local-orchestration-and-integration-tests.md)，归档不使未被替代的契约失效。

当前仅保留：[NB-12 有类型切分、保好回归与新根样片](NB-12-chunking-quality-iteration.md)。2026-11-15实现与诊断样片技术交付/复用已验；整体语义同步/出版NOT PASSED，未核听，质量迭代继续开放。

## 已交付与历史记录

2026-11-17按用户授权将NB-00～NB-10共11份移入[任务归档](../archive/tasks/README.md)：
- [NB-00基础实施地图](../archive/tasks/NB-00-implementation-map.md)及NB-01～07：技术迁移/实现/测试盘点记录，不作当前待办；旧失败和未等价断言保留。
- [NB-08全新真实链路验收](../archive/tasks/NB-08-full-fresh-acceptance.md)、[NB-09固定样片质量迭代](../archive/tasks/NB-09-editorial-quality-iteration.md)及[测试映射](../archive/tasks/NB-09-editorial-test-mapping.md)：实验/技术交付完成，不等于字幕质量通过。
- [NB-10逐cue反馈与术语](../archive/tasks/NB-10-cue-feedback-diagnosis.md)：诊断与术语交付；未解决问题仍可追溯，后续见NB-12，不冒称反馈已全部修复。

负责人只拆解/调度/验收/回归，编码由子agent实施；本次用户授权全部本地代码/测试/文档commit与push，由负责人执行，旧历史不commit约束不再是当前禁止。忽略的output/模型/媒体不提交，资产不删除。

SR-00、SR-07及runner设计交接也在[历史归档](../archive/tasks/README.md)，最终质量未通过记录保留。SA-00为已删除的无关旧路线，不恢复或执行。
