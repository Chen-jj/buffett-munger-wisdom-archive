# 原始双语文本独立语义审读（2026-10-24）

## 范围与冻结边界

- **本轮是文本研究，不是算法实现、cue 方案、听音、样片验证或全片质量签字。** 未调用 provider、ASR、ffmpeg；未改译文、时间或任何生成资产。
- 已读根、`src/translation/AGENTS.md`、`src/archive_core/AGENTS.md` 的规则。根指南历史结论仅作工作边界，不作本审读的切分依据。
- **未读取**旧 planner、`subtitle_plan.json`、旧参考、SP 报告、其他 agent 切法或负责人新方案。以下对应于 **2026-10-24 21:39:58 CST** 冻结；冻结依据只有下列两份输入。
- 逐词/中文 offset 映射覆盖 **9/97句**：s5、s6、s13、s14、s17、s22、s48、s74、s88。为定位两处时间查看了 s1–s16 的句级中英文本，但其余句不计入映射审查，不能把本报告外推为全97句已经通过。
- 成功检查：原始字节 SHA-256、translation 内嵌源哈希、ID 范围、中文原文切片，以及9句账本两侧无遗漏/重复。仅使用 JSON读取、hash 和切片/集合校验，**没有自动对齐推断、字数比例、DP或 cue 生成**。覆盖校验不证明语义结论正确。

## 唯一语义输入

| 文件 | 字节数 | SHA-256 |
|---|---:|---|
| `/Users/drchan/Codebase/buffett-munger-wisdom-archive/output/cue-evaluation/20261023-candidate-v3/workspaces/cnbc_2000_morning/source_alignment.json` | 551018 | `99f36287d28d0581ae039f64eeea55c14bef044dbb87fdca2f9c8d26ad7fbf91` |
| `/Users/drchan/Codebase/buffett-munger-wisdom-archive/output/cue-evaluation/20261023-candidate-v3/workspaces/cnbc_2000_morning/translation_result.json` | 15207 | `0862d8759a3bb0cec59bf2d3531fd2301a37b889d2499135c46ea24a608d1dfb` |

`translation_result.json.source_alignment_sha256` 与本次源文件 SHA-256 相同。源文件共97句、1564个词，音频标称长度623000ms；后者仅用于说明输入，不代表本轮确认音轨准确。

## 读表方式与证据强度

- 中文偏移是各句 **原始 `translated_text`** 的 Unicode code-point **0基半开区间 `[start,end)`**，不是UTF-8字节、UTF-16 code unit，也没有先做空白归一化。内部 Latin 空格、数字、百分号、破折号和标点都计数。
- `wA..wB` 是闭区间 word ID；`∪` 表示集合并，`⊕` 只用于显示不连续原文片段，不是重排生成文本。英文列从所列原词按空格串联便于阅读；词 ID 才是身份。
- 表内是**人工最小证据单元账本**，不是逐词翻译金标准或建议 cue。一个单元可以是短语、语法框架或多对多关系，**不要求单调**。标点随相邻单元记账，不为标点推断独立语义时间。
- 为可复算，账本把9句每个源word和每个中文code point各记一次；**功能词省译、增译或改写不能由这种机械分区变成真实的一对一词义锚点**。这些地方在每句注记中明确降级；可靠范围是整组短语。后续不应拿“账本全覆盖”代替人工语义验收。

## 两处时间的原始定位

| 观察点 | 原始相邻句 | 结论 |
|---|---|---|
| 00:30（30000ms） | s5为18310–29653ms，s6为32025–47519ms | 正在两句之间的2372ms空档，不落在任一源词内。重点审读接手/35年/每年正增长/24%，以及48年/无下滑/26%。 |
| 01:26（86000ms） | s13为74710–85814ms，s14为86761–89242ms | 正在两句之间的947ms空档；s14在86.761s才开始。不能仅凭“01:26附近”归责到某个cue或提前/延后词时间。 |

这些是输入数字定位，**不是**对现有字幕在该时间显示什么的判断；本轮没读plan、没播放样片。

## 冻结的逐句对应

### s5（18310–29653ms；中文57 code points）

英文原句：That means that since present management took over 35 years ago, Berkshire Hathaway has realized a positive gain each and every year, and produced an average annual gain of 24%.

中文原句：这意味着，自现任管理层35年前接手以来，Berkshire Hathaway年年都实现了正增长，年均增幅达24%。

| 源 word IDs | 英文词/短语 | 中文范围 | 中文原文切片 |
|---|---|---|---|
| `w32..w34` | That means that | `[0,5)` | 这意味着， |
| `w35` | since | `[5,6) ∪ [17,20)` | 自 ⊕ 以来， |
| `w36..w37` | present management | `[6,11)` | 现任管理层 |
| `w38..w39` | took over | `[15,17)` | 接手 |
| `w40..w42` | 35 years ago, | `[11,15)` | 35年前 |
| `w43..w44` | Berkshire Hathaway | `[20,38)` | Berkshire Hathaway |
| `w45..w49` | has realized a positive gain | `[41,48)` | 实现了正增长， |
| `w50..w53` | each and every year, | `[38,41)` | 年年都 |
| `w54..w55` | and produced | `[52,53)` | 达 |
| `w56..w60` | an average annual gain of | `[48,52)` | 年均增幅 |
| `w61` | 24%. | `[53,57)` | 24%。 |

**独立观察：** 关键内容是三组不同的事实：35年前接手、每年正增长、年均24%。`took over` 与 `35 years ago` 的中文次序互换；`positive gain` 与 `each and every year` 也互换。公司名的两个英文词共同对应完整 `Berkshire Hathaway`，不能按中文 Latin code-point 长度分摊语义。

### s6（32025–47519ms；中文78 code points）

英文原句：Including the years you ran the Buffett Limited Partnership, you have had a run of 48 consecutive years of positive gains in net worth without one single down year, producing a compounded rate of return of almost 26% annually.

中文原句：如果把你经营Buffett Limited Partnership的那些年也算在内，你已经连续48年实现净资产正增长，没有一年下滑，年复合回报率接近26%。

| 源 word IDs | 英文词/短语 | 中文范围 | 中文原文切片 |
|---|---|---|---|
| `w62..w64` | Including the years | `[0,3) ∪ [33,42)` | 如果把 ⊕ 的那些年也算在内， |
| `w65..w66` | you ran | `[3,6)` | 你经营 |
| `w67..w70` | the Buffett Limited Partnership, | `[6,33)` | Buffett Limited Partnership |
| `w71..w76` | you have had a run of | `[42,45)` | 你已经 |
| `w77` | 48 | `[47,49)` | 48 |
| `w78` | consecutive | `[45,47)` | 连续 |
| `w79..w80` | years of | `[49,50)` | 年 |
| `w81..w82` | positive gains | `[50,52) ∪ [55,59)` | 实现 ⊕ 正增长， |
| `w83..w85` | in net worth | `[52,55)` | 净资产 |
| `w86..w90` | without one single down year, | `[59,66)` | 没有一年下滑， |
| `w91..w97 ∪ w100` | producing a compounded rate of return of ⊕ annually. | `[66,72)` | 年复合回报率 |
| `w98` | almost | `[72,74)` | 接近 |
| `w99` | 26% | `[74,78)` | 26%。 |

**独立观察：** 开头 `Including the years ...` 被译为包裹经营史的“如果把……的那些年也算在内”，是非连续对应。`48 consecutive years` 是同一连续年份量，`positive gains in net worth` 是同一净资产增长事实；`without one single down year` 的否定必须与“下滑”保持同一语义范围。年复合回报率中的“年”来自末词 `annually`，不能把26%或“年”按位置比例丢到另一事实。`you have had a run of`→“你已经”、`positive gains`→“实现…正增长”是整句谓语改写的账本归属，不是逐词独立锚点。

### s13（74710–85814ms；中文62 code points）

英文原句：But the interesting thing about those figures— actually, the figures go back before that, because the very best period was pre-the-partnership days, because the amount I was working with was so small.

中文原句：不过，这些数字有意思的地方在于——其实数字还可以追溯到更早，因为表现最好的时期是在成立合伙企业之前，当时我运作的资金非常少。

| 源 word IDs | 英文词/短语 | 中文范围 | 中文原文切片 |
|---|---|---|---|
| `w173` | But | `[0,3)` | 不过， |
| `w174..w177` | the interesting thing about | `[7,17)` | 有意思的地方在于—— |
| `w178..w179` | those figures— | `[3,7)` | 这些数字 |
| `w180` | actually, | `[17,19)` | 其实 |
| `w181..w182` | the figures | `[19,21)` | 数字 |
| `w183..w186` | go back before that, | `[21,30)` | 还可以追溯到更早， |
| `w187` | because | `[30,32)` | 因为 |
| `w188..w191` | the very best period | `[32,39)` | 表现最好的时期 |
| `w192..w194` | was pre-the-partnership days, | `[39,50)` | 是在成立合伙企业之前， |
| `w195` | because | `[50,52)` | 当时 |
| `w196..w197` | the amount | `[55,58)` | 的资金 |
| `w198..w201` | I was working with | `[52,55)` | 我运作 |
| `w202..w204` | was so small. | `[58,62)` | 非常少。 |

**独立观察：** 有两个局部倒序：`interesting thing about those figures`→“这些数字有意思的地方在于”；`the amount I was working with`→“我运作的资金”。`pre-the-partnership` 是一个源 word ID（w193），不能据连字符虚造额外 word ID。需要保留的翻译不完全等价处：第二个 `because`（w195）在冻结译文中是“当时”[50,52)，因果连接变成时间连接；此行仅记现有译文对应，不把它认证为精确词义等价，也不在本轮修译文。

### s14（86761–89242ms；中文16 code points）

英文原句：there's nothing magic about a one-year period.

中文原句：一年这个周期并没有什么神奇之处。

| 源 word IDs | 英文词/短语 | 中文范围 | 中文原文切片 |
|---|---|---|---|
| `w205..w207` | there's nothing magic | `[6,16)` | 并没有什么神奇之处。 |
| `w208..w211` | about a one-year period. | `[0,6)` | 一年这个周期 |

**独立观察：** 英文先评价“nothing magic”，后交代“one-year period”；中文先交代“一年这个周期”，后否定神奇性。整句很短，却仍有固定译序交叉；这不是长句长度特有的问题。`nothing` 的否定不能只留一个“神奇”给另一段。

### s17（107591–117568ms；中文33 code points）

英文原句：It's been a fluke, to some degree, that we have not had any down years in terms of underlying value.

中文原句：从某种程度上说，我们的内在价值一直没有出现下滑年份，只是碰巧而已。

| 源 word IDs | 英文词/短语 | 中文范围 | 中文原文切片 |
|---|---|---|---|
| `w268..w271 ∪ w275` | It's been a fluke, ⊕ that | `[26,33)` | 只是碰巧而已。 |
| `w272..w274` | to some degree, | `[0,8)` | 从某种程度上说， |
| `w276` | we | `[8,11)` | 我们的 |
| `w277..w280` | have not had any | `[15,21)` | 一直没有出现 |
| `w281..w282` | down years | `[21,26)` | 下滑年份， |
| `w283..w287` | in terms of underlying value. | `[11,15)` | 内在价值 |

**独立观察：** 最强反例之一：英文先说 `fluke`，中文将“只是碰巧而已”放在最后；英文末尾的 `underlying value` 被中文放到主句前部。`that` 与“只是碰巧而已”同属评价框架，表中合并其非连续源范围。`we`→“我们的”是主语改为领属语；完整事实是“我们的内在价值一直没有出现下滑年份”，不是单独一个名词或负词。限定语“从某种程度上说”不能被误当成英文开头 `fluke` 的译文。

### s22（131657–148889ms；中文64 code points）

英文原句：And it's— the fact that, you know, the Earth revolves around the sun and really is not totally connected to most business activities, or the fruition of most investment ideas, or anything of the sort.

中文原句：而且，这——你知道，地球绕太阳公转这件事，其实跟大多数商业活动、大多数投资构想能否开花结果，或诸如此类的事情，并没有完全的关联。

| 源 word IDs | 英文词/短语 | 中文范围 | 中文原文切片 |
|---|---|---|---|
| `w343` | And | `[0,3)` | 而且， |
| `w344` | it's— | `[3,6)` | 这—— |
| `w345..w347` | the fact that, | `[17,21)` | 这件事， |
| `w348..w349` | you know, | `[6,10)` | 你知道， |
| `w350..w351` | the Earth | `[10,12)` | 地球 |
| `w352..w353` | revolves around | `[12,13) ∪ [15,17)` | 绕 ⊕ 公转 |
| `w354..w355` | the sun | `[13,15)` | 太阳 |
| `w356..w357` | and really | `[21,23)` | 其实 |
| `w358..w362` | is not totally connected to | `[23,24) ∪ [55,64)` | 跟 ⊕ 并没有完全的关联。 |
| `w363..w365` | most business activities, | `[24,32)` | 大多数商业活动、 |
| `w366..w369` | or the fruition of | `[39,46)` | 能否开花结果， |
| `w370..w372` | most investment ideas, | `[32,39)` | 大多数投资构想 |
| `w373..w377` | or anything of the sort. | `[46,55)` | 或诸如此类的事情， |

**独立观察：** “地球绕太阳公转”是完整事件，不能在“绕/太阳/公转”之间用位置当语义。否定关联框架 `is not totally connected to` 被译为“跟……并没有完全的关联”，包住商业活动、投资构想开花结果和诸如此类三项。英文把否定关联放在列举之前，中文放在列举之后；中文中间有逗号并不使它们自动成为可独立同步的三个断片。`or the fruition of`→“能否开花结果”含语法改写，强词义锚点是 `fruition`↔“开花结果”，不是把“能否”硬分给某一英文词。原译文的“这——”保留，不做破折号修复。

### s48（299603–308270ms；中文28 code points）

英文原句：And so you have this extraordinary liquidity in a company that has performed very well, to boot.

中文原句：所以，这家公司不仅表现非常出色，还拥有非同寻常的流动性。

| 源 word IDs | 英文词/短语 | 中文范围 | 中文原文切片 |
|---|---|---|---|
| `w741..w742` | And so | `[0,3)` | 所以， |
| `w743..w745` | you have this | `[17,19)` | 拥有 |
| `w746` | extraordinary | `[19,24)` | 非同寻常的 |
| `w747` | liquidity | `[24,28)` | 流动性。 |
| `w748..w751` | in a company that | `[3,7)` | 这家公司 |
| `w752..w755` | has performed very well, | `[9,16)` | 表现非常出色， |
| `w756..w757` | to boot. | `[7,9) ∪ [16,17)` | 不仅 ⊕ 还 |

**独立观察：** 英文先给非同寻常的流动性，再补充公司表现良好；中文先说公司表现，再说流动性。`to boot` 的追加关系被改写为非连续的“不仅…还…”，并非两个各自有时间的独立内容词。`you have this ... in a company`→“这家公司…拥有…”还发生了视角/句法改写；不能把 `you` 或 `this` 强行标成一个单独中文词。表中“拥有”的归属只是记账，强内容锚点是流动性与表现，整块更可靠。

### s74（470628–482977ms；中文40 code points）

英文原句：But we don't intentionally, or willingly, voluntarily, go into situations where we perceive really significant risks.

中文原句：但对于我们认为确实存在重大风险的情况，我们不会有意地，或心甘情愿地、自愿地涉足。

| 源 word IDs | 英文词/短语 | 中文范围 | 中文原文切片 |
|---|---|---|---|
| `w1168` | But | `[0,1)` | 但 |
| `w1169` | we | `[19,21)` | 我们 |
| `w1170` | don't | `[21,23)` | 不会 |
| `w1171` | intentionally, | `[23,27)` | 有意地， |
| `w1172..w1173` | or willingly, | `[27,34)` | 或心甘情愿地、 |
| `w1174` | voluntarily, | `[34,37)` | 自愿地 |
| `w1175..w1176` | go into | `[37,40)` | 涉足。 |
| `w1177..w1178` | situations where | `[1,3) ∪ [15,19)` | 对于 ⊕ 的情况， |
| `w1179..w1183` | we perceive really significant risks. | `[3,15)` | 我们认为确实存在重大风险 |

**独立观察：** 英文先给“不故意/不情愿涉足”的态度，再给“我们认为有重大风险”的条件；中文把风险条件整块前置。`don't`↔“不会”和 `significant risks`↔“重大风险”是两端强锚点；不能先显示风险态度却把风险条件分给尚未到来的另一段。`we perceive really significant risks` 整组对应“我们认为确实存在重大风险”，其中“存在”是中文谓语显化，不单独伪配给 `really`。三个意愿副词有同一个“不”作用域，不宜拆掉共同否定。

### s88（563235–579889ms；中文48 code points）

英文原句：So we think in terms of that moat and the ability to keep its width and its impossibility of being crossed as the primary criterion of a great business.

中文原句：所以，我们认为，一家伟大企业的首要标准，就是拥有这样的护城河，有能力保持它的宽度，让人无法跨越。

| 源 word IDs | 英文词/短语 | 中文范围 | 中文原文切片 |
|---|---|---|---|
| `w1418` | So | `[0,3)` | 所以， |
| `w1419..w1423` | we think in terms of | `[3,8)` | 我们认为， |
| `w1424..w1425` | that moat | `[22,31)` | 拥有这样的护城河， |
| `w1426..w1430` | and the ability to keep | `[31,36)` | 有能力保持 |
| `w1431..w1432` | its width | `[36,41)` | 它的宽度， |
| `w1433..w1438` | and its impossibility of being crossed | `[41,48)` | 让人无法跨越。 |
| `w1439..w1442` | as the primary criterion | `[15,22)` | 首要标准，就是 |
| `w1443..w1446` | of a great business. | `[8,15)` | 一家伟大企业的 |

**独立观察：** 英文先讲护城河、宽度和不可跨越，再说这是伟大企业的首要标准；中文先给“伟大企业的首要标准”，再列护城河及属性。`that moat` 的强名词锚点是“这样的护城河”[24,30)；中文“拥有”[22,24)是谓语显化，不宣称英文有一个独立的“拥有”词。`impossibility of being crossed` 的否定性质必须与“无法跨越”保留在一起，不能只展示“跨越”。

## 强锚点与固定译序交叉反例

下表只取可直接审读的内容核（有意去掉若干周边标点）。`A→B`表示英文源顺序，中文范围次序却是B在A之前。这里的“交叉”不是译文必然错误；它证明**英文按顺序切成N段，再把原中文也按顺序切成N段**并不必然有语义解。

| 句 | 英文顺序A→B | 中文B→A | 不能丢失的性质 |
|---|---|---|---|
| s5 | w38..w39 `took over` → w40..w42 `35 years ago` | [11,15) `35年前` → [15,17) `接手` | 数量35及接手事件 |
| s6 | w81..w82 `positive gains` → w83..w85 `in net worth` | [52,55) `净资产` → [55,58) `正增长` | 增长的对象，不能把“正”与增长分家 |
| s14 | w206..w207 `nothing magic` → w210..w211 `one-year period` | [0,6) `一年这个周期` → [7,15) `没有什么神奇之处` | 否定不是“神奇”单词的前缀装饰 |
| s17 | w271 `fluke` → w286..w287 `underlying value` | [11,15) `内在价值` → [28,30) `碰巧` | 对“无下滑年份”作碰巧评价，并受程度限定 |
| s22 | w359..w360 `not totally` → w363..w365 `most business activities` | [24,31) `大多数商业活动` → [56,60) `没有完全` | 否定的是关联程度，不是商业活动存在与否 |
| s48 | w746..w747 `extraordinary liquidity` → w753..w755 `performed very well` | [9,15) `表现非常出色` → [19,27) `非同寻常的流动性` | 两事实次序倒置；追加关系分散到“不仅/还” |
| s74 | w1170 `don't` → w1182..w1183 `significant risks` | [11,15) `重大风险` → [21,23) `不会` | 否定作用于涉足/意愿，风险条件前置 |
| s88 | w1424..w1425 `that moat` → w1441..w1442 `primary criterion` | [15,19) `首要标准` → [24,30) `这样的护城河` | 标准与例示/属性框架倒置 |

另外，专名/数字是强核查点，不是通用自动对齐器：

- s5 `Berkshire Hathaway` w43..w44 ↔ [20,38)；`35` w40 ↔ [11,13)；`24%` w61 ↔ [53,56)。
- s6 `Buffett Limited Partnership` w68..w70 ↔ [6,33)；`48` w77 ↔ [47,49)；`26%` w99 ↔ [74,77)。`almost` w98 ↔ [72,74)“接近”，不能把26%说成精确值。
- s22 `Earth` w351 ↔ [10,12)“地球”；`sun` w355 ↔ [13,15)“太阳”；`fruition` w368 ↔ [41,45)“开花结果”。
- s74 `significant risks` w1182..w1183 ↔ [11,15)“重大风险”；s88 `impossibility of being crossed` w1435..w1438 ↔ [43,47)“无法跨越”。

## 只依据原文可保留的合并范围

以下是**条件性文本结论，不是已验证的新切法**：若同时保持源词连续原序、中文连续原序、不改冻结译文，交叉关系应先保留在同一个语义块内。下列范围是本次可直接解释的保守块，不宣称唯一或全局最小，不借容量/时长选择它们。

| 句 | 可复算的保守块（源词 ↔ 中文范围） | 不宜再按词位或字数强拆之处 |
|---|---|---|
| s5 | w32..w34↔[0,5)；w35..w42↔[5,20)；w43..w53↔[20,48)；w54..w61↔[48,57) | “自…以来”、接手与35年前；公司/每年/正增长；年均增幅/达/24% |
| s6 | w62..w70↔[0,42)；w71..w85↔[42,59)；w86..w90↔[59,66)；w91..w100↔[66,78) | 包裹合伙企业经营史的开头；连续48年净资产正增长；没有一年下滑；年复合近26% |
| s13 | w173..w179↔[0,17)；w180..w186↔[17,30)；w187..w194↔[30,50)；w195..w204↔[50,62) | 数字/有意思倒序；合伙企业成立之前；运作资金/非常少；末连接词另有不等价注记 |
| s14 | w205..w211↔[0,16) | 周期与否定评价互换，整句保留最清楚 |
| s17 | w268..w287↔[0,33) | 程度限定、无下滑事实、内在价值、碰巧评价交叉包裹 |
| s22 | w343..w355↔[0,21)；w356..w377↔[21,64) | 地球/太阳/公转事件；“跟…并没有完全关联”包住三项列表 |
| s48 | w741..w742↔[0,3)；w743..w757↔[3,28) | 流动性/公司表现倒序，不仅/还跨两事实；前块只是连接词，不建议因此单成cue |
| s74 | w1168..w1183↔[0,40) | 前置风险条件与后置共同否定/三个意愿副词/涉足，不因中文逗号而拆开 |
| s88 | w1418↔[0,3)；w1419..w1446↔[3,48) | 伟大企业/首要标准前置于护城河/宽度/不可跨越；前块只是连接词，不建议因此单成cue |

这意味着“最小语义匹配单元”和“可按双边顺序独立显示的单元”并不相同。字词级对应可以交叉；如果未来发布格式不支持这种关系，就应显式面对整块保留或人工处理的代价，不能假称按字数分配已经语义同步。本报告不决定最终策略，也不以时长上限偷偷切开这些交叉范围。

## 复核记录与尚未证明的事项

- 两份输入的字节哈希与translation内嵌源哈希已校验；映射9句的源word ID及中文code-point集合均恰好覆盖一次。每个中文展示片段直接由原字符串切片生成，未改空格或标点。
- 此检查只确认引用可复算；改写/省译/增译已在 s6、s13、s22、s48、s74、s88 明示，不能由完整覆盖偷换为逐词金标准。
- 未读音轨、未看旧/新cue、未渲染媒体、未审余下88句，未证明新样片更好。没有代码改动，未运行离线pytest；文档中的“通过”仅指上述输入/范围机械校验，不是项目测试套件或语义质量验收。
