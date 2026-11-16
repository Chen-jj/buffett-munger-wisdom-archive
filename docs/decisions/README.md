# ADR导航：当前质量迭代与仍生效的已实施契约

## 当前目录仅保留

| ADR | 范围 | 当前状态 |
|---|---|---|
| [0006 ASS与烧录](0006-subtitle-rendering-ass-and-burn-in.md) | 渲染样式/布局/成片 | 技术样片已交付，整体质量验收未完成，仍保留当前 |
| [0013 切分评价与防退化](0013-typed-chunking-quality-and-regression.md) | 修订0010的84容量/typed DP/回归 | 实现及诊断样片技术交付，整体语义/出版NOT PASSED；见[NB-12](../tasks/NB-12-chunking-quality-iteration.md) |

## 已实施归档，未被替代的契约继续生效

**唯一总方案仍是[ADR-0008](../archive/decisions/0008-local-orchestration-and-integration-tests.md)**。从此阅读模块分工、流水线、依赖/恢复、单套替换及集中集成审核责任；2026-11-17移动位置，不改变契约效力。

| ADR | 负责什么 | 归档范围 |
|---|---|---|
| [0008 总方案与编排](../archive/decisions/0008-local-orchestration-and-integration-tests.md) | 统一入口、授权/恢复、测试/产物审核 | 生产编排及真实恢复/两种复用已实现；质量边界不因归档通过 |
| [0009 编辑标记](../archive/decisions/0009-cnbc-editorial-break-annotations.md) | transcription分离有来源的CNBC编辑破折号 | 公共annotations/canonical投影已实现，原设计/阶段记录保留 |
| [0010 英文chunking](../archive/decisions/0010-source-chunking.md) | 源词分组/只读预算/独立发布 | 初版已实现；当前容量/评分按0013修订，不照旧算法重建兼容路径 |
| [0011 上下文初译](../archive/decisions/0011-contextual-chunk-translation.md) | 分批/术语/标题及checkpoint | 已真实运行，结构与预算不代替翻译质量判断 |
| [0012 编辑与最终排时](../archive/decisions/0012-bilingual-translation-postprocessing.md) | 有界双语生成/唯一权威稿/统一排时 | NB-09已替换机械触发路径；仍按当前契约执行，不把结构采纳写成语义通过 |

初次真实链路见[NB-08](../archive/tasks/NB-08-full-fresh-acceptance.md)，固定样片迭代见[NB-09](../archive/tasks/NB-09-editorial-quality-iteration.md)，最新质量状态见NB-12；核听/人类出版签字未验证。新版直接替换旧契约与生产路径，不新增兼容；旧集成产物历史清理授权不扩为本次资产删除。

## 终止/历史依据，不是待实施队列

- [ADR-0007](../archive/decisions/0007-bilingual-semantic-alignment.md)：superseded且未实施的历史候选；不建设独立semantic_alignment，归档不冒称完成。
- [ADR-0001～0005及全部归档索引](../archive/README.md)：未被替代的转录/provider能力继续使用；不恢复旧句级翻译或比例字幕兼容。
- [业界调研](../reviews/2026-10-28-industry-bilingual-subtitle-pipelines.md)：方案来源，不是另一个当前总方案。
- SA-00为与本次无关、已授权删除的未实施旧任务，不恢复。

实施与验收仍须审核真实产物、独立agent回归并据实注明实际观看/核听范围；不增加运行时语义发布门禁。
