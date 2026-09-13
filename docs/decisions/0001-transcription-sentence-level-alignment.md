# ADR-0001：transcription 采用句级时间戳与可替换 ASR provider

- 状态：已接受
- 日期：2026-09-13
- 影响模块：`transcription`、`archive_core`（后续实现公共工件契约时）
- 所属阶段：Phase 1

## 1. 一句话结论

`transcription` 把已下载的 `video.mp4` 转为带句级时间轴的英文文本，以
`alignment.json` 和 `english.srt` 作为一等产物；不实现词级对齐。ASR、音频提取等
外部能力通过端口注入，昂贵的 ASR 结果按内容哈希缓存，并在落地前依次经过可选的
官方逐字稿文本融合和强制 SRT 可用性校验。

## 2. 背景

主链路为：

```text
media_download → transcription → srt_processing → translation → subtitle_rendering
```

上游已经提供下载完成且经过溯源记录的 `video.mp4`。下游需要合法、可追溯、可恢复
生成的英文字幕，而不是仅凭文件存在判断阶段完成。

CNBC 来源还可能提供 `transcript.txt`。它通常在人名、术语和原句文本上优于 ASR，
但没有时间信息，因此只能用于修正文本，不能取代 ASR 时间轴。

历史方案提出过词级时间戳和 forced alignment。最终烧录只消费 cue 的开始时间、结束
时间和文本，词级时间不会改善当前核心烧录能力，却会引入额外模型、耗时和失败面。

## 3. 目标与非目标

### 3.1 目标

- 从 `video.mp4` 提取适合 ASR 的音频。
- 生成英文句级文本及其开始、结束时间。
- 在有官方逐字稿时，用其修正可靠匹配到的 ASR 文本，同时保留 ASR 时间轴。
- 生成可被 `srt_processing` 稳定消费的 `english.srt`。
- 通过 manifest、校验和与参数记录实现可恢复、可解释的阶段执行。
- 通过 fake provider 让 domain/application 测试无需网络、ffmpeg 或真实 ASR 模型。

### 3.2 非目标

- 不生成或持久化词级时间戳。
- 不实现单词级 forced alignment、卡拉 OK 高亮或逐词动画。
- 不负责字幕翻译、双语合并、ASS 样式和视频烧录。
- 不在本模块中实现 CLI 业务规则或跨阶段任务调度。
- 不因模型能力“顺手”增加当前下游不消费的产物。

## 4. 输入、输出与权威性

### 4.1 输入

| 输入 | 必需 | 说明 |
|---|---:|---|
| `video.mp4` | 是 | 由 `media_download` 生成，并通过上游 manifest/校验和确认 |
| `transcript.txt` | 否 | 官方逐字稿；只有文本、没有时间，当前主要用于 CNBC 链路 |
| ASR 配置 | 是 | 模型、语言、设备、精度、VAD/分段等影响结果的参数 |
| 执行策略 | 是 | 是否允许覆盖、是否允许使用缓存、dry-run 等显式选项 |

### 4.2 输出

| 产物 | 角色 | 说明 |
|---|---|---|
| `audio.wav` | 可复用中间产物 | 16 kHz、单声道 PCM WAV；必须记录输入视频校验和与抽取参数 |
| `alignment.json` | 一等产物 | 后续投影 SRT 的句级时间轴与有效英文文本 |
| `english.srt` | canonical 产物 | 供下游消费；只有通过门禁 B 后才具权威性 |
| `transcription_manifest.json` | 阶段运行记录 | 输入/输出校验和、provider、参数、缓存、融合和校验结果 |

`archive_core` 当前还没有 `alignment.json` 对应的 `ArtifactType`，也没有阶段 manifest 的
公共类型。实现本模块前应先用最小改动补充公共工件契约；本 ADR 不修改代码。

阶段 manifest 使用独立文件名，避免不同昂贵阶段相互覆盖。未来由 orchestration 汇总到
资产级 `manifest.json`，但阶段完成判定不等待该汇总能力。

## 5. 句级 alignment 数据契约

时间使用非负整数毫秒，避免浮点误差影响 SRT 的毫秒精度。segment 顺序即时间顺序，
`id` 在单个 alignment 内连续且稳定。

建议的最小结构如下：

```json
{
  "schema_version": "transcription.alignment.v1",
  "language": "en",
  "segments": [
    {
      "id": 1,
      "start_ms": 1240,
      "end_ms": 4860,
      "text": "The effective text used for SRT projection.",
      "asr_text": "The original ASR text.",
      "text_source": "official_transcript"
    }
  ]
}
```

约束：

- `start_ms < end_ms`。
- segments 时间单调且不重叠。
- `text` 与 `asr_text` 均为规范化后的非空英文文本。
- `text_source` 只能表示本句最终文本来源，例如 `asr` 或
  `official_transcript`。
- 不加入 `words` 字段；未来若出现真实消费需求，必须另开 ADR。

## 6. 最终处理流程

```text
video.mp4
   │
   ▼
提取 audio.wav
   │
   ▼
ASR：原始英文句级文本 + 时间戳 ─────► ASR 内容哈希缓存
   │
   ▼
门禁 A：可选官方逐字稿文本融合（软门禁）
   │
   ▼
写出 alignment.json
   │
   ▼
纯函数投影 english.srt
   │
   ▼
门禁 B：SRT 可用性校验（硬门禁）
   │
   ▼
原子落地 canonical 产物 + transcription_manifest.json
```

### 6.1 音频提取

- 由 application 层调用 `AudioExtractor` 端口。
- 生产适配器使用 ffmpeg，将媒体转换为 16 kHz、单声道 PCM WAV。
- domain/application 不拼接 ffmpeg 命令。
- 音频是否可复用由 manifest 中的视频校验和与抽取参数共同决定，不能只检查
  `audio.wav` 是否存在。

### 6.2 ASR

- `AsrEngine` 返回按时间排序的句级 segment；application 不依赖 Whisper 特定对象。
- 生产环境首选 WhisperX 或 faster-whisper 适配器，最终选择通过配置显式指定。
- 模型名、模型版本（可得时）、语言、设备、精度、VAD/分段参数必须写入 manifest。
- provider 返回词级信息时也不进入领域契约和持久化产物。

### 6.3 门禁 A：官方逐字稿文本融合

这是质量增强步骤，不是阶段阻断条件，仅在存在 `transcript.txt` 时启用。

1. 对 ASR 句子与官方逐字稿进行文本规范化。
2. 用保序序列匹配建立官方文本片段与 ASR segment 的映射。
3. 只有达到显式匹配阈值的映射才用官方文本覆盖 `text`；`start_ms`、`end_ms` 始终
   保留 ASR 值。
4. 无法可靠匹配的 segment 保留 ASR 文本，流程继续。
5. 在 manifest 中记录逐字稿校验和、匹配阈值、覆盖 segment 数、总 segment 数、
   覆盖率与未匹配数量。

“冲突时采用官方逐字稿”仅适用于已经可靠映射的文本片段；禁止把未可靠匹配的官方
句子强行放到 ASR 时间段中。

### 6.4 SRT 投影

`alignment.json → english.srt` 是确定性的纯变换：

- cue 序号从 1 连续递增。
- cue 时间直接来自 segment 时间。
- cue 文本使用 segment 的 `text`。
- 相同 alignment 与投影配置必须得到字节一致的 SRT。

因此，调整 SRT 投影规则不触发 ASR 重算。

### 6.5 门禁 B：SRT 可用性校验

这是硬门禁。至少检查：

- cue 序号从 1 连续递增。
- `start < end`，时间轴单调且不重叠。
- cue 文本非空。
- 所有有效 alignment segment 均被投影，投影覆盖率为 100%。
- SRT cue 数与当前一段一 cue 的投影策略下的 segment 数一致。
- 最后一个 cue 不超过已探测的媒体时长（允许显式的毫秒级容差）。

失败时不发布 `english.srt`，阶段状态记为失败，并保留足够的诊断信息。不得把失败或
未校验的临时文件视为权威产物。

## 7. 缓存、幂等与覆盖策略

### 7.1 ASR 缓存键

```text
sha256(audio_content + canonical_asr_parameters)
```

`canonical_asr_parameters` 必须使用稳定序列化，至少包含会改变识别结果的 provider、
模型、语言、精度、VAD 与分段参数。

缓存保存原始 ASR 句级结果。`alignment.json` 是本次运行在可选融合后的权威物化结果。
这样，官方逐字稿变化时只需重跑融合与投影，不会错误复用旧融合文本，也不必重跑
昂贵 ASR。

若未来缓存融合后的 alignment，其缓存键还必须包含逐字稿校验和与融合参数；不能继续
只使用音频和 ASR 参数。

### 7.2 完成判定

阶段仅在以下条件全部满足时视为完成：

- manifest 状态为成功且 schema 可读。
- manifest 中的输入校验和与当前输入一致。
- 影响结果的参数与当前配置一致。
- `alignment.json`、`english.srt` 的校验和与 manifest 一致。
- 门禁 B 结果为通过。

文件存在本身不是完成判据。

### 7.3 写入和覆盖

- 所有正式 JSON/SRT 产物先写同目录临时文件，再原子 rename。
- 已存在的成功产物默认不覆盖。
- 覆盖昂贵产物必须由调用方显式请求。
- 缓存是可重建数据，canonical 产物是 manifest 追踪的数据；两者目录与生命周期分离。
- 本模块不得自行删除源媒体、canonical 产物或缓存。

## 8. 分层与端口

### 8.1 domain

纯领域对象与规则：

- `SentenceSegment`
- `SentenceAlignment`
- `TextSource`
- 时间轴不变量
- 文本融合决策与指标
- SRT 投影和可用性校验规则

domain 不得导入 ffmpeg、Whisper、文件系统、CLI 或网络客户端。

### 8.2 application

模块内用例协调：

- `extract_audio`
- `transcribe_session`
- `fuse_official_transcript`
- `project_english_srt`
- `validate_transcription_output`

application 依赖抽象端口，不直接构造具体 provider。

### 8.3 infrastructure

外部系统适配器：

- `FfmpegAudioExtractor`
- `WhisperXAsrEngine` 或 `FasterWhisperAsrEngine`
- 本地 ASR 缓存
- alignment/SRT/manifest 文件存储
- 媒体时长探测器

### 8.4 interfaces

提供给 CLI、Web UI 与 orchestration 的稳定 DTO/handler：

- 输入：资产标识、执行策略、ASR/融合/投影配置。
- 输出：状态、产物引用、缓存是否命中、融合摘要、校验摘要和错误码。
- 不暴露 Whisper 或 ffmpeg 的内部对象。

### 8.5 最小端口集合

- `AudioExtractor`
- `AsrEngine`
- `MediaProbe`
- `TranscriptionCache`
- `TranscriptionArtifactStore`
- `ChecksumService`

测试使用对应 fake，完整 application 流程不得要求网络、真实 ffmpeg 或模型文件。

## 9. 错误语义

- 输入视频或上游溯源无效：立即失败，不调用 ASR。
- 音频提取、媒体探测或 ASR provider 失败：阶段失败，记录具体步骤与可诊断信息。
- 官方逐字稿缺失或局部无法匹配：继续执行，记录融合未启用或未匹配指标。
- alignment 不满足时间轴不变量：立即失败，不生成权威 SRT。
- 门禁 B 失败：阶段失败，不发布 canonical `english.srt`。
- manifest/产物写入失败：阶段失败，不将部分落地视为成功。

## 10. 验证策略与验收标准

### 10.1 纯单元测试

- alignment 时间范围、排序、重叠和空文本不变量。
- 官方逐字稿可靠匹配时替换文本但不改变时间。
- 匹配不足时保留 ASR 文本并产生指标。
- alignment 到 SRT 的确定性投影。
- 门禁 B 对乱序、重叠、断号、空文本、越界和覆盖缺失的拒绝。
- 缓存键稳定，并随音频内容或任一结果相关 ASR 参数变化。

### 10.2 application 离线测试

- 注入 `FakeAudioExtractor`、`FakeAsrEngine`、`FakeMediaProbe` 和内存 store，完整流程
  无网络、无 ffmpeg、无 Whisper 可运行。
- 第二次以相同音频与参数运行时命中缓存，不再次调用 ASR。
- 逐字稿变化时复用原始 ASR 缓存，但重新执行融合和 SRT 投影。
- 产物或参数与 manifest 不一致时不得误判为完成。
- 写入失败时不会留下被识别为成功的半成品。

### 10.3 集成与 golden 验收

1. 对同一 `video.mp4` 与可取得的 legacy 输出比较，句级时间戳和英文字幕差异为空或
   有书面解释。
2. CNBC 样例中，可靠匹配处采用官方文本并保留 ASR 时间，manifest 包含融合覆盖率。
3. 故意构造乱序或重叠时间轴时，门禁 B 报错并阻止正式 SRT 发布。
4. 删除工作区视频衍生产物后重跑，只要音频内容和 ASR 参数相同，就命中 ASR 缓存。
5. 完整离线 pytest 套件通过。

## 11. 取舍与后果

### 正面后果

- 直接满足字幕烧录需要，减少模型依赖、运行时间和故障面。
- alignment 与 SRT 解耦，修改投影规则无需重跑 ASR。
- 官方逐字稿得到利用，同时不会伪造时间轴。
- provider 隔离使测试可离线运行，也允许以后替换本地 ASR 引擎。
- manifest 与内容哈希缓存避免昂贵阶段被重复执行或误判完成。

### 代价

- 不能支持逐词高亮或卡拉 OK 字幕；若未来出现此类需求需重新决策。
- 官方逐字稿融合需要可解释的保序匹配和阈值调优。
- 实现前需要为 `alignment.json` 补充 `archive_core` 公共工件契约。

## 12. 被替代的旧方向

本决策明确替代路线图和旧模块指南中关于“词级时间戳”“词级/分段对齐”和 forced
alignment 为 Phase 1 必需能力的表述。那些文档可在后续独立文档维护切片中同步；
实现时以本 ADR 和更新后的 `src/transcription/AGENTS.md` 为准。
