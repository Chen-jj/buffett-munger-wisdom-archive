# transcription AGENTS.md

## 模块定位

`transcription` 负责把已验证的英文源视频转换为带词级时间锚点和完整英文句界的
`source_alignment.json`。详细决策见
`docs/decisions/0001-transcription-sentence-level-alignment.md`。

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
- 真实模型测试必须显式门控，并使用 CNBC/YouTube golden sample 记录量化结果。
