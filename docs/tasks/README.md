# 技术任务索引

本目录把已接受的架构决策拆成可独立验证的小任务。优先级含义：

- `P0`：契约或安全前置，不完成会阻塞主要实现。
- `P1`：核心生产链路。
- `P2`：依赖核心链路的业务能力。
- `P3`：组装、真实评测和阶段验收。

## Transcription Phase 1 任务图

```text
MD-01 media_download 已有工件验证 ─────────────────────────────┐
                                                               │
AC-01 archive_core 公共契约 ─┬─▶ AQ-01 结构化逐字稿             │
                             │          │                       │
                             ├─▶ TR-01 可观测性                 │
                             │          │                       │
                             └──────────┴─▶ TR-02 音频/VAD/ASR  │
                                               │               │
                                               ▼               │
                                         TR-03 forced alignment│
                                               │               │
                             AQ-01 ─────────────┤               │
                                               ▼               │
                                         TR-04 官网融合         │
                                               │               │
                                               ▼               │
                                         TR-05 句界/canonical   │
                                               │               │
MD-01 ─────────────────────────────────────────┴───────────────┤
                                                               ▼
                                               TR-06 工作流/缓存/integration
```

## 任务清单

| ID | 优先级 | 任务 | 直接依赖 |
|---|---|---|---|
| `MD-01` | P0 | [media_download 跳过前验证已有工件](media-download-validate-existing-artifact-before-skip.md) | 无 |
| `AC-01` | P0 | [archive_core transcription 公共契约](archive-core-transcription-contracts.md) | 无 |
| `AQ-01` | P0 | [acquisition 结构化官网逐字稿](acquisition-structured-transcript-contract.md) | `AC-01` |
| `TR-01` | P0 | [transcription 事件、日志与报告](transcription-observability.md) | `AC-01` |
| `TR-02` | P1 | [transcription 音频、VAD 与 ASR](transcription-audio-vad-asr.md) | `AC-01`、`TR-01`；集成依赖 `MD-01` |
| `TR-03` | P1 | [transcription WhisperX forced alignment](transcription-forced-alignment.md) | `TR-02` |
| `TR-04` | P2 | [transcription 官网逐字稿融合](transcription-official-transcript-fusion.md) | `TR-03`、`AQ-01` |
| `TR-05` | P2 | [transcription 本地句界与 canonical 输出](transcription-sentence-boundaries.md) | `TR-03`、`TR-04` |
| `TR-06` | P3 | [transcription 工作流、缓存与 integration 验收](transcription-workflow-manifest-integration.md) | `MD-01`、`AQ-01`、`TR-01`～`TR-05` |

`MD-01` 可与 `AC-01` 并行。`AQ-01` 与 `TR-01` 可在 `AC-01` 后并行。每个任务只实现自己的
切片；不得为了提前跑通整条管线把后续任务的业务规则塞进当前任务。
