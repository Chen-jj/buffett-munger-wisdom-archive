# SP-13 — 候选v3：中文停顿单元与双语联合规划

- **Status:** accepted（候选实现技术验收；质量与真实样本由SP-15另验）
- **Owner:** planner 子开发agent；负责人只拆解、审查、验收，不直接编码
- **Depends on:** SP-12、2026-10-23用户偏好与澄清；和SP-14先冻结接口
- **Depended on by:** SP-15

## 用户已确认的规则

1. 中文只允许在停顿标点及句末切cue；逗号是可选断点，不是必须切。S17的“非逗号”是笔误。
2. 中文仍一逻辑行，16单位从硬容量改为软目标；Latin word计1的v2口径不变。逻辑一行不等于像素能放下。
3. 7000ms仅是cue显示时长告警目标，不是句长限制；**不另设10秒或其他硬时长上限**。仍受源锚点、媒体末尾、非重叠与最多500ms延长约束。
4. 9 CPS继续是告警目标，不能成为强拆完整语块的理由；英文仍实际最多2行、每行42的硬预算。
5. S34优先中文自然分块，不要求逐cue中英语义严格一致；不据此重译、重排或改源时间。
6. S19可独立一cue或逗号处两cue；S20独立一cue，不偷开头并入S18，不与S19强行合并。

## 实现范围与约束

- 负责domain规则、边界、planner和对应规则/边界/planner测试。先提交精确通用算法/代价供负责人审查，再编码。
- 中文停顿单元引导，英文word边界联合重选；不能先固定中文再用错误英文范围机械拼接（S6原c10+c11英文86，不等于完整条件的自然范围）。
- 英文gap仅弱质量信号，防止And/But/because/the悬挂和以词间空隙压过合理分句。不宣称机械比例等同语义对齐。
- 限制跨句偷头；短cue救援如跨下一句，须完整消费下一短句。section/speaker/null/gap硬规则不放宽。
- 逗号可合并，分号强停顿优先；精确代价、停顿标点集合、引号闭合处理与失败行为必须明确记录。
- 无合法路径应受控失败并指出限制，不能偷偷退回中文任意字符切分。无句ID/样本专用硬编码。
- 不重跑上游、不改字/词序/词时间、不覆盖旧正式输出或冻结v2/agent参考，不删除、不commit；不触碰translation已有外部改动。

## 验证

- 泛化测试：标点后含闭引号、Latin/数字/省略号保护、逗号可合并、分号拆分、无标点且英文预算不可满足时受控失败。
- 中文>16、时长>7秒、CPS>9仍可发布并有对应告警；保留英文word/实际两行packing硬门禁、完整覆盖/时间/媒体/说话人/section门禁。
- 以用户逐句反馈为允许变体集合，不固定cue编号；未达语义选择如实报告，不靠破坏完整性让测试过关。
- agent跑定向测试并交差异/命令/结果；负责人独立复验后才accepted，SP-15负责全97句与真实工件验收。

## 实施/验收记录

### 已批准并落地的候选算法（2026-10-23，待负责人复验）

profile为`netflix-audio-gap.zh-priority.v3`，算法`bilingual-pause-dp.v3`，边界
`chinese-pause-closed.v3`，成本`d39-pause-rhythm-rational.v3`；计数仍为
`unicode14-latin-word.v2`，词典身份不变。v3仅把旧profile中的中文硬容量/时长硬上限字段
改为`chinese_target_half_units=32`、`target_duration_ms=7000`；旧v1/v2精确shape/hash由SP-14保留。
没有别名/默认注入，也没有新增10秒或其他硬时长上限。plan/analyze/validate入口不变。

**中文边界：**纯函数`chinese_pause_boundaries(text)`返回0、len及内部合法停顿组结束offset；
`hard_chinese_boundaries`保持同义入口。允许中文/ASCII逗号、顿号、分号、冒号、句号/问号/
叹号、完整省略号组、em/en dash及重复hyphen组；单hyphen、Latin词内、组合序列、数字/Latin
内部句点及数字内部comma/colon不可切。闭引号/右括号、空格与停顿标点可以交错连续出现，
整组归前块且只暴露最终offset，例如`甲说“第一；”，`不会把外逗号遗留给下一cue。
固定closer集合为`" ' ” ’ 」 』 ） ) ] } 】 》 〉`，无运行时Unicode数据库分类。
`chinese_semicolon_boundaries(text)`保留整组中的强分号证据，末尾外逗号不掩盖分号。
分词/专名/数字单位仍只是局部质量证据，不能删除已经合法的停顿断点；不再提供非标点fallback。

**完整路径九层字典序（均越小越好）：**

|层|累计成本|
|---|---|
|1|cue内部跨过的中文分号停顿数，分号在跨句fragment末尾也计；无法切时可软保留|
|2|局部词/专名/数字单位/紧密短语断裂，或英文未加标点function-word悬挂数|
|3|使用同一时间函数调整后仍<834ms的cue数|
|4|跨原句边界数|
|5|中文节奏`ΣR(h)`，`R(h)=1+(2*max(0,h−T)/T)^2`，`T=32`半单位|
|6|英文内部无标点普通word切口数；达到250ms word-gap仍同计，不让gap压过节奏|
|7|各结束点中英累计比例偏差的精确Fraction之和|
|8|英文内部切口word-gap弱罚`max(0,250−gap_ms)`，250来自profile|
|9|完整路径断点序列，非仅比较最后一条edge|

第5层自带每cue切换成本1，不另设min-cue目标；20/23单位整句成本1.25/1.765625，均小于
两块各<=16的成本2，而28单位成本3.25可输给17+11的2.015625。这是明确、固定、版本化的
软折衷，不是16或24的新硬门禁：无停顿/源word不足时仍允许远超目标的完整一cue并告警。
9CPS和7秒完全不进入DP成本，避免把软告警重新变成高优先强拆；CPS仍可用合法空隙有限延长。
英文自然标点等级主要记录为break方法，不为semicolon/comma另加隐含代价。

function-word表固定为`and/or/but/because/if/although/while/the/a/an/of/to/for/with/from/by`，
仅惩罚**源句内部**无标点word切口，完整utterance结尾或`And,`/`to.`不因该表误判为悬挂。
这与专名/词典等均是启发式，不保证句法或语义；表误判仍可走高代价合法路径。

**跨句只作过短救援：**第一fragment原始时长<834ms，且把该fragment单独交同一时间函数、
以下一源词start作边界调整后仍too-short，才允许跨句；所有后继fragment必须完整消费其源句
全部word和全部中文，不允许偷下一句前缀。后继不必也<834ms，因此可救援短尾+完整900ms句。
每原始句间gap<500ms、单section、完整known-speaker集合至多一类、null保留、实际英文2×42
布局等硬门禁不变。能合法延长至834ms的800ms尾不跨句；9CPS超标本身不再赋予合并资格。
第3/4层保证只有消除最终过短才值得跨句，不为降低R把健康独立句吞并。

**告警与失败：**新增`reading.chinese_length`的observed为`half_units/target_half_units`，
`timing.target_duration`为最终显示`duration_ms/target_duration_ms`；均严格大于目标才warning，
不加summary schema字段。`planning.strong_pause_retained`含cue/sentence定位及`semicolon_count`。
复用沿用重算报告链，不能篡改warning自证通过。无完整路径时报`planning_failed`并明确
Chinese pause-only/English 2×42限制，不丢字/改序/偷偷退回任意字符切分。

**验证进度：**开发侧规则/边界/planner定向184 passed；保留并更新独立完整路径暴力oracle、
候选逆序扰动和非贪心反例，增加4/5词且EN>84、多停顿、分号/逗号及无路径小图。泛化测试覆盖
闭引号外逗号、无标点英文不可布局、超16/7秒/9CPS可发布、完整next救援与合法延长不跨句、
function-word完整utterance，以及原speaker/null/section/gap/时间/篡改/覆盖门禁。
真实97句生成/偏好满足程度由SP-15独立验证，未据样本再调权；不承诺机械规则重现agent语义。

### 负责人技术验收（2026-10-23）

已审查纯停顿组/闭引号、九层成本、无中文/时长硬帽、完整后句短尾救援、独立oracle与泛化回归。
负责人完整离线复验 **1395 passed / 5 deselected（5.31s）**，diff check通过。
冻结规则/边界/planner SHA分别为`9882f29321e05c2fb5f97818984f1c32db0f99900ca7fb4449277402c97657aa`、
`62fbc18b7b1dd5e1a7c3e7a5e17edf5cc05c1b7036b261108c13272af4d977cc`、
`9ab4888887dec3907c360006c653ef7dee926401fed6785cb95d520d0df06b2c`。
profile SHA为`dcde464d9e1ae536803b9da78abaf01bca3e51c61a977330cc4c58813f090a27`。
接受进入隔离真实生成，不等同于用户偏好或出版质量已通过；看到样本后不得私调本版。
