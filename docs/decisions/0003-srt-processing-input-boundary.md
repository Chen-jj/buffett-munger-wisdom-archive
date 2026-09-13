# ADR-0003：srt_processing 的输入契约与职责边界

- 状态：讨论中
- 日期：2026-09-14
- 影响模块：`srt_processing`、`archive_core`（公共工件契约）
- 所属阶段：Phase 1

> 本文是讨论稿。当前只确认输入可行性和模块边界，不决定双语 cue 的具体算法。被接受前
> 不替代模块 `AGENTS.md` 或现有实现约束。

## 1. 候选结论

`srt_processing` 负责把已经完成英文时间对齐和中文翻译的结构化工件转换为字幕 cue
计划，并序列化为所需 SRT。它不参与 ASR、句界恢复或翻译服务调用。

候选输入：

```text
source_alignment.json       ← transcription 输出
translation_result.json     ← translation 输出
```

候选流程：

```text
校验两个输入的 provenance 和 sentence 覆盖
  → 按 sentence_id 组合英文句子时间与中文句子
  → 规划统一 bilingual cue（具体算法待定）
  → subtitle_plan.json（是否 canonical 待定）
  → english.srt / chinese.srt / bilingual.srt
```

`english.srt` 不再是 transcription 的必要产物，而是可从统一 cue plan 派生的兼容/评审
格式。是否每次都生成仍待定。

## 2. 模块边界

### 负责

- 读取并校验字幕相关结构化输入。
- 通过 `sentence_id` 组合英文句子、词级时间和中文译文。
- 规划最终字幕 cue 的编号、时间区间和文本。
- 处理字幕行分割、cue 拆分/合并、阅读速度和时长约束。
- 保证英文、中文和双语投影之间的时间轴一致性。
- 解析、验证和序列化 SRT。
- 输出 cue QA、SRT QA 和可诊断发现。

### 不负责

- 音频提取、ASR、word alignment、标点或句界恢复。
- 调用 LLM 或其他翻译 provider。
- 修正翻译内容或用另一语言静默替代失败译文。
- ASS 样式、字体、画面布局和 ffmpeg 烧录；这些属于 `subtitle_rendering`。
- 擅自修改上游 canonical alignment/translation 工件。

“所有 SRT 操作归本模块”不表示本模块必须只消费已有 SRT。它可以从更权威的结构化
alignment 生成 SRT；SRT 是输出格式，不是翻译或时间对齐的权威来源。

## 3. 输入一：`source_alignment.json`

来自 transcription，候选最小内容为：

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
      "text": "I think the most important thing when you're evaluating a business is to understand its competitive position."
    }
  ]
}
```

SRT 模块需要词级时间，是因为长句可能必须拆成多个 cue；仅有整句开始/结束时间不足以
为句内断点提供可靠时间锚点。

## 4. 输入二：`translation_result.json`

来自 translation，候选最小内容为：

```json
{
  "schema_version": "translation.result.v1",
  "source_alignment_sha256": "abc123...",
  "source_language": "en",
  "target_language": "zh-Hans",
  "units": [
    {
      "sentence_id": "s1",
      "source_text": "I think the most important thing when you're evaluating a business is to understand its competitive position.",
      "translated_text": "我认为，评估一家企业时最重要的是理解它的竞争地位。"
    }
  ]
}
```

此输入目前只提供整句翻译，不承诺句内中英语义片段对应。

## 5. 输入关联与硬门禁

候选硬门禁：

1. `translation_result.source_alignment_sha256` 与实际 source alignment checksum 完全一致。
2. 源语言和目标语言符合当前运行配置。
3. 每个有效 source sentence 恰好有一个 translation unit。
4. 没有重复、缺失或多余 `sentence_id`。
5. translation 中重复保存的 `source_text`（若保留）与 alignment 对应文本一致。
6. source words 时间非负、单调，sentence word 范围存在、连续且覆盖合法。
7. 英文和中文文本规范化后非空。
8. 输入 manifest 状态成功，artifact checksum 与 manifest 一致。

任一硬门禁失败时不得生成 canonical cue plan 或 SRT。不得用“文件存在”绕过输入校验。

## 6. 组合后的句级中间表示

输入可以无损组合成：

```json
{
  "sentence_id": "s1",
  "source_word_range": {
    "first_word_id": 1,
    "last_word_id": 18
  },
  "start_ms": 1200,
  "end_ms": 7800,
  "english": "I think the most important thing when you're evaluating a business is to understand its competitive position.",
  "chinese": "我认为，评估一家企业时最重要的是理解它的竞争地位。"
}
```

这是句级双语数据，不等于最终 cue。一个句子可能生成一个或多个 cue；多个很短的句子
是否允许合并为一个 cue 仍待定。

## 7. 输入可行性结论

### 已足够支持

- 验证中英文句子一一对应。
- 生成“一个完整句子一个 cue”的最简单 SRT。
- 生成短句样本的 English/Chinese/Bilingual SRT。
- 以源 words 为后续句内时间切分锚点。

### 尚不足以无歧义支持

- 长句拆成多个自然且语义对应的双语 cue。
- 中文语序与英文语序不同情况下的句内时间映射。
- 一段中文天然比英文更短或更长时的 cue 数量选择。
- 跨句合并、借时、镜头切换和多 speaker 排版。

因此当前两个输入**可作为稳定基础**，但不能在 schema 或测试中预设：

```text
sentence = final cue
English phrase N = Chinese phrase N
```

## 8. 候选输出层次

候选设计区分领域计划与文件格式：

```text
BilingualSentenceDocument
  ↓ cue planner
SubtitlePlan / BilingualCueDocument
  ├── English SRT projection
  ├── Chinese SRT projection
  └── Bilingual SRT projection
```

候选 `subtitle_plan.json` 示例仅用于说明，不代表 cue 算法已确定：

```json
{
  "schema_version": "subtitle.plan.v1",
  "source_alignment_sha256": "abc123...",
  "translation_result_sha256": "def456...",
  "cues": [
    {
      "id": 1,
      "start_ms": 1200,
      "end_ms": 5100,
      "source_sentence_ids": ["s1"],
      "english_lines": [
        "I think the most important thing",
        "when you're evaluating a business"
      ],
      "chinese_lines": [
        "我认为，评估一家企业时最重要的"
      ]
    }
  ]
}
```

是否持久化 `subtitle_plan.json`、它是否为 canonical、以及 SRT 是否只是投影，均待定。

## 9. 分层设计候选

### domain

- `SubtitleCue`
- `SubtitleDocument`
- `BilingualSentence`
- `BilingualCue`
- `SubtitlePlan`
- `SubtitleFinding`
- 时间轴、覆盖、行长、阅读速度等规则

### application

- `validate_subtitle_inputs`
- `combine_source_and_translation`
- `plan_bilingual_cues`（算法待定）
- `project_english_srt`
- `project_chinese_srt`
- `project_bilingual_srt`
- `validate_subtitle_outputs`

### infrastructure

- SRT parser/serializer adapter（候选 `pysubs2`）
- artifact/manifest store
- checksum service
- 如需要，镜头切换或媒体时长探测 adapter（是否属于 v1 待定）

### interfaces

向 orchestration 暴露两个上游 artifact 引用、cue profile、执行策略以及稳定的结果/QA 摘要。
不得暴露 `pysubs2` 对象。

公共 artifact DTO/schema 必须位于 `archive_core`；srt_processing 不跨模块导入
transcription 或 translation 的内部实现。

## 10. 确定性、发布与失败

- 给定相同输入 checksum 和相同 cue profile，算法型 cue plan/SRT 应字节一致。
- 所有正式 JSON/SRT 先写临时文件，再原子发布。
- 成功工件默认不覆盖；替换必须显式请求。
- 输入变化、cue profile 变化或算法版本变化应使旧输出 stale。
- 是否将 serializer/tool patch version 计入 stale 判定待定。
- 任一输入门禁或输出 SRT 结构门禁失败时，不发布 canonical 结果。
- QA 警告与硬错误必须分开；不得静默修复上游工件。

## 11. 后续 cue 设计必须回答的问题

后续 ADR/revision 至少需要定义：

- 候选断点：英文标点、从句、停顿、source word 时间、中文标点。
- 最大行数、每行字符数、CJK 计数方式。
- 最短/最长 cue 时长、最小帧间隔、最大 CPS。
- 如何在多个候选断点中优化语义完整性、阅读速度和时间同步。
- 中文语序重排时如何获得中英句内对应。
- 是否由 translation 输出 `aligned_parts`，或使用本地双语 word aligner。
- 是否允许任何 LLM 能力进入 SRT 阶段；当前边界倾向禁止。
- 长句无法在时间约束内显示时，是合并、借时、重译、告警还是失败。
- 双语 SRT 的行顺序、空行、speaker 标签和样式标记。

## 12. 验证策略（输入部分）

### 纯单元测试

- checksum/source identity 不一致被拒绝。
- sentence ID 缺失、重复、多余被拒绝。
- translation source text 与 alignment 不一致被拒绝。
- word 时间乱序、重叠、空文本和非法 sentence word 范围被拒绝。
- 合法输入稳定组合为句级双语中间表示。

### application 离线测试

- 使用内存 artifact/fake store 验证完整输入加载与组合，无网络、ffmpeg 或 LLM。
- 输入 manifest/工件 checksum 不一致时不执行 cue planner。
- 任一正式写入失败不留下可误判为成功的工件。

### 后续 golden 测试

- 短句、一句跨多个 ASR segment、一个长句、多短句、数字和问答样例。
- 中英文语序相同和明显重排样例。
- 完整离线 pytest 通过。

## 13. 待决策问题

1. `subtitle_plan.json` 是否持久化并作为 canonical，还是只在内存中生成？
2. 是否每次都生成 English/Chinese/Bilingual 三份 SRT，还是按调用请求生成？
3. subtitle rendering 最终消费 bilingual SRT、Chinese SRT + English SRT，还是 ASS？
4. translation 结果是否必须增加中英语义 `aligned_parts`？
5. 若 translation 不提供句内对齐，本地双语 alignment 选择什么算法/模型？
6. cue planner 是规则/动态规划，还是允许 LLM；当前倾向纯本地确定性算法。
7. 最大行长、最大两行、CPS、最短/最长时长和 frame gap 的具体 profile 是什么？
8. 中英文是否必须共享完全相同的 cue 数和时间；是否允许某语言在某 cue 为空？
9. 长句拆分时如何把中文片段绑定到 source word 时间范围？
10. 是否允许跨 sentence 合并 cue；何时允许借用相邻静音时间？
11. 是否考虑 shot boundary；若考虑，媒体探测属于 srt_processing 还是 rendering？
12. speaker 信息从哪里来，如何表达双人同时/交替讲话？
13. bilingual SRT 中英文顺序、换行和 HTML/样式标签规则是什么？
14. `english.srt` 是默认产物、可选评审产物还是完全不生成？
15. SRT 编码是否固定 UTF-8、是否允许 BOM、换行符和末尾空行规范是什么？
16. `pysubs2` 是否只作为 adapter；canonical serializer 是否需要自有实现以保证字节稳定？
17. 哪些 QA 是硬门禁，哪些只是 warning；自动修复是否完全禁止？
18. canonical 产物的覆盖/stale/versioning 策略是什么？
19. 文件名、`ArtifactType`、manifest/report schema 如何在 archive_core 中定义？
20. 当前模块指南中“为翻译准备 SRT 文本单元”的旧职责何时在 ADR 接受后更新？

## 14. 风险

- **句级输入不足**：整句译文没有句内跨语言对齐，长句双语拆分可能语义错位。
- **词时间误差传播**：source word timing 漂移会直接影响最终 cue 边界。
- **中英文语序重排**：按字符比例或独立标点切分可能生成看似合法但语义不对应的双语 cue。
- **约束冲突**：自然断句、CPS、最大两行、音频同步和镜头边界可能无法同时满足。
- **职责越界**：为了修正坏译文而在 SRT 模块调用 LLM，会重新耦合 translation。
- **多份文件漂移**：若三份 SRT 分别规划而非同一 cue plan 投影，时间轴会不一致。
- **错误权威来源**：将 SRT 反解析结果作为 canonical 会丢失 word/sentence provenance。
- **静默修复**：自动调整上游时间或翻译会破坏可追溯性。
- **格式局限**：SRT 对复杂双语样式、speaker、位置和字体的表达能力有限，后续 rendering
  可能实际需要 ASS。
- **迁移冲突**：现有指南描述从 SRT 开始处理并为 translation 准备文本；讨论稿接受前存在文档不一致。

## 15. 参考

- [Netflix Subtitle Templates：从句分割与阅读速度](https://partnerhelp.netflixstudios.com/hc/en-us/articles/219375728-Timed-Text-Style-Guide-Subtitle-Templates)
- [Netflix Subtitle Timing Guidelines](https://partnerhelp.netflixstudios.com/hc/en-us/articles/360051554394-Timed-Text-Style-Guide-Subtitle-Timing-Guidelines)
- [SimAlign：本地跨语言 word alignment](https://aclanthology.org/2020.findings-emnlp.147/)

