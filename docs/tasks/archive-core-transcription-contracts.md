# 技术任务：archive_core 定义 transcription 公共工件与 DTO

- 任务 ID：`AC-01`
- 优先级：`P0`
- 影响模块：`archive_core`
- 依赖：无
- 被依赖：`AQ-01`、`TR-01`、`TR-02`
- 对应决策：[ADR-0001](../decisions/0001-transcription-sentence-level-alignment.md) §4、§5、§10
- 状态：待实现

## 目标

先建立跨模块稳定契约，使 acquisition、transcription、translation 和 srt_processing 不需要
互相导入内部模型。

## 实现范围

- 为 ADR-0001 的工件补充 `ArtifactType` 和 canonical filename：
  `vad.json`、`raw_asr.json`、`aligned_asr.json`、`transcript_fusion.json`、
  `source_alignment.json`、`transcription.log`、`transcription_report.json` 和
  `transcription_manifest.json`；复用已有 `audio.wav`。
- 定义版本化的结构化英文逐字稿公共 DTO/schema，至少覆盖 chapter、paragraph、可选
  `speaker_label` 和 language。
- 定义 `source_alignment.json` 的公共 DTO/schema：timed words、sentences、来源枚举、边界
  枚举和硬不变量。
- 固定稳定 ID 的格式和序列化规则；时间统一为非负整数毫秒。
- 保持模型纯净，不引入 ffmpeg、WhisperX、pyannote、spaCy 或文件系统重依赖。

## 非目标

- 不实现 acquisition HTML 解析。
- 不实现 transcription provider 或工作流。
- 不定义 translation 或最终 subtitle cue 算法。

## 验收标准

- 所有新增工件都能通过 `canonical_filename()` 和资产工作区解析。
- DTO 可显式往返序列化并拒绝未知 schema version。
- `speaker_label=null` 合法，非字符串非空值被拒绝。
- word/sentence ID、时间范围、连续覆盖、重叠、文本非空和 sentence 首尾时间不变量有单测。
- sentence text 无法从引用 words 按契约重建时被拒绝。
- 无跨模块内部 import 或外部工具依赖。
- 更新 `src/archive_core/AGENTS.md` 中发生变化的公开契约说明。
- `python -m pytest tests/ -q -m "not live"` 全绿。
