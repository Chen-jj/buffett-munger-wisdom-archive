# archive_core AGENTS.md

## 模块定位

`archive_core` 持有全仓库共享的领域原语与契约，是其他所有模块都可以安全依赖的基础。

## 职责

- 存放各模块都能安全共享的基础领域模型：资产身份、工件与命名契约、工作区路径策略、管线状态、溯源等横切领域概念。
- 判据：与具体站点、外部工具无关且被多个模块需要 → 放这里；只属于单个管线阶段的业务概念 → 放对应功能模块。
- 本模块的规则必须保持纯：不依赖 HTTP、ffmpeg、OpenAI 兼容 API 或 Web UI。

## 分层规则

- `domain/`：值对象、实体、校验策略、命名规则、工件状态流转。
- `application/`：仅当用例真正跨模块时才放这里，如解析资产工作区、校验工件 manifest。
- `infrastructure/`：读写核心 manifest 的最小共享适配器（仅当不属于某个具体功能模块时）。
- `interfaces/`：供 CLI、Web UI、review、orchestration 使用的 DTO 与序列化器。

## 技术方向

- 领域概念优先用 dataclass 或小型类型化对象。
- 序列化保持显式且有版本号；避免跨模块裸传 dict。
- 本模块避免重依赖。

## Transcription 公共契约

- `ArtifactType` 统一定义 transcription 的规范工件名：`audio.wav`、`vad.json`、
  `raw_asr.json`、`aligned_asr.json`、`transcript_fusion.json`、`source_alignment.json`、
  `transcription.log`、`transcription_report.json` 和 `transcription_manifest.json`。
- `archive_core.interfaces` 发布 `acquisition.transcript.v2` 的
  `StructuredTranscriptDTO`，chapter 下的 paragraph 显式区分 spoken `text` 与可空
  `speaker_label`，并以有序 `stage_directions` 保存不属于 spoken text 的舞台说明；纯舞台
  说明 paragraph 使用空 `text`，但 paragraph 的 `text` 和 `stage_directions` 不得同时为空。
  当前语言固定为 `en`。
- 同一入口发布 `transcription.source-alignment.v1` 的 `SourceAlignmentDTO`、
  `TimedWordDTO`、`SourceSentenceDTO`、`SourceSectionDTO` 及其来源/边界枚举。schema 记录
  `audio_duration_ms`，所有时间为原音频时间轴上的非负整数毫秒。
- timed word 与 sentence 的稳定 ID 分别严格使用文档顺序的一基格式 `w1..wN`、
  `s1..sN`。sentence 必须连续且恰好覆盖所有 words，冗余首尾时间必须匹配引用 word，
  文本按公共空格/标点规范可从引用 words 重建。
- source alignment 必须显式提供 `sections`；空列表表示没有可靠分组，非空时使用
  `sec1..secN`，连续且恰好一次覆盖全部 sentences。文档结构强制形成的句界使用
  `document_section_change` provenance。
- 版本化 DTO 只通过显式 `to_dict()` / `from_dict()` 进行 JSON 形状往返，未知版本必须失败。

## Translation 公共契约

- `ArtifactType` 统一定义 `translation_result.json` 与 `translation_manifest.json`。
- `archive_core.interfaces` 发布 provider-neutral 的 `translation.result.v1`：只保存 source
  alignment checksum、固定语言、按源顺序排列的 section 标题译文和 sentence 译文；完整覆盖需
  通过 `SourceAlignmentDTO` 校验。
- 同一入口发布严格审计用的 `translation.manifest.v1`：只描述成功工件，并记录输入/输出证据、
  prompt/glossary/provider/model/生成参数及本次执行计数和可空 token usage。生成参数是
  provider-neutral 的有限 JSON object，完整绑定 manifest provenance 与 checkpoint identity。

## 当前实现状态（2026-10-16）

- transcription 的 source section 扩展及 translation result/manifest 公共契约均已实现，并由离线
  schema、round-trip、覆盖和交叉校验测试验证。
- translation provider-neutral manifest 已由 OpenAI 与 Codex CLI 两种 identity 的离线测试验证；
  公共契约不负责 provider 选择。TA-10 已被取代且未运行；TA-16 已验证真实 Codex identity、
  输入/输出 checksum、可空 usage 与 byte-identical 正式工件复用。
