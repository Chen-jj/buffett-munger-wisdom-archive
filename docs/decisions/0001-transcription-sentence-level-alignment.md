# ADR-0001：transcription 采用词级对齐与本地句界恢复

- 状态：讨论中
- 日期：2026-09-14
- 影响模块：`transcription`、`archive_core`（公共工件契约）
- 所属阶段：Phase 1

> 本文是讨论稿。被接受前不替代模块 `AGENTS.md` 或现有实现约束。

## 1. 候选结论

`transcription` 把已下载的 `video.mp4` 转为带时间信息的完整英文句子。候选流程为：

```text
video.mp4
  → audio.wav
  → ASR / VAD
  → 词级时间对齐
  → 官方英文逐字稿融合（可选）
  → 本地标点恢复与句界检测
  → source_alignment.json
```

本模块候选边界：

- 负责音频提取、英文 ASR、词级时间对齐、英文文本融合、标点恢复和句界检测。
- 输出词级时间信息以及由词范围定义的完整英文句子。
- 不翻译。
- 不规划字幕 cue。
- 不生成 `english.srt`；英文 SRT 如有需要，由 `srt_processing` 从最终 cue plan 投影。
- 句界恢复只使用本地模型和算法，不调用远程 LLM。

这份候选决策撤回旧版 ADR 中“ASR segment 等于句子”“不持久化词级时间”“由
transcription 生成 canonical `english.srt`”的方向，但尚未被接受。

## 2. 背景与问题

ASR/VAD segment 是模型窗口、静音或解码边界，不保证是完整语言句子。例如：

```text
segment 1: I think the most important thing
segment 2: when you're evaluating a business
segment 3: is to understand its competitive position.
```

翻译需要看到完整句意，字幕又需要可靠时间锚点。因此必须区分：

```text
ASR segment      = 识别处理单元
word             = 最小时间锚点
sentence         = 英文完整句子/翻译单元
subtitle cue     = 最终显示单元
```

四者不要求一一对应。

## 3. 目标与非目标

### 3.1 目标

- 从 `video.mp4` 提取适合 ASR 的本地音频。
- 得到英文词序列及非负整数毫秒时间戳。
- 将 ASR segment 重建为完整、按时间有序的英文句子。
- 有官方英文逐字稿时，可靠地利用其拼写、大小写、标点和句界。
- 产出可供 translation 与 srt_processing 共同消费的权威结构化工件。
- 通过 provider 端口、内容哈希缓存和 fake 实现离线测试。
- 保存足够的 manifest/溯源信息解释结果如何产生。

### 3.2 非目标

- 不翻译文本。
- 不生成 English/Chinese/Bilingual SRT。
- 不决定字幕行宽、阅读速度、双语排版或最终 cue 边界。
- 不实现卡拉 OK、逐词高亮或视频烧录。
- 不使用远程 LLM 恢复标点或句界。
- 不把 ASR segment 当作自然语言句子。

## 4. 输入、输出与权威性

### 4.1 输入

| 输入 | 必需 | 说明 |
|---|---:|---|
| `video.mp4` | 是 | 来自 `media_download`，必须验证上游 manifest 和校验和 |
| 官方英文 `transcript.txt` | 否 | 可用于修正英文文本及句界，没有时间信息 |
| 官方中文翻译稿 | 否 | 不直接用于英文句界；将来可作为翻译参考或评测资料 |
| ASR/VAD/对齐配置 | 是 | provider、模型、语言、设备、精度、VAD、forced alignment 参数 |
| 句界配置 | 是 | 本地模型版本、停顿阈值、最长句长、缩写规则等 |
| 执行策略 | 是 | 缓存、dry-run、显式覆盖策略 |

### 4.2 候选输出

| 产物 | 角色 | 说明 |
|---|---|---|
| `audio.wav` | 可复用中间产物 | 候选为 16 kHz、单声道 PCM WAV |
| 原始 ASR 结果 | 可重建缓存 | 保存 provider 原始 segment/word 结果，不直接给下游 |
| `source_alignment.json` | canonical 工件 | 权威英文词级时间与完整句子 |
| `transcription_manifest.json` | 阶段记录 | 输入输出校验和、模型、参数、缓存、融合、句界与 QA 指标 |
| `transcription_report.json` | 诊断报告（待定） | 未对齐词、低置信度句界、逐字稿覆盖率等 |

`english.srt` 不属于本模块输出。文件名、`ArtifactType` 和公共 schema 需要在
`archive_core` 中补充，具体命名仍待定。

## 5. ASR 与词级时间对齐

### 5.1 provider 能力

OpenAI Whisper 和 faster-whisper 均能请求词级时间，但属于模型推算。WhisperX 在 ASR
之后使用 forced alignment 将文本重新贴合音频，候选生产实现优先考虑 WhisperX。

候选端口：

```python
class AsrEngine(Protocol):
    def transcribe(self, audio: AudioRef, config: AsrConfig) -> RawTranscription:
        ...
```

application 不依赖 Whisper/WhisperX 的具体返回对象。

### 5.2 原始 ASR 内部结构示例

```json
{
  "schema_version": "transcription.raw-asr.v1",
  "language": "en",
  "segments": [
    {
      "id": 1,
      "start_ms": 1200,
      "end_ms": 3100,
      "text": "I think the most important thing",
      "words": [
        {
          "id": 1,
          "text": "I",
          "start_ms": 1200,
          "end_ms": 1320,
          "probability": 0.98
        },
        {
          "id": 2,
          "text": "think",
          "start_ms": 1320,
          "end_ms": 1580,
          "probability": 0.97
        }
      ]
    }
  ]
}
```

此结构是 adapter 输出/缓存候选，不是跨模块公共契约。

### 5.3 词级不变量

候选硬门禁：

- word ID 唯一、连续或至少稳定有序（最终形式待定）。
- `0 <= start_ms < end_ms`。
- word 时间单调，不允许无法解释的重叠。
- word 文本规范化后非空。
- sentence 引用的 word 范围必须存在且连续。
- 未对齐词不得静默丢弃，必须采用显式策略并写入报告。

## 6. 官方逐字稿融合

### 6.1 官方英文逐字稿

候选流程：

1. 分别规范化官方英文文本和 ASR words。
2. 使用保序序列匹配建立 transcript token 与 ASR word 的映射。
3. 高置信度区域使用官方拼写、大小写、标点和句界。
4. 时间始终来自音频对齐结果。
5. 未可靠匹配的区域保留 ASR 文本，并进入本地句界恢复。
6. manifest 记录逐字稿校验和、阈值、覆盖率、未匹配数量和替换范围。

不得将官网编辑、删减或新增但音频中不存在的文字强行贴到时间轴。

### 6.2 官方中文翻译稿

如果来源只有官方中文译稿，它不直接参与英文句界恢复，因为跨语言对应关系尚未建立。
候选用途是 translation 的参考资料、术语来源或人工评测基准，是否纳入 v1 待定。

## 7. 本地标点恢复与句界检测

### 7.1 候选默认方案

当前讨论中的 v1 候选是：

```text
官方英文句界（可靠匹配区域）
  或
WhisperX 标点 + spaCy sentence detector + 词间停顿规则
```

候选规则信号：

- `. ? !` 等终止标点。
- 单词之间的停顿长度。
- 缩写、人名缩写、数字和小数点例外。
- 句子最大词数/持续时间。
- ASR segment 仅作为弱提示，不作为句界。

NVIDIA NeMo 等专用本地标点模型暂不确定是否引入；应先用真实长视频评测 WhisperX
标点质量和依赖成本。

### 7.2 句界结果示例

```json
{
  "sentences": [
    {
      "id": "s1",
      "first_word_id": 1,
      "last_word_id": 18,
      "start_ms": 1200,
      "end_ms": 7800,
      "text": "I think the most important thing when you're evaluating a business is to understand its competitive position.",
      "text_source": "official_transcript",
      "boundary_source": "official_transcript",
      "boundary_confidence": 0.97
    },
    {
      "id": "s2",
      "first_word_id": 19,
      "last_word_id": 27,
      "start_ms": 7900,
      "end_ms": 11200,
      "text": "That is what determines its long-term economics.",
      "text_source": "asr",
      "boundary_source": "punctuation_and_pause",
      "boundary_confidence": 0.91
    }
  ]
}
```

`start_ms/end_ms` 可从首尾 word 推导，但为方便消费者是否冗余持久化仍待定。

## 8. `source_alignment.json` 候选契约

```json
{
  "schema_version": "transcription.source-alignment.v1",
  "language": "en",
  "words": [
    {
      "id": 1,
      "text": "I",
      "start_ms": 1200,
      "end_ms": 1320
    },
    {
      "id": 2,
      "text": "think",
      "start_ms": 1320,
      "end_ms": 1580
    }
  ],
  "sentences": [
    {
      "id": "s1",
      "first_word_id": 1,
      "last_word_id": 18,
      "start_ms": 1200,
      "end_ms": 7800,
      "text": "I think the most important thing when you're evaluating a business is to understand its competitive position.",
      "text_source": "official_transcript",
      "boundary_source": "official_transcript"
    }
  ]
}
```

`sentences` 同时是 translation 的源翻译单元。translation 可在内存中提取紧凑的
`sentence_id + text` 请求，不需要再持久化一份重复的 `translation_units`。

## 9. 最终候选流程

```text
验证 video.mp4 与上游 provenance
  ↓
提取/复用 audio.wav
  ↓
ASR + VAD
  ↓
forced word alignment
  ↓
缓存原始 ASR 结果
  ↓
可选官方英文逐字稿融合
  ↓
本地标点恢复 + 句界检测
  ↓
词级/句级硬门禁
  ↓
原子发布 source_alignment.json + transcription_manifest.json
```

## 10. 分层与候选端口

### domain

- `AlignedWord`
- `SourceSentence`
- `SourceAlignment`
- `TextSource`
- `BoundarySource`
- 时间轴、word 覆盖、sentence 覆盖不变量

### application

- `extract_audio`
- `transcribe_words`
- `align_official_transcript`
- `restore_punctuation`
- `detect_sentence_boundaries`
- `build_source_alignment`
- `validate_transcription_output`

### infrastructure

- `FfmpegAudioExtractor`
- `WhisperXAsrEngine` / `FasterWhisperAsrEngine`
- 本地句界/标点 provider
- 原始 ASR 缓存
- alignment/manifest store
- media probe

### interfaces

向 orchestration 暴露资产标识、配置、执行策略以及稳定的产物引用和 QA 摘要，不暴露
Whisper、spaCy 或 ffmpeg 内部对象。

### 候选最小端口

- `AudioExtractor`
- `AsrEngine`
- `SentenceBoundaryDetector`
- `OfficialTranscriptAligner`
- `MediaProbe`
- `TranscriptionCache`
- `TranscriptionArtifactStore`
- `ChecksumService`

`PunctuationRestorer` 是否需要独立于 `SentenceBoundaryDetector` 仍待定。

## 11. 缓存、幂等与失败语义

- 原始 ASR 缓存键至少包含音频内容哈希及所有结果相关 ASR/VAD/对齐参数。
- 句界物化结果还依赖官方逐字稿校验和、句界模型/规则版本和阈值。
- `source_alignment.json` 与 manifest 必须原子发布。
- 成功产物默认不覆盖；覆盖必须由调用方显式请求。
- 文件存在不是阶段完成判据。
- ASR、forced alignment、硬门禁或正式写入失败时，阶段失败。
- 官方逐字稿缺失或局部不匹配可以降级到 ASR + 本地句界，但必须记录。
- 未对齐词、低置信度边界是否阻断发布由明确 QA 阈值决定，当前待定。

## 12. 验证与候选验收标准

### 离线单元测试

- word 时间范围、排序、重叠和空文本校验。
- sentence 对 word 的连续、无重复、全覆盖引用。
- 多个 ASR segment 合并为一个完整句子。
- 单个 ASR segment 内多个句子的边界恢复。
- 缩写、小数、问句、长停顿和无标点长句。
- 官方逐字稿高置信度匹配时采用其文本/句界但保留音频时间。
- 低置信度匹配时保留 ASR 文本。
- 缓存键随结果相关输入或参数变化。

### application 测试

- fake ASR、fake transcript aligner、fake sentence detector 下完整离线运行。
- ASR 缓存命中时不重复运行昂贵模型。
- 官方逐字稿变化时复用原始 ASR 缓存，但重做融合和句界。
- 任一正式产物或 manifest 校验和不一致时不得判定完成。

### golden/人工验收

- 选择至少一段 Buffett/Munger 长访谈，人工标注词时间和句界样本。
- 统计词时间误差、未对齐词比例、句界 precision/recall 或等价指标。
- 有/无官方逐字稿区域分别评测。
- 完整离线 pytest 通过。

## 13. 待决策问题

1. 生产 ASR provider 最终选择 WhisperX、原生 Whisper 还是 faster-whisper + 独立 aligner？
2. forced alignment 使用哪个模型、版本和设备策略？目标 macOS/CPU/MPS/CUDA 支持矩阵是什么？
3. `source_alignment.json` 的最终文件名、schema version 和 `ArtifactType` 是什么？
4. canonical `words` 应保存 ASR 词，还是保存官方 transcript token 与 ASR 时间融合后的有效词？
5. 官方文本与 ASR token 数不同、含编辑删减时如何表达一对多、多对一和未对齐 token？
6. 未对齐词采用 nearest/linear interpolation、附着相邻词还是阻断？
7. word ID 必须连续整数，还是只要求稳定唯一字符串？sentence ID 同理。
8. 是否持久化 word probability；若持久化，是否有可比较/可校准语义？
9. 是否冗余保存 sentence 的 `start_ms/end_ms`，还是只保存 word 范围？
10. 是否需要 speaker diarization/`speaker_id`；缺失它是否影响翻译上下文和双人字幕？
11. 默认句界实现使用 spaCy `senter`、dependency parser、纯规则还是专用本地模型？
12. 是否需要独立 NeMo `PunctuationRestorer`，其模型体积、许可、Apple Silicon 和离线安装成本是否可接受？
13. 停顿阈值、最长句长、异常句阻断阈值如何通过样本确定？
14. `boundary_confidence` 如何计算和校准；低于何值仅告警、低于何值失败？
15. 官方英文逐字稿的匹配算法、阈值和覆盖率门禁是什么？
16. 官方中文翻译稿是否进入 v1 translation 输入，还是只作为人工参考？
17. 原始 ASR 结果、`audio.wav` 和诊断报告是否持久化；生命周期和路径是什么？
18. 工具/模型版本变化是否使 canonical 工件 stale？
19. 当前模块 `AGENTS.md`、路线图和 archive_core 公共契约何时随 ADR 接受而同步？

## 14. 风险

- **词时间并非真值**：Whisper word timestamp 和 forced alignment 都会在噪声、重叠讲话、
  人名、数字和未登录词上漂移。
- **依赖与硬件风险**：WhisperX、对齐模型和 PyTorch 组合可能与 Python、macOS/MPS/CUDA
  版本冲突，首次模型下载昂贵。
- **标点错误传播**：错误句界会直接降低翻译质量，并使后续 cue 规划困难。
- **官方逐字稿并非逐字**：官网文本可能删改口语、遗漏段落或改变顺序，错误融合会伪造音频内容。
- **文本/时间双权威风险**：若 canonical words 与 sentence text 来自不同来源而没有明确映射，
  下游无法可靠分割英文文本。
- **置信度误用**：provider probability 和自定义 boundary confidence 可能不可校准，不能伪装成客观准确率。
- **长视频资源风险**：ASR、forced alignment 和本地 NLP 模型会增加内存、磁盘、模型加载和运行时间。
- **职责膨胀**：transcription 同时承担音频、ASR、融合、标点和句界，需要通过端口和层次避免形成单体流程。
- **迁移冲突**：现有指南仍描述句级 ASR 和 English SRT；讨论稿接受前存在文档不一致。

## 15. 参考

- [OpenAI Whisper `word_timestamps` 实现](https://github.com/openai/whisper/blob/main/whisper/transcribe.py)
- [WhisperX：词级时间与 forced alignment](https://arxiv.org/abs/2303.00747)
- [spaCy sentence segmentation](https://spacy.io/usage/linguistic-features)
- [NVIDIA NeMo punctuation and capitalization](https://docs.nvidia.com/nemo-framework/user-guide/24.07/nemotoolkit/nlp/punctuation_and_capitalization.html)
