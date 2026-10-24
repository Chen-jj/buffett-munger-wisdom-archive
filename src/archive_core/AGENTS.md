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

## Subtitle 公共契约

- `ArtifactType` 统一定义 `subtitle_plan.json`、`bilingual.srt`、
  `srt_processing_report.json` 与 `srt_processing_manifest.json`；沿用 `english.srt`、
  `chinese.srt`，不新增路径层级。
- `archive_core.interfaces` 发布 `subtitle.plan.v1` 的 `SubtitlePlanDTO`、cue/fragment、
  media/rules/timing DTO。plan 只存逻辑中英正文、顺序 `c1..cN`、原始词/译文字符范围、
  原 speaker（包括 `null`）、内容指纹和确定性规则身份；不含视觉 lines、finding 或执行时间。
- `SubtitlePlanDTO.validate_against_inputs(alignment, translation)` 核对公共输入的句子/section、
  源词与规范化中文范围顺序且恰好覆盖一次、正文重建、speaker 原值和词时间锚点。
  中文多片段显示正文是各原始范围去首尾 ASCII 空格后直接连接；范围本身仍保留空白。
- `subtitle_text` 的公共 `normalize_chinese_text()` 使用冻结布局空白表；
  `character_boundaries()` 使用冻结 Unicode 14 mark 表保护组合标记、variation selector、
  ZWJ 与 emoji modifier 序列。此边界保护不是完整 Unicode grapheme segmenter。
  `is_combining_mark()`、`is_layout_whitespace()` 供消费方复用同一固定分类。
- `srt-processing.report.v1` 保存严格 finding 定位、原始/最终时间、有限 JSON 观察值和固定
  统计项；成功 report 不得包含 error。`srt-processing.manifest.v1` 只描述成功发布，固定
  五项输入证据和五项输出证据，所有证据使用规范文件名、正大小和小写 SHA-256。
- manifest 使用 `SubtitleProfileDTO` 保存完整且冻结的参数，`sha256` 按 UTF-8、
  `ensure_ascii=False`、`sort_keys=True`、紧凑分隔符序列化计算；rules 必须匹配该参数身份。
  另显式绑定媒体探测值、ffprobe 版本/配置、pysubs2 1.8.1 与固定 SRT 序列化配置。
  `SrtProcessingManifestDTO.validate_against_plan()` 核对 plan 的输入指纹、规则、媒体和 cue 数。
- SP-11 候选 profile `v2` 精确增加 `english_line_capacity`、`english_max_lines` 与中文
  分词 engine/dictionary SHA-256/mode 三项身份；旧 `v1` 仍按原字段集合严格解析、序列化和
  计算指纹，不能补默认字段把旧工件伪装为新版本。未知 profile 版本失败。
- `SubtitleCodecDTO` 候选显式绑定 `serialization_version=word-wrap-english-2x42.v2`；
  旧版缺该字段的形状仍可精确往返，但不等于候选身份。此扩展不改变 plan/manifest schema，
  plan 正文仍无换行；英文一/两行和双语中文一行加英文一/两行仅属于 SRT 的计数行预算投影，
  不代表字体、像素或烧录排版验收。
- SP-14 候选 profile `v3` 以 `chinese_target_half_units`、`target_duration_ms` 替代旧
  `chinese_capacity_half_units`、`maximum_duration_ms`，明确中文16与显示7秒仅为软目标；
  不加入其他硬时长上限。`v1/v2` 仍精确保留原字段集合、指纹和序列化，不补别名或默认字段。
  英文2×42仍硬限制，中文仍一逻辑行；分词身份和现有codec序列化身份沿用。
- v3超目标观察值继续通过通用report finding表达，无需升级plan/report/manifest schema：
  `reading.chinese_length`记录`half_units/target_half_units`，`timing.target_duration`记录
  最终显示`duration_ms/target_duration_ms`。产生与重算warning是`srt_processing`的职责，
  本模块仅验证结构，不把16、7秒或9CPS重新解释为公共DTO硬门禁。
- 上述契约只负责公共结构、文本范围和机械交叉校验。容量、CPS、合并资格、动态规划及结束
  时间调整业务仍属于 `srt_processing`；本模块不得反向 import 其实现。

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
