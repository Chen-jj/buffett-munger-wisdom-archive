# 已完成与终止工作的归档

初次归档：2026-10-24；补充整理：2026-11-05、2026-11-17。保留历史内容、依赖、验收结果和质量限制；不将旧任务当作现行路线图。

## ADR

| ADR | 归档依据 |
|---|---|
| [ADR-0001](adr-0001-transcription-sentence-level-alignment/decision.md) | transcription 已完成，原归档位置不变 |
| [ADR-0002](decisions/0002-translation-sentence-units.md) | 完整句/section 翻译实现及 Codex CLI 真实集成已通过 |
| [ADR-0003](decisions/0003-srt-processing-input-boundary.md) | 公共字幕契约、v1/v2/v3 技术实现和实验交付完成；语义/阅读质量并未定版 |
| [ADR-0004](decisions/0004-transcription-source-sections.md) | source section 实现与离线/真实集成已通过 |
| [ADR-0005](decisions/0005-translation-codex-cli-chatgpt-provider.md) | Codex CLI provider 实现与真实集成已通过 |
| [ADR-0007](decisions/0007-bilingual-semantic-alignment.md) | superseded且未实施的终止历史候选，非完成验收 |
| [ADR-0008](decisions/0008-local-orchestration-and-integration-tests.md) | 已实施生产编排/集中测试总方案，仍是行为入口；语义/核听不判通过 |
| [ADR-0009](decisions/0009-cnbc-editorial-break-annotations.md) | 有来源编辑标记及canonical投影已实现，保留阶段原记录 |
| [ADR-0010](decisions/0010-source-chunking.md) | 初版源分组/预算/发布已实现，当前84/typed由0013修订 |
| [ADR-0011](decisions/0011-contextual-chunk-translation.md) | 上下文分批初译已实现/实跑，质量不由归档签认 |
| [ADR-0012](decisions/0012-bilingual-translation-postprocessing.md) | 有界编辑生成/唯一权威稿/排时已实现，语义残余保留 |

归档不自动撤销仍生效的契约。ADR-0006 的实现子任务完成不等于整份 ADR 最终验收完成，
所以[ADR-0006](../decisions/0006-subtitle-rendering-ass-and-burn-in.md)仍留当前；[ADR-0013](../decisions/0013-typed-chunking-quality-and-regression.md)与[NB-12](../tasks/NB-12-chunking-quality-iteration.md)的质量迭代也继续开放，整体语义/出版NOT PASSED、未核听。

## 任务

- ADR-0001 的任务仍在其[原归档目录](adr-0001-transcription-sentence-level-alignment/tasks/README.md)。
- TA-01..16（含 TA-03A）、SP-01..15（含 SP-08A）、SR-01..06 共39份任务移至 `tasks/`。
- [TA/SP 历史任务图与依赖](tasks/README.md)原文保留。
- TA-10 是 `superseded`，并未执行，也不是验收通过；随已结束的 TA 任务线归档，不再作为待办。
- SP 质量评估和候选任务的 accepted 仅指该实验/技术交付完成，不表示字幕质量通过。
- SR-00、SR-07 及 runner 设计交接已移入归档：技术实现已交付，最终质量未通过，旧验收队列由新方案替代。
  见[历史 SR 任务图](tasks/SR-00-rendering-task-map.md)及[SR-07 验收记录](tasks/SR-07-real-sample-acceptance.md)。
- SA-00 是与本次方案无关的未实施旧队列，已按用户要求删除，不归档为已实现。


## 2026-11-17 NB文档归档

NB-00～NB-10共11份技术交付/固定样片实验/诊断及测试映射见[历史任务索引](tasks/README.md)；不把旧头部待开发或中间失败删改为全部通过。NB-10仅诊断/术语交付，未解决问题转向NB-12。17份移动的原文、old/new路径、前后hash和路径改写记录见[完整保全映射](2026-11-17-document-relocation.json)。

本次用户授权全部本地代码/测试/文档commit与push，负责人最终验收后执行；忽略的output/模型/媒体不提交，不改冻结实验/资产。归档中的旧不commit/push是当时过程约束，不再覆盖本次明确授权。
