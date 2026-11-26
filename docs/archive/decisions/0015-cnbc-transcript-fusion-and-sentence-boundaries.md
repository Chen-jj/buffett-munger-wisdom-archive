# ADR-0015 改进 CNBC 逐字稿融合与句界恢复

- 状态 **已接受并实施**。完成离线验收后，使用已有声学工件重跑 2020 两场的融合与句界恢复，交付新旧工件对照。技术验收及待核听范围见 [NB-14](../tasks/NB-14-cnbc-fusion-sentence-replay.md)。
- 日期 **2026-11-25（Asia/Shanghai）**。

## 背景与取舍

CNBC 2020 Part2 旧融合把 `00:08:13` 的 `you know How` 连到约 `01:16:52` 的石油公司段落，形成 3 对 10,143 词的局部窗口。Part1 的 `3:45` 在开头缺少左锚，旧窗口以 5 个官网词整体参与缺失规模检查，实际未匹配的是 `3:` 和 `45`。扩大窗口会削弱定位，逐词回退到 ASR 会留下已经由人工确认的文字差异。因此按整句的锚点决定文字来源，对补词另外验证声学时间。[Part1 旧失败日志](../../../output/cnbc-2020-coco-full-20261117/fusion-failure-evidence-20261117T080253010500Z/part1/transcription.log#L15481) · [Part2 旧失败日志](../../../output/cnbc-2020-coco-full-20261117/fusion-failure-evidence-20261117T080253010500Z/part2/transcription.log#L20319)

句界在字幕切分前确定。旧版到 80 词可以直接断句，审阅版提到 200 词仍保留同一机制。`like I say` 和 `the B` 显示，按词数强切会打断紧密相连的表达。Part2 旧版有 22 个 fallback 句界，占 1,179 句的约 1.9%，因超过数量上限而停止发布。句界按一般规则和该处证据确定，fallback 数量和比例用于诊断。[Part2 门槛失败日志](../../../output/cnbc-2020-coco-full-20261117/pre-review-evidence-20261117T083822752987Z/part2/transcription.log#L42965) · [Part2 审阅版配置](../../../output/cnbc-2020-coco-full-20261117/cnbc_2020_part2/transcription_manifest.json)

## 逐字稿融合提议

1. 优先选择最多且不重叠、两边位置均向前的锚点链。先剥离相同前后缀，只按未匹配项计算差异规模；再用局部唯一锚点细分超限窗口。保持有界搜索。官网侧为空时按原顺序直接保留 ASR 词和时间。以 `d476fca` 的历史行为作为对照。
2. **按整句选择文字来源。** 如果若干可靠、顺序一致的锚点能把官网句子定位到同一段音频，以官网逐字稿作为整句正文。只有整句话完全对不上时才以 ASR 为准。对于已确认等价的匹配，采用官网表面写法及标点，例如 `345` 对应 `3:45`、`well-structured...` 对应 `well structured,`。开场或结尾缺一侧锚时，这类等价匹配可依据相邻上下文和已有声学范围核验。
3. 对 `a line, I mean`、`But we — money was — …` 等补词，在已定位的局部音频窗口验证词时间。**词级时间证据不足时，审阅版仍以官网逐字稿为正文**，记录 ASR 差异、所在音频范围以及哪些词的时间待复核。词时间字段只记录实际取得的证据。严格发布仍校验词级时间，证据不足时报告冲突。两种模式保留各自的策略和工件身份。

## 句界恢复提议

1. 移除仅因 80 或 200 词就分句的规则。优先使用可靠的原有句末标点和明确换人等边界证据，保留现行文档章节边界契约。段落、词间隔、ASR 分段和编辑标记可协助复核，具体的弱信号组合待确定。
2. CNBC 的 `—` 继续作为有官网来源的 `editorial_break` 保留。单独的破折号、省略号或句内逗号不足以结束句子。`well structured, well managed` 保留为一句内的连续表达；逗号可由 chunking 作为 cue 候选。分句在工件里记录首尾词范围，正文标点来自融合选定的文字。
3. **移除句界 fallback 数量和比例的发布门槛。** 保留逐条来源、数量和比例用于诊断。严格发布和审阅版均按适用的词时间、覆盖和来源契约校验。
4. **移除转录诊断日志 `source_text` 和 `result_text` 的 500 字符上限。** 日志完整记录事件传入的文字，取消为满足旧上限做的截断。

## 验收

以 `output/cnbc-2020-coco-full-20261117/` 中两场的 `chapters.json`、`aligned_asr.json`、`transcript_fusion.json`、`source_alignment.json` 及 `fusion-failure-evidence-*`、`pre-review-evidence-*` 的失败日志为固定基线。记录原始工件哈希，在独立位置验证，按各自原视频时间轴定位词及句子。

新增样例取自保存的文本、时间和来源记录，验收条件依照已确定的规则及现行契约。`s*` 和 `w*` 用于定位基线工件，核对新工件时按时间、文本和来源识别同一位置。待定的弱信号组合不预设句界结果。

### 逐字稿融合样例

| 样例 | 可观察的通过条件 |
|---|---|
| Part1 `00:00:01.946–00:00:05.029` | 使用 `3:45`，可追溯到原 `345` 声学范围 `00:00:02.687–00:00:02.907`。 |
| Part1 `00:00:31.741–00:00:32.361`，`ninety six` → `96` | 正文采用官网的 `96`。基线 `w78` 合并两个 ASR 词 `aw78`、`aw79` 的首尾声学时间，两个来源及顺序可追溯。 [融合工件](../../../output/cnbc-2020-coco-full-20261117/cnbc_2020_part1/transcript_fusion.json#L174889) |
| Part2 `00:00:10.840–00:00:12.101`，`from from Carol Loomis` → `from Carol Loomis` | 周围锚点把句子定位到开场段落。审阅正文按官网仅保留一个 `from`，两个 ASR `from`（`aw22`、`aw23`）及时间均可追溯。 [官网原文](../../../output/cnbc-2020-coco-full-20261117/cnbc_2020_part2/transcript.txt#L2) · [原审阅句](../../../output/cnbc-2020-coco-full-20261117/cnbc_2020_part2/source_alignment.json#L303465) |
| Part2 `00:08:11–00:08:16` | 审阅正文使用官网的 `a line, I mean`。检查该窗口引用的官网词 ID 均来自 `How can you` 前的本地段落。若补词的词级时间验证失败，正文仍包含官网措辞，复核记录可追溯到对应音频范围。 |
| Part1 `00:09:57.345–00:09:57.568`，`it's not — not that good` | 用保存的局部对齐成功记录复验官网补词 `ot1259`。第一个 `not` 有自己的声学时间，位于 `aw1247` 和 `aw1248` 之间，与已有 ASR 词时间不重叠。 [局部对齐记录](../../../output/cnbc-2020-coco-full-20261117/cnbc_2020_part1/transcript_fusion.json#L409668) |
| Part1 `01:33:48–01:34:01` | 审阅正文使用官网 `But we — money was — investment grade companies…` 的已确认文字，破折号按 ADR-0009 保存为辅助标记。检查补词的时间验证结果，时间缺失时有可定位的复核记录。 |
| Part2 `02:12:46–02:12:52` 和 `02:21:10–02:21:16` | 审阅正文使用前一段的 `see various statistics on that`、重复的 `I'd rather be in the`，以及后一段的 `Greg, you have any thoughts on that?` 和答话 `Nope.`。检查各自引用本地段落的官网词，复核补词的时间验证结果。`(Laughs)` 和 `[Laughter]` 等非口述标记仍按现行规则处理。 |
| Part1 `02:05:52.326–02:06:03.338`，官网收在 `So, thank you.` | 后面的 `I just looked at my watch…` 和 `That's not a unique experience…` 两句整句无官网覆盖。保留 27 个 ASR 词、原时间和句末句号。 [片尾英文源稿](../../../output/cnbc-2020-coco-full-20261117/cnbc_2020_part1/source_alignment.json#L240009) |

### 句界恢复样例

| 样例 | 可观察的通过条件 |
|---|---|
| Part2 `00:00:40.960–00:00:40.980`，`…coming in. ｜ So, there is…` | 官网有句号，同一说话人、词间隔仅 20 毫秒。保留两句，句界由句号提供。 [英文源稿](../../../output/cnbc-2020-coco-full-20261117/cnbc_2020_part2/source_alignment.json#L303489) |
| Part1 `00:03:48.375`，`berkshirehathaway. ｜ com,` | 官网写 `berkshirehathaway.com`，旧句界恰好落在域名内部的点。检查该点两侧在同一句内。 [官网原文](../../../output/cnbc-2020-coco-full-20261117/cnbc_2020_part1/transcript.txt#L21) · [旧英文源稿](../../../output/cnbc-2020-coco-full-20261117/cnbc_2020_part1/source_alignment.json#L231381) |
| Part1 `00:17:09.389–00:17:09.870`、`00:48:45.449–00:48:46.089`，`3.9 million`、`H. W. Bush` | 小数点和姓名首字母内的点保留在各自句内。 [小数样例](../../../output/cnbc-2020-coco-full-20261117/cnbc_2020_part1/source_alignment.json#L232437) · [姓名样例](../../../output/cnbc-2020-coco-full-20261117/cnbc_2020_part1/source_alignment.json#L234093) |
| Part2 `01:07:30.368–01:07:31.478` | `well structured, well managed` 在正文中采用官网写法，`structured` 和 `well` 属于同一个源句。 |
| Part1 `01:07:48.411–01:07:52.406`，`…a ｜ large 300-page…` | ASR 在 `a...` 后换 segment，词间隔 3.995 秒。官网把 `a large` 写在同一句，验收时保持连在同一源句。 [融合词 `w7787`、`w7788`](../../../output/cnbc-2020-coco-full-20261117/cnbc_2020_part1/transcript_fusion.json#L290050) · [英文源稿](../../../output/cnbc-2020-coco-full-20261117/cnbc_2020_part1/source_alignment.json#L235341) |
| Part2 `01:25:57.247–01:25:57.447`，`…that you— ｜ Well, I'm just…` | 官网说话人从 Becky Quick 变为 Warren Buffett，两侧处于同一个 ASR segment，词间隔 200 毫秒。边界按换人保留，`—` 另存为编辑标记。 [两句英文源稿](../../../output/cnbc-2020-coco-full-20261117/cnbc_2020_part2/source_alignment.json#L312021) |
| Part2 `01:50:46.622–01:50:46.682`、`01:53:23.237–01:53:23.277` | `like I say` 与 `the B` 各自保持在同一个源句内，检查双方的词 ID 和顺序。 |
| Part2 `00:20:43.830–00:20:45.370` | `but—` 保留官网编辑标记及词间隔证据。用只含破折号的对照样例证明标记本身不会新建句界，以实际换段与约 1.54 秒词间隔的组合复核待定规则。 |
| Part2 `02:21:23.691–02:21:23.731`，`yeah. ｜ And Becky, I would just say…` | 保留官网第 36 章到第 37 章的文档边界。`And Becky…` 开启 `Conclusion: Never bet against America` 的首句，上一句归前一章。 [英文源稿章节](../../../output/cnbc-2020-coco-full-20261117/cnbc_2020_part2/source_alignment.json#L317657) |

### 发布行为与回归验证

- **历史数量门槛。** 以 Part2 旧日志中的 1,179 句、22 个 fallback 为基线，固定句界计划，单独验证发布行为。其余契约通过时，严格发布和审阅版均可通过，22 个 fallback 仍可从诊断里核对。使用旧计划是为了单独验证发布行为，新规则的分句结果可以不同。 [Part2 旧失败日志](../../../output/cnbc-2020-coco-full-20261117/pre-review-evidence-20261117T083822752987Z/part2/transcription.log#L42965)
- **分别验证数量和比例。** 额外用两组符合其他契约的句界计划验收。`101 / 3,000` 超过历史审阅版数量上限，比例约 3.4%。`3 / 4` 低于历史数量上限，比例为 75%。两组均可发布，诊断如实保留数量和比例。
- **长句诊断。** Part1 `00:17:55.569–00:19:09.891` 的旧融合句在写日志前为 737 字符。读取写出的 JSONL，检查句界事件的 `source_text` 和输入逐字符一致、句界阶段成功、源稿正文完整。另用超过 500 字符的 `result_text` 验证事件写入后能读回原值。 [旧失败回执](../../../output/cnbc-2020-coco-full-20261117/part1-subtitle_rendering-20261117T084432094569Z.json#L64) · [旧截断日志](../../../output/cnbc-2020-coco-full-20261117/cnbc_2020_part1/transcription.log#L31840)

增加两个定向融合用例。固定整句锚点并模拟补词时间验证失败，审阅正文仍采用官网逐字稿，补词有待复核记录，时间字段仅保留实际取得的证据。提供一组整句无法对齐的 ASR 和官网文本，结果保留 ASR 正文及其时间并记录原因。

其余定向用例覆盖锚点远跳、去掉相同前后缀后仍超限、局部唯一锚细分及 2,000 词单侧区域。核对词时间不重叠、不倒退，ASR 来源词及其顺序可完整追溯，已发布的带时间词由句子完整覆盖，`audio`、`vad`、`raw_asr`、`aligned_asr` 哈希一致。用 `python -m pytest tests/ -q -m 'not live'` 完成离线验收。需要实际音频局部验证的样例在另行授权后取证。

## 影响范围与待决项

- 影响 `transcription` 的融合、句界、诊断和缓存身份。只改句界时复用融合结果，融合变化后重新验证句界及下游输入。
- 显式审阅策略在融合工件 v2 的 `review_sentences` 保存整句正文、对应 ASR 及声学范围，并列出缺词级时间的官网 token。一对多等价写法使用已有声学范围。`source_alignment.json` 的带时间轨继续要求实际词级证据，作为下游的内容输入。渲染输入验证识别新版融合信封，渲染内容仍取自最终双语稿。
- 对有可靠官网对应的连续表达，采用保守句界。原有句末标点、明确换人与文档章节承担断句依据。Part2 `but—` 用于观察换段和词间隔组合；放行更多弱信号组合仍需独立复核。
