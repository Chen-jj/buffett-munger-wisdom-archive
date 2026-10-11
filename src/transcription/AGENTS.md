# transcription AGENTS.md

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
- 校验时间轴、word/sentence 覆盖、溯源、缓存和发布门禁。

## 非职责

- 不使用 LLM，不翻译。
- 不把 VAD region、ASR chunk 或 ASR segment 当作完整句子。
- 不规划字幕 cue，不决定行宽、阅读速度或双语排版。
- 不生成 English/Chinese/Bilingual SRT；SRT 归 `srt_processing`。
- 不做 speaker diarization；只有可靠结构化来源才提供可选 speaker label。

## 分层规则

- `domain/`：VAD region、ASR segment、aligned word、transcript match、timed word、source
  sentence、finding 和纯校验规则。禁止 provider、文件系统、subprocess 和 UI。
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
  使用稳定 `EventCode`、明确 severity、asset、stage、action 和 reason。相关 ID、文本摘录与
  原视频毫秒范围只在适用时记录。
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
- `english-spoken.v1` normalization 只用于匹配，surface text 始终保留；规则显式覆盖大小写、
  标点、数字/年份、百分比、货币、连字符和 contraction。匹配先使用唯一且单调的连续 n-gram
  anchor，再只在受限局部窗口运行 DP，不做整场逐字稿大矩阵或 LLM 推断。
- exact、normalized exact、双侧锚定且由 policy 显式 allowlist 授权的拼写 substitution、
  one-to-many、many-to-one、ASR-only 与 official-only 都必须保留完整 source IDs。字符串相似
  不能证明 substitution（如 million/billion）；折叠仅在 normalization units 证明等价时允许，
  one-to-many 不得跨 chapter、paragraph 或 speaker，many-to-one 不得把 interpolated timing
  伪报成 merged acoustic。已对齐 ASR-only word 始终保留并记录。
- official-only run 仅在真正包围该 run 的最近两侧 n-gram anchor 全部是达到配置 score 阈值的
  acoustic timing、speaker 不跨界、窗口合法，且 `OfficialTranscriptAligner` 返回
  数量/顺序/文字/时间/score 全部
  合格时整体恢复；否则全部排除
  并保留诊断。单侧锚点、interpolated anchor、越界、重叠、部分返回或低分不得伪造时间；大段
  无可靠锚点冲突硬失败。
- `transcript_fusion.json` 仅官网路径持久化，记录 official token table、所有 timed mapping、
  ignored non-spoken content、排除内容与局部声学校验。没有 `chapters.json` 时返回 aligned ASR
  identity words，不写 fusion 文件，也不逐词发 ASR-only warning。
- fusion cache key 包含 aligned ASR SHA-256、chapters SHA-256、normalization/matching policy 与
  local aligner provider/model/config。cache hit 仍须校验 manifest status、canonical path、size、
  SHA-256 和可解析工件；stale fusion 只有显式 `TranscriptFusionPolicy(overwrite=True)` 才可替换，
  不得使 audio/VAD/raw ASR/alignment cache 失效。

## Sentence boundary 与 canonical 契约

- `SentenceBoundaryService` 同时消费已经验证的 `ForcedAlignmentResult` 与
  `TranscriptFusionResult`。官网路径必须验证 canonical `transcript_fusion.json` 的 manifest
  status/path/size/SHA-256、cache key 和 aligned checksum chain；无官网路径必须严格等于 aligned
  ASR identity projection，不允许伪造或跳过 fusion 决策。
- 官网映射 word 的 `. ? !` 经过版本化 abbreviation/name-initial 例外后是 verified boundary；
  reliable speaker 变化强制切句。paragraph 变化、ASR segment 变化和固定 pause 都只是弱信号，
  不得各自单独切句。
- 无官网或 ASR-only 区域综合 ASR 标点、`SentenceBoundaryDetector`、pause 与 segment 弱提示。
  ASR segment 可跨句也可被一句跨越；任何切分都不得使用字幕行宽、阅读速度或 cue 时长。
- 无标点异常长文本只由 `sentence-boundary.v1` fallback policy 处理。fallback 数量/比例超过
  policy 门禁时保留 boundary findings 与失败事件，但不得发布 `source_alignment.json`。
  当前 policy 数值是 TR-05 的版本化离线基线；如未来 orchestration 集成验收调整数值，必须升级
  policy 并使 sentence cache stale。
- canonical 发布前必须构造并 round-trip `archive_core.interfaces.SourceAlignmentDTO`，让公共 DTO
  校验稳定 ID、整数毫秒、时间单调、连续且恰好一次的 sentence 覆盖、冗余首尾时间和可重建文字。
  `speaker_label` 只来自映射后的结构化官网 token；identity/YouTube 路径保持 `null`。
- sentence cache key 包含 fused/aligned 输入 SHA-256、official/identity mode、detector identity 和
  完整 boundary policy。cache hit 仍须验证 canonical path/size/SHA-256 与公共 DTO；stale canonical
  只有 `SentenceBoundaryPublicationPolicy(overwrite=True)` 时才可替换。
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

## 当前实现与 integration 状态（2026-10-12）

- TR-01～TR-06 的 application workflow、分层 cache、manifest、失败保留与 provider-neutral
  command/result 已实现，并由 fake provider 离线测试覆盖；`source_alignment.json` 可作为
  transcription 的 canonical 输出，但仓库仍没有面向人的 CLI 入口。
- live 入口是 `tests/transcription/test_integration_live.py`；默认跳过，设置
  `RUN_TRANSCRIPTION_INTEGRATION=1` 后，从空 `output/` 自动准备 CNBC canonical 上游输入并运行
  真实 WhisperX。准备步骤使用 acquisition/media adapter 生成 fixture，不代表完整 orchestration。
- 所有输入和 transcription 工件统一保存在
  `output/transcription-integration/cnbc_2000_morning/`；第二次运行必须通过 manifest 命中 audio、
  VAD、raw ASR、alignment、fusion 和 source alignment 六层缓存。
- CNBC integration 已真实完成：gitignore 的 2000 上午场第 3 节 `11:48`～`21:40` 样本从
  `video.mp4` 跑到 `source_alignment.json`，产出 1,544 words、94 sentences、97.28% 官网词覆盖，
  时间轴单调且 report succeeded。实跑同时验证了固定 revision 模型、本地 HF 登录、NLTK 数据和
  断点 cache；`tests/transcription/test_integration_live.py` 验证所有 canonical 中间产物可解析。
- 当前 CNBC-only 连通性验收已完成。transcription 的 reference-based Golden Live 入口已移除；
  integration 输出不是人工真值，未来全管线连通性由 orchestration 集成测试负责。
