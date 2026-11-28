# ADR-0017 修正句界恢复的标点与换人判定

- 状态 **已实施，负责人验收通过**。2026-11-28 两名实现子 agent 完成代码和典型反例测试，负责人审查 diff、独立执行完整离线套件及两场回放。
- 最近复核 **2026-11-28（Asia/Shanghai）**。融合标点与官网不一致时按融合稿处理，不强求同步官网标点；实施与证据入口见 [NB-17](../tasks/NB-17-fused-punctuation-sentence-boundaries.md)。
- 当前输入为实际落盘的 **`monotonic-local-dp.v7`** 融合词；当前结果使用本次冻结的工作树句界代码。本文只描述这组输入和结果。

本文反例中的“当前切分”指修复前固定的 v7 基线，作为可复现失败输入保留。最终交付为 `sentence-boundary.v3`，以及只为 E11 调整跨句词条粒度的 `monotonic-local-dp.v8`；新结果 **743 / 1,151 句**。**28 个反例和 4 个连续样例全部通过，完整离线 3010 passed / 1 skipped / 6 deselected。** [负责人最终验收](../../../output/cnbc-2020-adr0017-20261128/run-accepted-2/负责人验收.md) · [任务与测试映射](../tasks/NB-17-fused-punctuation-sentence-boundaries.md)。

## 阅读方式与本次产物

流程为 `ASR 词时间 + 官网逐字稿 → v7 带时间融合词 → 句界恢复 → source_alignment.json → chunking`。下游消费 `source_alignment.json`；句界恢复从融合稿读取 `words` 和来源证据，不需要 `review_sentences`。

**句界使用融合 `words` 最终保留的标点。** 官网原词和 `official_sentence_spans` 可以保留为溯源及当前问题的解释材料，但官网句号不能为融合稿的逗号新增句界，官网逗号或续说符号也不能否决融合稿的有效句末。说话人、章节和编辑标记来源仍可按各自契约使用，不因此重新采纳未进入融合正文的官网标点。例如 `2009, they…` 不因官网为 `09. They…` 而切开；反过来，融合稿为 `okay. But…` 时，句号可以直接切句，无需官网末词映射成功。

一个“带时间词条”是 `words` 中的一条记录，例如 `class?` 有开始、结束时间和 ASR 来源 ID；它不一定只有一个英文单词，E11 的 `See's. And` 就被合成了一条。一个“官网词 ID”是官网分词的身份，例如 `ot14088` 表示 `classes?"`。有官网词 ID 的融合词，可以直接追溯它采用了哪个官网词；没有该 ID 的 `class?` 仍是有效的带时间融合正文。

文中的 **`｜` 表示句界**。`｜ A. B. ｜` 表示程序把 A、B 一起放在同一个源句里，只在两端切开；`｜ A. ｜ B. ｜` 表示应在中间再切一次。`…` 只在注明“局部片段”的表格里表示省略；E01–E11 的“当前实际切分”和“建议切分”展示整条当前源句及其建议拆分，不改输入拼写。C01 展示逗号处保持同句的保好样例。

| 场次 | v7 融合词数 | 当前源句数 | 句界 fallback 数 | 本次实际输入与输出 |
| --- | ---: | ---: | ---: | --- |
| Part1 | 15,504 | 734 | 0 | [融合稿](../../../output/cnbc-2020-adr0017-20261127/run-boundaries-v7-3/cnbc_2020_part1/transcript_fusion.json) · [源稿](../../../output/cnbc-2020-adr0017-20261127/run-boundaries-v7-3/cnbc_2020_part1/source_alignment.json) |
| Part2 | 20,399 | 1,137 | 0 | [融合稿](../../../output/cnbc-2020-adr0017-20261127/run-boundaries-v7-3/cnbc_2020_part2/transcript_fusion.json) · [源稿](../../../output/cnbc-2020-adr0017-20261127/run-boundaries-v7-3/cnbc_2020_part2/source_alignment.json) |

v7 用当前生产融合服务生成，复用了已保存的声学评分；只为 Part1 `01:42:09.442–01:42:11.904` 补算一个本地窗口。该窗口取得两种候选的完整返回，ASR 候选整段 CTC 对数似然为 -83.194，官网增词候选为 -104.744；融合结果保留 `Now, we weren't getting`，没有加入 `it wasn't—`。原始模型返回已保存。没有重新运行 ASR、全片词对齐或联网下载，原输入和原融合工件保持不变。两阶段再执行均命中缓存且零工件改写。[生成回执与代码指纹](../../../output/cnbc-2020-adr0017-20261127/run-boundaries-v7-3/replay_receipt.json) · [补算窗口原始返回](../../../output/cnbc-2020-adr0017-20261127/run-boundaries-v7-3/new_acoustic_evidence_cnbc_2020_part1.jsonl)

## 已确认的行为目标

1. 融合稿中的有效 `?`、`!` 和句末 `.` 应形成句界。例如 E01 的 `class? ｜ Well,` 必须切开。官网标点及来源范围不能取消已有句末，也不能把 C01 的 `2009,` 按官网句号切开。用户已确认：`asr_only` 只表示该融合词没有采用对应官网词，既可能是 ASR 真正多出的词，也可能是冲突比较后保留的词；这两种情况都不能降低其句末标点资格。
2. 点号也可能属于词组。例如融合稿中的 `berkshirehathaway. com`、`H. W. Bush`、`Mr. Jaskier` 内部不切；`Thank you, Mr. Jaskier. ｜ Warren Buffett, Charles Munger…` 中姓名末尾的句号仍可切。例外根据融合正文的域名、姓名缩写等结构判断，不能因为官网写成逗号或破折号就忽略一个融合句号。
3. 可靠来源证明换人时切句。例如 Becky 的问题结束后 Buffett 回答，即使没有问号也应有句界。未知身份不能因为后面出现 Buffett 就被补成 Buffett。
4. 停顿交给 chunking。例如 Part2 当前 `but Our Our position…` 保持同一句；不能因为 `but` 与 `Our` 之间有较长空隙就切句。口述中的重复和修正仍保留。
5. 章节变化处保留文档边界，全文最后一句正常收尾。只改变句界的修复不得改动已成立的词时间或丢失、重复词。

## E01–E11：当前结果中建议修正的详细反例

以下 11 处已逐条核对当前词 ID、词时间和所属源句，均可从融合正文自身的句末标点发现问题。官网文字只用来解释当前实现为何漏切。后文另列 P01–P14、Q01–Q03 的其他融合句号漏切，以及应保持连续的逗号或无句末样例；本轮未核听全片，不把这些判断当成对融合正文质量的核听确认。


### E01 · Part2 · 01:35:59.128 · 提问与回答被合成一句，并把提问标成 Buffett

当前源句是 `s766`，从 `w13765` 到 `w13804`，时间 `01:35:52.066–01:36:09.952`。程序实际只在这整段的两端切句，中间目标位置没有切开。

**当前实际切分**

> ｜ Will it eventually come from all businesses through some combination of higher tax rates on corporations, increased wages for the lower-middle class? Well, I certainly think that increased corporate taxes are a much higher probability than having lower corporate taxes. ｜

**建议切分**

> ｜ Will it eventually come from all businesses through some combination of higher tax rates on corporations, increased wages for the lower-middle class? ｜ Well, I certainly think that increased corporate taxes are a much higher probability than having lower corporate taxes. ｜

建议切点为 `w13786`（01:35:59.128 结束）之后，`w13787`（01:35:59.168 开始）之前。

**为什么出现**：官网问题末尾是 `classes?"`（`ot14088`），但这个官网词没有对应到任何融合词。融合稿采用的是有时间的 ASR `class?`。该官网句最后一个有映射的词停在 `lower-middle`（`w13785`），程序不允许把句末提前放在它后面，这一步拒绝提前断句是合理的。随后却又因为 `class?` 在该官网句关联的 ASR 范围内，禁止它自己的问号触发切句。问号一直保留在正文里，只是程序不据此切句。

**如何调整**：在 `class?` 后切开，回答从 `Well,` 开始。无需先解决 `class / classes` 的融合取词，也无需补造词时间。第 26 章第 1 段标 Becky，引入 Adam Schwartz 的问题；第 2、3 段是连续引用的问题且标签为空；第 4 段明确标 Buffett 的回答。可用这组连续引语来源补足提问者证据；若尚未实现这种证明，提问保留未知标签，回答标 Buffett。两种情况下都必须先按问号切开。


这里的说话人错误还有独立原因。当前换人规则要求前后都已知身份；`class?` 所在引语标签未知，下一词 `Well,` 才有 Buffett 标签，因此没有触发换人。合并成一句之后，`_sentence_speaker()` 忽略空标签，只收集已知标签；整句唯一已知标签是 Buffett，于是整个问题也被标成 Buffett。解决问号漏切与解决引语标签缺失，应分别验收，不能用“没识别出 Becky”解释为什么不按问号切句。


### E02 · Part1 · 01:16:17.214 · et cetera. 后的下一句被并入

当前源句是 `s400`，从 `w8780` 到 `w8833`，时间 `01:16:04.800–01:16:20.455`。程序实际只在这整段的两端切句，中间目标位置没有切开。

**当前实际切分**

> ｜ You're saying to yourself, I'm paying x dollars per acre, I think I'll get so many bushels of corn or soybeans on average, some years good, some years bad, some years the price will be good, some years the price will be bad, et cetera. But you think about the potential of the farm. ｜

**建议切分**

> ｜ You're saying to yourself, I'm paying x dollars per acre, I think I'll get so many bushels of corn or soybeans on average, some years good, some years bad, some years the price will be good, some years the price will be bad, et cetera. ｜ But you think about the potential of the farm. ｜

建议切点为 `w8824`（01:16:17.214 结束）之后，`w8825`（01:16:17.654 开始）之前。

**为什么出现**：官网这里以 `etc.`（`ot8952`）结束该句；融合词是 ASR 的 `et cetera.`，其中 `cetera.` 无官网词 ID。官网最后有映射的词是 `bad,`（`w8822`）。程序不把官网句末放到 `cetera.` 后，而范围屏蔽又让这个已有时间的句号不能切句。

**如何调整**：按融合稿的 `cetera.` 在 `But` 前切开。判断对象是融合稿保留的 `et cetera.`，无需官网 `etc.` 的句末映射。P06 的融合稿也保留 `et cetera.`，同样不能因官网写成 `etc.—` 而取消其句号。


### E03 · Part2 · 00:13:45.468 · okay. 后的 But 句被并入

当前源句是 `s131`，从 `w2055` 到 `w2106`，时间 `00:13:31.886–00:13:50.929`。程序实际只在这整段的两端切句，中间目标位置没有切开。

**当前实际切分**

> ｜ So, my timing was actually terrible in 2008 or' 09, but the what was available was so attractive that even though my timing was terrible, we still came out okay, or a little bit better than okay. But it was not designed what we did was not designed to make a statement. ｜

**建议切分**

> ｜ So, my timing was actually terrible in 2008 or' 09, but the what was available was so attractive that even though my timing was terrible, we still came out okay, or a little bit better than okay. ｜ But it was not designed what we did was not designed to make a statement. ｜

建议切点为 `w2091`（00:13:45.468 结束）之后，`w2092`（00:13:45.968 开始）之前。

**为什么出现**：官网末词为 `OK.`（`ot2135`），融合稿为 ASR `okay.`。最后一个有官网映射的融合词是 `than`（`w2090`），`okay.` 本身没有官网映射。程序既没在 `okay.` 后登记官网句界，又禁止该 ASR 句号切句。

**如何调整**：在 `okay.` 后切开；`But it was not designed…` 独立成句。`OK / okay` 的拼写差异不应取消两份文字都表达的句末。


### E04 · Part2 · 00:41:10.833 · 姓名句末 Stoller. 后漏切

当前源句是 `s357`，从 `w5924` 到 `w5953`，时间 `00:41:08.732–00:41:18.836`。程序实际只在这整段的两端切句，中间目标位置没有切开。

**当前实际切分**

> ｜ This next question comes from Steven Stoller. He's a shareholder in Atlanta, Georgia, and he says," Would you please help us understand the effects of COVID-19 on our insurance businesses. ｜

**建议切分**

> ｜ This next question comes from Steven Stoller. ｜ He's a shareholder in Atlanta, Georgia, and he says," Would you please help us understand the effects of COVID-19 on our insurance businesses. ｜

建议切点为 `w5930`（00:41:10.833 结束）之后，`w5931`（00:41:10.853 开始）之前。

**为什么出现**：官网写 `Stephen Tedder.`，融合稿保留 `Steven Stoller.`。官网最后有映射的词只到 `from`（`w5928`），姓名没有映射；但整个来源范围仍把 ASR 的 `Stoller.` 包住，导致其句号不能切句。

**如何调整**：按本次融合已经选定的正文，在 `Stoller.` 后切开。下一句从 `He's a shareholder…` 开始。这里是姓名结束后的句号，不能套用 `H. W. Bush` 中姓名首字母点号的例外。姓名是否应改为官网拼写属于融合问题，本例不改字。


### E05 · Part2 · 01:30:20.832 · changed. 后的 But 句被并入

当前源句是 `s724`，从 `w12912` 到 `w12950`，时间 `01:30:11.887–01:30:27.875`。程序实际只在这整段的两端切句，中间目标位置没有切开。

**当前实际切分**

> ｜ And I can't tell you exactly what would happen, for example, if certain ideas, in terms of wealth taxes, changed, or taxes on foundations changed. But my plan has been thought out and in place for a long time. ｜

**建议切分**

> ｜ And I can't tell you exactly what would happen, for example, if certain ideas, in terms of wealth taxes, changed, or taxes on foundations changed. ｜ But my plan has been thought out and in place for a long time. ｜

建议切点为 `w12936`（01:30:20.832 结束）之后，`w12937`（01:30:21.812 开始）之前。

**为什么出现**：官网末词为 `change.`（`ot13205`），融合稿末词为 ASR `changed.`。最后的官网映射只到 `foundations`（`w12935`）。由于同样的范围屏蔽，`changed.` 虽带句号且有词时间，仍不能切句。

**如何调整**：在 `changed.` 后切开，让 `But my plan…` 独立成句。动词词形的裁决已经由融合完成，句界恢复应处理当前留下的句末证据。


### E06 · Part2 · 01:44:42.964 · 姓名句末 Cass. 后漏切

当前源句是 `s833`，从 `w14989` 到 `w15006`，时间 `01:44:41.063–01:44:46.926`。程序实际只在这整段的两端切句，中间目标位置没有切开。

**当前实际切分**

> ｜ This question comes from David Cass. He is a clinical professor of finance at the University of Maryland. ｜

**建议切分**

> ｜ This question comes from David Cass. ｜ He is a clinical professor of finance at the University of Maryland. ｜

建议切点为 `w14994`（01:44:42.964 结束）之后，`w14995`（01:44:43.384 开始）之前。

**为什么出现**：官网写 `David Kass.`（末词 `ot15336`），融合稿写 `David Cass.`。最后的官网映射只到 `David`（`w14993`），而 `Cass.` 是 `asr_only` 来源词。程序没有把官网句末定位到 `Cass.`，又用官网关联范围禁止它的句号切句。

**如何调整**：在 `Cass.` 后切开，下一句从 `He is a clinical professor…` 开始。保留融合选定的 `Cass`，不在句界阶段顺便改姓名。

**“官网关联范围”在本例到底是什么**：`official_sentence_spans` 保存下面两列 ID 的整句关联：

| 一侧 | 关联的原词序列 |
| --- | --- |
| ASR `aw14913–aw14918` | `This question comes from David Cass.` |
| 官网 `ot15331–ot15336` | `This question comes from David Kass.` |

前五个词有逐词对应，最后一对候选经过比较后保留 ASR `Cass.`。融合词 `w14994` 因而没有官网词 ID，标为 `asr_only`；这里的含义是“正式正文没有采用对应官网词”，不等于“这一定是官网漏掉的一次额外口述”。这张整句关联表仍包含 `aw14918`，当前句界代码就用它禁止 `Cass.` 的句号触发切句。这正是要移除的范围屏蔽：整句关联可解释两份文字来自同一段口述，不能推翻正式融合稿已经留下的句末。无论该词因冲突比较保留，还是原本就是 ASR 多出的词，都按融合正文的同一套句末规则处理，不重新比较取词，也不要求补上官网映射才准切句。


### E07 · Part2 · 01:48:06.478 · business decisions. 后漏切

当前源句是 `s867`，从 `w15528` 到 `w15551`，时间 `01:48:01.132–01:48:08.239`。程序实际只在这整段的两端切句，中间目标位置没有切开。

**当前实际切分**

> ｜ Now, they'll make mistakes in that, but you make mistakes in a lot of business decisions. But over that should be the guiding principle. ｜

**建议切分**

> ｜ Now, they'll make mistakes in that, but you make mistakes in a lot of business decisions. ｜ But over that should be the guiding principle. ｜

建议切点为 `w15543`（01:48:06.478 结束）之后，`w15544`（01:48:06.518 开始）之前。

**为什么出现**：官网句末是 `businesses.`（`ot15892`），融合稿是 ASR 的 `business decisions.`。最后有官网映射的词停在 `of`（`w15541`）。官网句末无法直接落到词条上，ASR `decisions.` 的句号也被关联范围禁止使用。

**如何调整**：在 `decisions.` 后切开，下一句从 `But over…` 开始。不要提前在 `of` 后切，也不要等到下一句的 `principle.` 才收尾。


### E08 · Part2 · 02:12:03.007 · skills. 后的 So 句被并入

当前源句是 `s1055`，从 `w18999` 到 `w19067`，时间 `02:11:48.812–02:12:18.520`。程序实际只在这整段的两端切句，中间目标位置没有切开。

**当前实际切分**

> ｜ But they don't forget about you know the kid that actually may be a better citizen in some ways even than the one that does the best at business, but he just doesn't happen to have market value skills. So, I do not think that a very rich company ought to totally abide by what the market dishes out, you know, in 18th century style or something of the sort. ｜

**建议切分**

> ｜ But they don't forget about you know the kid that actually may be a better citizen in some ways even than the one that does the best at business, but he just doesn't happen to have market value skills. ｜ So, I do not think that a very rich company ought to totally abide by what the market dishes out, you know, in 18th century style or something of the sort. ｜

建议切点为 `w19036`（02:12:03.007 结束）之后，`w19037`（02:12:03.367 开始）之前。

**为什么出现**：官网末词是单数 `skill.`（`ot19525`），融合稿是 ASR 复数 `skills.`。最后有官网映射的词是 `value—`（`w19035`）。由于 `skills.` 没有官网映射而又处于关联范围内，其句号被禁止作为切句依据。

**如何调整**：在 `skills.` 后切开，让 `So, I do not think…` 独立成句。保留融合的单复数裁决及词时间。


### E09 · Part1 · 01:33:48.160 · 完整的 knew what to do. 被接到下一句

当前源句是 `s519`，从 `w11158` 到 `w11201`，时间 `01:33:30.967–01:34:01.045`。程序实际只在这整段的两端切句，中间目标位置没有切开。

**当前实际切分**

> ｜ But right around the day or two leading up to March 23 rd, we came very close, but fortunately we had a Federal Reserve that knew what to do. But money was investment grade companies were essentially going to be frozen out of the market. ｜

**建议切分**

> ｜ But right around the day or two leading up to March 23 rd, we came very close, but fortunately we had a Federal Reserve that knew what to do. ｜ But money was investment grade companies were essentially going to be frozen out of the market. ｜

建议切点为 `w11186`（01:33:48.160 结束）之后，`w11187`（01:33:49.001 开始）之前。

**为什么出现**：本例的 ASR `do.`（`aw11168`）被关联进下一条官网句的 ASR 范围；那条官网句实际以 `But we— money was— investment grade companies…market.` 为内容。其官网末词正常映射到 `market.`，但覆盖集合同时包含前面的 `do.`，于是 `do.` 的句号也不能切句。这说明问题不只发生在官网末词缺映射时，关联范围向前多包进一些 ASR 词也会误伤句末。

**如何调整**：在 `do.` 后切开，下一句从 `But money…` 开始。这里两边分别是“美联储知道怎么做”和“投资级公司几乎无法融资”的完整陈述，不是 `wish…everybody` 一类被点号截断的词组。


### E10 · Part1 · 00:48:25.188 · it?— 的问号在切句时没有被识别

当前源句是 `s248`，从 `w5470` 到 `w5573`，时间 `00:47:40.504–00:48:32.995`。程序实际只在这整段的两端切句，中间目标位置没有切开。

**当前实际切分**

> ｜ And it actually achieved it achieved such a level of worry about whether we were about to jump off another cliff, just because the 381 of 1929 had been succeeded exceeded that they held Senator Fulbright Bill Fulbright of Arkansas, who became very famous later, in terms of the Foreign Relations Committee but he headed the Senate Banking Committee, and he called a special for a special investigation and he called it the what did he call it? the stock market study, but it really is if you read through it he really was questioning whether we had built another house of cards again. ｜

**建议切分**

> ｜ And it actually achieved it achieved such a level of worry about whether we were about to jump off another cliff, just because the 381 of 1929 had been succeeded exceeded that they held Senator Fulbright Bill Fulbright of Arkansas, who became very famous later, in terms of the Foreign Relations Committee but he headed the Senate Banking Committee, and he called a special for a special investigation and he called it the what did he call it? ｜ the stock market study, but it really is if you read through it he really was questioning whether we had built another house of cards again. ｜

建议切点为 `w5547`（00:48:25.188 结束）之后，`w5548`（00:48:25.208 开始）之前。

**为什么出现**：融合词和官网词 `ot5637` 都是 `it?—`。`is_sentence_terminal()` 只去掉引号、括号等结尾符号，再检查最后一个字符是否为 `. ? !`；结尾的长破折号 `—` 不在去除列表，所以结果为“不是句末”。程序先完成切句，才调用 `separate_editorial_breaks()` 把有官网来源的 CNBC 长破折号移到 `annotations`。因此源稿最终显示 `it?`，但已经生成的句界不会重算。

**如何调整**：先按现有来源规则分离编辑标记，再用同一份正文判断句界。在 `it?` 后、`the stock market study…` 前切开。只是调整符号处理顺序，不延长 `it?` 的时间，也不把所有破折号都当成句号。


### E11 · Part2 · 00:25:52.485 · See's. And 被装在同一个带时间词条里

当前源句是 `s236`，从 `w3854` 到 `w3892`，时间 `00:25:45.222–00:25:58.447`。程序实际只在这整段的两端切句，中间目标位置没有切开。

**当前实际切分**

> ｜ And Easter is a big sales period for See's. And I don't know whether we were halfway through, but we weren't halfway through in terms of the volume that was going to be delivered, because it comes toward the end. ｜

**建议切分**

> ｜ And Easter is a big sales period for See's. ｜ And I don't know whether we were halfway through, but we weren't halfway through in terms of the volume that was going to be delivered, because it comes toward the end. ｜

建议切点为 `w3862` 内部 `See's.` 与 `And` 之间；现有源稿尚无两个独立词条可表达该边界。

**为什么出现**：融合词 `w3862` 的完整文本为 `See's. And`，统一时间为 `00:25:50.965–00:25:52.485`，官网 ID 为 `ot3919`（`See's.`）和 `ot3920`（`And`）。句界循环每次只走一个融合词；这一词尾对应的是没有句末符号的 `And`，而官网第一句的末词只占该词条的一部分，因此也不能把官网第一句的结尾登记为整个词条的结尾。

**如何调整**：应在 `See's.` 与 `And` 之间切。优先让融合产物在跨句末处提供两个有独立时间的词条；句界阶段再按词条之间的边界切分。不能把整个 `See's. And` 放在左句，否则 `And` 仍属错句；也不能同时分给两句。下面列出已有的词级评分证据，作为上游最小调整的依据。


已有的原始评分返回包含独立词时间，固定窗口 `1550904–1552485 ms` 上，官网候选 `See's. And` 的返回为：

| 候选中的词 | 开始 | 结束 | 对齐分 |
| --- | --- | --- | ---: |
| `see's` | `00:25:50.965` | `00:25:51.350` | 0.383610 |
| `and` | `00:25:51.451` | `00:25:52.485` | 0.349831 |

这些是已保存模型返回中的时间，不是按字符长度均分出来的。它们表明，问题出在融合发布时把两个词的区间合并为一条后，下游丢失了内部切分的表示能力。它们仍需按选中候选、窗口、非重叠和来源契约核验，不能直接把本表当作已发布的新词时间。

尤其不能按两个 ASR ID 直接一对一拆分：`aw3835` 的原文是 `a`，`aw3836` 的原文是 `season.`；两个 ID 并不是 `See's.` 和 `And`。推荐上游在跨句末的组合处保留已选候选的逐词区间，并满足 ASR 来源保序、每个来源 ID 只计一次的契约。备选是扩展下游格式，使一句可以只引用某词条的一部分，但这会同时影响源稿、chunking 和时间校验，影响范围更大。[原始局部声学返回](../../../output/cnbc-2020-adr0016-20261126/run-fusion-3/cnbc_2020_part2/local_acoustic_evidence.jsonl)


## C01 · Part2 · 01:55:03.805 · 2009, 后保持同句

当前源句是 `s911`，从 `w16713` 到 `w16737`，时间 `01:54:58.041–01:55:08.528`。融合词 `w16724` 是 `2009,`，结束于 `01:55:03.805`，下一词 `w16725` 是 `they`，开始于 `01:55:05.306`。

**当前实际切分，也应作为本例的验收目标**

> ｜ The banks were very involved with the problem in 2008 and' 2009, they had done some things they shouldn't have done in some of them. ｜

**为什么保持**：官网为 `in 2008 and' 09. They had done…`，但融合稿最终保留逗号。句界恢复按该逗号处理，不补官网句界，不把逗号改为句号，也不要求融合标点以后必须同步官网。这里没有独立的换人或章节变化依据；两词间 1,501 ms 的间隔也不构成句界依据。

**验收**：`w16724` 与 `w16725` 继续属于同一个源句。若未来另一次融合实际产出了 `2009.`，句界才按那个新输入的句号切开；本例不要求产生这种上游变化。


## 对着 E01 解释当前代码：为什么有问号却没有切

代码中的 `official_sentence_spans` 只保存“某个官网句关联哪些 ASR ID、哪些官网词 ID”，没有人工修订正文。以 E01 为例，这个关联列表包含 ASR `aw13710`，但实际融合词 `class?` 的 `official_token_ids=[]`。**“整句有一批来源关联”与“最后这个词有官网映射”是两件事。**

`_official_boundary_evidence()` 先执行下面的逻辑。这里保留原变量名，省略了索引构造。

```python
covered.update(asr_indices)
end_index = max(mapped_indices)
end_word = words[end_index]
if (end_index >= max(asr_indices)
        and set(end_word.asr_word_ids).issubset(sentence.asr_word_ids)
        and set(end_word.official_token_ids).issubset(sentence.official_token_ids)):
    endings.add(end_index)
```

- `covered` 是“被某个官网句关联到的 ASR 词位置集合”。E01 的 `class?` 进入了这个集合。
- `mapped_indices` 是“真正带官网词 ID 的融合词位置”。E01 最后只能找到 `lower-middle`，找不到 `classes?"`。
- `endings` 是“程序允许按官网句末切开的词位置集合”。E01 不把 `lower-middle` 登记进去，因为它后面还剩有时间的 `class?`，提前在那里切会把 `class?` 放到回答里。

随后 `recover_sentences()` 使用：

```python
asr_can_set_boundary = not official_word and index not in official_covered
if decision is None and asr_can_set_boundary and terminal:
    # 接下来才会把这个 ASR 标点登记为句界
```

E01 中 `class?` 的 `terminal=True`，说明问号其实已经被识别；`official_word=False`，说明该词没有官网映射；但它在 `official_covered` 内，令 `asr_can_set_boundary=False`。于是问号不能触发句界。所谓“压掉标点”只发生在**决策资格**上，正文字符 `?` 没有被删除。所谓“官网断点没落下来”，在此处具体是**没有把任何一个正确的带时间词位置加入 `endings`**。本文后续使用这些变量时均指这里的具体含义。

E02–E08 的结构相同：官网末词缺少映射，程序拒绝提前切；ASR 最后一个词本来有句末符号，却因范围关联被禁止使用。E09 则是范围把前一句的 `do.` 一起包进去了。以上是当前实现的问题解释，不是目标算法继续依赖官网标点的理由。目标应直接判断融合正文的句末，并保留融合正文中域名、姓名缩写等点号例外。[实际句界实现](../../../output/cnbc-2020-adr0017-20261127/run-boundaries-v7-3/source-snapshot/src/transcription/application/sentences.py#L320) · [标点判断实现](../../../src/transcription/domain/sentences.py#L91)

## P01–P14、Q01–Q03：其他被官网标点判断挡住的融合句号

下面各处当前都在同一个源句中，融合稿却已保留句号。当前代码把它们放入官网关联范围，从而没有按融合句号切开。官网在对应处使用逗号、破折号或不同词语，能够解释当前代码为什么保持续接，但这些差异不能作为目标算法不切的依据。

表中是**局部片段**；“当前文字”中的两侧目前没有句界，“目标”列的 `｜` 表示要在指定融合词之后新增句界。只增加句界，保留口误、重复、大小写和词时间。这里列出的点号均不是融合正文中的域名点或姓名首字母点。

| 用例 | 当前源句、词 | 当前文字 | 目标局部切分及冲突说明 |
| --- | --- | --- | --- |
| P01 | Part1 `s51 / w813` | `about him. fairly complex subjects` | `about him. ｜ fairly complex subjects`。官网为 `about fairly complex subjects`，但不能用它取消融合保留的 `him.`。 |
| P02 | Part1 `s52 / w874` | `Bill Gates too. as to what's going on` | `Bill Gates too. ｜ as to what's going on`。官网的 `Bill Gates— as to…` 不覆盖融合稿的 `too.` 句末。 |
| P03 | Part1 `s62 / w1051` | `DEFCON 6 on the other. 1 on the other side` | `DEFCON 6 on the other. ｜ 1 on the other side`。保留融合稿中的数字和重复，不为同步官网 `DEFCON 1…` 而合并。 |
| P04 | Part1 `s186 / w3870` | `a small business in Oman. I hate what this…` | `a small business in Oman. ｜ I hate what this…`。官网 `Omaha—` 不否决融合 `Oman.` 的句号，也不在本阶段改姓名或地名。 |
| P05 | Part1 `s204 / w4295` | `that, view held on. and the stock market…` | `that, view held on. ｜ and the stock market…`。官网同句的 `that, and…` 不取消融合 `on.` 的句号。 |
| P06 | Part1 `s295 / w6579` | `endowed by their Creator, et cetera. I think…` | `et cetera. ｜ I think…`。融合采用完整拼写 `et cetera.`，不能回到未采纳的官网 `etc.—`，再把此句号认作那个缩写的点。 |
| P07 | Part1 `s531 / w11465` | `very good Fed Chairman. but Paul Volcker…` | `very good Fed Chairman. ｜ but Paul Volcker…`。官网的 `chairmen, but…` 不替代融合句号。 |
| P08 | Part2 `s64 / w1044` | `never... never pay it. you don't need to pay attention` | `never... never pay it. ｜ you don't need to pay attention`。官网 `never pay—` 不取消当前 `it.` 的句末；省略号与口述重复保留。 |
| P09 | Part2 `s118 / w1880` | `didn't bother them. to extend out their borrowings` | `didn't bother them. ｜ to extend out their borrowings`。官网的 `didn't bother to extend…` 不是把融合两侧重新连起来的依据。 |
| P10 | Part2 `s194 / w3129` | `But we don't need it. we don't need a hundred…` | `But we don't need it. ｜ we don't need a hundred…`。官网 `we don't need—` 不取消融合 `it.` 的句末。 |
| P11 | Part2 `s255 / w4181` | `there's a couple of them. and and it may be…` | `there's a couple of them. ｜ and and it may be…`。保留两个 `and`，不按官网破折号强制合并。 |
| P12 | Part2 `s336 / w5534` | `we wish it. everybody the best` | `we wish it. ｜ everybody the best`。即使按官网 `we wish everybody the best.` 连读更通顺，也不能在句界阶段据此推翻融合标点。 |
| P13 | Part2 `s427 / w7254` | `three extraordinarily good, minds. in terms of allocating capital` | `minds. ｜ in terms of allocating capital`。官网的逗号结构不覆盖融合 `minds.`。 |
| P14 | Part2 `s542 / w9430` | `give it there. their best effort every day` | `give it there. ｜ their best effort every day`。官网 `give it their best effort…` 不取消当前 `there.` 的句末。 |
| Q01 | Part1 `s588 / w12575` | `upside down. And I don't know…` | `upside down. ｜ And I don't know…`。官网 `upside on—` 的差异可另行审查融合内容，当前句界按 `down.` 处理。 |
| Q02 | Part2 `s550 / w9598` | `infrastructure is continuing to, change. we're ready…` | `change. ｜ we're ready…`。官网缺 `change` 且使用逗号，不影响当前融合句号。 |
| Q03 | Part2 `s973 / w17581` | `But we didn't do anything. the price has not…` | `But we didn't do anything. ｜ the price has not…`。官网 `any— we—` 不取消融合 `anything.` 的句末。 |

**共同调整**：不再用官网句内范围或未采纳的官网标点禁止这些融合句号切句。像 P12 一样，按融合标点切后可能得到不完整的短语；这暴露的是融合稿自身可能需要另行审查的问题，不通过句界阶段偷偷采用官网标点来修正，也不要求融合稿为了同步官网而重跑。

## Q04–Q06：融合稿没有句末，不按官网新增断点

下列局部片段当前均保持同句，目标也保持。它们没有融合句末、已证明的换人或章节变化；官网出现句号不能单独创建断点。文字是否准确可单独记录，不把核听设为按当前融合标点切句的前置条件。

| 用例 | 当前实际所在源句与局部片段 | 保持及其原因 |
| --- | --- | --- |
| Q04 | Part1 `s214 / w4656`：`smooth smooth hall here and they I mean, they…` | 不在 `they` 后新增句界。官网 `Smoot-Hawley.` 未进入融合正文，不能按官网关联范围最后一个 ASR 词补切。 |
| Q05 | Part2 `s382 / w6442`：`not covered by the— I mean, that is not part…` | 保持连续。融合 `the—` 没有句末标点，破折号本身不要求切句；官网 `that.` 的句号不能搬过来。 |
| Q06 | Part2 `s1060 / w19128`：`I mean, you can see I would rather be…` | 不在 `see` 或 `would` 后凭官网补切。官网 `various statistics on that.` 未进入融合稿，不能据此增加当前正文没有的句末。 |

## fallback 到底是什么：当前标准、代码和实际次数

本节只解释**句界**中的 fallback。它是 `boundary_status="fallback"`、`boundary_source="pause_fallback"` 这组标签，中文可理解为“备用规则确定的句尾”。它没有声学概率分，也不是“用 ASR 替代官网文字”。本次两场的句界 fallback 均为 **0**，不能拿这个计数说明 E01–E11、P01–P14 或 Q01–Q03 没问题。以下解释的是当前代码，不表示目标算法保留官网标点优先级。

当前循环依次尝试明确换人、官网句末、可用 ASR 句末，仍没有决定时才执行下面的原代码：

```python
weak_detector_boundary = asr_can_set_boundary and index in detected and (
    pause_ms >= policy.inferred_pause_ms
    or segment_change
)
if decision is None and weak_detector_boundary:
    decision = _BoundaryDecision(
        BoundarySource.PAUSE_FALLBACK,
        BoundaryStatus.FALLBACK,
    )

if decision is None and not has_next:
    decision = _BoundaryDecision(
        BoundarySource.PAUSE_FALLBACK,
        BoundaryStatus.FALLBACK,
    )
```

| 条件或变量 | 当前具体标准 | 对着例子解释 |
| --- | --- | --- |
| `asr_can_set_boundary` | 当前词没有官网映射，而且不在 `official_covered` 中 | E01 的 `class?` 虽无官网映射，但在覆盖集合内，因此为 false，连这个备用分支也进不去。 |
| `index in detected` | 检测器提出“在这个词后面切”的位置 | 当前生产检测器是 `RuleBasedSentenceBoundaryDetector`，只调用同一个标点函数；`First.` 会被提出，普通 `ends` 不会。 |
| `pause_ms` | 下一词开始时间减去本词结束时间 | 例如 Part1 `s517` 的 `interestingly enough.` 结束到 `We had…` 开始相差 2,502 ms。 |
| `inferred_pause_ms` | 当前默认为 **700 ms**，比较使用 `>=` | 上例 2,502 ≥ 700，但它已有 ASR 句号，前面的标点分支已处理，故来源是 `punctuation_and_pause`，状态为 `inferred`，不是 fallback。 |
| `segment_change` | 两侧来源 ASR 词的 `segment_id` 不同 | 比如构造例子的 `This ends` 属于 `seg1`、`Another thought.` 属于 `seg2`。这只是 ASR 分段变化，不能据此说明换人。 |
| `not has_next` | 已到全文最后一个词，前面规则仍没决定 | 构造例子只有 `We are still thinking` 且无标点时，也必须结束全文最后一个源句，当前标成 fallback。本次 Part1 最后是 `occurred.`、Part2 是 `Good night.`，都先按句号结束，所以没有这种 fallback。 |

**第一种 fallback 在当前生产检测器下通常不会单独触发。** 检测器和主循环用同一套标点规则；一个可用 ASR 句末一般早已被标点分支处理。只有检测器提供了额外切点、或不同表面文本导致两处判断不同，这个备用分支才可能有独立作用。解释用的构造例子 `This ends ｜ Another thought.` 需要测试显式向检测器结果注入 `ends` 后的切点；当前生产检测器不会仅凭 `ends` 提出它。

当前还有另一处停顿判断：有 ASR 句末时，间隔 ≥700 ms 记为 `punctuation_and_pause`，更短记为 `asr_punctuation`。两者都切开，当前实际差别是**来源标签**。例如 E09 的 `do.` 到 `But` 相差 841 ms，但由于被覆盖集合拦住，它连这个分支也没进入，停顿再长也不能救回边界。

**当前没有 fallback 数量上限或比例上限。** 代码累计 `fallback_count`，完成事件输出数量及占总句数的比例，不据此拒绝发布。当前也没有“满 80 词就切句”的规则。文档里不再用这些计数代替逐句质量判断。[备用分支](../../../output/cnbc-2020-adr0017-20261127/run-boundaries-v7-3/source-snapshot/src/transcription/application/sentences.py#L182) · [当前 700 ms 配置](../../../output/cnbc-2020-adr0017-20261127/run-boundaries-v7-3/source-snapshot/src/transcription/domain/sentences.py#L42) · [检测器](../../../src/transcription/infrastructure/sentences.py) · [完成事件中的计数](../../../output/cnbc-2020-adr0017-20261127/run-boundaries-v7-3/source-snapshot/src/transcription/application/sentences.py#L597)

此外，`SectionAggregationResult.fallback_reason` 表示章节归属失败，例如无法证明一句属于哪个章节时发布 `sections=[]`。这是**章节列表的降级结果**，与这里的句界 fallback 是不同字段，不纳入本节的 0 次计数。[章节返回类型](../../../src/transcription/domain/sections.py#L103)

## 已实施调整、备选与取舍

### 1. 先分离有来源的编辑符号，再统一判断句末

复用现有 CNBC 长破折号分离规则，例如 `it?— → it? + annotation`、`but— → but + annotation`。切句和最终正文使用同一份处理后的文字；前者保住问号，后者仍无句末，不能因破折号切句。域名与姓名的点号例外继续生效。

只处理融合正文中实际保留、且满足现有来源规则的编辑符号，不把官网未采纳的词形或标点重新投到正文。比如 E10 的融合词确实是 `it?—`，分离 `—` 后按 `it?` 切；P06 的融合词是 `et cetera.`，直接按这个实际文字判断，不改成官网 `etc.—` 再以缩写或续说为由合并。缩写例外继续作用于融合稿自身，例如融合 `Mr. Jaskier` 中 `Mr.` 的点号不切句。

### 2. 按融合正文判断标点，官网原句不再创建或否决句界

所有词使用同一份处理后的融合正文，不再因为其来源是 ASR 或官网而赋予不同的标点资格。具体需要替换当前两种重新采用官网文字的行为：

- `_boundary_surface_context()` 对有官网映射的词，当前会用官网 token 文本替代融合 `word.text` 来判断标点。目标统一使用融合正文，例如融合写 `2009,` 就看逗号，不取官网 `09.`。
- `_official_boundary_evidence()` 当前生成官网句末位置和覆盖集合。目标不再用其中的句末位置新增断点，也不再用覆盖集合屏蔽融合句末。`official_sentence_spans` 如继续保留，只用于溯源和诊断，不参与正文标点的二次裁决。

E01–E10、P01–P14 和 Q01–Q03 直接使用融合稿保留的有效句末；C01 与 Q04–Q06 没有这种句末，保持当前连续。域名、姓名缩写、省略号等例外仍根据融合文字本身判断。例如 `berkshirehathaway. com` 内部点号不切，而 `Oman.` 不会因为官网写成 `Omaha—` 就成为例外。不要求借助官网补回 C01 的年份句末，也不在句界阶段把任何逗号改成句号。

### 3. 可靠换人独立于标点与停顿

保留明确标签之间的强制切句；补充 E01 这种有引入者、连续引用提问、明确回答者的引语来源。不能把“未知 → 已知”一律当换人，因为也可能只是同一个人连续段落省略标签；也不能把唯一已知标签填满一个包含未知提问的合并范围。

实施收敛为只在同章内前向记住最近的可靠说话人，供换人检测使用，不向未知源句填标签。例如 Part2 第 2 章前面已明确 Buffett，后面的无标签 `Greg, would you like to add anything` 遇到明确标 Greg 的 `Really nothing to add, Warren.` 时应切开；邀请句仍允许为未知，不能标 Greg。章变化时清空这项前向记忆，没有前位可靠来源时也不能把任意“未知 → 已知”判成换人。该保好样例补入 NB-17 测试与全量断点审查。

负责人第一轮审查另发现回答前缀误切，因此最终实现还要求当前源句内已有可追溯官网上下文，才允许借用前位可靠 speaker 判断换人；纯 ASR-only 的 `Okay,`、`Well,` 或 `uh` 回答前缀不能被当成前一位的尾句。四个真实前缀场景加入回归，第二轮均保持完整回答；该限制只影响换人证据，不影响 `asr_only` 词自身句末资格。

### 4. 跨句的融合组合提供独立词时间

E11 优先由上游融合在跨句末处发布独立词条，使用已选声学候选自己的逐词时间，并验证唯一来源和保序。当前 v7 仍是本 ADR 的固定输入；后续契约修复必须通过新的融合版本、缓存身份及实际工件验收，不能手工修改这份基线。

### 5. 句界不再使用停顿或 ASR 分段充当句末依据

去除 `inferred_pause_ms` 对句界决策及来源分类的影响，不使用“检测器候选 + 长停顿 / ASR 分段”创建句界。用融合正文的有效标点、可靠换人、章节变化和文末收尾说明每个边界。文末没有标点也要保留最后一句，但应明确记录“文末收尾”，避免继续用 `pause_fallback` 暗示它依赖停顿。相关枚举、政策和缓存身份需随实现统一更新，不增加新的数量或比例发布门槛。

备选一是继续按官网同步句末及句内标点，C01 与 P12 分别展示它会在融合逗号处补切、在融合句号处合并，用户已明确不采用。备选二是把所有点号都当句末，这会切坏融合稿中的域名和姓名缩写。确定采用融合正文的标点，并根据融合文字识别这些词内点号例外；结合 E11 的时间粒度修正，不引入 LLM 判句或重新识别全片。

## 可复现验收

### 固定输入与复现步骤

固定输入是上述两份 v7 `transcript_fusion.json`、同目录 `aligned_asr.json` 和 `chapters.json`。回执保存它们的 SHA-256、大小及代码指纹；代码快照位于本次输出根的 `source-snapshot/src`。核对回执后，从这些融合词运行 `SentenceBoundaryService.execute()`，向新目录发布，不能覆盖本文基线。当前结果用于复现反例，方案实施后的结果用于逐项验收。

本次生成脚本位于 `output/cnbc-2020-adr0017-20261127/tools/replay_v7_current.py`。默认输出目录已经存在，脚本会拒绝覆盖。若需从冻结声学输入完整复现 v7 与句界，可将模块的 `RUN` 显式设为一个尚不存在的新路径，然后调用 `main()`；这会重用保存的评分并补算那一个缺记录的本地窗口。重放前按仓库规则核对当轮的本地模型调用授权，不把本文的执行记录当作后续调用授权。示意调用如下：

```python
import runpy
from pathlib import Path
scope = runpy.run_path("output/cnbc-2020-adr0017-20261127/tools/replay_v7_current.py")
scope["main"].__globals__["RUN"] = Path("/absolute/path/to/a/new/run-root")
scope["main"]()
```

仅验收句界修复时直接消费已固定的 v7 融合稿，不需要补算模型窗口。文字与官网不一致不妨碍按当前融合标点验收；若另行发现融合稿的内容或标点有质量问题，单独记录，不要求同步官网或重跑融合才能验收本 ADR。

### 通过条件

| 范围 | 可观察的通过条件 |
| --- | --- |
| E01–E10 | 在各例指定的左右词之间增加一个句界，源句整段不再吞掉该边界；源词文字、时间和来源不因只改句界而改变。 |
| `asr_only` 句末资格 | 分别覆盖“冲突比较后保留的 ASR 词”（如 E06 的 `Cass.`）和“ASR 真正多出的词”。只要正式融合正文保留有效句末，两类都能触发句界，不以 `asr_only` 标签、缺少官网词 ID 或官网关联范围禁止切句。 |
| E01 说话人 | 提问与回答分成两个源句。回答标 Buffett；提问只有证明连续引语属于 Becky 时才标 Becky，否则保留未知。提问不得标 Buffett。 |
| E11 | `See's.` 与 `And` 有独立、不重叠的可追溯词时间，句界在两者之间；每个词、每个 ASR 来源恰好计入一次。不得按原始 `a / season.` 的词边界硬分，也不得重复整条 `w3862`。 |
| C01 | `2009,` 与下一词 `they` 保持同句，原逗号不变。不得在 `and'` 或 `2009,` 后按官网句号补切，也不要求上游改成句号。 |
| P01–P14、Q01–Q03 | 按表中融合句号新增对应句界，保留全部词、重复、修正和大小写。不得因官网逗号、破折号或不同词形而继续合并。 |
| Q04–Q06 | 保持当前局部连续；没有融合句末或其他独立强制边界时，不按官网原句补切。 |
| 标点来源独立性 | 固定融合 `words`、可用说话人及章节信息，仅改变参考官网的句内或句末标点，源句首尾词应一致。用“融合逗号、官网句号”及“融合句号、官网逗号或破折号”两种输入验证；构造合法输入及校验链，不绕过工件完整性校验。 |
| 域名与姓名 | Part1 `s33` 的 `berkshirehathaway. com`、`s249` 的 `H. W. Bush` 内部不切；`s639` 的 `Thank you, Mr. Jaskier.` 后保留句界。 |
| 明确句号、换人和章节 | 保住 Part2 `coming in. ｜ So, there…` 的 20 ms 间隔句界；`01:25:57.247–01:25:57.447` 的明确 Becky → Buffett 换人切开；保留已验证的章节变化边界。 |
| 停顿独立性 | 固定全部词、标点、来源 ID，只改变词间间隔，例如把 20 ms 改为 2,000 ms，源句首尾词及边界来源判断不因间隔变化而改变。Part2 `s193` 的 `but Our Our position…` 保持连续。 |
| 文末收尾 | 为无末尾标点的构造输入保留最后一个源句；明确标记文末原因，不能按词数强切或因备用计数拒绝发布。 |
| 完整性与复用 | 公共 DTO 校验通过，句子恰好覆盖所有词且无重复、遗漏或跨可靠说话人；缓存身份体现新政策，同输入复用不加载模型、不改写工件。 |

定向用例取自 E/P/Q/C 的真实片段及所需邻接词、来源；构造用例只补“改参考标点”“改间隔”“无末尾标点”等控制条件。实现交付还必须执行 `.venv/bin/python -m pytest tests/ -q -m 'not live'`，并在独立输出根回放这两场 v7 输入。不要以总句数或 fallback=0 代替以上逐例验收。

## 影响范围与实际交付

主要涉及 `transcription/application/sentences.py`、标点及编辑标记规则、说话人来源处理、句界政策与缓存身份、对应离线回归。E11 另涉及融合词的发布粒度与来源验证；如果选择扩展下游按词条内部切分的格式，还会扩大到 `archive_core` 和 chunking，因此优先上游独立词条方案。chunking 继续负责按停顿组织字幕块。

标点权威性已由用户确认，P/Q 不再以重新判断官网句内连续关系为实施前置。E11 使用选中候选的完整、保序、互不重叠逐词时间；ASR 来源按最大时间重叠、无重叠时最近区间唯一归属，拒绝倒序。在实际 E11 中两个 ASR 来源归 `See's.`，`And` 为有独立声学支持的 `official_only`，无来源重复。

负责人第二轮核对所有有效融合句末均已切开，原有有效融合句末全部保留；全量新增 30 处，其中 28 个为本 ADR 反例，另 2 个为可靠换人。按用户确认的标点权威性取消 7 个仅由官网补切、而融合正文无句末的旧断点，逐处依据保留在最终报告。原章节、域名与姓名、20 ms 句号、but Our 连续、Greg 接话和四个未知回答前缀均保住。

完整离线套件与两场实际产物、来源、时间、输入保护及同进程/新进程缓存复用均通过。回放仅消费保存的评分，零新模型调用；未改选稿裁决，未核听全片、翻译、渲染或外发。对于将来缺少有效逐词声学证据的其他跨句组合，仍保留组合并明确诊断，不会编造时间；本次唯一实际组合 E11 已满足证据要求。
