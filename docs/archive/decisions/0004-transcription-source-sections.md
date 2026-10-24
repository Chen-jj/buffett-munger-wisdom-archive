# ADR-0004：transcription 在 source alignment 中发布文档 section

- 状态：已实现并通过离线与 CNBC 真实集成验收
- 日期：2026-10-13
- 影响模块：`archive_core`、`transcription`、`translation`
- 关联决策：ADR-0001（已归档）、ADR-0002（已实现并通过Codex CLI真实集成；旧OpenAI gate由ADR-0005取代）
- 所属阶段：Phase 1

## 1. 决策摘要

`transcription` 在发布最终 `source_alignment.json` 前，利用结构化逐字稿 chapter 与
official token（OT）的既有映射，生成来源无关的 `sections`。一个 section 表示一段连续、
语义强相关的完整句子；对 CNBC，它对应官网逐字稿中的一个 chapter，通常是一组完整问答。

```text
chapters.json
  → official token 携带 chapter_index
  → timed word 引用 0、1 或多个 official token
  → 为 word 计算有效 document section
  → document section 变化时强制句界
  → 连续 sentences 聚合为 sections
  → source_alignment.json
```

核心决策：

- `source_alignment.json` 继续使用 `transcription.source-alignment.v1`；仓库仍处开发态，
  不为本次字段扩展升级 schema version，也不提供旧产物兼容 shim。
- 顶层始终序列化 `sections`；没有可靠分组时为 `[]`。
- section 生成与网站来源无关。translation 只判断 `sections` 是否为空，不判断资产来自
  CNBC 还是 YouTube。
- `effective_chapter_index` 是独立、可靠的句界信号。句界恢复负责保证一个 sentence 不跨
  document section；最终 section 生成算法只分组和校验，不拆分或修改 sentence。
- section 是翻译上下文增强，不是英文文字和时间轴的权威来源。任何 section 异常都保守
  回退为 `sections=[]`，保留已经生成并通过现有门禁的 words/sentences，让 translation 直接
  翻译全文。回退不撤销 `effective_chapter_index` 已形成的可靠句界。
- translation 发给模型的正文仍只包含 sentence `id + text`，不发送 speaker。

## 2. 背景

CNBC 官网逐字稿已经把内容组织为 chapter。股东大会场景中，一个 chapter 通常包含观众的
一个问题及 Buffett、Munger 或其他管理层针对该问题的完整回答。组内上下文强相关，不同组
之间通常高度不相关，因此 chapter 是比固定句数或固定 token 数更合适的翻译请求边界。

当前 acquisition 公共逐字稿已经保存 chapter：

```json
{
  "schema_version": "acquisition.transcript.v2",
  "language": "en",
  "chapters": [
    {
      "number": 1,
      "title": "Question about share repurchases",
      "paragraphs": [
        {
          "speaker_label": "BECKY QUICK",
          "text": "This question concerns Berkshire's share repurchases.",
          "stage_directions": []
        }
      ]
    }
  ]
}
```

transcript fusion 也已为每个 OT 保存其结构位置：

```json
{
  "id": "ot25",
  "text": "repurchases",
  "chapter_index": 1,
  "chapter_number": 1,
  "paragraph_index": 1,
  "speaker_label": "BECKY QUICK"
}
```

但当前 `source_alignment.json` 只发布 words 与 sentences，chapter 标题及其 sentence 范围在
canonical 输出中丢失。translation 不能通过读取 transcription 私有的
`transcript_fusion.json` 恢复它们，也不应重新做逐字稿文本匹配。

## 3. 已有映射的保证与限制

### 3.1 sentence 一定包含 timed word

`SourceAlignmentDTO` 已保证：

- 每个 sentence 引用一个非空、连续的 word 范围；
- 所有 timed word 按文档顺序恰好属于一个 sentence；
- sentence 文字可由其 words 重建。

```text
s1 → w1, w2, w3
```

### 3.2 timed word 不一定引用 OT

一个 timed word 可引用 0、1 或多个 OT：

| `match_type` | OT 数量 |
|---|---:|
| `exact` / `normalized_exact` / `substitution` | 1 |
| `one_to_many` | 多个 |
| `many_to_one` / `official_only` | 1 |
| `asr_only` | 0 |

例如官网未记录的口头语：

```json
{
  "id": "w11",
  "text": "uh...",
  "match_type": "asr_only",
  "official_token_ids": []
}
```

因此 `word → OT → chapter` 不是每个 word 都成立的反向链。

### 3.3 每个 OT 一定属于一个 chapter

每个 `OfficialTranscriptToken` 必须具有正整数 `chapter_index`。一个 word 引用多个 OT 时，
现有融合与句界输入校验已要求这些 OT 位于同一个 chapter、paragraph 和 speaker 上下文。
内部计算使用文档内唯一且有序的 `chapter_index`，不使用可能为 0 或不连续的页面显示
`chapter_number`。

## 4. 公共输出契约

`SourceAlignmentDTO` 新增 `sections`，`source_alignment.json` 顶层始终包含该字段：

```json
{
  "schema_version": "transcription.source-alignment.v1",
  "language": "en",
  "audio_duration_ms": 7200000,
  "words": [],
  "sentences": [],
  "sections": []
}
```

每个 section 只包含四个字段：

```json
{
  "id": "sec1",
  "title": "Question about share repurchases",
  "first_sentence_id": "s1",
  "last_sentence_id": "s18"
}
```

字段含义：

- `id`：按文档顺序生成的稳定 ID，格式为 `sec1..secN`；
- `title`：可靠结构化逐字稿中的 chapter 标题，只作为上下文，不是 spoken text；允许空字符串，
  因为空标题不影响可靠 section 范围本身；
- `first_sentence_id`、`last_sentence_id`：该 section 覆盖的连续 sentence 范围。

公共 section 不重复保存 `chapter_index`、`chapter_number`、speaker 或 word 范围；这些属于
transcription 内部映射与诊断信息。

非空 `sections` 必须：

- 使用 `sec1..secN`，按文档顺序排列；
- 不重叠、不倒退；
- 每个范围引用存在的 sentence；
- 连续且恰好一次覆盖全部 sentences。

只允许两种完整状态：

```text
sections = []
  没有可安全发布的分组，translation 使用全文

sections = [sec1, ..., secN]
  完整、连续、无重叠地覆盖全部 sentences
```

不发布遗漏部分 sentence 的半成品 sections。

## 5. word 的有效 section 算法

### 5.1 直接 chapter 标签

对每个 timed word，读取其 `official_token_ids`：

```text
direct_chapter_index(word)
  = 该 word 引用 OT 的 chapter_index
  = None，若 official_token_ids 为空
```

一个 word 的全部 OT 必须属于同一 chapter，否则是已有融合不变量被破坏。

小例子：

```text
w1 → ot1(chapter 1)       direct = 1
w2 → 无 OT                direct = None
w3 → ot2(chapter 1)       direct = 1
w4 → ot20(chapter 2)      direct = 2
```

直接标签为：

```text
1, None, 1, 2
```

### 5.2 填充无 OT word

若文档至少有一个直接 chapter 标签，则按时间顺序确定每个 word 的
`effective_chapter_index`：

- 开头连续的 `None` 归后面第一个有效 chapter；
- 中间的 `None` 归前面最近的有效 chapter；
- 结尾的 `None` 归前面最后一个有效 chapter。

例一，两个 chapter 之间的 ASR-only words 归前一个 chapter：

```text
direct:    None, None, 1, None, None, 2, None
effective: 1,    1,    1, 1,    1,    2, 2
```

例二，全部 words 都没有 OT：

```text
direct:    None, None, None
effective: 不存在
sections:  []
```

第二种情况覆盖没有结构化逐字稿的普通 YouTube 路径。该路径不产生 document section 变化，
继续使用原有 ASR 标点、本地 detector 与 pause 句界逻辑。

跨不同 chapter 的 `None` 区间归前一个 chapter 是显式 fallback，而不是官网直接映射；必须在
transcription report 中记录 warning。

## 6. 句界恢复改动

句界恢复在构造 `SourceSentenceDTO` 之前使用 word 的 `effective_chapter_index`。该值从一个
chapter 变化为另一个 chapter 时，在新 section 的第一个 word 之前强制结束当前 sentence：

```text
w1 → section 1
w2 → section 1
w3 → section 1（ASR-only fallback）
w4 → section 2
w5 → section 2

强制句界：w3 | w4

s1 = w1...w3 → section 1
s2 = w4...w5 → section 2
```

新增来源无关的边界 provenance：

```text
boundary_source = document_section_change
boundary_status = verified
```

它表示边界来自可靠上游文档结构。当前 CNBC chapter 变化会触发；未来如果 YouTube 提供可靠
的多 section 结构，也可触发同一规则。没有结构化逐字稿或只有一个 section 时不会触发。

如果同一位置已经由更直接的可靠信号形成句界，例如官网终止标点，则保留既有更具体的
boundary source；`document_section_change` 只记录实际由结构变化强制产生的边界。

句界恢复完成后，每个 sentence 应最多具有一个 effective chapter。section 生成阶段不拆分、
重写或重新编号 sentence。effective chapter 参与句界恢复和最终 section 聚合是两个独立步骤：
即使后续 section 聚合因专属校验失败而回退为空，已经形成并通过句界门禁的
`document_section_change` 仍然保留。

## 7. section 生成算法

workflow 已经加载并校验可选的 `OfficialTranscriptInput`。句界/canonical 阶段必须同时接收其
`StructuredTranscriptDTO` 与 checksum，并验证 checksum 与
`TranscriptFusionArtifact.chapters_sha256` 一致。章节标题通过文档内唯一的、从 1 开始的
`chapter_index` 读取：

```text
transcript.chapters[chapter_index - 1].title
```

不得用可能为 0、不连续或重复的页面显示 `chapter_number` 关联标题，也不得从 ignored content
反向猜测标题。

发布最终 canonical 前，对 sentences 做一次顺序遍历：

1. 验证 sentence 的所有 words 具有同一个 `effective_chapter_index`；
2. 将连续、`effective_chapter_index` 相同的 sentences 合并为一个 section；
3. 从对应结构化 chapter 复制 title；
4. 生成 `sec1..secN` 与首尾 sentence ID；
5. 通过公共 DTO 验证完整覆盖、顺序和无重叠；
6. 验证成功后随 words/sentences 一起原子发布。

例子：

```text
s1 → 1
s2 → 1
s3 → 1
s4 → 2
s5 → 2
s6 → 3
```

输出：

```json
{
  "sections": [
    {
      "id": "sec1",
      "title": "Capital allocation",
      "first_sentence_id": "s1",
      "last_sentence_id": "s3"
    },
    {
      "id": "sec2",
      "title": "Insurance underwriting",
      "first_sentence_id": "s4",
      "last_sentence_id": "s5"
    },
    {
      "id": "sec3",
      "title": "Management succession",
      "first_sentence_id": "s6",
      "last_sentence_id": "s6"
    }
  ]
}
```

## 8. 保守回退语义

section 是可选上下文增强。以下任一情况都不猜测、不发布部分 section，而是发布：

```json
{
  "sections": []
}
```

同时保留已通过现有门禁的 words 与 sentences，包括已经由 effective chapter 形成的可靠
`document_section_change` 句界；section 聚合失败不触发第二次句界恢复，也不撤销该边界：

- 一个非空、包含 spoken text 的官网 chapter 没有任何 mapped timed word；
- effective chapter 顺序倒退或出现无法解释的跳跃；
- 句界恢复后一个 sentence 仍包含多个 `effective_chapter_index`；
- section 范围遗漏、重叠、倒退或不能完整覆盖 sentences；
- `chapter_index` 无法关联到对应结构化 chapter，或 sentence 范围无法建立可靠关联；空标题本身
  不属于关联失败；
- 其他 section 专属校验失败。

例如若最终仍出现：

```text
s10 → {1, 2}
```

section 生成算法不得把 chapter 1 和 2 合并，也不得在发布前一刻重新拆 sentence；它记录
finding 并回退 `sections=[]`。核心英文内容或时间轴自身若违反原有不变量，仍按现有规则使
transcription 失败，不能借 section 回退绕过。

纯舞台说明或没有 spoken text 的空 chapter 不属于“chapter 无 mapped word”的失败情况。

## 9. translation 消费语义

translation 不根据 `asset.source` 分支：

```text
sections 非空
  → 每个完整 section 形成一次翻译请求
  → section title 只作为上下文
  → 正文 items 只发送 sentence id + text

sections 为空
  → 全部 sentences 形成全文翻译请求
```

普通无逐字稿 YouTube 示例：

```text
所有 word.official_token_ids = []
  → 没有 effective section
  → 不产生 document_section_change
  → sections = []
  → translation 翻译全文
```

如果未来 YouTube 有一个可靠 section，则它覆盖全文，仍等价于全文请求；如果有多个可靠
sections，则使用与 CNBC 相同的 `document_section_change` 和 section 输出规则。

## 10. 分层改动

### archive_core

- 新增 `SourceSectionDTO`；
- `SourceAlignmentDTO` 新增 `sections` 及完整覆盖校验；
- 新增 `BoundarySource.DOCUMENT_SECTION_CHANGE`；
- JSON 序列化始终输出 `sections`。

### transcription domain/application

- 从 word 的 `official_token_ids` 与 OT table 计算 `direct_chapter_index` 和
  `effective_chapter_index`；
- 在句界恢复前填充无 OT word 的 section；
- document section 变化成为强制句界；
- workflow 将已验证的 `StructuredTranscriptDTO` 与 checksum 传给句界/canonical 阶段；该阶段
  验证它与 fusion 的 `chapters_sha256` 一致，并按 `chapter_index` 读取标题；
- 最终 canonical 发布前生成并校验 sections；
- section 失败时发布空数组并记录 finding，不修改或回滚已经生成的 words/sentences；
- section policy/version 进入 sentence/canonical cache key。

### translation

- 只消费 `SourceAlignmentDTO.sections`；
- 不读取 `chapters.json` 或私有 `transcript_fusion.json`；
- 不重新做 chapter/sentence 文本匹配；
- 不发送 speaker。

acquisition 的现有 `StructuredTranscriptDTO.chapters` 已能提供所需 chapter 顺序和标题，本决策
不要求修改 acquisition 页面解析。

## 11. 可观测性

实现至少应能诊断：

```text
section.asr_only_assigned_to_first
section.asr_only_assigned_to_previous
section.document_change_boundary
section.chapter_unmapped
section.non_monotonic
section.sentence_crosses_sections
section.publication_skipped
section.published
```

具体 event code 可以在实现任务中按现有 transcription 命名风格收敛，但必须区分：

- 官网/结构直接映射；
- 无 OT word 的 fallback 分配；
- document section 强制句界；
- section 回退为空的原因。

translation 不需要读取这些诊断事件。

## 12. 缓存、开发态迁移与集成产物

- 保持 `SOURCE_ALIGNMENT_SCHEMA_VERSION = "transcription.source-alignment.v1"`。
- 不读取或迁移缺少 `sections` 的旧 canonical JSON；公共 DTO round-trip 以新字段为准。
- section policy/version、chapter 输入 checksum 与结果相关参数必须进入 sentence/canonical
  cache key，避免复用旧的无 section canonical。
- 本次实现不使 audio、VAD、raw ASR 或 forced alignment 的结果相关算法失效；正常工作流应
  允许复用仍有效的昂贵上游工件。
- 仓库处于开发态。更新真实集成产物前，清理现有被 gitignore 的 `output/` 测试工作区，
  从空 workspace 重新生成，不把旧 `source_alignment.json` 当作兼容输入。

## 13. 验证范围

实现仍需在现有离线测试门槛内覆盖本次新增的纯规则，至少包括：

- word 有单一 OT chapter、多个同 chapter OT 和无 OT；
- leading/middle/trailing ASR-only word 填充；
- 全部无 OT 时 `sections=[]`；
- document section 变化强制句界；
- section 完整覆盖、顺序、重叠与稳定 ID；
- chapter 无 mapped word、顺序异常、残留跨 section sentence 时回退空数组；
- 空 chapter title 仍可发布具有可靠句子范围的 section；
- `OfficialTranscriptInput` checksum、fusion `chapters_sha256` 与 `chapter_index` 标题关联；
- source alignment JSON round-trip 始终包含 `sections`。

现有 transcription 离线套件仍是代码完成门槛，并必须增加至少一个双 chapter 的完整 workflow
离线测试，验证 chapter 变化、强制句界、标题关联和两个 section 的完整覆盖。

真实 transcription 集成用例改为仍使用 CNBC 2000 年股东大会视频，但准备并运行
`35:01`～`45:24`，对应官网逐字稿连续两个 chapter：

```text
6. “There’s nothing magic about a one-year period”
7. We want a “mathematical edge in every transaction”
```

实现该迁移时必须先清空现有被 gitignore 的 `output/` 集成测试工作区，再从空 workspace 准备
视频片段、两个 chapter 的 `chapters.json` 与 manifest，并完整运行到
`source_alignment.json`。真实验收至少验证：

- 输出包含两个按文档顺序排列的 section；
- 两个标题分别来自 chapter 6 和 7；
- section 范围连续、无重叠并完整覆盖全部 sentences；
- chapter 6→7 处存在合法句界，必要时使用 `document_section_change`；
- 第二次运行按 manifest 复用仍有效工件，并得到相同 canonical checksum。

上述真实验收已于 2026-10-15 完成：从空 integration workspace 运行 CNBC 2000 上午场
`35:01`～`45:24` 后，canonical 输出包含 1,564 words、97 sentences 和两个 section，范围分别为
`s1..s52` 与 `s53..s97`，标题与 chapter 6、7 一致；report 为 `succeeded` 且 error 为 0。
`source_alignment.json` SHA-256 为
`99f36287d28d0581ae039f64eeea55c14bef044dbb87fdca2f9c8d26ad7fbf91`。同一次测试第二次运行命中
audio、VAD、raw ASR、alignment、fusion、source alignment 六层 manifest cache，checksum 不变。

## 14. 结果与权衡

收益：

- CNBC 翻译请求可以沿用官网提供的完整问答上下文，而不是按固定句数机械切分；
- YouTube 与 CNBC 继续共享同一份来源无关的 source alignment 和句界逻辑；
- chapter 标题、句子范围与 transcription 已完成的声学/文字融合保持同一 checksum 链；
- 下游不依赖 transcription 私有工件，也不重复文本匹配；
- 异常时退回全文翻译，不因可选分组阻断有效 canonical 英文内容。

代价：

- `source-alignment.v1` 在开发态发生结构扩展，现有输出必须清理重建；
- chapter 变化成为强制句界，可能在上游结构与自然语言边界不一致时产生更强的切分；
- 跨 chapter 的 ASR-only 内容按前一个 chapter 归组是一条显式启发式规则；
- section 异常时会失去分组优化，但不会静默发布不可靠或部分分组。
