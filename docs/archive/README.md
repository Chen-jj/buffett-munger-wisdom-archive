# 已完成与终止工作的归档

保留技术契约、历史决策、任务验收和评审限制；不将旧任务当作现行路线图。当前进度和待复审项见 [PROGRESS.md](../../PROGRESS.md)。

## ADR

| ADR | 归档依据 |
|---|---|
| [ADR-0001](adr-0001-transcription-sentence-level-alignment/decision.md) | transcription 已完成，原归档位置不变 |
| [ADR-0002](decisions/0002-translation-sentence-units.md) | 完整句/section 翻译实现及 Codex CLI 真实集成已通过 |
| [ADR-0003](decisions/0003-srt-processing-input-boundary.md) | 公共字幕契约、v1/v2/v3 技术实现和实验交付完成；语义/阅读质量并未定版 |
| [ADR-0004](decisions/0004-transcription-source-sections.md) | source section 实现与离线/真实集成已通过 |
| [ADR-0005](decisions/0005-translation-codex-cli-chatgpt-provider.md) | Codex CLI provider 实现与真实集成已通过 |
| [ADR-0006](decisions/0006-subtitle-rendering-ass-and-burn-in.md) | ASS 排版与烧录契约已实施，仍生效；技术样片已交付，不是最终质量通过 |
| [ADR-0007](decisions/0007-bilingual-semantic-alignment.md) | superseded且未实施的终止历史候选，非完成验收 |
| [ADR-0008](decisions/0008-local-orchestration-and-integration-tests.md) | 已实施生产编排/集中测试总方案，仍是行为入口；语义/核听不判通过 |
| [ADR-0009](decisions/0009-cnbc-editorial-break-annotations.md) | 有来源编辑标记及canonical投影已实现，保留阶段原记录 |
| [ADR-0010](decisions/0010-source-chunking.md) | 初版源分组/预算/发布已实现，当前84/typed由0013修订 |
| [ADR-0011](decisions/0011-contextual-chunk-translation.md) | 上下文分批初译已实现/实跑，质量不由归档签认 |
| [ADR-0012](decisions/0012-bilingual-translation-postprocessing.md) | 有界编辑生成/唯一权威稿/排时已实现，语义残余保留 |
| [ADR-0013](decisions/0013-typed-chunking-quality-and-regression.md) | 84 字符逻辑 cue、typed DP 和回归已实施；修订 ADR-0010，整体质量未通过 |

归档不自动撤销仍生效的契约。2026-11-23 归档 ADR-0006、ADR-0013 与 NB-12 的已结束实施记录，不关闭整体语义/出版质量问题，不将未核听改为已核听。

## 任务

- ADR-0001 的任务仍在其[原归档目录](adr-0001-transcription-sentence-level-alignment/tasks/README.md)。
- TA-01..16（含 TA-03A）、SP-01..15（含 SP-08A）、SR-01..06 共39份任务移至 `tasks/`。
- [TA/SP 历史任务图与依赖](tasks/README.md)原文保留。
- [NB-00～NB-12 交付与诊断记录](tasks/README.md#nb-技术交付固定实验与诊断)：NB-12 技术实施、诊断样片与复用留证已收尾；质量结论见 [NB-12](tasks/NB-12-chunking-quality-iteration.md)。
- TA-10 是 `superseded`，并未执行，也不是验收通过；随已结束的 TA 任务线归档，不再作为待办。
- SP 质量评估和候选任务的 accepted 仅指该实验/技术交付完成，不表示字幕质量通过。
- SR-00、SR-07 及 runner 设计交接已移入归档：技术实现已交付，最终质量未通过，旧验收队列由新方案替代。
  见[历史 SR 任务图](tasks/SR-00-rendering-task-map.md)及[SR-07 验收记录](tasks/SR-07-real-sample-acceptance.md)。
- SA-00 是与本次方案无关的未实施旧队列，已按用户要求删除，不归档为已实现。


## 研究与评审

- [历次评审](reviews/)：旧候选对比、真实样片自审与独审；[用户语义反馈](reviews/2026-10-24-rendering-technical-and-semantic-review.md)和[业界调研](reviews/2026-10-28-industry-bilingual-subtitle-pipelines.md)是方案依据，不是待办。
- [历史探索 prompt](prompts/bilingual-semantic-alignment-exploration.md)：保留原探索范围，不作为当前指令。

## 历史迁移记录

[2026-11-17 保全映射](2026-11-17-document-relocation.json)记录当日 17 份文档的路径、原文及哈希；哈希针对当日快照，不是后续导航调整的校验值。历史授权只适用于各自批次。
