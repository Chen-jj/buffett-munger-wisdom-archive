# NB-10 用户逐 cue 反馈溯源

> 2026-11-17归档说明：反馈溯源/术语交付已完成；不表示全部反馈或候选P1～P4已解决，后续质量工作仍在NB-12。 原路径`docs/tasks/NB-10-cue-feedback-diagnosis.md`；原状态、历史不commit/push约束及验证结果属于当时记录。后续入口：[NB-12](../../tasks/NB-12-chunking-quality-iteration.md) / [ADR-0013](../../decisions/0013-typed-chunking-quality-and-regression.md)。

状态：2026-11-08，18项诊断及两个术语补充完成；其他算法/稿件问题尚未修正。用户本轮要求解释结果，不擅自重生成翻译或覆盖样片。

## 切片与验收

1. 负责人只读核对当前权威稿、初分块、初译、编辑账本、冻结独立稿和官网逐字稿。
   - 验证：逐项区分确定性规则、模型实际输出与不可观察的选择理由；不把结构合格写成编辑质量合格。
2. translation 子 agent 加入用户明确指定的两个术语：`underlying value` →「内在价值」、`net worth` →「净资产」。
   - 仅改默认术语数据、必要单元测试及模块实现说明；不猜改 JET，不调用 provider，不改现有产物。
   - 验证：真实默认表加载、大小写/词边界匹配；初译及编辑仍使用既有共用术语传递路径，不为两个数据项新增私有工作流集成入口；完整离线 pytest。
3. 负责人验收术语差异并说明现有样片仍为变更前生成；记录其他 16 项诊断，不冒称算法已修复。

## 当前证据

- 工作区：`/Users/drchan/Codebase/buffett-munger-wisdom-archive/output/orchestration-integration/NB09-20261107-iteration-v2/cnbc_2000_morning-ch6-7`。
- 权威稿 SHA-256：`06bbcea7a2af4e1c92753676037d221c94ffd0c7808fc4360b881539e0d404d9`。
- 用户反馈表明：NB-09 的“整体同档”不能代表逐 cue 达到独立编辑稿标准。旧验收记录保留为当时判断，本轮不沿用其质量结论。
- 当前批次账本不返回模型的切分理由；可以核验输入、输出与接纳规则，不能声称知道模型内部理由。

## 验证结果

- 子agent定向54 passed；负责人首次完整离线2449 passed / 7 skipped（11.77s）。验收发现新增测试直接使用私有编辑payload，已要求缩减为默认资源/匹配测试，不保留新增私有工作流调用；最终完整复验见下。
- 新测试：`tests/orchestration/integration/offline/translation/test_translation_prompt.py::test_default_glossary_matches_underlying_value_and_net_worth`。实际加载默认表，验证两个目标值、大小写与词边界负例；不是真实模型翻译质量验证。
- 最终负责人复验：`.venv/bin/python -m pytest tests/ -q` → **2449 passed / 7 skipped（11.83s）**；`git diff --check`无输出、退出0。最终检查默认表19项；source alignment/chunks、initial translation、final draft、bilingual SRT/ASS和成片7份SHA-256均与NB-09记录相同，未重生成或改写这些产物。
- 生产改动仅为术语数据；没有算法、prompt或契约改动，不需伪造新ADR决策。既有样片内容/hash不应变化；新术语会改变后续生成身份，不改写旧manifest冒称复用。

## 确定性算法复算

负责人以当前 canonical words 和锁定本地Stanza模型，只读重放s4/s16/s18/s29/s33/s39/s61/s74/s88/s94；未调用ASR/LLM或发布工件。
Stanza返回句法树，**本仓库适配器**为边界赋代价（小为优），不是Stanza的置信度。
当前先尝试整句纯逗号的合规分组；失败则整句Stanza，不是固定逗号后只对超长段调用Stanza。
动态规划顺序为超短块数、边界代价之和、块数、负gap之和、位置。因此合法但不自然的断点可以胜出；最终编辑也可保留初稿，并未逐项纠正。

| 用户项 | 可核验的当前结果、来源与结论 |
|---|---|
| 1 c4–5 | 当前 `net worth of / one-half of one percent.`，中文`增幅为 / 0.5%。`；独立稿`net worth / of one-half of one percent.`。两切点代价均2、块数相同，现切点gap181ms胜过80ms；两方案都在80字符内。初译不跨屏提前数字，但没有把“增幅为”留在数字屏，编辑亦未纠正。 |
| 2 c29 | 当前`a number / that were down, And...`。`a number`后代价0，逗号后1；独立稿完整`I know that there were a number that were down,`仅47字符/3601ms，并非限额不能容纳。 |
| 3 c31 | 初译即`假如我活得够久——我们会遇到不少下跌的年份。`，最终保留破折号；不是导出程序换标点。官网把该段视为插入语，canonical英文是逗号；中文如此排插入语并非必需。 |
| 4 c33 | 旧术语表有intrinsic value但没有underlying value，初译及最终自由译为`基础价值`。新增用户指定`内在价值`；尚未重生成。 |
| 5 s18 | 当前`...intrinsic value / a few times, but...`，中文却已在前屏表达`有几次`。独立三组为`The stock has gone up and down / in ways that are not related to intrinsic value a few times, / but that is totally a fluke.`。原切点代价0，独立稿两个切点代价2+1；这是句法评分不足且模型跨屏提前量词，不能称为合格的逐屏对应。`in ways that`不是必须永不拆的固定词条。 |
| 6 c51 | 当前`it's interesting, I called I / their soft drink business...`。独立3组`it's interesting, / I called I their soft drink business / and their razor...`为41/36/52字符；两方案边界总代价均2，少块方案获选。直接把I called I塞给原下屏会达89字符，但重切下屏即可，不是无法解决。 |
| 7 s33 | 初译c61有`我会称为`，最终变成`称为`；即完整I would没有在本屏明确译出。不能证明模型内部理由；提示词反对口误变重复断言可能影响选择。独立稿在`inevitable,`后切成42/36字符、1941/4152ms，两屏均可保留完整“我会称它们为…”。 |
| 8 c68 | 核对当前so确在c68末：`Berkshire, so / over 80 million...`。so后代价0，前方逗号1。按“应归下屏，不应挂在本屏末”理解；应与后续结果相连，不建议另造单独so屏。 |
| 9 c70 | 当前`are being consumed by people for / where the economic benefit...`，中文为`也就是正被人们饮用，而 / 相关经济利益...`。for后代价0且gap540ms，无介词+口语where从句保护；“而”是模型接续用语，不是for必须如此翻译。移for到下屏后英文58字符/3201ms，可行。 |
| 10 net worth | 用户所指短语位于s47/c81（不是当前c47）；当前已译`净资产`但无固定术语，新表已补，不代表旧稿重生成。 |
| 11 c93–94 | 官网实际是`[Berkshire reinsurance chief] Ajit Jain`，并非JET；raw ASR/canonical为`a JET`。融合把含说明与名字的ot839–843五词run判为超过局部声学验证限额而排除，JET保持asr_only。不能未核听就断定JET对应姓Jain或伪造两个词锚。全句74字符/7266ms，整屏会产生7秒warning；在`In there,`后切，开头1101ms，其余可保持完整。最终在JET后切是编辑改变了原`In there, / you described...`，模型未留理由，1241ms停顿仅是可见相关条件，不是确定动机。c96完整保留as important as是实际改善。 |
| 12 c104 | 源文`And some businesses that's very it's impossible to figure`是未完句接重起。初译`这就很……`被最终编辑改成`情况很……`；“情况”是补出的衔接词，不是英文存在situation，也非丢了一整段内容。当前中文生硬，应处理口语重起，不能捏造very后未说的形容词。 |
| 13 c105–106 | 当前`figure and then / we just...`，两个候选断点代价均0、块数不变，现gap40ms胜过在and前20ms。合理方案`figure / and then we just...`为41/51字符；纯gap择优把连接语挂错屏。 |
| 14 c108 | 初稿2块被最终编辑合成108字符/4861ms一屏，明确记录英文长度warning；不是source chunking没有执行。模型可改分组且正常80不是最终硬门禁。独立稿`losing a billion dollars / if there were an earthquake...`为59/48字符，可切，不必为保全条件强行一屏。 |
| 15 c114 | 初稿`In other words, / we want to think...`被最终编辑合并为89字符并报warning。恢复逗号切点可行，开头841ms刚过834ms下限，之后英文73字符；代价是短转场屏及60ms原间隔（第二轮复核纠正此前20ms误记），不是不能切。 |
| 16 c125 | c124当前6783ms；把voluntarily直接并入变7604ms，不是容量问题。首轮7秒硬条件确实拒绝这种局部移动；最终可保留warning或重排更早的切点，例如独立稿在intentionally后切。属于真实取舍，不宜和纯坏断点混为一谈。 |
| 17 c149 | 当前`and the ability / to keep its width...`，前切点代价0；独立稿`that moat / and the ability to keep its width...`前切点代价2。没有保护名词ability与不定式补语；独立方案33/72/45字符、4321/4901/5661ms可行。当前中文`其能力 / 也就是...能力`还重复/绕口，是坏源切点加编辑未修正。 |
| 18 s94 | 当前c159–160 `...virtually all of our businesses have / pretty darn good moats, and...`。现边界代价3，独立3屏边界2+1同样为3，少一屏获选；现800ms停顿也是可见条件。独立稿30/60/44字符更好展示all→virtually all的口头收窄和后续并列句。 |

结论：以上不是SRT/ASS导出或显示换行制造的问题。主要是源语评分对某些语义依赖估计不足、最终编辑保留坏初稿或主动过度合并，以及逐屏翻译/口语处理缺陷。结构校验通过并不能证明这些质量项目通过；本轮只修术语，不宣称其余问题已解决。

## 第二轮追问（2026-11-08）

- 负责人核对通用规则的适用条件、反例和验证方法；本轮回答不承诺未经实测的“通篇更优、零副作用”，不擅自上线所有算法建议。
- 用户明确认可c70的540ms停顿切点及c114短cue合并；不把这两处继续当作必改项。
- 子agent只读调查CNBC方括号类别、官方token过滤及Ajit Jain恢复条件，不直接把所有`[]`内容删除或伪造词时间。
- translation子agent新增官网明确全名`Ajit Jain`→「阿吉特·贾恩」，验证默认表匹配；不添加`JET`别名、不猜改canonical或现有样片。

### 复核结果与边界

- c31当前最终中文仍为`假如我活得够久——我们会有很多下跌的年份。`，渲染未替换为逗号；英文正文使用逗号和中文模型重新选用破折号是两回事。
- c108合并不是机械短cue救援：初稿34/73字符、1460/3361ms；c114初稿15/73字符、841/4243ms。两者均在同一全量编辑生成权限内由模型选择合并，不存在“仅短cue才允许合并”的程序条件。
- c149选中`ability / to`间60ms，未用`moat / and`间1011ms。s88另有`So / we`921ms及`primary / criterion`2041ms，说明长gap并不自动等于好的切点；当前原始gap仅在短块数、句法代价和cue数均同分后才起作用。
- s94当前2屏与独立3屏均无超短；当前边界总代价3，独立方案2+1=3；下一项cue数2胜3，比较尚未轮到800ms gap即已决胜。需要区分严重语法依赖中断与普通切点，不能只继续调同一个代价和。
- CNBC角色插注`[Berkshire reinsurance chief]`未进舞台说明allowlist，进入正文token并连姓名组成5词official-only run；上限3，声学验证尚未调用即排除。完整23章另含`[for]`、`Ajit [Jain]`、`199[9]`，不能全局删括号内容或一律视作已发音；原注记应保留并分型。
- 去角色插注只解除长度门槛；现有official-only恢复是插入，不会抑制ASR-only的a/JET。名字纠错仍须明确替换证据、真实声学锚和来源映射，不能添加a→Ajit/JET→Jain来借旧时间；目前仍未核听。

### 候选改进切片（本轮未实施，不冒称已接受或全篇更优）

| 切片 | 依赖 | 候选逻辑与验证 |
|---|---|---|
| P1 依赖边界与语块质量 | 当前源词/完整句 | 区分完整从句、名词+关系从句、谓词+补语、名词+不定式、连接语归属；评价两边语块是否残缺，不再只依赖每边界0–3总和与少块择优。保护、容量无解时保留可选弱点，不能无限硬保护整句。重放全97句及反例；不只验证指定cue。 |
| P2 有意义停顿 | P1 | 微小gap无奖励、较大gap分档有界；候选阈值是工程试验，不写成行业规范。验证20/40ms不主导、540ms/1011ms仍有影响、长gap不强切数量/姓名/基础名词短语；c70当前切法保留为允许结果。 |
| P3 现有编辑生成内的局部重整 | P1/P2 | 孤立依附尾片允许移动相邻边界而非只全并；口语重起后的完整表态保留；已有合理边界不为整句中文顺读而过度合并。使用既有一次编辑及持久额度，不加语义评分器、发布门禁或每warning新请求。问答/强调数字/长停顿为反例；c114合并为允许结果；实际翻译与样片仍需全片人工/agent验收。 |
| P4 CNBC注记与姓名来源 | 注记类别及声学证据 | 非口述角色说明不参与声学匹配；补词、姓名补充、词内数字补写分别处理并保留来源。姓名纠错与插入缺词分开，不伪造词时。验证全23章括号类别及ASR词来源恰好覆盖；不因能强制对齐就宣称姓名被说出。 |

“更好”需分层验证：确定性保证源词/顺序/来源链与声学锚不被错误改写；非触发句分组是否不变、全97句有无退步、口语/问答/数字反例及新样本均需实测。不能从少数正例推出任意输入零副作用。所有候选仍未上线。

### 本轮实际交付与验证

- 默认术语表新增`Ajit Jain`→「阿吉特·贾恩」，现20项；新增测试`test_default_glossary_matches_ajit_jain_without_guessing_asr_aliases`，覆盖全名大小写/所有格和JET、a JET、Jain及子串负例。
- 子agent定向55 passed；负责人 `.venv/bin/python -m pytest tests/ -q` → **2450 passed / 7 skipped（11.17s）**，`git diff --check`通过。未改算法/prompt或现有样片；7份关键工件hash仍与前轮相同。没有运行真实provider、ASR、aligner或烧录；没有commit/push或删除。
