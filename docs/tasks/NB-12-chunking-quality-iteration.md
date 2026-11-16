# NB-12 源语切分评价改良、保好回归与新根样片

- 日期：2026-11-13（Asia/Shanghai）；2026-11-15核对v7证据并授权adapter-only v8。
- 状态：**v9实现/开发集有限取舍及真实source精确证明已验；真实166cue最终稿已全97句独审，整体语义同步/出版质量未通过。当前仅放行诊断候选样片供用户复审，不改稿/重置额度，真实诊断渲染及五阶段复用已留证，负责人仅目视18抽帧，未全面观看/核听；双破折号视觉断行残余披露不修。**
- 行为依据：[ADR-0013](../decisions/0013-typed-chunking-quality-and-regression.md)，总入口仍是[ADR-0008](../archive/decisions/0008-local-orchestration-and-integration-tests.md)。
- 角色：负责人只拆解/调度/读diff/验收/回归，不编写生产或测试代码；编码子agent实施，独立子agent质量复审。文档作者不因此获得编码权限。
- 保全：现有dirty改动是开工基线，不回滚、不删除任何文件/资产、不覆盖旧输出；2026-11-17用户已明确授权全部本地代码/测试/文档commit与push，由负责人执行，旧阶段禁止提交记录保留为历史。只复用校验通过的媒体/转录，**不重跑ASR/词对齐**。候选/失败/账本/样片保存在新独立根。

## 1. 开工现实与冻结证据

开工生产为80字符、逗号优先、完整句Stanza回退及v4窄幅三块整形。NB-09样片为旧术语身份，NB-10后术语共20项；不能因本轮设计就声称旧样片已改进。负责人本次实际baseline为2450 passed / 7 skipped（12.69s），不是新算法验证。用户已明确84替代80的逻辑cue容量，换行由rendering负责；本模块不处理显示换行/字号/像素，不改变既有渲染规则或新增单行门禁。

现存证据（均只读）：
- `output/orchestration-integration/NB09-20261107-iteration-v2/cnbc_2000_morning-ch6-7/`：媒体、alignment、chunks、初译、权威稿及样片。
- `output/subtitle-editorial-comparison/NB11-20261109-boundary-score-audit-v1/`：12句301边界评分、97句重放验证；未核听，不是gold。
- `output/subtitle-editorial-comparison/NB09-D2-final-review/all-97-sentences.md`及`NB08-reference-v1/`：冻结对照，允许多解，不是盲测结论。
- [NB-10](../archive/tasks/NB-10-cue-feedback-diagnosis.md)：c70/c114允许结果与源切分/最终编辑分责，不能全部当必改项。

## 2. 分阶段依赖、负责角色与验收

| 切片 | 依赖 | 子agent实施范围 | 负责人验收/放行条件 |
|---|---|---|---|
| NB12-0 文档与基线 | 无 | 仅ADR/任务/导航；源码/测试/现存资产只读 | 阅读方案；冻结首版向量/严重度及局部可分解去重，记录250ms、帧档/MAD工程初档及待验假设；快照dirty代码/模型/policy/资产hash/size/mtime/链接；完整离线实际baseline；本阶段未通过不得编码 |
| NB12-1 多解基准与实验基座 | NB12-0 | 编排集中测试/runner、固定输入/句法特征、人工标签schema、旧算法实验快照；不新增旧生产路径 | 80/84×旧新对照身份可追溯；基线重放等于现存source；保好/允许/反例/未见分组先冻结；实验0provider/0ASR/0覆盖；小型穷举oracle验证DP |
| NB12-2 有类型解析与最小保护 | NB12-0；实验依赖1 | `srt_processing`局部关系/边界特征、数量介宾漏标、精确token映射；公共字段必要时单一作者修改`archive_core` | 原树/POS证据可解释、不伪造depparse/置信度；冠词/形容词/aux-neg/姓名/数量单位/短PP保护正反例；长RC/PP可切、c70不误封；定向及完整离线 |
| NB12-3 统一DP与同目标救援 | NB12-1/2 | 删除旧逗号优先决策分支但不删文件；>84/>7秒触发；cue特征、分层罚分、有界奖励；三块/短块同目标 | 3不能被2+1抵消；同根因不重复罚；严重技术闪现处理；一阶DP只加可加cue特征；相邻节奏只报告；穷举/确定性/80-84边界/无解/救援不退化测试；完整离线 |
| NB12-4 第5轮停顿消融 | NB12-3 | 实际PTS帧档、相对gap统计及资格、封顶收益；CPS/短缺口/裕度诊断 | 微小gap同档、硬保护/强依附无奖励；MAD>=8样本/非零才启用，z初档2/3、单点总收益<=2；2秒不自动判强调；无停顿/固定帧档/固定档+MAD分别重放；不动词时/借时预算；完整离线 |
| NB12-5 第6轮节奏与全量评测 | NB12-1～4 | domain子agent接入正确二阶DP的相邻字符节奏；评测子agent只读固定输入实验、全变化对照、盲A/B人工标注汇总及消融报告 | 二阶DP对照小规模穷举oracle、比较开/关节奏；指定问题改善；新增严重缺陷0；保好/允许结果无未接受退化；所有变化/争议列出；四组容量/评分对照不混因；未见样本未参与调参；负责人及独立agent复审后才放行昂贵下游 |
| NB12-6 新根接入及84下游一致 | NB12-5 | 集中测试runner的`frozen_source_replay`五阶段adoption view；translation及导出/rendering政策/prompt身份最小适配；不添加语义门禁 | adoption view不伪称前四生产阶段fresh/reused、不扩张生产编排接口；不复制改路径manifest冒充复用；不跨模块私有import；旧输出新配置受控冲突；词时/保护/来源链不变；中文和像素不由84假定通过；定向/完整离线及fake零调用复用 |
| NB12-7 真实初译/编辑/导出/烧录 | NB12-6及负责人明确放行 | 新根真实source chunks/翻译/编辑/SRT/ASS/成片，通过公开入口与持久额度 | 按真实成本/失败/恢复记录；不重跑ASR/词对齐；保留所有失败；全97句逐阶段读稿，检查编辑是否重新破坏源切分，核中文逐屏对应与术语；不能用prompt测试冒充模型遵守 |
| NB12-8 独立成片与复用验收 | NB12-7 | 独立agent全量文本/实际画面与核听，测试代码必要补强由子agent实施 | 负责人独立审查/播放/核听，范围据实；字体/像素/媒体/PTS及声轨；同进程/独立新进程0昂贵调用/0阶段改写；保护集不变；完整离线/diff检查；更新指南/真实结论后交付 |

可并行只限冻结后不冲突的特征实现与基准构建。公共DTO、policy、同一测试文件指定唯一作者；依赖完成后再组装。不以并行节省时间为由绕过负责人阶段验收。

## 3. NB12-0负责人允许试验的首版工程假设

设计/基线已验收，首版定价与状态见ADR-0013 §5；以下不是行业或实验事实，变更须先记录决定再实验：

1. ADR-0013 §5向量及每个规则的高影响/一般结构分类；同一根因事件的确定性去重ID。
2. 极端闪现工程初档<250ms（负责人允许试验，非行业值）；正常短cue仍以834ms数量/缺口细分，覆盖249/250/833/834ms、完整问答及不可合短句。
3. 实际空帧奖励工程初档0–3无、4–8收益1、>=9收益2；仅结构适合且罚分同档比较，单点总收益封顶2。
4. `log1p(实际空帧)`中位数/MAD：完整原句全部有效gap（含零）>=8、MAD>0；z=(x−median)/MAD，初档2/3，收益0/1/2，与固定档相加后封顶2。缺PTS/不足/零MAD收益0并明示原因；第5轮实际消融后决定默认，不预先以未实现收尾。
5. 第1～5轮只报告相邻节奏；第6轮接入正确二阶DP，初档相邻字符数差绝对值总和，单cue贴顶风险用字符数平方和，均后于结构/技术/少cue及合格停顿收益；验证最优子结构及跨句救援同目标窗口。
6. 首轮未见集具体源句/话语及数据来源；如只能用当前已反复审过97句，明确没有真正holdout，不伪造新样本。

冻结后每项写入policy/测试/报告身份；阈值变更另起实验，不改旧证据和标签。

## 4. 各轮统一报告

- 输入证据：source alignment/PTS/模型/policy/特征/代码快照hash；来源绑定与实际可复用范围。
- 不变量：源词覆盖/顺序/时间/保护/section/speaker，未触发句不变，输出来源链与旧资产零变更。
- 质量：固定源单位原始严重/普通事件数、A/B胜平负、保好退化、所有新错与未定；不按候选cue数归一化藏错。
- 技术：cue数量、长度/CPS/时长超额与分布、短时缺口、实际空帧/未知帧、只读预算；源DP前/救援后分别记录。
- 消融：候选统一、保护、关系、cue特征、停顿/统计、阅读负担各自效果；四组80/84对照完整。
- 真下游：每阶段输入/输出hash、provider调用和额度、实际usage未知项、失败/恢复、正文及词锚、SRT/ASS同稿同时间。
- 最终：审核人与范围、未核听/未播放/缺帧等事实；复用与保护集；不把技术通过写为出版签字。

## 5. 验证入口与非入口

- 模块隔离测试：`.venv/bin/python -m pytest tests/srt_processing/test_source_chunking.py -q`。
- 集中离线来源/发布/复用：`tests/orchestration/integration/offline/test_source_chunking_publication.py`；新增跨层实验/新根runner归`tests/orchestration/integration/`，生产不得依赖tests。
- 每阶段完整门槛：`.venv/bin/python -m pytest tests/ -q`及`git diff --check`。
- 历史candidate/sample/projection runners已退役，不能恢复旧生产算法凑对照；`full_fresh`会跑昂贵上游，本次不直接调用它绕过“不重跑ASR”。
- 五阶段frozen_source_replay runner先dry-run/来源验证/调用预算，再由负责人放行真实翻译与烧录；具体命令及新根路径由NB12-6实际实现后记录，不编造尚不存在的入口。

## 6. 执行记录

2026-11-13：设计与基线已由负责人验收，三位子agent分工实施中，尚无通过的新试验/样片结果。负责人baseline为2450 passed / 7 skipped（12.69s），文档验证待写入；保留原任务历史与全部资产，不回填通过结论。


### 2026-11-13 domain阶段记录（尚未质量验收）

- typed内部契约由domain唯一维护，Stanza/runner分别由其他子agent独占；统一DP、局部根因计费、二阶字符节奏、原句MAD与同目标单邻居救援已落盘。
- 原triplet分支候选是统一DP候选子集，已撤下其独立择优；新测试保留保护/容量/源词/词时/技术实报护栏，验证不能用帧gap奖励赎回结构缺陷。
- 旧s47单元只有伪句法、原承诺是逗号路径不调用Stanza；现改为完整句确被调用、84与全部源锚精确保留。真实s47切法交冻结97句重放，不用无句法fake强造新gold。s9在84下整句已可容纳，不再制造旧80容量导致的短尾屏。其他旧容量边界79/80/81改为83/84/85；typed映射测试仍验证损坏/缺词/多句失败，不撤下业务断言。
- 首次完整离线：6 failed / 2492 passed / 7 skipped（12.10s），日志`/private/tmp/nb12-domain-full-first.log`，均为旧80/旧数字边界断言；保留失败，不改生产算法兼容旧形状。随后逐项最小迁移，完整复验待负责人记录。
- domain定向68 passed（0.19s）；含独立全分组枚举oracle（非调用DP评分器作oracle）、明确一阶节奏错误反例32对35、250/834边界、长依附仍可切、同根因不重复罚、0–3帧即使MAD高z仍中性、救援保持每句MAD上下文。不是全97句/未见集或真实字幕质量结论。


### 2026-11-14恢复与同cut计费修复（待负责人验收）

- 恢复先读磁盘，不假定上轮完成；scholarship已核对comparison-v1四格/四消融14文件及原证据保全，并释放src write barrier。v1当前new84为170 chunks，仅技术实验完成，不是质量通过。
- 上轮domain完整第二次日志`/private/tmp/nb12-domain-full-second.log`为2554 passed / 7 skipped（12.76s）；负责人独立复验2554 / 7（13.31s）。它们不覆盖本次新修复。
- 独立验收确认v1把同cut左侧新陈述前缀混接与右侧主谓断裂重复计费；现按实际cut汇总左右cue及边界最高严重度，仅在右cue收费一次。不同cut与flash独立计费，排序/阈值不动。
- DP state扩为(first_offset, previous_first_offset)，由上一range计算字符节奏/左cue结构；即使关闭节奏仍需上一range。政策升为typed v2，新实验必须独立comparison-v2，不覆盖v1。
- 定向75 passed（0.29s），包含same-cut=1、中间cue首尾不同cut=2、flash独立，以及spans/关系交互的独立全分组oracle；完整离线和负责人独立验收待记录。未放行真实provider/ASR/渲染，不改现存资产。


### 2026-11-14同因v2完成离线、特征修复另轮进行

- 同cut修复完整离线2563 passed / 7 skipped（13.83s），日志`/private/tmp/nb12-domain-cut-anchor-full-20261114.log`；不是全97句质量通过。
- 已实际核对comparison-v2证据：`output/subtitle-editorial-comparison/NB12-20261113-chunking-v1/comparison-v2/experiment_evidence.json` SHA-256 `c2c8002ab58ca8f5e43b4719ed8d314cdabd6fc65ff6ac5aaba5c51fff8f8c66`；97句/1569词、old80精确重放、运行期间source/code未变、provider/ASR调用0。候选源码及worker另存独立快照，v1保持原样。
- v1人工复审发现s6、s29/33、s68、s74、s75/80等新退化，当前不放行昂贵下游；具体问题不能被少数forbidden消失抵销。v2同因修复还须单独人工复审。
- v2 barrier释放后，负责人批准Stanza子agent修六类确认漏标/过护及时间ago附着，详细授权/限制见ADR-0013末节；domain沿用现有attachment.adverbial一般档及其他typed标签，不改排序/阈值、不扩全部名词of关系。新增规则须独立身份/正反例，后续只写新comparison-v3，不覆盖v1/v2。


### 2026-11-14 v3/v4真实离线记录（仍未质量通过）

- v3七项feature及数量一般档已独立回放：97句/1569词，new80=169、new84=168；old80=165精确、old84=160。`comparison-v3/experiment_evidence.json` SHA-256 `9363dbb64585aac5d3b5aea5b30ab5feaad0750dfbe0e3794ba32829c9a09583`，运行期source/code保全、provider/ASR调用0。负责人独立全套2590 passed / 7 skipped（14.11s）。
- v4只修statement所属marker跨度，排序/阈值不变；纯DP正反例7实例已持久化，含合法marker+长S续屏、marker|S仍坏、真旧句/新头及旧尾/新句不豁免、s16 And/future/assuming形状。domain+adapter定向145 passed（0.84s）。
- v4稳定完整日志`/private/tmp/nb12-v4-stable-full-20261114.log`实际为2607 passed / 7 skipped（12.97s）；负责人独立2607 / 7（13.50s），不能再沿用in-flight失败或声称无验证。
- 已实际核对`comparison-v4/experiment_evidence.json` SHA-256 `356ef7d2308848a7382ba00b5a86b5a8f45c8d818e894099860eb63b11efc683`：97/1569，new80=170/new84=167，old80精确165/old84=160，四消融/why trace及冻结源码齐全，source/code保全、provider/ASR调用0。
- v4修掉s16/s39的marker归属假H，不代表剩余所有源语切分可接受；尚不放行初译/provider/烧录。root AGENTS最终状态待负责人集中按真实实现/样片结论更新，不把每次pytest绿扩散成质量通过。

### 2026-11-14 objective-v1隔离试验已授权，生产不变

- 依据ADR-0013末节，批准B/U/S/US两因子2×2：U仅普通未知3→2；S仅将普通等级置于CPS之前，其他变量冻结，CPS保持开启。精确13字段置换`(0,1,2,3,6,7,8,4,5,9,10,11,12)`；stable_offsets最后。
- runner子agent唯一修改实验worker/tests，domain及适配器生产源码不改。v4冻结源码/raw树/标签为输入，独立新objective-v1目录，不覆盖comparison-v1～v4。
- B须精确重放v4 new84 plan；四variant记录objective_id/ordered score_fields/完整why，DP与短cue救援同变换，原始CPS等指标照常报告。选项/非法字段/控制组/字段置换与归因须有离线护栏。
- 四组全97及所有变化独立审读后，才决定是否另切片实施唯一生产目标及oracle/身份更新；不自动选分数最低或forbidden最少者。不混新noun-of/NP-coordinate等特征，不放provider/ASR/编码。


### 2026-11-14 objective-v1四组完成（仅实验，不是生产/语义验收）

- 执行前独占落盘的`objective-v1/experiment_plan.json` SHA-256 `1c060dfef2a98508ef6a6dd851393de71ab570accaa094fa53eabc5acb929ad1`；结果`objective_evidence.json` SHA-256 `ea4fdf3d82b765aa66c4c8d1e87a55f269de4e2ae775f89a2375f6172e1bbaca`。两者均位于`output/subtitle-editorial-comparison/NB12-20261113-chunking-v1/objective-v1/`，原v1～v4未覆盖。
- B完整plan精确等v4 new84；四组固定plan证据（除分组正文外）、97句实际使用features/保护/分析句IDs均相等；CPS全开。U/S/US只在冻结副本worker内存覆盖，未改production、未发布manifest，provider/ASR/编码0。
- 子agent独立核对四组各99个评分表（97句＋全局短救援前/后）：ordered score_fields、数值components及各cue分量加总一一对应；S/US字段置换真实用于DP/救援/why，没有以旧字段名误标。不同目标数值仍不能当人工质量分横比。

| 组 | cue数 | CPS超标cue | CPS总超额 | 不足两空帧 | 超短cue/缺口ms |
|---|---:|---:|---:|---:|---:|
| B | 167 | 46 | 420940 | 55 | 5 / 1749 |
| U | 165 | 46 | 420940 | 53 | 5 / 1749 |
| S | 166 | 54 | 454600 | 49 | 5 / 1749 |
| US | 165 | 52 | 443860 | 48 | 5 / 1749 |

- B→U变6句、B→S变11句、B→US变12句；四组全部差异union为15句，已供负责人及独立agent逐句审读。指标不自动选胜；当前只有实验完成，尚无源语质量通过/真实下游放行。
- runner子agent完整离线2640 passed / 7 skipped（13.51s），日志`/private/tmp/nb12-objective-full-20261114.log`，diff检查通过；未把此测试结果写成内容质量签字。
- domain子agent建议US作为后续唯一生产目标候选，但指出新问句核心断点`would you | give`、`do | you`，以及若干noun-of/短ADVP等残余；生产选择与后续最小typed切片仍待负责人决定，不提前编码或以修改gold掩盖退化。


### 2026-11-14 US唯一生产实现进行中（与CF/question严格分轮）

- 负责人已正式批准US两原则生产落地，不是质量放行；仅ordinary未知默认2及普通语法等级先CPS。policy typed v4永久单路径，实际有序`SCORE_FIELDS`绑定policy身份，未保留生产objective开关或旧评分兼容。
- Stanza保持comparison-v4冻结feature身份，CF/question四项即使已获后续授权，也须等US单独证明完成后再改，不能混入目标变更归因。
- 本次恢复从磁盘确认：两项生产改动/字段绑定已持久化，但先前只到84项定向，完整证明未完成；没有把usage-limit中断视为任务结束。随后补齐机制及普通grade×CPS的独立穷举oracle，当前模块定向89 passed（0.31s）。
- 新worker由runner子agent唯一维护，实际字段顺序从生产SCORE_FIELDS读取；旧v1/v2/v3字段仅测试冻结身份支持，新US拒绝B/U/S/US重复覆盖。同容量旧typedv3产物的只读冲突测试由原publication测试扩参保留。
- 后续完整pytest及独立`production-us-proof-v1`应证明：cached97与objective-v1/US的分组/词时/保护/模型一致，policy身份差异明确；仅此证明后释放CF barrier，不覆盖任何既有实验/资产，不调用真实provider/ASR/编码。


### 2026-11-14 US稳定全套通过，精确重放证明进行中

- US永久单路径及有序字段身份已落盘；机制/独立oracle定向89 passed（0.31s）。oracle已加入普通grade与CPS交互，不只验证零普通代价或一阶等价情形，既有左右cue同因/二阶节奏反例继续保留。
- 首次完整快照留证`/private/tmp/nb12-us-production-full-20261114.log`为4 failed / 2654 passed / 7 skipped（14.31s）：当时runner新增拒重复覆盖测试的MediaBoundaryDTO fixture缺显式None；其作者修复后该文件独立70 passed（1.57s），未删除日志或撤掉断言。
- 双方冻结源码/测试后稳定完整复验：2658 passed / 7 skipped（14.19s），`/private/tmp/nb12-us-production-full-stable-20261114.log`，`git diff --check`通过。旧typedv3/84同容量manifest冲突及新US拒二次objective覆盖均保留覆盖。
- 已将src（含模块AGENTS）/tests write barrier交runner，独立新`production-us-proof-v1`将核cached97生产与冻结objective-v1/US分组、词时、保护、模型一致，policy v4及score_fields身份不同单列。证明未完成前不释放CF/question写入，不调用provider/ASR/新渲染。


### 2026-11-14 US生产精确证明完成，独立CF/question切片获放行

- 已实际核对`production-us-proof-v1/equivalence_to_objective_us.json` SHA-256 `bba5e3bce1694c3d368d260df4b63ea19c092c4e680c3615bc03c56e846ab89b`：97句/1569词、165 cue，除policy外完整plan的8字段（含chunks/词时、media、保护、analyzer）与冻结objective US均等；metrics、全局短救援前/后评分及实际ordered fields也精确相等。
- policy仅version/ranking/有序score_fields/defaultgrade四项预期差异，旧objective US未改写。四格/四消融证据`production-us-proof-v1/experiment_evidence.json` SHA-256 `cedcec20812a195f95f2725da6b7d9ba1bc38eb857d4a4c02e58611adac1d5cb`，原资产/source/模型保持，provider/ASR/render调用0。该证明只验证US正确落地，不是新语义签字。
- runner已明确释放barrier，负责人随后才放行独立CF/question四项适配器修复：SQ/SINV倒装最小核心；标点＋完整SQ/SBARQ的问句入口归属；NP直WDT＋完整S的不确定附属；逗号后已完成谓词的无主语VBG补述。各项须有反例，不能扩全部名词of或硬锁长问句。
- domain唯一作者仅加`clause.interrogative`低档与`noun.clause`一般档，policy/ranking升typed v5，US向量/字段顺序/阈值不动；定向93 passed（0.32s），含4个新类型正反例，普通grade/CPS与cue交互独立oracle纳入新类型覆盖。adapter guards、完整离线与新comparison-v5待完成后共同验收。


负责人随后独立US全套2658 passed / 7 skipped（14.21s）、diff检查通过，并亲自比较两份plan去policy后完全一致、核读8字段equivalence；US落地仅实现正确验收通过，CF/question及整体源语质量仍待本轮独立验证，不放行真实下游。


### 2026-11-14 CF/question实现离线验收、comparison-v5进行中

- CF/question domain仅2个映射及policy/ranking v5，SCORE_FIELDS/US顺序/阈值未改；adapter四guards单独升级feature身份，未混nominal-of/WHNP/scope扩展。最小类型及其独立oracle93项，合并domain/adapter定向173项通过。
- 首次工具实测完整2682 passed / 7 skipped（14.21s）；随后为持久日志，在源码/测试同一冻结状态重新运行：`/private/tmp/nb12-cf-question-full-20261114-v1.log`，2682 passed / 7 skipped（14.28s），pipefail退出0。保留两次真实记录，不编造首次log。
- 双方src（含模块AGENTS）/相关tests已正式freeze，交runner新建comparison-v5，基准为production-us-proof-v1，四格/四消融/97 why只归因CF四项。完整离线不等于新分组或整体源语质量通过，实际97句人工/独立审查仍待结果，不放行provider/ASR/编码。


comparison-v5执行前hold记录：runner尚未建立v5目录/采快照；适配器作者发现`what would you`不完整问句会被误当完整入口，负责人批准在原CF四项范围补guard/负例。其作者收回adapter barrier修正，domain/policy/排序及module AGENTS指纹不变；此前2682是修正前中间态，不能算新guard已验证。须等新定向/完整离线及最终共同freeze后才运行v5，不豁免源码race，不覆盖历史结果。


### 2026-11-14 CF最终guard与v5完成，独立NomOf计划先落盘

- 适配器最终guard已实查：不完整`what would you`/`who would`不作为完整question入口，保留predicate依赖；domain两tag及US字段顺序不变。最终工具实测完整2684 passed / 7 skipped（14.32s），其旧temp log本轮已不在盘；负责人当前独立2684 / 7（14.78s）覆盖最终指纹。旧2682不是最后guard验证，历史日志不撤销。
- comparison-v5已实际exit0并释放barrier，证据`experiment_evidence.json` SHA-256 `ab0c5af48bcf2152fd53b9c676a198ee664d655900bab0392f924fb306c3b56b`；旧80精确165/旧84=160，新84=164、新80=168，四格/四消融/全97 why及源码快照保全，provider/ASR/render0。负责人亲读关键组确认s59/s74改善、s16保持，整体仍有of附着等问题，不放真实下游。
- 负责人随后批准只做NomOf软附着，计划已先写ADR-0013末节：NP/NML/WHNP/QP下直接of-PP＋可见名词/数量/WH头或all/most/some量词，新增attachment.nominal-of一般档，不删候选或硬锁长NP/PP，不改VP的prep-of/非of PP/无头损坏结构。
- 实施归属仍为adapter作者独占特征/正反例，domain作者独占一般档映射/policy typed v6及纯软/oracle；不动US排序/阈值、有序字段或其他scope。定向/完整离线后共同freeze比较v6，仅归因本片，旧实验/失败保留，不commit/push、不删除/覆盖资产。


### 2026-11-14 NomOf实现离线通过，独立v6运行中

- domain仅新增attachment.nominal-of一般档与policy/ranking typed v6；纯软边界/负例及同cue交互oracle覆盖100项（0.40s），US有序字段/目标/阈值不变。适配器只按计划识别直接名词of-PP，量词最小清单all/most/some；不新增hard spans，不混scope/短ADVP等。
- 双作者定向205项通过；完整稳定2723 passed / 7 skipped（13.66s），已实际核读持久证据`nomof-validation-v1/full_pytest.log` SHA-256 `e157beb129c0ff126356eea9f8dfd259045d2043b47be1c5e2d28897b8e772ba`；同目录`validation.json` SHA-256 `83820a9056d24ddcf3c0dbbf67d0770520d23e714f04c9a741e2081b08c18ef0`。
- 只读诊断97句精确映射/public plan校验通过，与v5硬保护及触发分析句IDs精确相同；这不是源语质量通过。此前runner并行in-flight身份断言失败保留，不代替本次冻结后完整结果。
- 最终adapter/test与srcAGENTS指纹已共同freeze，runner实核后独占启动新comparison-v6（session94808），对照v5只归因本片；evidence尚待完成/独立全97审读，provider/ASR/render仍禁。不得在barrier内改src或豁免codehash race。


comparison-v6随后实际exit0并释放barrier；已核证据SHA-256 `d000c6958034ab7d175788c61d19775b42c06b40c1ae2d3c9b9e7ee643b7c28e`，source/code保护及old80精确重放通过，旧80/84为165/160，新80/84为169/165。runner稳定独立全套2723 / 7（13.47s）、diff检查绿；v5→v6全部变化及全97文本人工审查待完成，不从cue数或soft标签自动判好。无provider/ASR/新渲染。


### 2026-11-14 v6负责人审读后的局部scope/小单位计划（先落盘，尚未编码）

- 负责人独立v6完整2723 / 7（13.62s），读六变句及全165 cue后，确认多数NomOf改善，但s94新virtually|all阻断；s18 up|and down/频次NP、s68 no matter|what、s60 years|from now仍是局部缺陷，不放行真实下游。
- 已批准只按ADR-0013末节五项：最小no-matter-WH核心hard及connector；严格三项非clausal ADVP协调；NP/QP量词scope；VP下带限定的NNS times频次；数量时间＋from now软附着。四个新tag均一般soft：attachment.coordination/scope/frequency/temporal。
- domain作者唯一映射及policy typed v7/纯soft和oracle测试，adapter作者唯一结构/最小核心/正反例。US字段/向量/阈值不变，不扩长hard span，不碰其它scope；s60 in terms of|what为允许取舍，不增PP规则。
- 本段计划先落盘后通知adapter开工；完成定向/完整离线后共同freeze比较v7，持久日志/旧资产/失败候选全部保留，provider/ASR/编码0。


五项切片的domain最小实现：四个attachment tag仅加入现有一般结构档，policy/ranking typed v7，SCORE_FIELDS/US目标/阈值不动；纯soft/强标签不被洗白/未标文字不猜关系及四种新tag的独立cue交互oracle，共定向129 passed（0.79s）。no-matter硬核及实际结构正反例由adapter作者实现，完整离线/比较v7仍待验证，不放真实下游。


### 2026-11-15恢复v7验收：不把上轮domain定向当适配器完成

- 实查typed v7四个一般档映射、SCORE_FIELDS/阈值及纯规则/oracle测试已持久化；module Guide为上轮最终指纹b4245887…，不重复或扩大domain编码。
- 适配器五项半成品在盘，专用test仍NomOf末版identity/无scope用例，无新scope validation或comparison-v7成功证据。其作者独占收尾adapter/test，定向及97只读诊断ready后由domain验收者统一跑合并/稳定完整并持久新日志。
- srcGuide将在完整验收/final freeze前更新15日真实语义状态；benchmark barrier内不改源码/指南，不豁免race。129旧定向及2723旧full都不冒称本次五项通过；真实样片仍待后续源语审读放行。


### 2026-11-15 v7稳定全套/回放后仅授权adapter最小predicate core

- 五项v7已合并279 passed（1.58s）、完整2795 / 7（15.16s），持久`scope-validation-v1/full_pytest.log` SHA-256 `5bc094485ac28765434804f839054e00e8f2b8be9348651ac7f1450cd47b8438`，`validation.json` SHA-256 `3fee70a10527fe9c1599260e1cad508be4a32add88ffc9f57203b326863d8720`；负责人独立2795 / 7（13.88s），持久root_full_pytest.log，diff检查绿。
- comparison-v7实际exit0/释放barrier，evidence SHA-256 `32e1eaac2b38e1f8ccdbe2cd802b1579f0084aa7fd11b1993ce94c9a68fb6e7b`；独立review SHA-256 `00f4a240065529cc3c65d839f38500b8ee17aa1cd3c357bd255c4245d549672a`。负责人已核97/1569/165、old80精确及全部source保护，裁决s68/s94改善，s18 are|not、s60 currently|exist仍阻断，say|five只披露不扩大。
- 新comparison-v8计划已先落ADR-0013：仅adapter copular be＋simple adverb＋ADJP首JJ最小核（ADJP前缀只许直接RB/RBR/RBS或纯RB simple ADVP，首JJ即止、不递归），以及已确认VP补语内bare单子S/SBAR末端单叶ADVP＋VP首VB两词核；严格中止/结构负例，不吞长结构。adapter唯一编码/tests/feature identity，domain/policy typed v7/US有序字段/阈值不动。
- 已只读核现有manifest/plan analyzer identity及生产/样片verify显式model bundle路径覆盖adapter保护/排名版本；不用为v8改DP身份或新增框架。省略bundle的独立verify仅自洽，不冒称当前feature校验。完整离线及新v8全97审读后才决定样片，所有旧资产/失败保留，provider/ASR/新渲染仍禁。


2026-11-15 v8两core已实现并稳定全套：332项合并（0.81s）、完整2848 passed / 7 skipped（13.24s），diff检查绿；持久证据`predicate-core-validation-v1/validation.json` SHA-256 `a105d2274b12fe5878e3a74ce0a4095b1b49b49dc38f3b035e12f648cfa2be4e`及`full_pytest.log` SHA-256 `b412a07347fab750f9a8d5ff2be5f1445366ed1d109eafc2800a89a1f29050d5`。最终Guide SHA-256 `60d3a393b53052a02e10fa7df4477e9505df65042a925e81cb186e94fecdbf9d`，adapter `7f82efc268f56765b6733840cd6da04b9a9a6b51da7afce1269e13546866f0bf`，专用test `e0b4ddd98a8cb6f3328017356e8fefbb016d71a61387a8d0e29ef88bc7cd31e2`；三者及其它domain/tests已共同freeze交runner。201份source清单与v7相同，只有adapter/Guide hash变化；policy保持typed v7，adapter protection v6/ranking v9。正式comparison-v8和全97源语质量复审尚待，不把只读s18/s60改善/165 cue或pytest通过当放行；provider/ASR/新渲染仍0。

2026-11-15负责人独立完整2848 passed / 7 skipped（12.91s），持久`predicate-core-validation-v1/root_full_pytest.log`及diff检查通过；已静态核两core无范围外改动。comparison-v8已实际启动，source/tests保持冻结；下一ADJP→PP软附着仅待实验后另行裁决，尚未授权实施/落计划。

2026-11-15 comparison-v8已实际exit0并明确释放source/tests barrier，evidence SHA-256 `4b0ca013a5c794de2ddc4431e8099c5c447e1dae77db9efe58d0939644540b0d`；source/code保护通过、新84仍165 cue，但短cue由5至6、shortfall增加54ms、warning由103至105。自动指标只供披露，不据此定胜；全部变化已交负责人/独立复审，整体源语仍未通过，不放provider/ASR/新渲染。


### 2026-11-15正式授权的单一ADJP→PP soft片（comparison-v9）

v8已实际exit0/barrier释放，负责人有限认可两core实现，但s18 `related|to`仍未过；s60 `say|five`与末端`in a business`780ms（真实短warning）明确保留取舍，本片不追VP-owned PP、词表或其它规则。先落本计划，再由适配器作者唯一编码：仅同一ADJP内，直接可见JJ/JJR/JJS head后直接PP的beforePP，加`attachment.adjectival`一般结构soft；不跨comma/CC/clause/PRN、不从深ADJP或其它祖先借head。VP/NP-owned PP、无adj头为负例；不增加hard保护、不删候选，长PP因预算仍可切。

domain作者唯一新增该一般tag映射，并将policy/ranking升级typed v8；US有序SCORE_FIELDS、阈值、源词/时间不变。适配器独立升级feature身份，模型/mapping不变。补纯soft、强标签优先、独立穷举oracle及身份测试；合并定向、完整离线/持久日志后共同freeze新comparison-v9，80/84×旧新、4消融、全97复审并列出所有退化。若无新严重退化，目标是负责人决定是否放行实验样片与最终稿审查，不宣称全局/出版质量已通过；当前provider/ASR/新渲染仍禁，旧资产/失败全部保留。

2026-11-15 v9 domain最小映射/身份已落盘，137项domain/segmentation定向通过（0.87s）：`attachment.adjectival`一般结构、强关系仍优先、无标签不词面猜测、长附着容量可切，并加入独立cut-interaction穷举oracle全部reading/rhythm组合。policy为`english-typed-cue-dp.v8`，ranking为`typed-cut-anchor-local-units-adjectival-short-syntax-ordinary2-cps-count-pause-rhythm-headroom-offset.v8`，SCORE_FIELDS及阈值未改。此为中间定向验证，待adapter/合并完整离线与独立v9，不提前宣称语义通过。

2026-11-15 v9单一ADJP→PP soft已合并稳定验证：361 passed（0.93s）、完整2873 passed / 7 skipped（13.39s），负责人独立2873 / 7（13.00s）及diff检查绿。持久`adjectival-validation-v1/full_pytest.log` SHA-256 `6199efff5bf77b475f8848ee4f0e85b8f66ded0a2cd12ca852fabed512adbb18`、`validation.json` SHA-256 `3e2018cb135d04e1f5dccdee97957b1cae5076744d1efcfe4179eb3c2e357bc8`与`root_full_pytest.log`；8项source/tests前后指纹不变，201份source清单与v8相同，仅adapter/domain/policy/Guide四个允许hash变化。policy精确只变version/ranking两项，US字段/阈值不变；v7/84同容量旧manifest复用零写冲突测试通过。最终Guide `c4ef08bbff5a42c728c79f33735d92fee7b41b1e2da6f144bcb16b6882d2d09e`、adapter `30515a23d2c9f95bbd2f73b6226e698879a03c91e70040160677182053e9db0b`、专用test `197257aea373ae98ca8b73bded83d51f1eb8536cf2a3ba8c88256409865f4659`已共同freeze交独占comparison-v9。97句只读仅s18分组变、165 cue，hard/spans/trigger相同；不是正式v9或质量放行。负责人静态验收范围后要求不再新开生产规则片，待v9实际exit/独审才有限决定真实样片；s60已披露warning不藏。

2026-11-15 comparison-v9已实际exit0，evidence SHA-256 `3635a6031c6657a8d346d6c416f71522920f6bf310945b70ef5d15a0494cfa0d`已实际核hash；old80精确165、old84 160、新84 165，source/code保护通过。另独立逐字段核v8→v9新84：除s18外其余96句chunk记录精确相同，词ID/顺序、hard/media/trigger/mapping/model不变，policy仅version/ranking与analyzer ranking预期变化。独立v9复审`independent-source-review-v9/review.json` SHA-256 `4aa7e5b039eb617611be578f56b9f2d0dd561f82a723ae7aa9b15b0d91d054dd`：对v8为1胜/96平/0负；对旧80为15/81/1，对旧84为14/82/1，s60仍旧更好。负责人有限认可本轮实现及开发集取舍，不等于全局或出版质量通过。只正式放行prepared新根实际source_chunking，先证真实模型plan精确等cached v9；provider/ASR/新渲染仍禁，下一步须等实际source证明及独审意见后另行放行。


### 最终97句双语稿独立审查准备（未预签字）

- 以canonical s1～s97和连续word IDs为单位，逐句列最终cue/词范围/英文/中文/实际显示时间，先核真实source等cached v9的证明及当前术语、prompt和来源身份；不按可变cue数或DP自动分数选胜。
- 全97逐屏读语义：数字/单位/比例分母、否定与程度、条件/例外/预测、并列继承范围、代词指代及口语改口；检查中文有无跨屏提前/滞后、重复补主谓、遗漏或将风险不确定性改写为确定断言。术语查现行20项表（如内在价值/净资产/阿吉特·贾恩），未确认专名不凭猜测补名：canonical仍为`a JET`时不能因术语表有Ajit Jain就猜改为阿吉特·贾恩；c70/c114是用户允许结果，不以历史cue号当强制必改。
- 对照实际source好切法和初译，逐项列编辑重切/合并/措辞变化：既验s16四屏、s18三屏及no matter what/virtually all等保好，也允许有证据的更好变体，不机械复刻参考；不能仅因warning减少而撤销语义边界。s60 say|five/780ms尾PP持续显式审查，允许编辑在权限内改善但不隐藏残余。
- 词锚/保护/覆盖/section/speaker仍为硬契约，预算与最终实际借时分开；长度/CPS/短时/空帧warning如实记录，中文与像素另验，不用84容量假定显示合格。SRT/ASS核为同一权威稿/时间，不让导出重切。
- 文本、实际静音画面、核听分别记录范围与未验证项；最终稿审查不冒称已看新成片/已核听或人类出版签字。全部失败/旧稿及昂贵调用实绩保全，任何provider/渲染仍待明确放行。

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

2026-11-15最终负责人验收实际exit0：`final-acceptance-validation-v1/root_full_pytest.log`为2873 passed / 7 skipped（14.79s）；同目录`asset_verification.log`独立核143份生产.py逐字等v9、仅3份模块AGENTS变化、14输入/NB09库存不变、实际source完整9字段exact。五阶段公开只读verify全reused且整root bytes/mtime不变，video SHA-256 `12092104058edb3b7dffa5a1dc307b6ea14c61184824e346c68d324677da4514`及final SHA-256 `36721b9d5686438f3522c5301ee9e1408ff5ff2c08ee1d8ba6d9171ea5ed274f`精确匹配。实现＋诊断样片技术交付至此收尾；整体语义/出版仍NOT PASSED，未核听，供用户诊断复审，不再编码/改稿/重置额度。
