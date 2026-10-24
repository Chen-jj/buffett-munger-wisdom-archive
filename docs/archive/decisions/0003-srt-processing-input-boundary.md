# ADR-0003：srt_processing 的双语 cue 规划、时间调整与工件契约

- 状态：已实现，离线与 CNBC 真实技术集成通过；质量边界见第15节

> 2026-10-24归档说明：本文件记录已完成的实现/候选实验，不代表语义质量定版。
> 用户播放烧录样片后进一步指出中文分块与英文词区间的语义错位；新方案尚未接受。
> 当前问题见[复审报告](../../reviews/2026-10-24-rendering-technical-and-semantic-review.md)。
- 创建日期：2026-09-14
- 决策整理日期：2026-10-21
- 影响模块：`srt_processing`、`archive_core`（公共工件契约）、`subtitle_rendering`（消费边界）
- 关联决策：ADR-0001（已接受并归档）、ADR-0002、ADR-0004、ADR-0005
- 所属阶段：Phase 1

> 2026-10-23用户反馈修订（候选v3技术与比较交付通过，质量未定版）：中文只在停顿标点/句末切，中文16单位为软目标；
> 7000ms是单cue显示时长告警目标，不是句长限制，不再是硬错误，也不另设10秒硬上限；
> 9CPS仍只告警，不能为达标破坏完整语块。S34接受中文自然分块优先而非逐cue严格语义对应。
> 英文实际2×42、中文一逻辑行、覆盖/锚点/非重叠/媒体末尾/500ms延长等硬约束保留。
> 本修订覆盖下文历史v1/v2冲突条款；实施与验收依赖见[SP-13](../tasks/SP-13-candidate-v3-pause-planner.md)、
> [SP-14](../tasks/SP-14-candidate-v3-contracts.md)、[SP-15](../tasks/SP-15-candidate-v3-comparison.md)。
> v3负责人完整离线复验1395 passed / 5 deselected；隔离CNBC163 cues生成与零写复用通过，
> 负责人独立复用及97句四方机器对照重算一致。短cue0、中文非停顿cut0；长度/7秒/CPS告警
> 81/9/18，S17/S22/S48等质量残余保留。全97句手工对照与33偏好验收已完成独立复算/审读，
> 中文23满足/4允许/5部分/1未满足，双语节奏18/2/12/1，**不建议质量定版**。
> [本轮报告](../../reviews/2026-10-23-cue-candidate-v3.md)保留逐句入口与成本原因；
> 不将技术通过等同于用户偏好全面满足、语义或出版质量通过。

> 2026-10-22候选试验修订：用户要求先实现英文最多2行、中文仍1行、中文内英文word计1并修边界，
> 然后逐句对照独立agent稿再决定最终策略。当前工作树已是该候选v2；本ADR以下主体保留历史v1
> 决策/验收，不把候选策略冒充最终接受。精确临时规则/接口见[SP-10](../tasks/SP-10-candidate-v2-rules.md)、
> [SP-11](../tasks/SP-11-candidate-v2-projection.md)，真实隔离集成与97句对照见
> [SP-12](../tasks/SP-12-candidate-v2-comparison.md)。新profile/词典/codec指纹使旧工件受控冲突，
> 旧资产不覆盖；候选1329离线通过、224 cues技术集成通过仍不等于内容质量定版。

> 状态核对：2026-10-21 10:11 CST。公共字幕契约、planner、适配器与 workflow 已实现，
> 完整离线1220 passed / 5 deselected；CNBC真实技术集成生成242 cues并验证即时/独立进程复用。
> 负责人/agent文本审读已完成，但不是人类签字、语义对齐或出版级字幕质量通过，已知错位与
> 拆词限制见第15节及SP-08。SP-08已通过负责人最终技术与文档验收；rendering仍是脚手架。
> 本次未改上游输入输出契约或重跑ASR；用户明确授权的SP-08A仅以现有translation准备并保留
> 正式译文，SRT实现仍完全不调用provider。

## 1. 决策摘要

`srt_processing` 消费已经完成英文词级对齐和整句中文翻译的工件，使用本地确定性动态规划
生成统一双语字幕计划。中文主导阅读速度优化；英文和中文必须同时满足字符容量、文本覆盖
与时间轴硬约束。长句可拆，符合条件的相邻句子可合并。结束时间可在源词间隙中有限延长，
但不能改变上游词时间。

核心决策：

- 分别验证 transcription、translation 两条 manifest/工件链，不能只依赖后者的传递证明。
- 使用现有公共 `SourceAlignmentDTO`、`TranslationResultDTO` 和 `TranslationManifestDTO`。
- `subtitle_plan.json` 是唯一权威字幕内容工件；固定生成英文、中文、双语三份 SRT 投影。
- 三份 SRT 共用 cue 数、序号、起止时间；rendering 消费 plan，不反解析 SRT 恢复权威数据。
- cue 规划使用本地单调比例规则和动态规划，禁止 LLM、翻译 provider、重译及文本压缩。
- 禁止跨 section、禁止一个 cue 包含已知不同 speaker；允许已知 speaker 与 `null` 合并。
- 两个 `null` 可以合并，但不能把 `null` 推断成已知标签，或借它串联两个不同已知 speaker。
- CPS 是软目标：中文主导规划和延长，中文/英文超标都只报告，不因 CPS 失败。
- 过短 cue 先尝试合并，再有限延长，仍不足则 warning。最大时长与绝对字符容量仍是硬门禁。
- 最短时长、CPS、gap 调整共用最后一个源词结束后最多 500ms 的延长额度。
- gap 美化只按调整前的原始 gap 分类，一次性处理，不做第二轮收紧。
- ffprobe 提供平均帧率近似，两帧阈值按此换算并报告警告；不检测镜头切换。
- word 间隙只是可延长空间的近似，不宣称经过静音检测，也不读取 transcription 私有 VAD。
- 本模块不做视觉换行、字体、像素测量、ASS 或烧录；这些属于 rendering。
- `pysubs2` 同时负责 SRT 写出与读回验证，已锁定 Python 3.11 兼容版本 `1.8.1`。
- profile 使用代码内版本化常量；不设置 checkpoint，不自动覆盖旧正式结果。

## 2. 术语与已有事实

### 2.1 术语

| 术语 | 本文含义 |
|---|---|
| artifact / 工件 | 管线保存的文件，例如 alignment、译文或字幕。 |
| canonical / 权威工件 | 下游正式消费的内容来源，不是临时文件或私有缓存。 |
| manifest | 保存阶段成功状态、资产身份、输入输出路径、大小和文件指纹的记录。 |
| SHA-256 / checksum | 文件内容的指纹，用于验证文件没有被替换或损坏；不是文件名。 |
| provenance / 溯源 | 记录结果来自哪些输入、规则、参数和工具版本。 |
| schema / DTO | JSON 的版本化结构及其类型化数据对象；DTO 不携带外部库对象。 |
| ASR / word alignment | 自动语音识别把声音变成文字；词级对齐为每个词提供音频时间锚点。 |
| LLM / provider | 大语言模型；provider 是执行外部识别或翻译等能力的服务实现。本模块不调用它们。 |
| speaker_label | 上游可靠来源提供的说话人标签；`null` 表示不知道，不是一个实际说话人。 |
| timed word | 一个带原视频毫秒起止时间的英文词，ID 为 `w1..wN`。 |
| sentence | 完整英文句子，ID 为 `s1..sN`，是 translation 的正文翻译单位。 |
| section | 连续句子的文档分组，例如一组问答；不是显示标题的字幕。 |
| cue / 字幕块 | 在一段时间内同时显示的一块字幕；不等于一个完整句子。 |
| fragment / 片段 | 一个 cue 内来自同一句子的英文词范围和中文字符范围。 |
| projection / 投影 | 从同一个 plan 生成不同语言文件，不再独立规划时间轴。 |
| SRT / ASS | SRT 保存序号、时间和正文；ASS 还能表达字体、颜色、位置等样式，归 rendering。 |
| codec / 序列化 | codec 负责字幕文件读写；序列化指将结构化对象写成 JSON 或 SRT。 |
| ffprobe | FFmpeg 工具集中的媒体信息探测程序；本模块只用它读取帧率和时长。 |
| QA / finding | 质量校验；finding 是校验发现的具体问题，带位置、严重程度和原因。 |
| CPL | Characters Per Line，每行字符容量；本项目使用明确定义的逻辑计数，不是像素。 |
| CPS | Characters Per Second，每秒显示字符数，即字符计数除以显示秒数。 |
| gap | 下一 cue 开始与当前 cue 结束之间的间隔；负值是重叠。 |
| frame / fps | 视频的一帧、每秒帧数；可变帧率下平均 fps 不能代表每一帧的实际时长。 |
| profile | 一组带版本和指纹的字幕参数，如字符容量、时长和目标 CPS。 |
| 动态规划 / DP | 比较完整切分路径并复用最佳部分结果的算法，不只选择眼前最佳断点。 |
| 单调比例对应 | 中英片段按原顺序配对，优先接近整句中的相对位置；不是语义对齐证明。 |
| 字典序代价 | 像比较数字列表：先比较第一项，相同才比较下一项。 |
| hard gate / 硬门禁 | 违反就不能发布成功结果；warning 只报告，不阻止发布。 |
| 确定性 | 相同输入、规则与工具版本产生字节相同的内容工件。 |
| port / adapter | port 是业务依赖的抽象接口，adapter 是文件系统、外部程序或库对该接口的实现。 |
| command / outcome | 用例的输入请求及结果摘要，不是把业务规则放进命令行处理器。 |
| overwrite / artifact conflict | 显式允许替换本阶段旧结果；否则发现损坏、残缺或过期结果时报冲突。 |
| checkpoint | 长任务的中间恢复点，不等于正式阶段完成；本模块不使用。 |
| UTF-8 / BOM / LF | 文本编码；BOM 是文件开头的编码标记；LF 是单字节换行。本方案不带 BOM。 |
| round-trip / fake | 写出再读回的往返验证；fake 是测试中替代真实文件、工具或时间的可控实现。 |

### 2.2 以当前代码为事实来源

- `src/archive_core/interfaces/transcription.py` 发布 `transcription.source-alignment.v1`，包含
  `audio_duration_ms`、`words`、`sentences`、`sections`。word/sentence ID 是字符串，不是整数。
- sentence 引用连续词范围，文字可从这些词重建，首尾时间与引用词相同；所有词恰好覆盖一次。
  非空 sections 连续、完整覆盖 sentences；`sections=[]` 表示没有可靠分组。
- `src/archive_core/interfaces/translation.py` 发布 `translation.result.v1`。正文位于
  `sentence_translations`，只有 `sentence_id + translated_text`，不是旧草案的 `units`，也不重复
  保存 `source_text`。标题位于 `section_title_translations`。
- 译文只有整句中文，不含句内中英片段对应。字幕模块不能假设两种语言的第 N 个逗号对应。
- transcription 的 `raw_asr.json`、`aligned_asr.json`、`transcript_fusion.json`、`vad.json`
  不是本模块的输入；translation checkpoint 同样不是正式完成证明。

现有 CNBC 双 section 验收 alignment 包含 1,564 words、97 sentences。21 个句子超过 8 秒，
10 个超过 12 秒，最长约 19.68 秒，说明固定 `sentence = cue` 不足以处理实际长句。此统计
只是样本，不作为硬编码参数或代表性质量结论。

## 3. 业界参考、取舍与适用范围

### 3.1 Netflix：借鉴制作原则，不宣称完整交付合规

Netflix template 规范重视从句级分段及阅读节奏；timing 规范使用语音锚点、有限结束延长、
短间隔收紧和必要的合并借时，同时还考虑镜头。本项目只采用 audio/gap 子集，不处理镜头，
不删除或压缩原文/译文。[Subtitle Templates](https://partnerhelp.netflixstudios.com/hc/en-us/articles/219375728-Timed-Text-Style-Guide-Subtitle-Templates)、
[Timing Guidelines](https://partnerhelp.netflixstudios.com/hc/en-us/articles/360051554394-Timed-Text-Style-Guide-Subtitle-Timing-Guidelines)

本项目允许原有非重叠的 0～2 帧 gap 保留，最短时长和 CPS 违规只告警；空格不计数、中文
半宽累计也是本项目约定。这些不是 Netflix 完整交付规则，参数档不能命名为“Netflix 合规”。

### 3.2 AppTek 2025：借鉴 source template 的时间锚点与容量意识

AppTek 2025 先形成源语言字幕模板，再在固定 block 数量和时间下放入完整句子的译文；使用
神经分段、逐行容量和时长/CPS 预算，还通过翻译长度控制压缩译文。本文不复制其专有模型或
重新翻译机制，只借鉴 word 时间锚点、统一计划、容量校验和利用间隙改善阅读的思路。
[AppTek 2025 论文，§2.3、§4.1](https://aclanthology.org/2025.iwslt-1.21.pdf)

| 维度 | Netflix 规范 | AppTek 2025 source template | 本项目决策 |
|---|---|---|---|
| 分段方式 | 人工遵循自然从句 | 神经分段与硬约束 | 本地规则 + DP |
| 目标译文 | 可以编辑 | 可控长度翻译 | 已固定，禁止改写 |
| 时间来源 | 音频与镜头 | 源词与有限延长 | 源词与 word 间隙近似 |
| 双语时间 | 不是本项目式同屏约束 | 固定源模板时间 | 单一双语 plan，三种投影 |
| 无法全部满足 | 编辑与制作判断 | 长度控制等处理 | 硬约束无解失败，阅读问题告警 |

### 3.3 已选择与未选择的方案

| 议题 | 已选择 | 未选择及原因 |
|---|---|---|
| 长句 | 本地中英单调比例规划 | 一句一 cue 无法应对长句；不引入新对齐模型。 |
| 权威工件 | 持久化 plan | SRT 会丢失词范围、中文范围和方法溯源。 |
| 搜索 | 确定性动态规划 | 贪心无法比较后续的碎片、时长和阅读代价。 |
| SRT 编解码 | `pysubs2` 同时读写 | 不另建完整自有 codec，但固定版本并读回校验。 |
| 文本溢出 | 再切分/合法合并/有限延长 | 不采用 AppTek 式重译压缩，不自动增加行数。 |

## 4. 流程图与职责

```text
transcription_manifest.json                  translation_manifest.json
source_alignment.json                       translation_result.json
             |                                         |
             +--------------+--------------------------+
                            v
               [分别验证 + 交叉校验 SHA-256]
                            |
video.mp4 -> [同源校验 + ffprobe 平均帧率/时长]
                            |
                            v
                [按 sentence_id 关联双语文本]
                            |
                            v
             [英文词断点 + 中文断点 + 合并候选]
                            |
                            v
             [硬约束过滤 + 有限延长预估 + DP]
                            |
                            v
            [一次性时间调整 + 全文覆盖/时间轴 QA]
                            |
                            v
                   subtitle_plan.json
                            |
            +---------------+----------------+
            v               v                v
       english.srt     chinese.srt     bilingual.srt
            +---------------+----------------+
                            v
               [pysubs2 读回并对照 plan]
                            |
                            v
             srt_processing_report.json
             srt_processing_manifest.json（最后发布）

subtitle_plan.json -> subtitle_rendering
                      视觉换行 / 字体与像素 QA / ASS / 烧录
```

### 4.1 本模块负责

- 输入及媒体证据验证、双语关联、cue 拆分/受限合并、字符容量、时间调整和 QA。
- 统一 plan 与固定三份 SRT 投影；SRT 的结构解析、校验和序列化。
- manifest 驱动的确定性复用、显式覆盖、报告及失败分类。

### 4.2 本模块不负责

- ASR、词级声学对齐、英文句界恢复、speaker 识别或重新推断 section。
- LLM、Codex CLI、翻译 provider、补译、润色、压缩、删除填充词或修改标点。
- 新的音频静音检测、镜头/场景检测。
- 根据实际字体或画面宽度插入视觉换行、像素测量、样式标签、ASS 或 ffmpeg 烧录。
- 显示 section title、speaker 名称或没有公共时间锚点的舞台说明。

## 5. 正式输入、工作区与门禁

### 5.1 对外调用

对外 command 提供 `asset_id`、`transcription_manifest_path`、`translation_manifest_path`、
`overwrite=false`。v1 使用代码内唯一版本化 profile，不由调用方传递任意阈值或输出 variant。
工作区从 `archive_core.application.build_asset_workspace()` 派生，文件名统一由
`archive_core.domain.artifacts` 定义。视频路径也是规范 `video.mp4`，不接受另一个任意视频。

对外 outcome 区分 `succeeded`、`reused`、`failed`，提供 plan/manifest/report/SRT 路径、cue
数量、warning 数及安全的错误类别；不得暴露 `pysubs2` 对象。接口仅校验输入、调用用例和展示。

### 5.2 第一条链：transcription

1. 校验当前受支持的 `transcription.audio-vad-asr-cache.v1`、资产身份与规范 manifest 路径。
2. 要求 workflow 成功，`records.source_alignment` 成功且路径规范。
3. 验证实际 alignment 大小、SHA-256，与成功 record 一致。
4. 使用公共 `SourceAlignmentDTO.from_dict()` 解析，继承其词时间、ID、句子与 section 覆盖检查。
5. v1 要求非空 words/sentences，语言为 `en`；不接受损坏、未知版本或旧草案字段。

### 5.3 第二条链：translation

1. 使用公共 `TranslationManifestDTO` 验证版本、成功状态、资产身份和规范路径。
2. 验证正式 result 的大小、SHA-256 与 manifest 的 output 一致。
3. 使用 `TranslationResultDTO.from_dict()` 解析，要求 `en -> zh-Hans`。
4. 调用 `validate_against_alignment()`，验证 sentence 顺序、完整覆盖、唯一 ID 及 section 标题规则。
5. result 的 `source_alignment_sha256`、translation manifest 的 input 指纹，必须同时等于本次
   实际计算的 alignment 指纹。不能因为翻译自己的 manifest 成功就跳过第一条链。

标题仍作为上游完整工件的一部分接受验证，但不产生 title cue，不把标题混入 spoken text。

### 5.4 媒体验证与 ffprobe

- 对规范 `video.mp4` 计算指纹，核对 transcription 成功 audio record 的
  `provenance.video_sha256`，确保探测视频与转写同源；不得只相信文件名。
- ffprobe 通过本模块端口和 infrastructure adapter 执行，读取选定视频流的平均帧率及媒体
  时长；进程使用参数数组，不在 domain/application 调用 subprocess。
- 平均帧率保存为正有理数 `p/q`，保留原始分子分母；两帧整数毫秒阈值为
  `G = ceil(2000 * q / p)`，`ceil` 表示向上取整。24fps 下 `G=84ms`。
- 这是平均帧率近似，不是逐帧校准；包括可变帧率在内都按相同近似处理并记录 warning。
  不读取逐帧时间戳，不把毫秒时间强制吸附到帧网格。
- 缺少可用视频流、无效/零平均帧率、探测失败或无效时长属于输入/媒体错误，不静默猜测24fps。
- 显示结束不得超过实际视频末尾；同时不超过公共 `audio_duration_ms`。两者取较早者作为可用
  末尾。源词本身若超出可用媒体时间则失败，不能截词来修复。

## 6. 参数档、计数和视觉换行边界

### 6.1 版本化 profile

参数档命名为 `netflix-audio-gap.zh-priority.v1`，算法标识为 `bilingual-monotonic-dp.v1`。
profile 在代码中定义，完整内容稳定序列化并计算 SHA-256；参数、计数规则或代价变化必须更新
相应版本并使旧结果产生冲突。以下是本项目初值，不是运行时可变选项。

| 参数 | 值 | 违规后果 |
|---|---|---|
| 英文单行容量 | 42，按英文计数 | 硬错误 |
| 中文单行容量 | 16，按中文加权计数 | 硬错误 |
| 中文目标 CPS | 9，主导规划与延长 | warning，不失败 |
| 英文参考 CPS | 17，仅质量报告 | warning，不失败 |
| 最短显示时长 | 5/6秒，整数毫秒实现向上取整为834ms | 合并、延长后仍不足则 warning |
| 最大显示时长 | 7000ms | 硬错误 |
| 相邻间隔目标 | 平均帧率换算的2帧阈值 `G` | 不强制截词，不足只保留/报告 |
| 短 gap 分类上界 | 500ms，不含等号 | 按第9节处理 |
| 单 cue 延长总额度 | 相对于最后一个源词结束最多500ms | 不得突破 |
| 跨句合并停顿上界 | 原始句间停顿严格小于500ms | 不合格就排除候选 |
| 单语显示行数上界 | 每种语言最多2行 | 实际排版由 rendering 验证 |
| 双语显示行数上界 | 中文1行、英文1行，中文在上 | 实际排版由 rendering 验证 |

最短/最长时长和阅读速度基线参考
[Netflix General Requirements](https://partnerhelp.netflixstudios.com/hc/en-us/articles/215758617-Timed-Text-Style-Guide-General-Requirements)、
[English Template](https://partnerhelp.netflixstudios.com/hc/en-us/articles/219375728-Timed-Text-Style-Guide-Subtitle-Templates)、
[Chinese Simplified](https://partnerhelp.netflixstudios.com/hc/en-us/articles/215986007-Chinese-Simplified-Timed-Text-Style-Guide)。
最短时长按约0.833秒的时间目标使用，不在所有帧率下固定20帧。

### 6.2 文字规范与计数

- 英文从引用 timed words 按公共 `reconstruct_sentence_text()`/空格标点规范重建，不改写词。
- 中文将上游译文的布局空白（含换行、制表）折叠为一个普通空格并去首尾空白；不改字、数字、
  大小写或标点。原始工件不修改，字符范围以此规范化后的译句为准。
- 中文：汉字/全角字符计1；Latin 字母、数字、半角标点计0.5；空格计0，标点不能忽略。
  内部用整数半字符单位，例如汉字计2、Latin计1，避免浮点累积。
- 英文：普通非空白字符和标点计1，空格计0；不能将中文的半宽规则套到英文42容量上。
- 不切开字符的组合标记序列，不把纯空白片段作为 cue。其他 Unicode 边缘字符的分类表与测试
  随计数规则版本固定，不因运行机器不同自行改变。
- CPS 使用实际最终显示时长；规划时以同一时间调整函数的预估结果计算，发布前再复算。
  英文超标不反过来驱动重切分或额外延长，中文容量/目标优先不豁免英文容量硬约束。

### 6.3 字符容量不等于视觉换行

本模块决定“什么时候换下一块字幕”，rendering 决定“同一块内部如何按画面排版”。

- plan 只保存 `english_text`、`chinese_text`，不保存 `english_lines`/`chinese_lines`。
- 单语 SRT 不插入视觉换行；双语仅用一个换行分隔中文与英文，不按字体/屏宽计算行断点。
- 三种投影共用 cue，v1 以双语各一行的容量为更严格上界：每 cue 英文不超过42、中文不超过16。
  单语通常也是一行，满足“最多两行”，但不利用第二行扩大共享 cue 容量。
- 字符合格不能保证任意播放器都不自动换行。rendering 直接消费 plan，做实际字体/字号/画面
  的像素 QA；不能为排版需要静默改变 cue 时间或正文。
- SRT 不生成 HTML/ASS 样式标签，不把输入中的类似标签文本静默解释为排版指令。codec 若不能
  无损表示正文，结构/读回门禁失败，不能自动剥除文字后宣告成功。

## 7. 双语关联、候选断点与合并

### 7.1 关联成句级数据

按 `sentence_id` 关联英文句子、timed words、完整中文译句、可空 speaker 及所属 section。
有 sections 时记录 section ID；`sections=[]` 时保持无分组，不自行猜测。ID 是机械关联依据，
不能依赖相似文本或猜测数组位置。

句级数据只是工作视图，不是另一份权威内容。一个句子可生成多个 cue，一个合法 cue 也可包含
多个相邻句子的片段。

### 7.2 候选断点

| 来源 | 候选位置与优先性 |
|---|---|
| 英文 | sentence 末尾优先；其次分号/冒号、逗号/破折号和合理停顿；局部规则保护姓名、数字单位及紧密短语；普通 word 边界是应急候选。 |
| 中文 | 句末标点优先；其次分号/冒号、逗号/破折号；普通字符边界是应急候选。 |
| section/speaker | 不允许的边界是硬限制，不只是“代价较高”。 |

标点、局部语言规则和停顿只是启发式信号，不宣称具有句法模型或语义模型的判断能力。英文
只在 word 之间切，不把单个 word 再拆成无时间锚点的字符。若一个不可拆 word 已超绝对容量，
且没有合法规划，则失败，不自动加行。

### 7.3 单调对应与文本守恒

- 一个句内英文词前缀只能对应中文前缀，后段不能回头映射到前段。
- 句内用英文累计文本长度与中文累计加权长度的归一化位置作为比例参考，标点优先级独立参与
  代价。停顿只影响时间与断点提示，不当作跨语言语义证据。
- sentence 的英文末尾与其完整中文译句末尾必须对应；不把 `s1` 的中文分配给 `s2` 的英文。
- 跨句 cue 在每个 sentence 边界拆成 provenance fragment，保存各自源词与中文范围；允许连续
  的尾片段、完整中间句、首片段组合，但每个片段两种语言均须有正文。
- 全部 fragments 的 word 范围按顺序恰好覆盖全部源词一次。每句中文字符范围也须按顺序恰好
  覆盖其规范化译句一次，不能只检查“字符计数相等”。
- 中文范围使用从0开始、含起点不含终点的 Unicode 字符索引，例如 `[0,5)` 取前5个字符。
  范围不是 UTF-8 字节位置，也不是加权字符容量。保留原范围足以恢复布局空白，显示时不把
  片段首尾空格当作新文本；拼接守恒按源范围验证。

### 7.4 跨句合并资格

```text
至少一个待合并单元的原始时长 <834ms，或原始中文 CPS >9
  AND 每个被跨越的原始句间停顿 <500ms
  AND 同一 section（或全文没有 sections）
  AND cue 内全部非空 speaker 标签至多一种
  AND 合并后通过全部硬门禁
  -> 才允许作为 DP 合并候选
```

“原始”均根据源词首尾时间计算，不用已经延长后的显示时间创造合并资格。待合并单元是该候选
涉及的各 sentence 片段；原始句间停顿由相邻两个 source sentences 的首尾词计算，不使用
ASR segment 边界。候选资格不等于必须合并；不得只为减少条目数吞并明确停顿。

| speaker 组合 | 资格 |
|---|---|
| 相同已知标签 | 可进入候选 |
| `null + null` | 可进入候选 |
| 已知标签 + `null`，或反向 | 可进入候选 |
| 两个不同已知标签 | 禁止 |

`BUFFETT -> null -> MUNGER` 不能整体合为一个 cue；判断完整候选中非空标签的集合，不能只
检查相邻一对。片段保留自己的 `speaker_label`，不把 `null` 填成已知标签。section 变化是
绝对边界，speaker 不确定不等于可忽略已知不同 speaker。

## 8. 动态规划算法

### 8.1 状态和转移

状态表示“已经消费到哪个英文 word 边界、哪个 sentence 的哪个中文字符位置”。从起点到
终点的一条路径就是完整 cue 序列。一次转移创建一个中英均非空的候选 cue：

1. 选择连续源词范围及其英文文本。
2. 在对应 sentence 内选择中文范围，跨句时保留 sentence 锚点与 fragments。
3. 使用第7节排除非法跨界/合并，使用容量与7000ms限制排除不可能候选。
4. 基础开始为第一个 word.start，基础结束为最后一个 word.end。
5. 下一个未消费 word 就是下一 cue 的开始锚点；因此候选生成时即可按第9节预估可用延长。
6. 用最终可行时间计算软代价，保存通往下一状态的最佳完整前缀。

无回边，所有转移都向前消费文本。可以按已确定的 section 拆开计算；不能因为局部 speaker
未知就丢失第7.4节的完整候选检查。枚举受时间和字符容量限制，不为超长全文生成全量稠密
中英矩阵。只按硬约束和已证明不会更优的状态剪枝，不能因为 CPS 超标就剪掉唯一合法路径。

### 8.2 D39：字典序代价

先排除硬错误，再依次比较下表；前项更优就不被后项反转。不使用一组难解释的任意浮点权重。

| 顺序 | 目标 | 解释 |
|---|---|---|
| 1 | 最少应急断点 | 普通英文 word/中文字符边界只在需要时使用。 |
| 2 | 最少局部规则识别的不自然断点 | 尽量不拆姓名、数字单位和紧密短语；不是语义正确性证明。 |
| 3 | 最少延长后仍过短的 cue | 已先枚举合法合并，再评估延长，最终不足可告警。 |
| 4 | 最低中文 CPS 超标代价 | 只累计超目标部分，超标程度越大代价越高，不作为可行性门禁。 |
| 5 | 最低句内中英累计位置偏差 | 用单调比例降低明显错位，不承诺语义等价。 |
| 6 | 最少跨句合并 | 同等质量时保留完整句子边界。 |
| 7 | 最少 cue 数 | 前面质量相同时减少不必要切换。 |
| 8 | 固定断点顺序 | 按整条路径的英文、中文断点序列比较，保证唯一稳定结果。 |

各项聚合使用固定、版本化的整数/有理数计算；精确计算公式与规则表在实现单元测试中固定，
不能因机器、哈希遍历顺序或浮点精度变化。不存在“为了降低英文 CPS，推翻中文规划”的隐藏
代价。没有覆盖终点的合法路径即规划失败，不能发布部分 plan 或删除正文后再尝试。

### 8.3 执行顺序

```text
先生成并比较拆分/合法合并候选
  -> 对每个候选调用同一个纯时间调整函数预估最终时间
  -> DP 选定完整路径
  -> 对已选路径使用同一函数物化时间与方法记录
  -> 重新验证、重新计算 CPS 与报告
```

“先合并、再延长”不是先运行一个不可回退的贪心合并器；合并必须进入整体候选比较。时间
预估与最终物化不可使用两套规则，否则 DP 代价与发布结果会不一致。

## 9. 结束时间调整：共享额度、原始 gap 与单次处理

### 9.1 固定基础与边界

对每个选定 cue 定义：

```text
start     = 第一个源词.start_ms（不提前、不推迟）
base_end  = 最后一个源词.end_ms
base_dur  = base_end - start
raw_gap   = 下一 cue.start - base_end（最后一条为 null）
```

`raw_gap` 在分段/合并确定后、任何结束延长前计算并保存。所有预估也使用这个定义，不能用
前一次调整后的 gap 重新分类。原始时间覆盖不得重叠；负 gap 先报时间轴错误，不属于美化。

不修改任何上游 word 时间。调整不能越过下一 cue 的语音开始、已知不同 speaker 或 section
下一段的语音开始、7000ms显示时长以及可用媒体末尾。没有更早可靠时间锚点时，不虚构位于
间隙中间的 speaker/section 时间；这些边界的下一段起点就是对应源词起点。

### 9.2 可读性需求

```text
required_duration = max(834ms, ceil(1000 * 中文加权字符数 / 9))
read_extension    = max(0, required_duration - base_dur)
```

只用中文计算 CPS 延长需求。英文 CPS 另算另报，不增加延长量。最短时长、CPS 和 gap 美化
共用一份上限为500ms的额度，而不是每项各500ms，也不是多轮各500ms。

### 9.3 gap 分类

| 调整前的 raw_gap | gap 美化行为 |
|---|---|
| `raw_gap >=500ms` | 不为衔接整齐而延长；允许为最短时长或中文 CPS 延长。 |
| `G < raw_gap <500ms` | 尝试延长上一 cue，将 gap 收紧到 `G`。 |
| `0 <= raw_gap <=G` | 保留原结束，不截掉对应讲话，也不为了美化移动下一条。 |
| `raw_gap <0` | 时间轴错误，硬失败。 |
| 最后一条 | 没有 gap 美化需求，但可以为最短时长或中文 CPS 延长。 |

对原始 gap 足够的 cue，调整时以 `next_start-G` 作为相邻保护上限；已有0～G的短间隔直接
保留，不倒退截词以制造两帧间隔。这是显示调整的上限，不是要求原始输入必须有两帧间隔。

### 9.4 一次性计算

令 `B` 为在以下上限内的最大非负延长量：

- `base_end+500ms`；
- `start+7000ms`；
- 可用媒体末尾；
- 有下一条时的下一语音/section/speaker 边界及第9.3节相邻保护上限。

```text
原始长 gap 或最后一条：
    extension = min(read_extension, B)

原始短 gap（G < raw_gap <500）：
    gap_extension = raw_gap - G
    extension = min(max(read_extension, gap_extension), B)

原始 gap 在0～G：
    extension = 0

end_ms = base_end + extension
```

`max` 表示需求取足够量，而不是相加。扩展后仍不足最短时长/CPS目标则 warning；短 gap
因时长/边界限制无法收紧也只 warning。达到硬上限后不再重切或再次追加延长来掩盖问题。

**原始长 gap 例外必须保留：**800ms原始间隔，有可读性需求时延长500ms，剩余300ms可以
接受，不对这300ms再做 gap 美化，也不产生“短 gap 未收紧”警告。没有可读性需求则保留800ms。
不为了整齐强行制造500ms间隔。最后一条也受同一500ms额度及媒体末尾限制。

### 9.5 近似和风险的记录

- 全部时间仍是原视频整数毫秒。平均帧率近似产生 `timing.average_frame_rate_approximation`
  warning；记录 `p/q`、`G`、probe 版本，不宣称逐帧准确。
- 延长空间来自 word 间隙，方法记录 `space_source=word_gap`；报告说明它不证明静音，不能
  写成“音频已验证无声”，也不为了改善 CPS 启动额外 VAD。
- plan 保存 `base_end_ms`、`end_ms`、原始 gap 分类及调整用途；用途可同时包含最短时长、
  中文 CPS 和 gap 收紧，但总延长只能计算一次。

## 10. 输出契约与 SRT 投影

### 10.1 文件与 schema

所有路径均为规范资产工作区内的文件，不设置 subtitles 子目录、任意输出目录或输出选择开关。

| 文件 | schema / 角色 | archive_core 中的工件类型 |
|---|---|---|
| `subtitle_plan.json` | `subtitle.plan.v1`，权威内容 | 新增 `SUBTITLE_PLAN` |
| `english.srt` | 英文投影 | 已有 `ENGLISH_SRT` |
| `chinese.srt` | 中文投影 | 已有 `CHINESE_SRT` |
| `bilingual.srt` | 双语投影 | 新增 `BILINGUAL_SRT` |
| `srt_processing_report.json` | `srt-processing.report.v1`，诊断与统计 | 新增 `SRT_PROCESSING_REPORT` |
| `srt_processing_manifest.json` | `srt-processing.manifest.v1`，成功完成证据 | 新增 `SRT_PROCESSING_MANIFEST` |

### 10.2 plan 的内容

公共 `SubtitlePlanDTO` 至少保存：

- schema、源/目标语言、alignment/result/video 指纹；
- 可用媒体时长、平均帧率与两帧阈值；
- profile 名称/版本/内容指纹、算法及文本规范版本；
- 按顺序排列的 `c1..cN`；
- 每 cue 的 `start_ms`、`base_end_ms`、`end_ms`、可空 section ID、逻辑中英正文；
- fragments：`sentence_id`、`first_word_id`、`last_word_id`、中文起止字符索引、原 speaker 标签；
- 中英对应方法及断点/时间调整方法，不复制 findings 或执行时间戳。

以下仅示意 cue 形状，不是完整公共 DTO JSON；严格字段与交叉验证已在
`src/archive_core/interfaces/subtitles.py` 实现，以代码为准。示例假定完整英文句子是
`We agree.`，规范化中文是 `我们同意。`：

```json
{
  "id": "c1",
  "section_id": "sec1",
  "start_ms": 1000,
  "base_end_ms": 1800,
  "end_ms": 1834,
  "english_text": "We agree.",
  "chinese_text": "我们同意。",
  "fragments": [
    {
      "sentence_id": "s1",
      "first_word_id": "w1",
      "last_word_id": "w2",
      "chinese_start_offset": 0,
      "chinese_end_offset": 5,
      "speaker_label": "WARREN BUFFETT"
    }
  ],
  "mapping_method": "monotonic_proportional.v1",
  "timing_adjustment": {
    "extension_ms": 34,
    "purposes": ["minimum_duration"],
    "original_gap_ms": null,
    "original_gap_class": "last_cue",
    "space_source": "word_gap"
  }
}
```

rendering 按语言字段取正文，不能依靠“第几行是哪种语言”反推；speaker 保存在片段中，不能
把混合已知/null的 cue 简化成所有片段都有同一已知身份。

### 10.3 固定三份投影

```text
English   = cue.english_text
Chinese   = cue.chinese_text
Bilingual = cue.chinese_text + 一个换行 + cue.english_text
```

- SRT 序号为 `1..N`，与 plan 的 `c1..cN` 顺序对应；三份起止毫秒完全一致，均不得缺语言。
- 不显示 speaker、section title，不输出额外空白语言行，不新增视觉换行或样式标签。
- UTF-8、无 BOM、LF；条目用空行分隔，文件末尾有换行。时间使用 `HH:MM:SS,mmm`。
- `pysubs2` 只在 adapter 内出现，写出后必须用它重新读回，逐条比较数量、序号顺序、时间
  和纯文本。不允许库的隐式样式、转义或空事件过滤静默改变正式结果。
- 依赖已锁定为 `pysubs2==1.8.1`。2026-10-21核对：最新发布1.9.0要求Python>=3.12；
  1.8.1要求Python>=3.9，符合仓库主要使用Python3.11的约束，因此选择最新兼容版本，不升级
  整条ASR环境。[PyPI 1.8.1](https://pypi.org/project/pysubs2/1.8.1/)、
  [PyPI 1.9.0](https://pypi.org/project/pysubs2/1.9.0/)

### 10.4 report 与 manifest

report 保存阶段状态、finding code/severity、cue/sentence/word 引用、原始/最终时间和观察值；
汇总至少包括 cue、合并/拆分、过短、中文/英文 CPS 超标、未收紧 gap、延长及平均帧率近似。
报告区分启发式断点和结构错误，不把人工翻译质量评审伪装为自动语义门禁。

manifest 只证明成功的一整套正式输出，至少记录：

- 资产、`status=succeeded`、UTC完成时间；
- 两条内容输入及 manifest 的路径和 SHA-256、源视频指纹；
- profile、算法、文字/计数规则、完整相关参数；
- ffprobe 版本及探测结果、pysubs2 精确版本和固定序列化配置；
- plan、三份 SRT、成功 report 的规范路径、大小、SHA-256及摘要。

失败可尽力写出 `status=failed` 的 report，但不得生成本次成功 manifest；报告写入失败不能
掩盖原始业务错误。不新增独立日志工件或数据库。

## 11. QA、错误与发布门禁

### 11.1 硬错误：不发布成功结果

- 输入身份、路径、schema、成功状态、大小或指纹不符；媒体不可用或不可解释。
- ID不唯一/不顺序，词/译文字符覆盖缺失、重复、重排或跨 sentence 错配。
- 空正文、越界片段、非法 section，或同 cue 存在不同已知 speaker。
- 时间为负、倒退、重叠、超媒体末尾；开始不锚定首词或结束截掉末词。
- 任何 cue 超7000ms、超绝对中/英字符容量，或不存在完整合法 DP 路径。
- 三份 SRT 的数量/时间与 plan 不一致，codec 无法无损读回正文。
- 输出写入或成功发布证据失败。

不通过截词、删除译文、空语言、增加视觉行、放宽硬上限或调用 provider 来兜底。

### 11.2 warning：允许发布

- 合并/延长后仍短于834ms。
- 中文 CPS >9，英文 CPS >17；无额外“绝对 CPS 上限”。
- 原始短 gap 无法在合法延长额度内收紧；已有0～G非重叠间隔保留，不将其升级为硬错误。
- 平均帧率近似、word 间隙近似；应急断点/比例切分的诊断。

原始长 gap 因可读性延长留下中间长度间隔是明确例外，不作为收紧失败。finding 可以关联
多个原因，但不得因此重复计算延长量。

## 12. 确定性、复用、覆盖与多文件发布

### 12.1 复用身份

复用绑定实际输入指纹、profile内容指纹、算法/文字/计数版本、ffprobe探测身份与结果、
pysubs2版本和序列化参数。plan及三份SRT给定这些输入应字节一致；执行时间只放manifest，
不进入plan。复用成功工件时不为了更新计数或时间而重写正式文件。

默认 `overwrite=false`：

- 全套不存在时生成。
- 全套存在时，验证manifest、所有输出大小/指纹、可解析性、当前输入/参数身份后复用。
- 部分文件、损坏文件或身份不匹配，报 `artifact_conflict`；不静默修复/覆盖。

`overwrite=true` 才重新生成并替换本阶段整套文件，不删除/修改源视频、ASR、alignment、译文
或其他阶段资产。无checkpoint；中断后依靠正式manifest判断，必要时显式overwrite整体重跑。

### 12.2 manifest-last 发布

1. 在同一文件系统准备全部临时输出。
2. 对临时plan/SRT/report执行完整QA并计算指纹。
3. 逐文件原子替换正文与报告；“原子”只保证单个文件不出现半写内容。
4. 最后原子写入成功manifest，作为整套完成标记。

多文件重命名不是整体事务。崩溃可能留下部分新文件或旧manifest指向不匹配文件；下游必须
验证manifest列出的全部输出证据，不得因manifest存在或`status=succeeded`就接受混合代次。
失败恢复不保证自动回滚旧文件，也不自动删除残留。未来 orchestration 保证同一资产串行；
v1 不实现资产锁、不支持同一资产并发直接调用。

## 13. 分层与公共契约改动范围

| 层 | 职责与建议对象 |
|---|---|
| `domain/` | `CueProfile`、`BilingualSentence`工作视图、fragment/cue/plan、finding；纯断点、容量、合并、DP、时间调整与QA规则。 |
| `application/` | 输入加载/门禁、workflow、复用身份、投影编排、失败处理和发布；只依赖端口。 |
| `infrastructure/` | ffprobe、pysubs2、JSON/SRT文件store、指纹和原子写入适配器；共享进程能力可用`infrastructure`公共接口。 |
| `interfaces/` | command/outcome/handler及面向人的摘要；不持有规划规则，不泄漏第三方对象。 |
| `archive_core` | 新工件类型、规范文件名、`SubtitlePlanDTO`/cue/fragment及manifest/report公共schema与显式序列化。 |

跨模块不能import transcription或translation的内部实现来复用门禁；只通过archive_core公共
契约消费其工件。已有transcription manifest形状按输入schema显式验证，不为了本次方案
重构前置模块。rendering的消费约定是设计目标，不意味着当前已有实现。

方案整理时同步更新`srt_processing/AGENTS.md`，撤回“为翻译准备SRT文本单元”和“拆分仍保持
原序号/原cue不变”的旧描述。实施新增公共字幕契约及本模块实现，并在requirements锁定
pysubs2；未修改transcription/translation实现或config。rendering仅更新plan消费边界，仍是脚手架。

## 14. 验证与验收用例

### 14.1 公共契约与输入门禁

- alignment使用实际`w1..wN`/`s1..sN`/sections契约，translation使用`sentence_translations`。
- 两条链分别失败、asset不同、路径不规范、指纹/大小不符、translation引用旧alignment均失败。
- section标题按公共规则校验但不出现在cue；`sections=[]`可正常处理。
- 非空、连续/完整覆盖、未知schema、JSON round-trip及fragment字符索引交叉校验。
- 视频指纹与transcription同源证据不符时，不调用probe或planner。

### 14.2 分段、DP与文本守恒

- 短句、长句、一句跨多个ASR segment、数字/百分比/姓名、无标点以及中英明显语序重排。
- 正常标点优于应急边界；应急边界有报告但不伪装语义对齐。
- 每个word和每句规范化中文范围恰好一次覆盖；不能靠相同总长度掩盖重排。
- 中英两侧的sentence锚点一致，多句cue保存独立fragment，不串错译文。
- 单个word超容量、无合法路径、超7秒、负时间等失败；高CPS路径不得仅因高CPS被剪枝。
- 相同输入重复运行、候选生成顺序变化时输出完全稳定，tie-break覆盖等价路径。

### 14.3 合并资格与 speaker

- 过短或中文CPS超标、停顿499ms可作为候选；500ms及以上禁止跨句合并。
- 双方均无阅读问题不为减少条目而新增合并；每条被跨越的句间停顿都须检查。
- 同speaker、null/null、已知/null均允许；不同已知speaker禁止。
- `BUFFETT/null/MUNGER`不可整块合并；null标签原样保存，不推断填充。
- section边界不因speaker相同或阅读困难被跨越；合并后重新验容量与时长。

### 14.4 时间调整回归矩阵

下表非特别说明时假定24fps，`G=84ms`，且没有更紧的时长/媒体边界。

| 原始条件 | 预期 |
|---|---|
| gap800ms，无阅读延长需求 | 保留800ms，不为了衔接延长。 |
| gap800ms，阅读需要500ms | 延长500ms，剩300ms；不第二轮收紧，不报gap未收紧。 |
| gap300ms，无阅读需求 | gap美化延长216ms，剩84ms。 |
| gap300ms，但7秒上限只允许延长100ms | 剩200ms，收紧失败warning，不突破时长。 |
| gap40ms，cue过短 | gap保持40ms，不截词/移动下一条；仍短则warning。 |
| gap0ms | 保留相接，不为制造84ms空档截掉讲话。 |
| gap为负 | 时间轴错误，与gap美化无关，硬失败。 |
| 最短时长/CPS/gap各有需求 | 需求取足够量并共享额度；最终结束<=base_end+500ms。 |
| 最后一条需要延长 | 允许，但受500ms、7秒和媒体末尾共同限制。 |
| 英文CPS超标而中文无需延长 | 只报告英文超标，不额外改变中文主导时间。 |
| 可变帧率或非整数平均fps | 有理数近似及向上取整稳定，报告warning，不猜逐帧精确。 |

### 14.5 投影、发布与离线验证

- plan无视觉lines数组，单语无插入换行，双语只有中文/英文结构分隔。
- 三份SRT cue数与时间完全一致；UTF-8无BOM、LF、末尾换行、标点/转义和长时间码读回一致。
- 使用内存fake store、fake probe/process及固定clock，默认测试不运行ffprobe、模型或网络。
- 任一发布阶段故障不产生可误判的新成功状态；模拟混合代次时下游证据验证失败。
- 完整复用、部分残留/损坏/参数变化冲突、显式overwrite及上游工件不受修改。
- 用现有CNBC双section正式输入生成字幕样本，人工评审长句、短句、未知speaker和比例错位；
  像素与真实画面排版验收属于rendering，不在本模块宣称已验证。
- 实现完成门槛为完整离线pytest全绿；SRT实现/默认测试不新增网络或LLM调用。SP-08A的既有
  translation真实运行是用户明确授权的样本输入准备例外，不进入SRT实现。

## 15. 决策状态与实现状态

本轮已列出的产品/技术选择均已确认，不保留未回答的方案选项。参数边界、纯函数公式、
完整DTO严格字段与错误码已在实现切片中用上述不变量及测试固定；这是落实方案，不允许
以“实现细节”为由改回LLM、静默重译、强制CPS失败或视觉换行。若发现必须改变已确认行为，
应先回到ADR讨论，不能自行引入新默认值或降级路径。

### 15.1 历史离线验收与样本前置阻断（2026-10-21 09:05 CST）

截至2026-10-21 09:05 CST，SP-01..07已全部accepted：公共字幕DTO、冻结文本规则、确定性
稀疏DP、双链/媒体门禁、ffprobe/pysubs2/本地store、三份投影、复用与manifest-last发布已实现。
跨层/对抗验收与完整离线pytest通过（1220 passed / 5 deselected）；依赖已锁定，显式本地
样本入口为 `PYTHONPATH=src .venv/bin/python -m tests.srt_processing.sample_runner --run`。

负责人实际运行该入口，返回 `precondition_missing`（退出2），准确缺少
`output/transcription-integration/cnbc_2000_morning/translation_result.json` 和同目录的
`translation_manifest.json`。SP-08 blocked；用户此前要求记录并继续逻辑开发，现逻辑开发已验收，
仍待提供匹配正式工件目录或明确授权既有translation流程补齐。transcription集成测试不生成
translation工件，本轮未重跑ASR/翻译、伪造译文、放宽门禁或删除资产。

真实CNBC字幕生成、第二次正式复用与内容人工抽检均未执行，ADR最终样本验收尚未完成。
临时合成离线样本通过不替代该项；rendering、像素/ASS/烧录和端到端管线仍未实现或验收。

以上为09:05的历史记录，不代表当前仍缺译文或未运行技术样本；下节记录用户授权后的恢复。

### 15.2 当前真实技术集成与持久复用（2026-10-21 10:11 CST）

用户明确选择方案2，SP-08A通过未改动的现有Codex CLI translation生产流程补齐并持久保存
97句/2 sections正式译文与manifest：2次生成调用成功，第二次provider/process/exec均0，
17份原工作区文件不变。该样本准备任务已accepted，未重跑ASR，未改provider/auth/config，
SRT workflow与本地字幕入口本身仍完全不调用provider。证据见
[SP-08A](../tasks/SP-08A-prepare-persistent-cnbc-translation.md)。

负责人实际运行独立字幕入口，首次`succeeded → reused`（99.7455s / 0.7465s），生成242 cues
和六份正式工件；第二次零stage/publish、六输出bytes/mtime一致、19份现有上游文件未变。
另启独立Python进程再次`reused → reused`（0.7470s / 0.7328s），证明持久文件而非进程内缓存
复用。真实ffprobe9.0.1探测30/1fps、G=67ms、可用时长623000ms，codec为pysubs2 1.8.1。
双输入链、所有输出证据、公共DTO/全文覆盖/时间及三投影读回通过；完整离线复验仍为
1220 passed / 5 deselected。SP-08技术样本、负责人内容审读与最终文档验收已完成，任务accepted；详尽hash/工具/统计/证据见
[SP-08](../tasks/SP-08-real-sample-and-final-status.md)。

保留规范工作区正式工件后，未来可直接独立运行同一字幕入口验证并复用，无需ASR、translation
或其他模块live测试；完整离线pytest仍是代码改动门槛。生成资产保留在gitignored output，
没有删除或提交。

### 15.3 真实内容审读的质量边界

负责人/agent已审读97句及242 cues的长短句、null speaker、数字/否定/术语及比例错位。
**这不是人类签字，未观看音画，也不证明语义对齐、出版级字幕或像素/ASS/烧录质量通过。**
无ADR硬契约缺陷，不等于全片字幕质量过关；已知限制明确保留：

- c3/c4（s3）中人物Moe Spence与地名Waterloo/Nebraska语序不同，cue人物/地名明显错位。
- c183–185（s74）出现中文语义提前与“风/险”拆分。
- c142–147（s60）将长句拆成六cue，硬门禁合法，但“认/为”“——”被切开且有片段语义滞后。
- c12–14、c116/117等把中文栏英文专名或“有价证券”拆开；这些应急字符边界阅读不自然。

样本185项warning中含2条过短、中文CPS超标12个及英文CPS超参考95个，无硬错误；CPS是软
目标，不能把发布成功当作舒适阅读证明。若要求汉语分词、中文栏专名保护或句内语义对齐，
需另行确认算法/决策版本，不在本轮静默重译、改字或放宽硬门禁。内容编辑、人类复核与
rendering视觉验收仍不在本次技术完成声明内。

## 16. 主要风险与已知限制

- **比例不是语义**：中英语序变化可能造成看似合法但意义提前/滞后的片段，需要样本人工评审。
- **词时间误差传播**：本模块不能修正上游声学时间，发现问题应报告或回到上游。
- **word gap并非静音**：未知声音或未识别讲话可能位于间隙内；最多500ms仍只是有限风险控制。
- **平均帧率近似**：可变帧率下两帧阈值不具逐帧意义，报告必须明确。
- **完整保留文本的代价**：不压缩正文且CPS只告警，不承诺所有字幕都能舒适读完。
- **双语更严格**：共享时间轴和各一行限制可能增加cue数；单语两行容量不用于放宽本版规划。
- **字符非像素**：保留Latin专有名词可能导致真实视觉溢出，rendering必须另外验证。
- **多文件非事务**：manifest-last仍要求下游完整校验证据，不能只检查成功字符串。

## 17. 参考

- [Netflix Subtitle Templates](https://partnerhelp.netflixstudios.com/hc/en-us/articles/219375728-Timed-Text-Style-Guide-Subtitle-Templates)
- [Netflix Subtitle Timing Guidelines](https://partnerhelp.netflixstudios.com/hc/en-us/articles/360051554394-Timed-Text-Style-Guide-Subtitle-Timing-Guidelines)
- [Netflix General Requirements](https://partnerhelp.netflixstudios.com/hc/en-us/articles/215758617-Timed-Text-Style-Guide-General-Requirements)
- [Netflix Chinese Simplified Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/215986007-Chinese-Simplified-Timed-Text-Style-Guide)
- [AppTek 2025: Generating Accurate and Well-Readable Subtitles](https://aclanthology.org/2025.iwslt-1.21/)
- [AppTek 2025论文PDF](https://aclanthology.org/2025.iwslt-1.21.pdf)
- [pysubs2 1.8.1兼容性与发布信息](https://pypi.org/project/pysubs2/1.8.1/)
- [pysubs2 1.9.0的Python版本要求](https://pypi.org/project/pysubs2/1.9.0/)
