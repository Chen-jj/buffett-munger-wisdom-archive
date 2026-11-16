# ADR-0013：有类型的源语切分评价与防退化迭代

- 日期：2026-11-13（Asia/Shanghai）；2026-11-14恢复实施并修正cut根因收费锚；2026-11-15完成v7离线/实验并授权adapter-only两类predicate core。
- 状态：**v9实现/开发集有限取舍及真实source精确证明已验；真实166cue最终稿已全97句独审，整体语义同步/出版质量未通过。当前仅放行诊断候选样片供用户复审，不改稿/重置额度，真实诊断渲染及五阶段复用已留证，负责人仅目视18抽帧，未全面观看/核听；双破折号视觉断行残余披露不修。**
- 归属：总方案仍是 [ADR-0008](../archive/decisions/0008-local-orchestration-and-integration-tests.md)。本决策修订 [ADR-0010](../archive/decisions/0010-source-chunking.md) 的候选生成、容量、评分及确定性救援，不新建总方案或模块；下游编辑/排时继续遵守 [ADR-0012](../archive/decisions/0012-bilingual-translation-postprocessing.md)。
- 实施入口：[NB-12](../tasks/NB-12-chunking-quality-iteration.md)。负责人仅拆解、调度、验收、回归；生产及测试代码由子 agent 实施；2026-11-17用户授权全部本地代码/测试/文档commit与push，由负责人执行，历史阶段不提交约束不再覆盖此次授权。
- 安全边界：保留已有全部 dirty 改动和资产；不回滚、不删除、不覆盖旧输入/输出；本次复用已验证转录及媒体，**不重跑 ASR、词对齐或伪造时间**。所有候选、账本、译文、样片及失败证据写独立新根。

## 1. 目标与不做的事

保留 DP，完善其对“坏切分”的描述：边界有类型、严重关系中断不被多个轻代价抵消、评价整个 cue，并让停顿在符合结构条件时有限参与。减少 cue 和均衡容量是后位收益，不得补偿实质缺陷。

成功不是单句复刻参考稿、警告减少或 pytest 数量增加，而是固定同源条件下：指定问题改善、已认可切法不退化、未见样本无新严重问题，且源词/时间/来源链和复用保证不变。暂不新增模型、音频呼吸检测、镜头检测、运行时语义评分器或自动出版门禁。

源语分组、初译、最终双语稿、实际烧录分别验收。初稿变好不代表编辑器必然保留；编辑稿结构合格不代表语义通过。中文逐屏对应、提前/滞后、口语改口和9 CPS需在下游单独检查。

## 2. 统一候选和不可变输入

```text
完整 canonical 句子
  → 仅容量或基本最长时长判断是否需要切
  → 需要时完整句 Stanza（固定现有本地模型）
  → 所有安全词间边界的有类型特征、局部保护
  → 同一 DP 评价完整分组
  → 同目标的有限救援
  → 只读预算、真实报告、独立发布
```

- 项目英文容量改为 **84 Unicode 码点/cue，含空格/标点**，替代80。用户已明确本模块不负责显示换行；84是逻辑cue预算，不是Netflix的84字符单行许可。保持rendering既有换行/字号/像素职责及规则，不新增单行门禁。实际画面另验，不缩字号或改稿伪造容量通过。
- 基本时间为首词 start 至末词 end。仅字符数>84或基本时长>7000ms触发解析/裁切；只有CPS>20或基本时长<834ms不新增裁切。未触发整句原样保留。
- 取消独立“先试只在逗号切”的通道；逗号、从句、连词/介词前及其他合法词间位置共同进入一次 DP。数字逗号不提供标点奖励。
- 不改英文词、词ID、顺序、句界、speaker、section、词时间。canonical与Stanza按精确字符跨度映射；不可词内切。缺模型、映射不确定或错误时间轴失败，不静默fallback。
- 只读预算继续最多500ms、实际PTS留两帧、媒体尾/下一源词/7秒限制；预算不改变基本时间，不冒充实际借时或已通过指标。
- 硬保护与容量/时长共同无解时保留完整句及真实warning，不能偷偷放开保护或删词。源覆盖/来源链/重叠等硬错不降为warning。

## 3. 硬保护先于评分

仅保护有局部可验证证据的最小组合，不无限封锁整棵NP/PP/RC：

| 硬保护 | 首版边界 |
|---|---|
| 已确认专名/术语、连续姓名核心 | 沿用已确认跨度；大小写不是姓名证明 |
| 冠词/形容词与最小名词核心 | 不把其任意长后置修饰语、关系从句一起锁住 |
| 助动词/否定词与动词核心 | 补查中间副词/多助动结构；不吞并整个长谓语 |
| 数量、单位、比例/分母核心 | 基于词性/局部数量结构；保护百分比等完整计量，不靠样片词表开特例 |
| 短介词与宾语核心 | `of / one-half`与`of / one`应一致识别；介词引导长从句/口语where结构不一律硬护 |
| 跨词数字逗号结构 | 数字—逗号—数字不作为普通标点候选 |

`×2/×3`是旧审计展示记法，不是“付2/3分即可切”。确认保护内的边界始终不合法。长PP、主谓、谓词补语、关系从句可用分级软罚，不滥增硬禁切。`c70`已认可停顿切法不能因泛化介宾保护被无条件否决。

## 4. 保留类型，不提前压成0–3

首版从现有 constituency树/POS及canonical标点提取特征，不新增depparse；不得声称已有`acl:relcl`或解析概率。以下数字只用于解释旧分值/普通边界等级，不再把所有关系加成一个总和：

| 类型 | 证据与默认处理 |
|---|---|
| 独立/并列分句边界 | 完整S等结构及并列关系提供低代价0；不能只看and或大写 |
| 高层条件、附加从句、完整插入语边界 | 0/1级候选，保存父节点/覆盖跨度；不是见SBAR就0 |
| 合理完整短语边界、长PP之前 | 通常2级；保留修饰对象及附着方向 |
| 名词与限制性关系从句/不定式补语 | 不因S/SBAR起点自动0；记录紧密依附及可能的前屏悬空 |
| 谓词与宾语/补语、主语与谓词 | 区分核心依赖与可独立后补；核心中断单列较严重事件 |
| 频次/程度/数量附属、否定/限定范围 | 按可识别结构记录依附；不把全部副词强制归前/后 |
| 连接语与所引出的陈述 | so、and then等不应只因后面有gap就挂前屏；必须有结构证据，不机械词表切 |
| 普通/未知边界 | 保留低优先候选；未知不等于坏，也不假装关系已确定 |

标点和句法可以同时提供证据，但标点不能洗掉紧密依赖。受口语重起、解析歧义影响的规则应降低判断强度并报告证据限制，不编造模型置信度。

## 5. cue本身与分层目标

### 5.1 候选语块特征

评价连续词窗(i,j)，不只看右端切点：

- 悬挂的引导成分、连接语、主语或需要补足的名词/谓词；
- 没有合理独立作用的依附尾片；
- “上一陈述的依附尾部＋下一独立陈述开头”的混接；
- 可识别的否定、限定、数量/比较/条件作用范围被切断；
- 完整判断、条件、并列项与口语后补的可处理性。

不是凡语法未完都罚。问答、完整短句、独立插入语、强调/迟疑/后补允许保留；两个完整短句同屏也不等于混接。canonical一句可能包含多个话语陈述，不把原句ID等同于独立陈述边界。

### 5.2 首版工程比较器（2026-11-13负责人允许试验）

先过滤保护、84字符和7000ms不合法方案，再比较非负分层罚分；同罚才比较有界收益，最后稳定offset。**任何高层罚分都不能被奖励抵消；不再出现3等于2＋1。**

首版提议采用可解释的字典序向量，不先拟合大组实数权重：

```text
(高影响缺陷事件数,
 一般结构缺陷事件数,
 超短cue数, 超短总缺口ms,
 普通边界3级数, 2级数, 1级数,
 CPS超标cue数, CPS总超额负担,
 cue数,
 -合格停顿的封顶收益,
 相邻cue字符数绝对差之和,
 单cue贴顶风险平方和,
 完整切点offset序列)
```

- 高影响：有明确结构证据的强依附中断、依附尾片混接，以及极端闪现；一般结构：较弱的依附/附着问题。首版将**<250ms**闪现升级为高影响事件；这是负责人已确认可试验的工程假设，不是FAR/行业分级，须覆盖100/249/250/833/834ms及问答、不可合并完整短句反例后再决定是否保留。
- 诊断标签可以多个，但收费必须局部可分解：以每个实际cut b为事件锚，边界依赖、左cue含新陈述前缀、右cue含旧陈述尾片等同切点表现取最高严重度，只在右cue收费一次。不同实际cut分别计费，同一中间cue首尾引出的两次独立缺陷不能全压成一个cue最大值；<250ms闪现是独立技术事件。当前工程口径对同一cut的重叠关系只收费一次，避免句法树嵌套多标签反复收费。无全局set，不把全局去重伪装成可加代价。短时数量与缺口是同类事件的同分细化，不是不同根因重复累计。
- CPS负担使用精确非负超额`max(0,字符数×1000−20×基本时长ms)`；只是已需裁切的候选之间择优，不由CPS触发新切分。
- “全项达标”仅容量、CPS、834–7000ms，不能把它称为语义/像素通过。达标比例只报告，不进入DP；技术罚层已包含这些指标，不再另加冗余的达标率奖励。
- 容量裕度只在其他层完全相同时比较，首版用`sum(字符数²)`表示贴顶风险（每cue最多84²），在cue数已相同后才比较；不能为了均衡多切cue，也不以非可加最大值偷偷破坏一阶最优子结构。
- 相邻两屏节奏属于二阶特征：**第1～5轮先报告相邻字符数/CPS/时长落差，不进入一阶DP；本任务第6轮必须实现含上一cue状态的正确二阶DP并消融**，不能以仅报告作为本轮完成。初档只在前面结构/技术罚分、cue数及合格停顿收益同分后比较相邻`abs(本cue字符数−上cue字符数)`总和，再看贴顶风险平方和；它是对称整数节奏代理，不假称完整阅读/声学节奏。
- 上述向量内关系严重度和事件去重须随NB12-0冻结，250ms及收益分档为已允许试验的首版工程假设，不代表实测最优；未冻结项目不得由编码者临时自行决定。每轮先固定再实验，不追着单例改权重。

首版工程类型定价冻结：`subject.predicate`、`predicate.complement`、`noun.infinitive`、`connector.after`及`clause.relative`同时有`evidence.relative.no-comma`为高影响；只有relative或relative+comma及`attachment.adverbial`为一般结构。没有对应结构证据不猜测。2026-11-14现行US普通层为independent/coordinate/adverbial=0、punctuation=1、phrase.preposition及ordinary/未知=2；未知不自动视作已证实弱依赖3。已在结构层收费的边界不再收普通层费用。语块混接按上一段实际cut锚，与该边界及左右相邻cue表现取最高级一次。每条<250ms闪现为独立技术事件，可与结构事件并存；问答反例检查其是否造成过度合并。

二阶状态于2026-11-14修正为`(first_offset, previous_first_offset)`，上一cue范围为`[previous_first_offset, first_offset)`；由该范围读取字符数与左cue混接证据。关闭节奏消融时仍保留上一范围，以正确按cut去重。旧prev_chars状态不足以处理左右cue根因交互，不再使用；如未来新增非相邻或全局特征仍须重新论证state/最优子结构。原句DP内连续比较；跨句短块救援比较完整分组（含左右外邻居），其相邻字符代理在当前源序列上连续计算，speaker/section资格仍先硬过滤，不能用节奏越界合并。将来若要求跨speaker/section重置，须同改评分/DP/救援/测试，不隐含两套目标。

### 5.3 同目标的确定性救援

原窄三块整形的候选已全部在统一完整DP中；其最优方案不可能被同目标的局部替换严格改善，因此撤下该冗余决策分支而不删除文件。保护/容量/源词/词时及真实技术报告的旧护栏仍由DP和新回归覆盖。同句短cue合并不得继续只按gap/少块改写新DP的好结果。有限邻域仍按现有允许范围生成候选，但以同一目标比较原方案与候选，只有严格改善才采纳；不可绕过硬保护/容量/时长及既有四项合并资格。

跨原句只合完整原句、原始gap<500ms，不跨section、不同已知speaker或经null桥接。不能把从句尾巴接下一句来救短cue。保持有界单邻居/局部候选搜索，不扩大为跨句全局优化。

此处“后处理同目标”仅指source chunking内部的确定性救援。translation的有界编辑生成不改为DP评分采纳，不跨模块import私有评分器、不新增运行时语义门禁；通过prompt说明优先级，并在真实成品回归中核验。

## 6. 停顿：资格、相对性、实际帧、有界奖励

- 保留gap毫秒、实际decoded PTS空帧数和结构类型；绝不以平均fps四舍五入替代真实空帧。
- 硬保护内无资格、强依附中断无资格；只有结构可接受的候选才获得停顿收益。长停顿不能赎回紧密依赖；气口不直接制造合法切点。
- 首版提议固定帧档：0–3空帧无收益、4–8弱收益1、>=9封顶2；微小毫秒差异同档不决胜。档位是工程假设，须在消融中与无gap收益比较，不能冒称已验证行业参数。
- 第5轮实现并消融相对统计：完整原句全部有效词间实际空帧数取`log1p(frames)`，包括零帧；样本数>=8且MAD>0才计算`z=(x−median)/MAD`，不额外乘正态尺度系数。工程初档z<2不增加相对收益、2<=z<3增加1、z>=3增加2；0–3帧先绝对中性返回0，即使相对z高也无收益；其余与固定帧档收益相加后每个合格切点总收益封顶2，不按毫秒继续奖励。样本不足、MAD=0或缺PTS时相对收益为0并记录原因，固定档也只在有真实帧证据时可用。比较无停顿、固定档、固定档+MAD三组；默认是否启用由实测决定，不能未实现就以“未来研究”收尾。全段短cue救援保留每个canonical原句的上述统计上下文，跨原句边界仅固定帧档，不将原句MAD替换为全片MAD。
- 2秒仅作为重点核听/修辞候选的审查提示，不是自动“强调/悬疑”分类器。没有核听就不定性呼吸、迟疑、笑点或揭示时机。
- <2帧是独立打点风险，不等于结构切分必须否决。源语阶段不能缩短已发音词尾、提前start或假称chaining已经修好；最终排时继续按ADR-0012权限实测。

## 7. 四组对照、消融与多解防退化

先固定源alignment、PTS、完整句、解析模型/输出和保护证据；变更特征提取时另记新特征身份。旧代码基线来自本次dirty工作区的实际快照/hash，不是Git HEAD。旧评分仅放冻结测试/实验基线，不保留第二条生产路径。

必须完成80/84 × 旧/新评分四组对照。旧评分80组保留原逗号/评分行为；为隔离收益，额外消融统一候选、保护修复、typed关系、cue特征、停顿、阅读负担，不能把所有收益归于权重。

基准以固定源句/话语单元为单位，标注：不可接受边界/结构、必须保留已认可结果、多套可接受分组、成对偏好、需核听及争议。reference不是唯一gold，不用候选自己cue数量作主分母。

| 集合 | 作用 |
|---|---|
| 用户纠错集 | s4、s16等明确问题及逐项原因 |
| 保好/允许结果集 | 未触发完整句、已有好边界、c70/c114允许结果 |
| 反例集 | 长RC/PP、问答、后补、口语重起、数字单位、否定范围、长gap落在NP内、保护/容量无解 |
| 全97句回放 | 展示所有变化与不变；已反复调参，不称holdout |
| 未见集 | 其他章节/说话人冻结后先盲判，完整话语不跨调参与验证分组；已看过的内容不得冒称未见 |

先标注再调参；隐藏A/B版本名独立评判，分歧保留，不把自动语言模型打分当客观gold。报告原始严重/普通错误数、固定单位win/tie/loss、各类技术负担、全部退步和未定项目；不能靠总均分盖过新增严重错误。FAR可辅助人工错误分析，但不是现成DP权重，也不因混接每词正确就豁免其segmentation问题。

每轮只加一类特征并做消融。所有阶段来源/词时/覆盖不变量先通过；新增严重问题0、保好集无未经接受退化、指定问题可解释改善，才进入昂贵下游。无法达到时保留候选和失败，不偷偷改gold。

## 8. 新根真实样片与验收边界

冻结的NB-09现存媒体/转录需先验证输入hash及来源链。新根采用集中测试runner的`frozen_source_replay`五阶段adoption view：校验并记录冻结媒体/转录证据后，只真实执行source chunking、初译、编辑、SRT导出、渲染五阶段。adoption view是试验来源绑定，不伪称生产编排前四阶段fresh/reused，不扩张生产编排接口；**不复制旧manifest改路径冒充复用**，不重跑ASR。

按新身份生成source chunks → 真实初译 → 现有有界双语编辑 → 三SRT → ASS/烧录。保留默认20项术语及本次配置身份，不沿用旧样片宣称已更新。逐阶段检查97句与所有cue；特别检查编辑器是否重新混接/合并、数字/否定/条件/限定/专名与中文逐屏对应。

必须实际查看成片并按记录范围核听。无声音访问、播放失败或未听完均据实披露，不拿文本/帧图代替核听。验证真实字体/像素、声轨一致、最终PTS/间隔、同进程及独立新进程复用0昂贵调用/0阶段改写；保护集hash/size/mtime及链接目标不变。

## 9. 规范与学术证据的使用边界

- [Netflix通用要求](https://partnerhelp.netflixstudios.com/hc/en-us/articles/215758617-Timed-Text-Style-Guide-General-Requirements)、[英文指南](https://partnerhelp.netflixstudios.com/hc/en-us/articles/217350977-English-USA-Timed-Text-Style-Guide)、[简中指南](https://partnerhelp.netflixstudios.com/hc/en-us/articles/215986007-Chinese-Simplified-Timed-Text-Style-Guide)、[模板指南](https://partnerhelp.netflixstudios.com/hc/en-us/articles/219375728-Timed-Text-Style-Guide-Subtitle-Templates)、[时间指南](https://partnerhelp.netflixstudios.com/hc/en-us/articles/360051554394-Timed-Text-Style-Guide-Subtitle-Timing-Guidelines)：区分每行42与项目84/cue，英文20/模板17 CPS，简中9 CPS与项目16单位；行内断行和跨cue组织不是同一对象。
- [Prime Video总指南](https://videocentral.amazon.com/support/delivery-specifications/prime-video-subtitling-guidelines?language=en_US)与[官方2026-09语言包](https://m.media-amazon.com/images/G/01/CooperWebsite/dvp/downloads/AmazonPrimeVideo_Localization_and_Technical_Style_Guides_September_2026.zip)支持跨cue语义/句法自洽及韵律协同。已核查包内2026-09-17英文/简中DOCX：英文42/行、成人20 CPS，简中18/行、成人10 CPS；不与Netflix的9 CPS或项目16单位混用成一套行业参数。
- Titford 1982（本轮未取得原文；谱系参考[Díaz Cintas本人的研究史综述](https://www.jostrans.org/article/download/8045/7904?inline=1)）、[Chaume 2004](https://doi.org/10.7202/009016ar)、[Georgakopoulou 2009出版社原章](https://link.springer.com/chapter/10.1057/9780230234581_2)及[Pedersen 2011](https://benjamins.com/catalog/btl.98)支持多维约束/语块组织与规范分析方向，不能把五位作者写成共同提出过一个专名框架、统一阈值或现成DP算法。Georgakopoulou保留/压缩/省略三级引自Kovačič，不授权本项目删source词；Díaz Cintas/Remael 2007原书89–90页及Chaume完整原文未取得，不冒称已核查精确引文/代码数。
- [FAR原文（Pedersen 2017）](https://www.jostrans.org/article/download/7801/7457/18803)是暂定人工错误分析模型，普通罚分0.25/0.5/1，语义等值才0.5/1/2；跨cue分段通常standard，行内minor，混接可落segmentation，不挂在2011年ECR研究名下，不直接用候选cue数归一化后的分数做本项目优化目标；换气、强调及未知镜头不能仅凭时间阈值下结论。

## 10. 当前事实

开工生产为80字符逗号优先v4；设计/基线已验收，子agent正在实施，尚未通过新算法验收。负责人本次实测离线基线2450 passed / 7 skipped（12.69s）。本ADR的授权不等于已经实现、实验改善、未见集通过、核听或出版签字。后续真实结果由NB-12按阶段记录，不改写NB-09/10/11历史证据。


### 2026-11-14同因计费修正（独立于后续句法漏标修复）

v1在statement[0,2)、[2,4)、边界3 subject.predicate且分组[0:3]|[3:4]时，左cue混接与右cue主谓断裂会分别收费，独立审查确认属于同cut重复计费。现按上文左右cue的实际cut锚取最高级，例中高影响从2改为1；中间cue有首尾两个不同cut时仍计2，flash另计。不改通用排序/阈值，不把其他新坏断点混入该修复归功。

政策身份升级为`english-typed-cue-dp.v2`及cut-anchor ranking v2；旧comparison-v1产物保留，不冒称应用此修复。新增包含spans/关系交互的独立枚举oracle，正确二阶state为上一range而不是仅上一字符数。全97句v2及未见集仍待真实回放/审查，不凭单元绿声称质量改良通过。


### 2026-11-14后续特征切片授权（与cut-anchor v2分开验收）

comparison-v1人工审读发现新增坏断点，六个已标forbidden消失不能代表整体质量提高；暂不放行真实provider/样片。cut-anchor修复只处理重复计费，不能把下列句法修复的收益归于同因去重。

负责人另批准现有Stanza适配器的通用漏标/过护修复，并要求各自正反例、来源可见及analyzer身份升级：

1. aux跨越带逗号/并列CC的长ADVP时停止硬吞整段，不把口语插入与另一谓词合成大保护。
2. coordinated NML与外层NP右侧名词head提取最小核心保护，保住blade business这类结构，但不整棵锁长并列NP。
3. 有VP/POS结构证据的收缩助动词参与现有aux核心保护，不仅靠字符串列表猜全部所有格。
4. 直接WDT的关系从句/连接结构保留关系与归属标签，不只识别WHNP包装。
5. 数字枚举的单位/比例核心保护与并列item边界分开，逗号不成为拆数量单位的理由，也不整段锁全部枚举。
6. 同一引导结构的连续IN marker（如so that）不从中拆开，不把所有相邻IN词无条件合并。
7. 同ADVP内的时间NP + ago附着使用既有`attachment.adverbial`一般结构档，可另带诊断证据`evidence.temporal.ago`；不因该单例升级为强依附或任意长硬保护。

上述不改变向量排序/阈值；数量枚举采用新增`attachment.quantity`一般结构档（与adverbial同档），其余沿用现有typed标签。数量列表只保护每个item/单位最小核心，不整列硬护；政策身份升typed v3、适配器单独记录新身份。不引入“全部名词of短语强罚”；如后续原句证据提示需要，另立消融切片和负责人决定。特征实现、全97句/反例复审及新comparison-v3均须留真实记录，目前仍属迭代中，不是质量通过。


### 2026-11-14 statement归属修复（独立comparison-v4）

固定v2源码/原树的只读反例确认：合法前导marker属于后续长S，但statement跨度漏掉marker，会使该S内部的合法切分被`previous_first < statement.first < cut < statement.last`误报为“旧陈述＋新陈述头”。86字符的`so + long S`合成中，合法两屏27/58字符与错误`so | S`同时H1；仅将所属so纳入span后，合法H0，错误仍为connector.after H1。

真实s39第二statement从w629 over开始而漏w628 so；s16 statement[20,36)漏And19，参考future|assuming31因此误得H1。独立v4仅修适配器statement所属前导CC/RB/无clause ADVP跨度，允许纯S wrapper传递prefix，不跨前置条件SBAR或旧独立S；保留/补齐connector.after，不靠删依赖罚分掩盖。domain排序/阈值不变。新增纯DP正反例保留真“完整旧句＋新头”及“旧尾＋新句”，并覆盖s16 And长S的合法续屏。

v4固定源回放已完成，但不代表全97句质量通过；s16参考四屏已恢复、s39 so挂前屏消失，s6/7/13、what kind/of、terms/of及up/and down等残余仍待独立裁决，不放行真实provider或烧录。

### 2026-11-14已批准的objective-v1：两因子2×2，仅隔离实验

当前向量明确把CPS负担排在普通语法等级之前。v3同源重算显示s7、s13、s18、s47、s75的坏/好分组在H/一般结构/超短均相同后，最早由CPS超标cue数决胜；完全关CPS虽恢复若干句，也会损害别处，因此不据此关掉CPS上线。另s88参考and前只有unknown/ordinary3，而三个PP2碎片可先胜；强依附已有typed独立档后，缺信息是否应当被视为最高普通坏档需要单独实证。

负责人已批准以下**实验，不批准直接改生产**；由编排runner在v4冻结candidate源码副本的独立worker内覆盖，源码文件、raw树、保护、84容量、触发、H/一般结构/超短、奖励/阈值及源词时间均不变：

| 组 | unknown因子 | 排序因子 |
|---|---|---|
| B | 现有默认3 | 现有CPS在普通语法等级前 |
| U | 仅`_ordinary_grade`原返回3时改2，其余返回不变 | 同B |
| S | 同B | 仅普通语法等级移到CPS前 |
| US | 同U | 同S |

S的精确局部13字段置换为`(0,1,2,3,6,7,8,4,5,9,10,11,12)`：

```text
high_impact_events, ordinary_structure_events, short_cue_count, shortfall_ms,
ordinary_grade3_count, ordinary_grade2_count, ordinary_grade1_count,
cps_exceed_cue_count, cps_excess_burden,
cue_count, negative_pause_reward, adjacent_character_rhythm, squared_character_load
```

完整stable_offsets仍在最后；DP、全段短cue救援及why trace使用同一变换。S/US的`score_fields`有序标签必须同置换，明确objective_id/选项/顺序；不让新数值被旧字段名误标，不把不同目标的分数横比当质量分。所有组CPS仍启用并真实测量，不改变“只有CPS超标不触发裁切”的规则。

验收先要求B精确重放v4 new84 plan及输入/code保全，再对四组全97句及全部变化独立人审，冻结原有多解/保好/反例标签，不按cue数归一化藏错。报告各因子独立效应及US交互、新增/修复缺陷、未定项和技术代价；不能由CPS更低、cue更少或forbidden清零直接选上线。

本轮不增加noun-of、partitive、NP phrase.coordinate、零关系代词或新硬保护，不把特征和目标排序同时改来混淆归因。若S/US/U经负责人审查胜出，才另切片实施唯一生产目标、版本身份及独立oracle更新；原生产行为不会因worker实验自动变化。新实验只写独立objective-v1目录，v1～v4及其冻结源码保留，不发provider/ASR/编码请求。


objective-v1已按上述预注册计划完成四组回放，B精确复现v4，变量/有序字段/DP及救援同目标与来源保全已独立核对；plan SHA-256 `1c060dfef2a98508ef6a6dd851393de71ab570accaa094fa53eabc5acb929ad1`，evidence SHA-256 `ea4fdf3d82b765aa66c4c8d1e87a55f269de4e2ae775f89a2375f6172e1bbaca`。实验执行时未改生产；随后负责人的有限生产选择与剩余验收见下节，数值汇总见NB-12，不将实验完成写成语义通过。


### 2026-11-14负责人批准US唯一生产落地（尚非源语质量放行）

负责人及独立审读认为，US同时保留普通句法先行的单元改善与unknown回普通2的保守性；不因cue数165、空帧或CPS汇总更低就选中，也不认为US没有新错。现已授权且只实施单一目标：未知默认2，普通等级在CPS之前；CPS仍开启、同语法层仍择优，只有CPS超标仍不触发新裁切。不提供运行时B/U/S/US路径，不让生产兼容旧评分。

政策升`english-typed-cue-dp.v4`及对应ranking v4，`srt_processing.domain.chunking_policy.SCORE_FIELDS`是实际13分量的只读有序定义，并以`score_fields`写入policy身份；稳定cut序列另置最后。新why读取实际顺序；旧实验只由测试层冻结副本/明确旧身份解释，不让新US再被旧U/S覆盖重复变换。

落地验收包括：普通2、普通语法可胜更低CPS、同普通层CPS仍生效、一个普通cut不必输给三个PP、CPS-only不切、同容量旧typed身份只读冲突；独立全分组oracle同时包含普通grade/CPS、左右cue根因与二阶节奏。完整离线后，cached97生产分组/词时/保护/模型须与冻结objective-v1/US精确一致，policy身份不同单列；不修改旧实验来伪造一致。

Stanza保持v4 feature不动，CF/question另轮须等待上述证明及barrier释放后才实施；当前仍有问句倒装、名词附着及小单位漏标，US实现及实验选择都不等于源语质量通过，不放行provider、ASR或新烧录。


### 2026-11-14 US精确证明后的独立CF/question切片

US正式生产已经在新`production-us-proof-v1`与冻结objective US精确一致：完整plan除policy以外8字段、metrics、短救援前/后有序评分均同，policy四项身份差异明确，证据见NB-12。这是实现等价证明，不是整体源语质量通过。

负责人在证明完成/释放barrier后，另授权四项通用适配器修复，并保持排序、阈值及源词/词时不变：

1. SQ/SINV中有结构证据的倒装助动词—代词主语—动词核心，局部保护/typed主谓；不无限锁长NP主语或整问句。
2. 标点＋完整SQ/SBARQ的question引入为`clause.interrogative`低档，节点和VP子项分类共用guard，避免旧predicate.complement残留压过新正确类型；非问句/无标点普通补语不误放。
3. NP下直接WDT＋有主语的完整S，保留不确定性为`noun.clause`一般档；明确WHNP/无主语限制性RC仍按原强档，连接语之后仍有归属保护，不把所有名词从句无条件放低。
4. 逗号后无主语S/VP-VBG补述，只有同VP逗号前已有独立NP/PP内容（或嵌套VP对象）才作为附加边界；不跨S/SBAR借主语判完成，不把`kept, running`误作独立补述。

domain只新增两个tag映射：`clause.interrogative`并入GOOD低档、`noun.clause`并入一般结构；policy/ranking升typed v5，实际SCORE_FIELDS与US顺序完全不变。最小类型/长软依附/强标签不被GOOD洗白及独立oracle必须覆盖。Stanza适配器另升级feature身份；新comparison-v5独立归因，不覆盖US证明或旧实验。仍不扩nominal-of方案，不放行provider/新烧录，待完整离线/全部97句及反例审查。


### 2026-11-14负责人批准的独立NomOf软附着切片（comparison-v6）

CF最终完整问句guard已补齐，comparison-v5成功并释放barrier后，负责人另批准本切片；不混入此前US目标/CF四项归因。CF最终guard工具实测2684 passed / 7 skipped（14.32s）；先前临时完整log本轮已不在盘，不伪造持久可复核路径。负责人当前独立2684 / 7（14.78s）。整体源语质量及真实下游仍未放行。

范围只识别名词/数量/疑问名词头与其直接of-PP的软附着：

- parent限定NP、NML、WHNP、QP；目标必须是该parent的直接PP子项，首叶为IN `of`，不把任意包含of的祖先跨度都标注。
- 左侧必须有可见NN*名词头、CD数量、疑问名词头证据，或非冠词partitive量词；量词首版明确限制`all`、`most`、`some`，其余另以通用证据/测试接受，不凭`the/a/an`触发。不向无头PP或不相关从句内寻找一个词来凑头证据。
- 在of前增加`attachment.nominal-of`，domain映射到现有一般结构档，与adverbial/quantity/noun.clause同层；保留原phrase.preposition等证据，按原cut锚最高级收费，不叠加多罚。
- **始终是soft**：不删候选、不扩大任何硬保护、不硬锁整条of链或长NP/PP；长of短语受84/7秒预算时仍可从该处切。动词所属VP+of、非of PP、只有冠词/无名词头的损坏结构及长RC保持原行为。

适配器子agent唯一修改树/POS特征及独立正反例；domain子agent唯一增加该tag的一般档映射、typed policy/ranking v6身份、纯软边界/oracle测试。US向量、有序SCORE_FIELDS、时间/停顿/阅读阈值不变。不混`no matter`、短ADVP、时间、scope等其他修复，不以句ID或样片词组开特例。

验收先正反例/长of仍可切及完整离线，再共同freeze新comparison-v6与v5对比，全97逐句列所有变化与退化；0 provider/ASR/编码，源词/词时/来源/旧资产不变。不因新增tag、自动约束清零或pytest通过就认定质量通过。未来本切片完整log写独占持久验证证据，不冒称恢复已消失的临时log。


### 2026-11-14负责人批准的独立局部scope/小单位切片（comparison-v7）

负责人独立v6完整2723 / 7（13.62s），已审六个变句及全165 cue。NomOf多数改善，但s94新增virtually|all阻断；s18、s68、s60另有明确局部关系缺失。本计划先落盘再编码，只做以下五项，不改US向量/SCORE_FIELDS/阈值或源词时间：

1. 有ADVP或相关局部树结构证据的`no matter + WH`：只硬护最小no/matter/WH核心，后续内容不硬锁，继续表达connector归属。普通matter、独立what、无该局部结构均为负例。
2. 严格三项、非clausal ADVP `[RP/RB, CC, RP/RB]`，before-CC标`attachment.coordination`一般soft；逗号、长列、含clause/口语插入ADVP不扩展，保留s74反例。
3. NP/QP内紧邻degree RB/RBR/RBS＋all/most/some，before-quantifier标`attachment.scope`一般soft；不凭冠词/跨标点或句首actually触发，不把任意RB全局当scope。
4. VP下NP以NNS `times`为head且局部有CD或few/several/many/some，before-NP标`attachment.frequency`一般soft；those times、Times专名或任意宾语不按此泛化。
5. 数量＋时间单位并跟随`PP from + ADVP now`，before-from及from/now标`attachment.temporal`一般soft；不改时间或硬锁长枚举，from London、收入from overseas、非时间NP为负例。

s60 `in terms of | what`已被负责人裁为允许的长PP取舍，本片不额外添加PP规则。domain作者唯一增加上述四tag一般档映射及policy/ranking typed v7，独立纯soft/根因去重/oracle/身份测试；适配器作者唯一实现局部结构/最小no-matter硬核及正反例、升级feature身份。不得混其它关系、改权重或以句ID特判。

先定向/完整离线、持久验证日志，再共同freeze独立comparison-v7与v6比较，逐句列出全部变化及已好切法回归；来源/词时/旧资产不变，仍禁provider/ASR/新渲染，不把技术通过当整体源语或出版签字。


### 2026-11-15负责人批准的adapter-only最小predicate-core片（comparison-v8）

comparison-v7已实际exit0并释放barrier，负责人核对97句/1569词/165 cue及全部输入/source保护；独立复审仍因s18 `are | not related`、s60 `currently | exist`不通过，s60 `say | five`保留但不扩本片。先落本计划，再由适配器作者唯一编码以下两类最小hard核：

1. **同VP的copular be→ADJP**：be与ADJP间仅可跳simple RB/纯RB ADVP；ADJP直接前缀仅可为RB/RBR/RBS或纯RB simple ADVP，随后必须是第一个直接JJ*。hard到首个形容词即止，不递归深ADJP、不跨其它子项/comma/CC/PP/clause/PRN，不吞后续PP/RC/长ADJP；has、keep、非be、名词be为负例。`is very good`、`is not particularly clear`与`are not related`走同一局部结构核，不按当前词特判。
2. **已确认VP complement的bare S/SBAR wrapper链**：无marker、每层仅单子纯S/SBAR，末端S无NP/旧S，单叶simple ADVP后直接VP，其首子必须直接VB*；仅hard该adverb＋首verb两词。独立S、if/WH、question、supplement、长/插入ADVP均不触发，不扩整个VP或补语。

本片不改domain/tag/policy typed v7、US有序SCORE_FIELDS、排序或阈值，不为comparison-v8编号强行升级DP版本。只由adapter的protection/ranking显式新版本绑定行为身份，模型/mapping不改。

现有公开链足够覆盖本片身份：SourceChunkingWorkflow构造identity时包含当前analyzer完整identity，复用同时核manifest及plan analyzer；生产orchestration与frozen_source_replay均在verify_source_chunking传model_bundle_path，进一步将保存analyzer与当前Stanza identity精确比较，不运行推理/写入。单独省略model_bundle_path的verify只证明保存链自洽，不能冒称核对当前本地feature；它不是本次样片/生产编排使用的路径。

两类结构正反例、精确mapping、完整离线及持久日志后，最终freeze新comparison-v8与v7比较、全97复审，消除明确功能核残片后才讨论实验样片。保留所有旧/失败候选，不把轻微合法PP取舍继续扩为无限规则，也不提前调用provider/ASR/新渲染。


2026-11-15该adapter-only两core已完成：保护identity为`minimal-np-pp-quantity-aux-marker-inversion-scope-predicate.v6`、ranking为`typed-constituency-relations.v9`，domain/policy typed v7、有序字段、阈值精确不变；相对comparison-v7的201份source清单相同，只有adapter与模块指南hash变化。本轮合并定向332 passed（0.81s）、稳定完整2848 passed / 7 skipped（13.24s）、diff检查通过，7项source/tests指纹前后不变。持久`predicate-core-validation-v1/full_pytest.log` SHA-256 `b412a07347fab750f9a8d5ff2be5f1445366ed1d109eafc2800a89a1f29050d5`，`validation.json` SHA-256 `a105d2274b12fe5878e3a74ce0a4095b1b49b49dc38f3b035e12f648cfa2be4e`。97句只读诊断精确mapping/public plan通过、旧保护及relations/spans/trigger相同，仅增加两reason共9个最小核、s18/s60分组改变；它不是正式实验或质量通过。源码/测试已finalfreeze交独占comparison-v8；`related|to`、`say|five`及末端`in a business`780ms残余如实保留，不追加规则。

2026-11-15负责人独立完整2848 passed / 7 skipped（12.91s），持久`predicate-core-validation-v1/root_full_pytest.log`及diff检查通过；已静态核两core无范围外改动。comparison-v8已实际启动，source/tests保持冻结；下一ADJP→PP软附着仅待实验后另行裁决，尚未授权实施/落计划。

2026-11-15 comparison-v8已实际exit0并明确释放source/tests barrier，evidence SHA-256 `4b0ca013a5c794de2ddc4431e8099c5c447e1dae77db9efe58d0939644540b0d`；source/code保护通过、新84仍165 cue，但短cue由5至6、shortfall增加54ms、warning由103至105。自动指标只供披露，不据此定胜；全部变化已交负责人/独立复审，整体源语仍未通过，不放provider/ASR/新渲染。


### 2026-11-15正式授权的单一ADJP→PP soft片（comparison-v9）

v8已实际exit0/barrier释放，负责人有限认可两core实现，但s18 `related|to`仍未过；s60 `say|five`与末端`in a business`780ms（真实短warning）明确保留取舍，本片不追VP-owned PP、词表或其它规则。先落本计划，再由适配器作者唯一编码：仅同一ADJP内，直接可见JJ/JJR/JJS head后直接PP的beforePP，加`attachment.adjectival`一般结构soft；不跨comma/CC/clause/PRN、不从深ADJP或其它祖先借head。VP/NP-owned PP、无adj头为负例；不增加hard保护、不删候选，长PP因预算仍可切。

domain作者唯一新增该一般tag映射，并将policy/ranking升级typed v8；US有序SCORE_FIELDS、阈值、源词/时间不变。适配器独立升级feature身份，模型/mapping不变。补纯soft、强标签优先、独立穷举oracle及身份测试；合并定向、完整离线/持久日志后共同freeze新comparison-v9，80/84×旧新、4消融、全97复审并列出所有退化。若无新严重退化，目标是负责人决定是否放行实验样片与最终稿审查，不宣称全局/出版质量已通过；当前provider/ASR/新渲染仍禁，旧资产/失败全部保留。

2026-11-15 v9 domain最小映射/身份已落盘，137项domain/segmentation定向通过（0.87s）：`attachment.adjectival`一般结构、强关系仍优先、无标签不词面猜测、长附着容量可切，并加入独立cut-interaction穷举oracle全部reading/rhythm组合。policy为`english-typed-cue-dp.v8`，ranking为`typed-cut-anchor-local-units-adjectival-short-syntax-ordinary2-cps-count-pause-rhythm-headroom-offset.v8`，SCORE_FIELDS及阈值未改。此为中间定向验证，待adapter/合并完整离线与独立v9，不提前宣称语义通过。

2026-11-15 v9单一ADJP→PP soft已合并稳定验证：361 passed（0.93s）、完整2873 passed / 7 skipped（13.39s），负责人独立2873 / 7（13.00s）及diff检查绿。持久`adjectival-validation-v1/full_pytest.log` SHA-256 `6199efff5bf77b475f8848ee4f0e85b8f66ded0a2cd12ca852fabed512adbb18`、`validation.json` SHA-256 `3e2018cb135d04e1f5dccdee97957b1cae5076744d1efcfe4179eb3c2e357bc8`与`root_full_pytest.log`；8项source/tests前后指纹不变，201份source清单与v8相同，仅adapter/domain/policy/Guide四个允许hash变化。policy精确只变version/ranking两项，US字段/阈值不变；v7/84同容量旧manifest复用零写冲突测试通过。最终Guide `c4ef08bbff5a42c728c79f33735d92fee7b41b1e2da6f144bcb16b6882d2d09e`、adapter `30515a23d2c9f95bbd2f73b6226e698879a03c91e70040160677182053e9db0b`、专用test `197257aea373ae98ca8b73bded83d51f1eb8536cf2a3ba8c88256409865f4659`已共同freeze交独占comparison-v9。97句只读仅s18分组变、165 cue，hard/spans/trigger相同；不是正式v9或质量放行。负责人静态验收范围后要求不再新开生产规则片，待v9实际exit/独审才有限决定真实样片；s60已披露warning不藏。

2026-11-15 comparison-v9已实际exit0，evidence SHA-256 `3635a6031c6657a8d346d6c416f71522920f6bf310945b70ef5d15a0494cfa0d`已实际核hash；old80精确165、old84 160、新84 165，source/code保护通过。另独立逐字段核v8→v9新84：除s18外其余96句chunk记录精确相同，词ID/顺序、hard/media/trigger/mapping/model不变，policy仅version/ranking与analyzer ranking预期变化。独立v9复审`independent-source-review-v9/review.json` SHA-256 `4aa7e5b039eb617611be578f56b9f2d0dd561f82a723ae7aa9b15b0d91d054dd`：对v8为1胜/96平/0负；对旧80为15/81/1，对旧84为14/82/1，s60仍旧更好。负责人有限认可本轮实现及开发集取舍，不等于全局或出版质量通过。只正式放行prepared新根实际source_chunking，先证真实模型plan精确等cached v9；provider/ASR/新渲染仍禁，下一步须等实际source证明及独审意见后另行放行。

2026-11-15新根`output/orchestration-integration/NB12-20261113-frozen-source-v1/cnbc_2000_morning-ch6-7/`已实际运行本地Stanza source_chunking：46次analyzer、165 chunks；`actual-source-plan-proof-v1/actual_vs_reference.json` SHA-256 `2a9bd5af79fff1b28d878935af71871690a26392d254c46cb57aaf5ab443bc3f`已读核complete_plan_exact及9项字段全true（含policy/analyzer/词ID词时/保护/media），等于cached v9。14份冻结输入、NB09原库存及运行时201份source不变；只读source verifier通过，provider/ASR/对齐/render调用均0。此为真实模型与缓存实现一致证明，不是新的翻译或成片；初译/编辑尚待负责人单独授权。按负责人要求继续冻结src及模块指南，后续最终状态只在明确验收后doc-only窗口同步，不混入算法身份。

2026-11-15负责人独立复算actual source完整9字段JSON精确等v9（实际source SHA-256 `61edf1126faa72a49c0f17646a66e78bbc6f21007c3ac8f6386377f8434a9e83`），正式授权C在同一prepared新根仅执行translation＋bilingual_postprocessing，到权威最终稿即停，不导出SRT或render。恢复先核checkpoint/账本以免重复，不改默认provider/20项术语/每批既有3次持久额度，失败调用数未知须保留未知，不按零报告。本次恢复查盘尚无新最终稿，不能预签字；等C实际全97材料后独立审读并由负责人决定下一阶段。srcAGENTS/source/tests持续冻结至最终明确doc-only同步窗口；保留所有旧资产/失败，无新生产编码。

2026-11-15真实初译/编辑的正常`require_escalated`启动被auto-review在CreateProcess前拒绝：尚缺用户明确授权将源载荷发送给外部已认证Codex提供方。没有创建provider进程、发请求、checkpoint或最终稿，源与新根保持不变；不换沙箱/间接命令绕过拒绝。已向负责人报告并待取得明确授权，当前停在实际source精确证明之后，不能将‘已授权管线阶段’写成‘已实际生成’，最终97句审读尚无新稿可开展。

2026-11-15用户已明确允许将本次英文正文/词时间/上下文/术语/初译发送给已登录的Codex服务，不发送视频或音频。负责人据此让C按原命令、正常`require_escalated`重试既有translation＋postprocessing；新根、默认provider及3次持久额度不变，不绕过审查。此前CreateProcess前拒绝记录保留。此次为明确授权，不是provider已调用、最终稿已生成或质量通过；待C实际结果/97句材料后独立审读，SRT/render尚未放行，srcGuide/source/tests继续冻结。

2026-11-15原`require_escalated`已正常获准，C实际启动同新根的`bilingual_postprocessing`目标（session24168，依次含translation），未换provider/客户端或绕过审查。运行前14份输入及source精确不变、无checkpoint。此时仅确认进程已启动，尚未完成，provider调用/usage及最终稿以真实运行证据为准；不提前写成功或开始最终97句质量签认，SRT/render仍未放行，源码/测试/模块指南继续冻结。


### 2026-11-15真实最终稿与独立全97文本审查（仅诊断候选）

正常获准的真实translation＋postprocessing已exit0：初译4calls/4requests，编辑10calls/10窗口均首请求结构采纳；最终166 cue/173条warning，权威稿SHA-256 `36721b9d5686438f3522c5301ee9e1408ff5ff2c08ee1d8ba6d9171ea5ed274f`。source公开复用0写，ASR/对齐/encode均0；结构采纳不代表语义通过。负责人独立全读166cue/97句并实际`--reuse`三阶段全reused、0 provider/analyzer/writes、正文/checkpoint不变，receipt `84211f2732ba45a9b47b7c38515d08e8`。

独立双语审读`independent-final-bilingual-review-v1/review.json` SHA-256 `78821edd91be1359e654b607887d7e0ec86a8fd6cf042daabe0b19892733b8e7`及`review.md` SHA-256 `b6a6e4861269773d3cd519db78c66926030380629d7b2ca607ea0bbccce23c75`已逐97列读核，输入hash前后不变；A另有全97英文/双语报告`independent-final-source-bilingual-review-v1/review.json` SHA-256 `2a44bd0fdf96b1b580d3d95abcc3a78b2e789a8c8a0a62beba3b42e0f9cf8132`。s16四屏/s18三屏/s88三屏保好；s60编辑已把say/five重归同cue且最后一屏变1740ms，原780ms是source旧残余，不冒称final仍780。

文本结论明确NOT PASSED整体同步/出版质量：c69中文每天提前到246477ms起的前屏，源per day到250519ms/下一屏，提前4042ms；c66/c69初译每份8盎司被编辑成8盎司装，有计量口径精度退化风险。c61本屏I would未显式我会但前c59已有我仍会，列原偏好部分未满足而非整句漏译；c46中文口头重起略机械。负责人追加c10您的净资产个人/经营业绩歧义与c135 razor blades译剃须刀的产品精度项，单独标注，不冒称独立发现。JET是canonical源残余，未猜改；旧c70/c114为用户允许项。真实warning分布53英文CPS/69中文长度/44短gap/5中文CPS/1英文长度/1短时，不用总量决定语义。

负责人据此仅放行诊断候选样片供用户复审，不是整体字幕/出版签字；不再改prompt、重置额度或手改权威稿。下一阶段SRT/render实际结果尚待，未看新片/未核听。生产源码/测试/srcGuide继续冻结，最终模块状态仅待明确doc-only窗口同步，所有旧/失败资产保全。


### 2026-11-15诊断候选真实烧录与复用（非质量通过）

同新根已通过公开SRT/render入口实际烧录：`output/orchestration-integration/NB12-20261113-frozen-source-v1/cnbc_2000_morning-ch6-7/video_中文字幕.mp4`，623秒/166 cue，SHA-256 `12092104058edb3b7dffa5a1dc307b6ea14c61184824e346c68d324677da4514`。权威稿/字号/代码均未改；前3阶段reused、无新provider，SRT导出及render成功、真实编码1次，ASR/对齐0。像素/字形/ASS往返/媒体技术检查均pass、0error；217条报告warning=权威173＋ASS短gap44，非217个互不相关语义缺陷，也不是语义通过。

`diagnostic-render-proof-v1/after_render.json` SHA-256 `b91a6b283023f75721ff07b126e3ed939a90303a709301ba23518a7fa87761e7`已实际读核；同/新进程五阶段公开复用证据SHA-256 `d67621476135909a0bbca017971e31e7c6e3806b71bad5c3126b4c24c6e3d841`，全部reused、0provider/analyzer/encoding/阶段改写、checkpoint不变。音轨使用copy，源/出片AAC packet SHA-256精确一致`30349dbba520c600c4657288c5cf05de05d66e7b37856ccc10f98f63cc82dd68`；这是流一致证据，不是核听。14输入/NB09旧库存/渲染前新根既有文件/201source均不变。已生成18抽帧/3张原尺寸tile供负责人目视，实际观看/核听范围尚待负责人记录；本子agent仅全量文本审读，未观看新片。

成片仍明确为诊断候选供用户复审，c69每天提前4042ms及精度残余未改，不能改称最终合格字幕或出版签字。不再变prompt/重置额度/手改稿，旧/失败资产全部保留，srcGuide等待最终明确doc-only同步窗口。


### 2026-11-15负责人目视范围与验收后doc-only收尾

负责人实际view三张原像素tile共18帧，并额外看frame018原640×360，覆盖c4/5/6、c27～30、c34/35、c69/70、c101～104、c152、c161/162；这些帧未见裁切/缺字/tofu/中英实际重叠。不是全166cue目视、连续播放或核听。新明确布局残余：c162中文`其实是几乎所有企业——都有很不错的护城河，`在plan `chinese_break_offsets=[10]`处断为`其实是几乎所有企业—` / `—都有很不错的护城河，`，原帧已见；归rendering视觉换行，本轮不修。profile SHA-256 `3f046085c35d808ee228ce7bc03840d399dbc2e5b0d78409eebdd99232ae20fc`与NB09精确相同，未改字号或样式。负责人观察独立记录`independent-final-bilingual-review-v1/root_visual_addendum.json` SHA-256 `658eb37ab1e7891b200f9e568cd181afe0be6e1f1239e03c6d0641786e9d5772`，明确为root观察而非本子agent目视；原双语独立分级/报告保持不变。

负责人在所有C proof/audit/audio/frames完成后明确开放最终doc-only窗口，仅更新srt_processing、translation、subtitle_rendering模块指南最新短段及根/ADR/NB12事实；这是验收后文档状态同步，不回签冻结201source快照/manifest，不动生产.py、测试、模型、权威稿、prompt、术语表或样式。更新前实际143份生产Python与comparison-v9冻结字节完全一致，实际video SHA仍`12092104058edb3b7dffa5a1dc307b6ea14c61184824e346c68d324677da4514`。最终结论为**实现＋诊断样片技术交付；整体语义/出版NOT PASSED，未核听**。无新规则片、不commit/push/删除，所有失败与旧资产保留；负责人将作最后全套及视频/代码不变量复核后交用户诊断视频。
