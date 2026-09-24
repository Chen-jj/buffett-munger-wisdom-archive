# ADR-0001：transcription 采用 WhisperX 词级对齐、官网逐字稿融合与本地句界恢复

- 状态：已接受，待实现
- 首次提出：2026-09-14
- 接受日期：2026-09-24
- 影响模块：`archive_core`、`acquisition`、`transcription`、`infrastructure`
- 下游模块：`translation`、`srt_processing`
- 所属阶段：Phase 1

## 1. 决策摘要

`transcription` 把经过验证的 `video.mp4` 转换为带词级时间锚点和完整英文句界的
`source_alignment.json`。生产 ASR 使用 WhisperX 一体化管线，固定英文识别、质量优先，
不使用 LLM。

```text
video.mp4
  → audio.wav
  → pyannote VAD
  → Whisper large-v3 ASR
  → raw_asr.json
  → WhisperX forced alignment
  → aligned_asr.json
  → 官网逐字稿本地融合（可选输入，CNBC 路径）
  → transcript_fusion.json（有官网逐字稿时）
  → 本地句界恢复
  → source_alignment.json
```

本 ADR 接受以下边界：

- `transcription` 负责音频提取、VAD、英文 ASR、词级声学对齐、官网英文逐字稿融合、
  本地句界恢复、QA、缓存、日志和阶段 provenance。
- `transcription` 不调用 LLM，不翻译，不规划字幕 cue，不生成任何 SRT。
- `source_alignment.json` 是本模块唯一供下游消费的 canonical 内容工件。
- `english.srt`、`chinese.srt` 和 `bilingual.srt` 由 `srt_processing` 从最终 cue plan 投影。
- 所有时间使用原视频时间轴上的非负整数毫秒。
- 昂贵和诊断工件持久化；不得因文件存在就判定阶段完成，也不得静默覆盖或删除。

## 2. 背景与术语

ASR/VAD segment 是处理窗口或解码边界，不保证是完整语言句子：

```text
ASR segment 1: I think the most important thing
ASR segment 2: when you're evaluating a business
ASR segment 3: is to understand its competitive position.

完整句子：
I think the most important thing when you're evaluating a business
is to understand its competitive position.
```

必须区分：

```text
VAD region       = 检测到语音的时间范围
ASR chunk        = 为模型计算组织的音频块
ASR segment      = Whisper 解码处理单元
ASR word         = WhisperX 声学对齐前后的识别词
timed word       = 融合后供下游使用的最小时间文本单元
sentence         = 完整英文句子，也是 translation 的翻译单元
subtitle cue     = srt_processing 决定的最终显示单元
```

这些概念不要求一一对应，尤其禁止把 ASR segment 直接当作 sentence 或 subtitle cue。

## 3. 权威来源

不同输入只在各自擅长的范围内权威：

```text
音频                    是否真的说过某段内容
WhisperX 声学对齐        时间位置
CNBC 官网英文逐字稿      拼写、大小写、标点、句界和可选 speaker 标签
本地句界算法             无可靠官网覆盖区域的句界
```

官网逐字稿相对正确，但可能删掉口头语、修正文法、补写内容、遗漏片段或与视频剪辑版本
不完全一致。因此它不能无条件覆盖音频，也不能给未验证的官网文本伪造时间。

## 4. 输入契约

| 输入 | 必需 | 说明 |
|---|---:|---|
| `video.mp4` | 是 | 来自 `media_download`；必须验证成功 manifest、路径、大小和 SHA-256 |
| `chapters.json` | 否 | 结构化官网英文逐字稿；CNBC 路径使用，YouTube 通常没有 |
| ASR/VAD/对齐配置 | 是 | 模型身份、版本、设备、精度、VAD 和 alignment 参数 |
| 句界配置 | 是 | 缩写规则、停顿规则、fallback 与 QA policy 版本 |
| 执行策略 | 是 | dry-run、缓存和显式替换策略 |

`transcript.txt` 是人工查看和归档格式，不是 transcription 的机器输入。机器输入使用
结构化 `chapters.json`。

### 4.1 结构化官网逐字稿

`acquisition` 应发布版本化、来源无关的结构化契约，示意如下：

```json
{
  "schema_version": "acquisition.transcript.v2",
  "language": "en",
  "chapters": [
    {
      "number": 1,
      "title": "Opening Remarks",
      "paragraphs": [
        {
          "speaker_label": "WARREN BUFFETT",
          "text": "Good morning. We welcome shareholders to the annual meeting."
        }
      ]
    }
  ]
}
```

- chapter title、speaker label 和舞台说明不作为 spoken words 送入对齐器。
- `speaker_label` 是通用可选字段；YouTube 或无法可靠识别的来源写 `null`。
- CNBC 页面格式知识属于 `acquisition.infrastructure`，不得进入 transcription。
- transcription 不用正则重新解析 CNBC 专用的 `SPEAKER: text` 格式。
- 公共 DTO/schema 放在 `archive_core`，两个功能模块不得互相导入内部实现。

## 5. 输出与持久化工件

| 文件 | 角色 | 是否供下游消费 |
|---|---|---:|
| `audio.wav` | 16 kHz、mono、PCM 的可复用派生音频 | 否 |
| `vad.json` | pyannote VAD region、参数与原时间映射 | 否 |
| `raw_asr.json` | WhisperX/Whisper 原始 segment 结果和缓存 | 否 |
| `aligned_asr.json` | 词级声学对齐结果和 alignment score | 否 |
| `transcript_fusion.json` | ASR 与官网 token 映射及取舍；仅官网路径 | 否 |
| `source_alignment.json` | 完整 timed words 与 sentences | **是，canonical** |
| `transcription.log` | 全级别详细结构化事件日志 | 否 |
| `transcription_report.json` | 汇总、findings、QA 和阶段状态 | 否 |
| `transcription_manifest.json` | 输入输出 checksum、工具、模型、参数和状态 | 否 |

`raw_asr.json`、`aligned_asr.json` 与 `transcript_fusion.json` 是持久化缓存/诊断工件，
不是跨模块业务契约。它们不得被 translation 或 srt_processing 直接消费。

所有文件名和公共 schema 必须先在 `archive_core` 中形成契约。写入者使用
`build_asset_workspace()` 和 canonical filename，不得自创工作区路径。

## 6. 音频、VAD 与 ASR

### 6.1 音频提取

`transcription` 使用 ffmpeg 从 `video.mp4` 生成并持久化：

```text
audio.wav
format: PCM WAV
sample rate: 16 kHz
channels: mono
sample format: signed 16-bit
```

`audio.wav` 是 transcription 派生工件，不属于 `media_download`。管线禁止自动删除；只有
用户显式授权替换时才能重建并覆盖。manifest 记录输入视频 checksum、ffmpeg 版本与完整
参数。

### 6.2 VAD

VAD 使用 pyannote，只判断哪些原视频时间范围包含语音，不负责识别文本、speaker 或句界。
处理块可以跳过静音，但必须保留到原视频绝对时间轴的映射。

```text
原视频： | music | speech A | pause | speech B | applause |
VAD：             [A]                 [B]
ASR chunk：       [A + B]
时间映射：         A→原视频区间，B→原视频区间
```

`vad.json` 记录模型身份/版本、onset/offset、padding、region、cut-and-merge 配置和映射。
pyannote VAD 不等于 speaker diarization；v1 不根据声音猜 speaker。

### 6.3 ASR

生产配置：

```text
provider = WhisperX
model    = large-v3
language = en
task     = transcribe
quality  = priority
```

开发测试可以显式使用小模型，但结果不能冒充正式产物。ASR segment 仅是处理单元；
`raw_asr.json` 保存其粗时间、文本和必要诊断信息。

## 7. WhisperX forced alignment

WhisperX 在 ASR 粗时间窗口内把已识别文本重新贴合声学信号，输出词级时间。

```text
ASR segment:
06.000 ├──── "We'll start with the questions." ────┤ 12.000

forced alignment:
06.100 |We'll| 06.510 |start| 06.950 |with| |the| |questions| 08.120
```

### 7.1 `aligned_asr.json`

```json
{
  "schema_version": "transcription.aligned-asr.v1",
  "language": "en",
  "words": [
    {
      "id": "aw1",
      "segment_id": "seg1",
      "text": "We'll",
      "start_ms": 6100,
      "end_ms": 6360,
      "alignment_score": 0.91,
      "timing_source": "acoustic_alignment"
    }
  ]
}
```

- 不持久化字符级时间，只保存词级时间。
- `alignment_score` 只在 `aligned_asr.json` 中保留并用于诊断；它不是文字正确率，也不
  跨模型比较。
- 标点附着到相邻 word 的表面文本，如 `morning,`、`everyone.`；标点没有独立时间单元。
- 所有时间为非负整数毫秒。

### 7.2 未对齐 word

不得静默丢词。只有同时满足以下条件才允许插值：

1. 未对齐范围很小；
2. 左右两侧都有可靠声学锚点；
3. 可用时间范围合法且足以容纳文本；
4. 原因可解释，例如数字、符号或 alignment model 词表限制。

允许时记录：

```json
{
  "text": "10%",
  "start_ms": 10700,
  "end_ms": 11200,
  "alignment_score": null,
  "timing_source": "interpolated",
  "left_anchor_id": "aw10",
  "right_anchor_id": "aw12"
}
```

连续大段未对齐、缺少双侧锚点、时间不足、明显幻觉或非法时间轴均为硬失败。v1 不自动
修复 word overlap；发现无法解释的重叠时记录错误并阻止 canonical 发布。

## 8. 官网逐字稿融合

有 `chapters.json` 时，在 `aligned_asr.json` 之后运行纯本地融合；没有时直接使用 aligned
ASR words 进入本地句界恢复。transcription 不使用 LLM。

### 8.1 规范化与保序对齐

每个 token 同时保留：

```text
surface text     最终候选显示文字
normalized text  只用于匹配
```

规范化覆盖大小写、标点、可证明等价的数字/百分比/货币、连字符和 contraction。例如：

```text
10%                    ↔ ten percent
1998                   ↔ nineteen ninety eight
cannot                 ↔ can not
Berkshire-Hathaway     ↔ Berkshire Hathaway
```

长视频先寻找顺序一致的连续 n-gram 锚点，再只在相邻锚点之间做局部动态规划，避免对数万
个 token 做一个巨大矩阵。允许 exact、normalized exact、substitution、one-to-many、
many-to-one、ASR-only 和 official-only 映射，顺序不得倒退。

### 8.2 冲突规则

| 情形 | 处理 |
|---|---|
| exact / normalized exact | 使用官网表面文字，保留声学时间 |
| 双侧锚定的拼写替换 | 使用官网拼写，保留声学时间并记录 substitution |
| ASR 有、官网没有 | 只要已声学对齐就保留，并记录 ASR-only |
| 官网有、ASR 没有 | 必须在双侧锚定的局部音频窗口再次 forced align；成功才加入 |
| 无可靠双侧锚点的大段冲突 | 不猜测，记录失败并阻止 canonical 发布 |

官网独有文字未通过局部声学验证时，保留在诊断报告但不得进入 spoken timeline。

### 8.3 一对多与多对一

只有已经确认语义等价时才能折叠；不能仅凭 token 数量选择文字。

```text
ASR 一个、官网多个：
ASR [10%] ↔ 官网 [ten] [percent]
显示 "10%"，直接使用 ASR 单词时间。

ASR 多个、官网一个：
ASR [nineteen] [ninety] [eight] ↔ 官网 [1998]
显示 "1998"，时间合并为第一个 ASR word start 到最后一个 ASR word end。
```

融合后的一个 timed word 可以引用多个来源 token：

```json
{
  "id": "w301",
  "text": "1998",
  "start_ms": 20000,
  "end_ms": 21010,
  "asr_word_ids": ["aw301", "aw302", "aw303"],
  "official_token_ids": ["ot280"],
  "match_type": "many_to_one",
  "text_source": "official_transcript",
  "timing_source": "merged_acoustic_alignment"
}
```

`transcript_fusion.json` 保存全部映射、未采用内容、局部声学验证和取舍原因。

## 9. 本地句界恢复

### 9.1 CNBC 高可信覆盖区

- 已可靠融合的官网 `. ? !` 是确定句界，但必须排除缩写、小数、姓名首字母等例外。
- speaker 变化强制结束当前 sentence；一个 sentence 不得跨 speaker。
- paragraph 变化只是弱信号，不能无条件切句。
- chapter 是文档结构边界，不作为 spoken word。

### 9.2 YouTube 与官网未匹配区

v1 使用：

```text
Whisper 标点
+ 本地 sentence detector
+ 词间停顿规则
+ ASR segment 弱提示
```

不引入 NeMo 等独立标点恢复模型。固定停顿阈值不能单独决定句界；长停顿可能发生在
句中，而句间也可能没有明显停顿。ASR segment 只提供弱提示。

不得为了字幕行宽、阅读速度或时长而在 transcription 中机械切句；这些属于
`srt_processing`。无标点异常长文本只能按版本化 fallback policy 恢复边界，并记录为
低可信 finding。

### 9.3 边界 provenance

不用未经校准的 `0.0..1.0` confidence，改用可解释枚举：

```text
boundary_source:
  official_punctuation
  speaker_change
  asr_punctuation
  punctuation_and_pause
  pause_fallback

boundary_status:
  verified
  inferred
  fallback
```

`speaker_label` 是 sentence 的通用可选元数据；没有可靠来源时为 `null`，不得猜测。

## 10. `source_alignment.json` 公共契约

示意：

```json
{
  "schema_version": "transcription.source-alignment.v1",
  "language": "en",
  "words": [
    {
      "id": "w1",
      "text": "Good",
      "start_ms": 2100,
      "end_ms": 2320,
      "asr_word_ids": ["aw1"],
      "official_token_ids": ["ot1"],
      "match_type": "normalized_exact",
      "text_source": "official_transcript",
      "timing_source": "acoustic_alignment"
    }
  ],
  "sentences": [
    {
      "id": "s1",
      "first_word_id": "w1",
      "last_word_id": "w3",
      "start_ms": 2100,
      "end_ms": 3050,
      "text": "Good morning, everyone.",
      "speaker_label": "WARREN BUFFETT",
      "text_source": "official_transcript",
      "boundary_source": "official_punctuation",
      "boundary_status": "verified"
    }
  ]
}
```

硬不变量：

- word 和 sentence ID 稳定、唯一且按文档顺序排列；具体字符串生成规则由公共 schema 固定。
- `0 <= start_ms < end_ms`，且不得超过音频时长。
- word 时间单调，不允许无法解释的重叠。
- 每个 word 文本规范化后非空。
- sentence 引用的 word 范围存在、连续、无重复；所有有效 word 恰好属于一个 sentence。
- `sentence.start_ms == first_word.start_ms`。
- `sentence.end_ms == last_word.end_ms`。
- sentence text 必须能由其 timed words 按规范化空格/标点规则重建。
- `speaker_label` 可以为 `null`；非空时必须来自结构化可靠来源。

translation 只提取完整 sentence 的 `id + text`。srt_processing 同时使用 words、sentences
和 translation result 规划 cue。

## 11. 日志、报告与用户可见性

alignment 和 transcript fusion 的匹配、替换、插值、冲突、排除、恢复及失败均产生带稳定
事件 code 的结构化事件。

```text
事件流
  ├── transcription.log
  │     DEBUG / INFO / WARNING / ERROR 全部详细事件
  ├── transcription_report.json
  │     汇总计数、WARNING/ERROR findings、QA 与最终状态
  └── CLI
        只显示 WARNING / ERROR 和阶段汇总
```

事件至少包含可用的：

- `asset_id`、stage、event code、severity；
- word/token/segment ID；
- 原始文本、结果文本和原视频时间范围；
- 采取的动作与原因。

典型 event code：

```text
alignment.word_unaligned
alignment.word_interpolated
alignment.word_unrecoverable
alignment.word_overlap
fusion.surface_adjusted
fusion.text_replaced
fusion.one_to_many_collapsed
fusion.many_to_one_collapsed
fusion.asr_only_retained
fusion.official_only_recovered
fusion.official_only_excluded
fusion.region_unmatched
boundary.official_applied
boundary.speaker_change
boundary.pause_inferred
boundary.fallback_used
```

普通完全匹配只进入 DEBUG 或汇总。大小写/标点等实际调整写详细日志但不逐条打印到 CLI。
阶段汇总至少显示 aligned/interpolated/unrecoverable、各融合类型、warnings、errors 和状态。

失败时仍尽力持久化详细日志、report 和失败 manifest，但不发布不完整的
`source_alignment.json`。

## 12. 分层与端口

### 12.1 domain

- `VadRegion`
- `RawAsrSegment`
- `AlignedAsrWord`
- `TranscriptToken`
- `TranscriptMatch`
- `TimedWord`
- `SourceSentence`
- `SourceAlignment`
- `TranscriptionFinding`
- 时间轴、覆盖、融合和句界不变量

domain 不依赖 ffmpeg、WhisperX、pyannote、spaCy、文件系统或日志实现。

### 12.2 application

- 验证输入视频和上游 manifest；
- 提取/复用音频；
- 运行或复用 VAD、ASR 与 forced alignment；
- 融合可选官网逐字稿；
- 恢复句界并构建 `SourceAlignment`；
- 运行 QA、管理缓存键和阶段状态；
- 通过事件端口发布结构化事件；
- 原子发布成功工件或持久化失败诊断。

### 12.3 infrastructure

- ffmpeg 音频提取；
- WhisperX + pyannote adapter；
- 本地 sentence detector adapter；
- JSON/file artifact store；
- checksum、原子写和结构化日志 adapter。

### 12.4 interfaces

向 orchestration/CLI 暴露稳定 command/result、工件引用、阶段摘要和事件，不暴露 WhisperX、
pyannote 或 spaCy 返回对象。CLI 只负责过滤和展示 WARNING/ERROR 与汇总，不持有业务规则。

最小端口集合：

- `AudioExtractor`
- `AsrEngine`
- `ForcedAligner`
- `OfficialTranscriptAligner`
- `SentenceBoundaryDetector`
- `MediaProbe`
- `TranscriptionArtifactStore`
- `ChecksumService`
- `TranscriptionEventSink`

## 13. 缓存、幂等和替换策略

缓存逐层失效：

```text
audio cache key
  = video SHA-256 + ffmpeg identity + extraction config

VAD/ASR cache key
  = audio SHA-256 + WhisperX/Whisper/pyannote identities + 所有结果相关参数

alignment cache key
  = raw_asr SHA-256 + alignment model identity + alignment/interpolation policy

fusion cache key
  = aligned_asr SHA-256 + chapters.json SHA-256 + normalization/matching policy

sentence cache key
  = fused/aligned input SHA-256 + sentence detector/rule policy
```

- 官网逐字稿变化时复用 audio、VAD、raw ASR 和基础 alignment，只重做融合及其下游。
- 句界规则变化时只重做句界及 canonical 输出。
- 工具、模型、配置或输入 hash 变化使相应层及其下游 stale。
- manifest 和 checksum 决定完成状态，文件存在不构成完成证据。
- 成功的昂贵工件禁止自动删除或静默覆盖；只有用户显式授权替换时才允许重建。
- 正式输出先写临时文件、完成 QA 后原子发布。

## 14. 失败语义与 QA

硬失败至少包括：

- 上游下载 manifest/checksum 无法验证；
- ffmpeg、VAD、ASR 或 forced alignment 失败；
- 无法安全恢复的大段未对齐词；
- 非法、倒退、越界或无法解释的重叠时间；
- 官网与 ASR 大段冲突且没有可靠单调双侧锚点；
- timed words 无法被 sentences 连续且完整覆盖；
- 正式工件或 manifest 写入/校验失败。

可发布但必须 warning/report 的情形包括：

- 少量有双侧锚点的插值词；
- ASR-only spoken words 被保留；
- official-only word 经局部声学验证恢复或因失败被排除；
- 低可信 fallback 句界未超过配置的发布门禁。

具体 VAD、alignment、融合覆盖和 fallback 句界数值阈值不是架构常量。实现任务必须基于
真实 CNBC/YouTube golden sample 建立版本化 QA policy，并把最终数值、样本和评测结果写入
实现文档/配置；阈值变化会使相关缓存 stale。

## 15. 验证标准

### 15.1 离线单元测试

- 16 kHz mono PCM 音频计划与 provenance；
- VAD 原视频时间映射与 chunk 重组；
- raw/aligned ASR schema、整数毫秒、单调性、重叠和越界；
- 有双侧锚点的少量插值与不可恢复区域失败；
- exact、substitution、ASR-only、official-only、one-to-many、many-to-one；
- official-only 局部 forced alignment 成功与失败；
- chapter/speaker/annotation 不进入 spoken word timeline；
- 缩写、小数、问句、speaker change、跨 ASR segment、长停顿和无标点长句；
- speaker 为可选通用字段，缺失时序列化为 `null`；
- 所有调整产生稳定日志事件，CLI 仅显示 warning/error 与汇总；
- cache key 随相关输入、模型、配置或 policy 变化。

### 15.2 application 测试

- fake audio extractor、ASR、aligner、transcript aligner、sentence detector 下完整离线运行；
- cache hit 不重复执行昂贵 provider；
- 官网逐字稿变化只重做融合及下游；
- 失败时保留 log/report/failed manifest，不发布 canonical；
- 成功时 `source_alignment.json` 与 manifest 原子发布；
- 未显式授权时不覆盖任何昂贵成功工件。

### 15.3 golden/人工验收

至少覆盖：

- CNBC 清晰单人讲话；
- CNBC 多 speaker 问答；
- YouTube 老录音或噪声；
- 人名、公司名、数字、百分比和货币；
- 官网删口头语、ASR 漏词、官网新增/编辑内容；
- 跨 ASR segment 的完整句子和一个 segment 内的多个句子。

记录词时间误差、未对齐/插值比例、融合覆盖、冲突类型、句界 precision/recall 或等价
人工指标、运行时间和峰值资源。完整离线 pytest 必须通过。

## 16. 已决策与实现期参数

以下架构问题已经关闭：

- WhisperX 一体化、`large-v3`、`language=en`、`task=transcribe`；
- pyannote VAD；
- transcription 不使用 LLM；
- 持久化 audio、VAD、raw ASR、aligned ASR、融合、日志、报告和 manifest；
- 只持久化词级而非字符级时间；
- 少量双侧锚定未对齐词可显式插值；
- 结构化官网逐字稿、保留 ASR-only、声学验证 official-only；
- 可证明等价的一对多/多对一折叠规则；
- 本地句界、optional speaker、冗余 sentence 时间和枚举式 boundary provenance；
- CLI 只展示 WARNING/ERROR 和汇总，详细事件进入日志文件。

实现时仍需通过任务验收确定并锁定：

- WhisperX、pyannote、alignment model 和 sentence detector 的具体版本与设备支持矩阵；
- batch size、compute type、VAD/padding 参数；
- normalization 字典和 n-gram/局部匹配阈值；
- interpolation、融合覆盖和 fallback 句界发布阈值；
- golden sample 的量化基线。

这些是版本化运行参数和评测结论，不得改变本 ADR 的权威来源、失败语义或模块边界。

## 17. 后果与风险

- **收益**：官网文字质量和音频时间各取所长；YouTube 仍有完整本地降级路径；翻译获得完整
  句子，字幕规划获得词级锚点；所有调整可审计且昂贵计算可分层复用。
- **代价**：transcription 管线和持久化工件增加，WhisperX/pyannote/PyTorch 依赖较重，
  首次模型下载和长视频资源消耗高。
- **词时间非真值**：噪声、重叠讲话、数字和词表外字符仍可能漂移，必须依赖 QA 和人工
  golden sample，而不能把 alignment score 当准确率。
- **官网逐字稿非逐字真值**：错误融合会伪造内容，因此 official-only 必须声学验证，
  ASR-only 默认保留。
- **公开契约迁移**：现有 acquisition `chapters.json` 需要升级为结构化、版本化 schema；
  下游必须只依赖 archive_core 公共 DTO。
- **日志体积**：详细调整全部落盘，CLI 通过级别过滤避免刷屏；日志生命周期后续由统一
  本地资产策略管理，不得自动删除生成资产。

## 18. 参考

- [OpenAI Whisper `word_timestamps` 实现](https://github.com/openai/whisper/blob/main/whisper/transcribe.py)
- [WhisperX：词级时间与 forced alignment](https://arxiv.org/abs/2303.00747)
- [WhisperX 项目与限制](https://github.com/m-bain/whisperX)
- [spaCy sentence segmentation](https://spacy.io/usage/linguistic-features)
