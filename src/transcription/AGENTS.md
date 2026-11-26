# transcription AGENTS.md

2026-11-06：生产编排完整转录复用命中全部cache时，复验成功日志/报告/manifest并返回原报告，
不重写任何阶段工件；实际工具身份可只读探测。真实ASR/跨层集成已迁入编排。

## 2026-11-05 ADR-0009 开发交付（待负责人完整验收）

融合结果/声学缓存不改；SentenceBoundaryService在canonical发布前按明确asset source=cnbc及
官网token证据分离保留的U+2014，重建正文，发布source-alignment.v2的无时间annotations。
非CNBC、ASR-only、无官网符号证据、U+2013和U+002D保持；canonical缓存身份绑定标记政策，
不使audio/VAD/ASR/alignment/fusion无故失效。旧schema明确拒绝。
公共factory为transcription.interfaces.build_transcription_handler(output_root=...,runtime=...)，
构造不探测工具/加载模型/读凭据；execute时才preflight并组装现有production能力，不import tests。
定向325 passed / 1 skipped；真实空工作区重跑和全样本标记审核由编排验收，不预称完成。

## 模块定位

`transcription` 负责把已验证的英文源视频转换为带词级时间锚点和完整英文句界的
`source_alignment.json`。详细决策见
`docs/archive/adr-0001-transcription-sentence-level-alignment/decision.md`。

## 职责

- 从 `video.mp4` 提取并持久化规范 `audio.wav`。
- 通过 WhisperX 一体化管线运行 pyannote VAD、英文 ASR 和词级 forced alignment。
- 持久化 VAD、raw ASR、aligned ASR、逐字稿融合、日志、报告和阶段 manifest。
- 有结构化官网英文逐字稿时，本地融合其拼写、标点、句界和可靠 speaker metadata。
- 无官网覆盖时，使用 Whisper 标点、本地 sentence detector 和停顿规则恢复完整句界。
- 从可靠 chapter 映射派生来源无关的 sections，并在 document section 变化处强制完整句界；无法
  可靠派生时发布 `sections=[]`，不阻断有效 words/sentences。
- 校验时间轴、word/sentence 覆盖、溯源、缓存和发布门禁。

## 非职责

- 不使用 LLM，不翻译。
- 不把 VAD region、ASR chunk 或 ASR segment 当作完整句子。
- 不规划字幕 cue，不决定行宽、阅读速度或双语排版。
- 不生成 English/Chinese/Bilingual SRT；SRT 归 `srt_processing`。
- 不做 speaker diarization；只有可靠结构化来源才提供可选 speaker label。

## 分层规则

- `domain/`：VAD region、ASR segment、aligned word、transcript match、timed word、source
  sentence、document section、finding 和纯校验规则。禁止 provider、文件系统、subprocess 和 UI。
- `application/`：验证输入、提取/复用音频、编排 ASR/alignment/fusion/sentence、缓存键、QA、
  阶段状态和结构化事件。只依赖端口，不直接依赖具体工具。
- `infrastructure/`：ffmpeg、WhisperX/pyannote、本地 sentence detector、JSON/file store 和日志
  adapter。
- `interfaces/`：面向 orchestration/CLI 的 command/result、进度事件和摘要。CLI 只过滤与
  展示 WARNING/ERROR 和汇总，不持有业务规则。

## 工件与权威性

- 音频决定是否真的说过；声学对齐决定时间；官网逐字稿优先提供文字/标点/句界；本地规则
  处理无官网区域。
- `source_alignment.json` 是唯一供下游消费的 canonical 内容工件。
- `raw_asr.json`、`aligned_asr.json`、`transcript_fusion.json` 是持久化缓存/诊断工件，不能被
  下游直接消费。
- 所有时间使用原视频时间轴上的非负整数毫秒。
- 所有写入路径使用 `archive_core` 的 workspace 与 canonical filename。

## 事件与报告边界

- application 通过 `TranscriptionEvent` 与 `TranscriptionEventSink` 发出结构化事件；事件必须
  使用稳定 `EventCode`、明确 severity、asset、stage、action 和 reason。相关 ID、原文、结果和
  原视频毫秒范围只在适用时记录。文本字段完整记录传入的文字。
- event `details` 只接受 JSON scalar，敏感配置键（API key、authorization、credential、
  password、secret、token）禁止进入事件或 related IDs。
- `JsonLinesEventSink` 将 DEBUG/INFO/WARNING/ERROR 全部写入详细 JSON Lines 日志；不得在
  adapter 中按用户可见级别过滤。
- `TranscriptionReportAggregator` 只把 WARNING/ERROR 保存为 findings，并始终提供 aligned、
  interpolated、conflict、warning、error 汇总计数、QA 与阶段状态。
- 默认 presenter 只显示 WARNING/ERROR 和阶段汇总。此过滤属于 interfaces 展示逻辑，不得
  复制到 domain/application 或详细日志 adapter。
- 业务失败路径必须通过 `flush_observability_on_failure()` 尽力写出失败事件、刷新详细日志和
  保存可解析 report；任何观测性写入失败都不得替换原始业务异常。

## Audio / VAD / raw ASR 契约

- `AudioVadAsrService` 只接收带上游 manifest 证据的 `SourceVideoInput`；必须在调用 probe、
  ffmpeg、VAD 或 ASR 前验证资产身份、canonical `video.mp4` 路径、成功状态、大小和 SHA-256。
- `AudioExtractionConfig` 固定输出 16 kHz、mono、signed 16-bit PCM `audio.wav`。
  provider 名称、版本和完整结果相关参数必须进入分层 cache key 与 manifest provenance。
- `VadArtifact` 保存原视频绝对毫秒 region，以及 padding/cut-and-merge 后 chunk 到原时间轴的
  等长分段映射；不得把 VAD 当 speaker diarization。
- `RawAsrArtifact` 保存 coarse ASR segment，不把 segment 当 sentence。language 固定 `en`，
  task 固定 `transcribe`；production/development profile 必须进入 cache key，不能共享完成状态。
- cache hit 同时要求成功 manifest record、匹配的 cache key/path/size/SHA-256 和可解析工件。
  单纯文件存在或损坏/过期的 record 不得跳过 provider。已存在但不能复用的昂贵工件只有在
  `AudioVadAsrPolicy(overwrite=True)` 时才可替换；有效上游 cache 仍应复用。
- provider-specific 模型加载只在 infrastructure adapter：WhisperX production 固定
  `large-v3` 并显式使用 pyannote VAD。`PyannoteVadDetector` 和 `WhisperXAsrEngine` 都在首次
  调用时才加载模型；pyannote 4 使用固定 revision 的 segmentation model 组装 VAD，并从 canonical
  PCM WAV 预载内存 waveform，避免依赖 torchcodec 解码。首次真实运行可能下载模型文件，应复用
  本地模型缓存。默认测试必须注入 fake/loader，不联网、不加载模型。

## Forced alignment 契约

- `ForcedAlignmentService` 只消费已经通过 manifest path、size 和 SHA-256 验证的规范
  `audio.wav` 与 `raw_asr.json`；每个 raw ASR lexical word 必须严格保序映射到一个 aligned
  word，稳定 ID 分别为 `rw1..rwN` 与 `aw1..awN`，不得静默丢词或跨 segment 改写文字。
- 标点附着到相邻 lexical word 的表面文本，不作为独立时间单元；`aligned_asr.json` 只保存原
  视频时间轴上的整数毫秒 word timing，不保存 character timing。声学时间必须位于对应 raw
  segment 内，且全局不得越界、倒退或重叠。
- 未对齐 word 仅在数量不超过 policy、原因在 allowlist、左右均为同一 raw segment 的可靠声学
  锚点、窗口不超过上限且为每个 word 提供最小时长时插值。插值结果必须记录双侧 `aw*` 锚点、
  `alignment_score=null` 和 `timing_source=interpolated`；缺单侧锚点、大段缺失、幻觉、时间不足、
  跨 segment、越界或重叠均硬失败，v1 不自动修复。
- alignment cache hit 同时要求 raw ASR SHA-256、alignment provider/model identity、完整配置与
  interpolation policy 匹配，并验证 aligned artifact 的 path、size、SHA-256 与可解析性；命中时
  从缓存 word timing 恢复 aligned/interpolated 汇总，不重放逐词 warning。已有但不可复用的
  `aligned_asr.json` 只有在 `ForcedAlignmentPolicy(overwrite=True)` 时才可替换。
- `WhisperXForcedAligner` 是唯一 provider-specific adapter；首次调用才导入 WhisperX、加载音频与
  alignment model，并显式关闭 character alignment。alignment `model`/`model_version` 分别表示
  Hugging Face repo/revision；adapter 先把 revision 解析为本地 snapshot，再交给不支持 revision
  参数的 WhisperX 3.8.5 loader，禁止只记录版本而仍加载未固定模型。默认测试注入 fake
  backend/resolver，不联网、不加载模型。official-only aligner 使用相同模型解析语义。

## Official transcript fusion 契约

- 融合只读取 `archive_core.interfaces.StructuredTranscriptDTO`：仅 paragraph `text` 生成稳定
  `ot1..otN` spoken token；chapter title、speaker label 与 `stage_directions` 永不作为 spoken
  word。official token 保留 chapter/paragraph 位置和 speaker metadata，供后续句界使用。
- `english-spoken.v2` 对时间、日期、分数、百分比、金额等结构化形式先判等价，保留数值、
  币种与显式精度。官网 token 保留原表面文字，已验证的带时间词可使用 `1.25%`、`3rd` 等排版。
  匹配选择最大的不重叠单调 n-gram 锚点链，超限区间先去相同边缘再寻找局部唯一锚点，
  DP 只比较有界局部窗口。
- 所有 exact、normalized exact、substitution、one-to-many、many-to-one、many-to-many、ASR-only 与
  official-only 词保留完整源 ID。归并依赖可验证的等价读法，多个官网 token 需来自同一章段和
  说话人，`many_to_one` 使用合并的声学区间。经声学验证的替换时间来自候选本身。
- NB-09 默认拼写清单加入 ASR `seas` 与实际官网 `See's` 的单词配对；只有局部 DP 具备
  双侧词汇锚点才可纳入，保留声学时间、ASR ID 和官网 token ID。保留官网拼写的撇号，
  不将普通动词 `sees` 当作该别名；无官网的 identity 路径不改写。清单已纳入融合缓存身份，
  不使 audio/VAD/ASR/alignment 失效。需重新切词或涉及官网编辑插注的疑似专名不自动猜测。
- `monotonic-local-dp.v7` 按顺序对同一段里的差异配对。定位需要至少两个可靠声学匹配，且匹配
  的相对位置在局部窗口内唯一。相邻保留词的声学时间或音频端点限定差异，窗口上限 5 秒。
  句端可使用一侧同章段的定位证据。大段无可靠锚点冲突硬失败。
- 官网连续增词按同一差异组发布，全部取得独立区间且对齐分均达到 `0.20` 可直接写入。完整
  片段复核同时比较含该组和省略该组的上下文，仅在整个候选有声学支持时整组发布。已有 ASR
  词默认保留。弱分差异在完整口述上下文比较保留与省略，确认省略优势和共有词不借时后才删除。
- 同一位置的冲突以相同窗口上的整段 CTC 对数似然比较。定位和时间证据通过后优先官网，ASR
  只有用独立发声稳定支持实际差异时才推翻。候选可共享经独立校验的上下文切点，差异与共有词
  时间一起提交。单个外窗上限为 5 秒，切点扰动为 `40 ms`。能量是发声覆盖的近似，数值和
  强反证门槛为 ADR-0018 的试跑值。
- 两侧数量表达独立规范化，保留币种、精度及来源，等值百分比发布项目统一格式。同一人名
  需要已定位的引介上下文、名字与称呼、结构化身份和原声学时间证据，规范姓氏不改变发言者归属。
- 完整金额在局部计划进入声学裁决前做等值归并，按统一格式及官网尾部标点发布。两侧均为多词时
  记录 `many_to_many` 及完整首尾声学范围。官网证实 `a` 属于数词且与相邻的短弱读 `a` 完整对应
  时一并归入金额。缺少显式币种证据的 `pounds` 保留原单位。
- `transcript_fusion.json` v3 仅官网路径持久化，正文为 `words`，并记录官网词表、非口述内容、
  排除词、对齐验证和只含来源 ID 的 `official_sentence_spans`。`excluded_asr` 记录经验证移出的
  ASR ID、原词时间及原因。写入和复用都需按原顺序完整对账。没有 `chapters.json` 时返回
  aligned ASR identity words，不写融合文件，也不逐词发 ASR-only warning。
- fusion cache key 包含 aligned ASR SHA-256、chapters SHA-256、normalization/matching policy 与
  local aligner provider/model/config。cache hit 仍须校验 manifest status、canonical path、size、
  SHA-256 和可解析工件；stale fusion 只有显式 `TranscriptFusionPolicy(overwrite=True)` 才可替换，
  不得使 audio/VAD/raw ASR/alignment cache 失效。

## Sentence boundary 与 canonical 契约

- `SentenceBoundaryService` 同时消费已经验证的 `ForcedAlignmentResult` 与
  `TranscriptFusionResult`。官网路径必须验证 canonical `transcript_fusion.json` 的 manifest
  status/path/size/SHA-256、cache key 和 aligned checksum chain；无官网路径必须严格等于 aligned
  ASR identity projection，不允许伪造或跳过 fusion 决策。
- 官网映射 word 的 `. ? !` 经过版本化的省略号、缩写、姓名首字母和域名点号例外后是 verified boundary；
  reliable speaker 变化强制切句。paragraph 变化、ASR segment 变化和固定 pause 都只是弱信号，
  不得各自单独切句。
- 无官网或 ASR-only 区域综合 ASR 标点、`SentenceBoundaryDetector`、pause 与 segment 弱提示。
  ASR segment 可跨句也可被一句跨越；任何切分都不得使用字幕行宽、阅读速度或 cue 时长。
- `official_sentence_spans` 提供官网边界的来源 ID。可靠定位的官网句内使用官网标点，
  官网句末缺少独立词时间时，仅在最后一个带时间词完整属于该句且有官网映射时设置边界。
- 无标点异常长文本只由 `sentence-boundary.v2` fallback policy 处理。fallback 数量/比例超过
  policy 门禁时保留 boundary findings 与失败事件，但不得发布 `source_alignment.json`。
  当前 policy 数值是 TR-05 的版本化离线基线；如未来 orchestration 集成验收调整数值，必须升级
  policy 并使 sentence cache stale。
- canonical 发布前必须构造并 round-trip `archive_core.interfaces.SourceAlignmentDTO`，让公共 DTO
  校验稳定 ID、整数毫秒、时间单调、连续且恰好一次的 sentence 覆盖、冗余首尾时间和可重建文字。
  `speaker_label` 只来自映射后的结构化官网 token；identity/YouTube 路径保持 `null`。
- sentence cache key 包含 fused/aligned 输入 SHA-256、official/identity mode、detector identity 和
  完整 boundary/section policy 及 chapter 输入 checksum。cache hit 仍须验证 canonical
  path/size/SHA-256 与公共 DTO；stale canonical 只有
  `SentenceBoundaryPublicationPolicy(overwrite=True)` 时才可替换。
- timed word 的 effective document section 由 OT chapter 映射和显式 ASR-only fallback 规则产生；
  section 变化是独立 verified 句界信号。非空 sections 必须使用 `sec1..secN` 连续、无重叠且恰好
  一次覆盖全部 sentences，并保留 chapter 标题；任一 section-only 门禁失败时整体回退空数组。
- 本阶段唯一内容输出是 `source_alignment.json`，同时更新 transcription manifest 的
  `source_alignment` record；不生成任何 SRT 或 cue plan。

## 技术方向

- 生产 ASR 固定 WhisperX + Whisper `large-v3` + pyannote VAD，`language=en`、
  `task=transcribe`，质量优先；具体版本与设备参数必须进入 provenance/cache key。
- transcription 不调用 LLM。
- 只持久化词级时间，不保存字符级时间。
- 未对齐词只在少量、可解释且有可靠双侧锚点时插值，并显式标记。
- 官网独有词必须通过局部声学对齐才能进入时间轴；ASR-only 已对齐词默认保留。
- 成功昂贵工件不得自动删除或静默覆盖；替换必须由用户显式授权。
- manifest/checksum 决定完成状态，文件存在不是完成判据。
- 详细事件全部写日志；CLI 只显示 WARNING/ERROR 和阶段汇总。

## 测试方向

- provider、ffmpeg、文件系统与日志均通过可注入端口离线 fake。
- 单元测试覆盖时间轴、插值、融合映射、speaker、句界、日志和 cache stale 传播。
- 默认 pytest 不访问网络、不运行 ffmpeg、不加载 WhisperX/pyannote 模型。
- 真实模型测试必须显式门控；当前模块只维护 CNBC live integration，完整跨模块管线由未来
  orchestration 集成测试覆盖。

## 当前实现与 integration 状态（2026-10-15）

- TR-01～TR-06 的 application workflow、分层 cache、manifest、失败保留与 provider-neutral
  command/result 已实现，并由 fake provider 离线测试覆盖；`source_alignment.json` 可作为
  transcription 的 canonical 输出，但仓库仍没有面向人的 CLI 入口。
- live 入口是 `tests/transcription/test_integration_live.py`；默认跳过，设置
  `RUN_TRANSCRIPTION_INTEGRATION=1` 后，从空 `output/` 自动准备 CNBC canonical 上游输入并运行
  真实 WhisperX。准备步骤使用 acquisition/media adapter 生成 fixture，不代表完整 orchestration。
- 所有输入和 transcription 工件统一保存在
  `output/transcription-integration/cnbc_2000_morning/`；第二次运行必须通过 manifest 命中 audio、
  VAD、raw ASR、alignment、fusion 和 source alignment 六层缓存。
- ADR-0004 的 CNBC integration 已从空 workspace 真实完成：2000 上午场连续第 6、7 节
  `35:01`～`45:24` 从 `video.mp4` 跑到 `source_alignment.json`，产出 1,564 words、97 sentences
  和两个连续完整 section（`s1..s52`、`s53..s97`），标题与 chapter 6/7 一致；report succeeded
  且 error 为 0，canonical SHA-256 为
  `99f36287d28d0581ae039f64eeea55c14bef044dbb87fdca2f9c8d26ad7fbf91`。
- 同一次 live 测试的第二次运行通过 manifest 命中 audio、VAD、raw ASR、alignment、fusion 和
  source alignment 六层缓存，canonical checksum 保持不变；测试同时验证所有 canonical 中间
  产物可解析、section 覆盖及 chapter 6→7 的 verified 句界。
- 当前 CNBC-only 连通性验收已完成。transcription 的 reference-based Golden Live 入口已移除；
  integration 输出不是人工真值，未来全管线连通性由 orchestration 集成测试负责。
