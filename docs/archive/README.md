# 已完成与终止工作的归档

归档日期：2026-10-24。保留历史内容、依赖、验收结果和质量限制；不将旧任务当作现行路线图。

## ADR

| ADR | 归档依据 |
|---|---|
| [ADR-0001](adr-0001-transcription-sentence-level-alignment/decision.md) | transcription 已完成，原归档位置不变 |
| [ADR-0002](decisions/0002-translation-sentence-units.md) | 完整句/section 翻译实现及 Codex CLI 真实集成已通过 |
| [ADR-0003](decisions/0003-srt-processing-input-boundary.md) | 公共字幕契约、v1/v2/v3 技术实现和实验交付完成；语义/阅读质量并未定版 |
| [ADR-0004](decisions/0004-transcription-source-sections.md) | source section 实现与离线/真实集成已通过 |
| [ADR-0005](decisions/0005-translation-codex-cli-chatgpt-provider.md) | Codex CLI provider 实现与真实集成已通过 |

归档不自动撤销仍生效的契约。ADR-0006 的实现子任务完成不等于整份 ADR 最终验收完成，
所以[ADR-0006](../decisions/0006-subtitle-rendering-ass-and-burn-in.md)仍留在进行中目录。

## 任务

- ADR-0001 的任务仍在其[原归档目录](adr-0001-transcription-sentence-level-alignment/tasks/README.md)。
- TA-01..16（含 TA-03A）、SP-01..15（含 SP-08A）、SR-01..06 共39份任务移至 `tasks/`。
- [TA/SP 历史任务图与依赖](tasks/README.md)原文保留。
- TA-10 是 `superseded`，并未执行，也不是验收通过；随已结束的 TA 任务线归档，不再作为待办。
- SP 质量评估和候选任务的 accepted 仅指该实验/技术交付完成，不表示字幕质量通过。
- SR-01..06 的完成记录通过[当前 SR 任务图](../tasks/SR-00-rendering-task-map.md)进入；SR-07 尚未通过，不归档。
