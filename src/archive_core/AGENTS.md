# archive_core AGENTS.md

## 2026-11-05 新路径公共契约开发交付（待负责人完整验收）

`interfaces.bilingual` 已定义当前唯一新链路的 SourceChunkPlanDTO、ChunkTranslationResultDTO、
FinalBilingualDraftDTO、StageManifestDTO，以及严格证据/实际帧PTS/保护跨度/只读预算。
`interfaces.bilingual_timing` 统一冻结中文混排计数（unicode14-latin-word.v2）、含空格标点的
英文码点计数、[start,end)实际帧间隔及可借上界。指标warning不由DTO升级为硬错误。
转录schema已直接替换为transcription.source-alignment.v2，annotations必需序列化且无发音时间。
新增规范工件及build_pipeline_run_path纯路径函数；不在core运行文件/工具/模型。
开发过渡期间旧字幕/译文DTO待下游切换后移除，不宣称旧生产路径已替换完毕。
本片定向325 passed / 1 skipped；完整离线与下游/真实集成尚待负责人与后续切片验收。
实施直接替换旧版，不留兼容解析器；旧集成产物已按授权清理；后续由编排完整生成，不建设旧格式导入。

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

## Subtitle rendering 公共契约（SR-01，2026-10-24 00:00 CST 核对）

- 已增加 ADR-0006 的四个独立 rendering 工件类型及规范文件名，沿用既有 `RENDERED_VIDEO`。
- `archive_core.interfaces.rendering` 和公共导出发布严格的 profile/font/tool/media、视觉断点、
  plan/report/成功 manifest DTO；显式版本化序列化拒绝未知字段、未知版本和非有限数值。
- render plan 对公共 `SubtitlePlanDTO` 验证原毫秒时间、逻辑正文 SHA-256、code-point offset
  与重建；保留原始正文及空白，不依赖 SRT。ASS 显示时间按用户批准的
  `nearest-centisecond-half-up.v1` 投影，单边误差不超过 5ms，必须保持正时长、不重叠、不越界。
- profile hash、字体 PostScript name/face/文件指纹、完整工具身份、微秒媒体描述、严格 tags /
  chapters 和固定主视频/全部音频映射进入审计；manifest 与 plan/report 交叉验证，不以文件
  存在代替完成。布局搜索、字体读取、像素渲染、媒体 QA 和实际发布仍属于 rendering 模块。
- 本轮定向契约 188 passed，连同既有核心/字幕契约 344 passed；当时完整离线为
  1592 passed / 5 skipped。这里只记录开发验证，负责人验收及 rendering 下游实现另行记录，
  不代表已经生成 ASS、成片或完成像素/出版质量验收。

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

## 当前 Subtitle 公共契约（2026-11-06）

- `archive_core.interfaces.bilingual` 发布独立英文候选、分块初译、权威双语最终稿、
  已识别保护范围、实际媒体帧、证据及阶段 manifest DTO，拒绝旧形状，不提供兼容分支。
- `FinalBilingualDraftDTO` 是 SRT/ASS 唯一内容和毫秒权威，中文不要求等于旧译文切片。
  词覆盖/锚点/时序/来源错误阻断；可读性指标 warning 不改变内容。
- `archive_core.interfaces.subtitles` 当前仅保存严格 `SrtExportReportDTO`。旧比例 plan、
  多版本 profile/codec 和 SRT 旧 manifest 已直接替换，不保留生产读取入口。
- `bilingual_timing` 发布同一版本化计数和实际 decoded frame PTS 的半开区间规则；
  决策算法仍归阶段模块。Rendering 继续发布独立视觉计划与执行报告，布局和像素 IO 不归 core。
- 公共渲染计划绑定 `pixel-wrap.v4`（保留中文词边界软择优并保护紧密 `8盎司`/`8000万份`，分词依赖/词典绑定 measurement identity）；复验仅权威中文 cue 原有首码点 U+2026 可出现在
  首视觉行。ASS 投影间隔告警定位仍绑定关联 cue 原始毫秒，投影证据放诊断。

## 当前实现状态（2026-10-23 04:07 CST）

- transcription 的 source section 扩展及 translation result/manifest 公共契约均已实现，并由离线
  schema、round-trip、覆盖和交叉校验测试验证。
- translation provider-neutral manifest 已由 OpenAI 与 Codex CLI 两种 identity 的离线测试验证；
  公共契约不负责 provider 选择。TA-10 已被取代且未运行；TA-16 已验证真实 Codex identity、
  输入/输出 checksum、可空 usage 与 byte-identical 正式工件复用。
- ADR-0003 的公共字幕工件、严格 DTO、冻结文本边界及输入交叉校验已实现，并通过离线
  round-trip、未知字段/版本、类型、覆盖顺序、speaker/section/时间和 manifest 证据测试。
  本轮 SP-01..07 的 `srt_processing` workflow 与离线跨层验收也已通过（完整离线1220 passed /
  5 deselected）；公共契约自身仍不是阶段完成证明。用户授权的 SP-08A 已持久补齐正式译文，
  CNBC 真实技术集成通过242 cues生成、即时与独立进程复用、19份上游不变及六输出bytes/mtime
  不变验证。负责人/agent文本审读不是人类签字或语义/出版级/像素质量证明，已知比例错位与
  应急拆词限制见 [SP-08](../../docs/archive/tasks/SP-08-real-sample-and-final-status.md)。
- SP-11 已加入候选 v2 profile 和 codec 身份的最小兼容扩展，旧 profile/hash/codec 形状保持；
  公共契约、多行 codec、workflow 与完整离线套件已通过。候选仅为用户授权试验，真实隔离
  样本验收由 SP-10..12 统一记录，不表示最终字幕质量通过。
- SP-14 v3公共profile扩展及v1/v2黄金hash、manifest往返和严格参数测试已通过；与SP-13的
  domain目标告警、workflow/codec跨层定向及完整离线集成已通过（1395 passed / 5 deselected），
  真实样本与负责人最终验收由SP-15统一记录，不宣称候选质量已通过。
