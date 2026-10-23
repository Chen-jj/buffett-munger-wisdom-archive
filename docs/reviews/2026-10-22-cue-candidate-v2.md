# SP-12：224-cue候选v2与旧242/冻结153参考的全量对照

- 日期：2026-10-22；范围：CNBC既有97句、2个section、1564个timed words、2912个规范中文codepoints。
- **结论：候选技术闭环可复现、专名/成组标点的硬断裂得到保护，部分样例明显改善；但短cue和部分语义错位回归，当前不建议定版为字幕质量通过。** 本轮保持224版冻结，交用户看对照后决定，不按坏例继续偷偷调算法。
- 没有重跑ASR、翻译/provider或修改译文/词时间；没有改旧正式33文件或SP-09的139份历史工件。没有音画、像素/ASS/烧录或真人出版验收。

## 1. 先看全部97句，而非只看总cue数

**主交付：** [全部97句易读Markdown](../../output/cue-evaluation/20261022-candidate-v2/review_v2/all_sentences.md)。每句包含：旧242、新224、原153的所有cue中英正文、英文实际v2换行、词ID/中文offset、时间、关联跨句组、硬兼容性、人工优/平/劣及具体原因/残余。对应JSONL/TSV和手写原始判断均保留：

- `output/cue-evaluation/20261022-candidate-v2/manual_notes.v2.{txt,jsonl}`：97条逐句手写判断；v1保留，v2把s90明确改为词完整/谓语滞后相抵，不判整体优。
- `review_v2/all_sentences.{md,jsonl,tsv}`、`review_v2/summary.json`：机械拼接证据，不自动推断语义。
- `comparison_v1/three_way_sentences.jsonl`、`three_way_metrics.json`、`extra_metrics.v1.json`：三方原始比较、逐cue新口径指标。
- `workspaces/cnbc_2000_morning/`：新候选规范plan、三SRT、report、manifest，只在隔离候选工作区发布。
- `workflow.v1.json`：真实workflow、耗时、复用、独立投影读回和原件不变。

“更接近参考”有两个不同含义：

1. **结构上更近：** 与参考断点完全相同的句数从旧19变为候选26；新增s3/s7/s27/s31/s36/s54/s59/s86八句，s35因新的跨句合并失去完全相同。内部英词末/中文offset切点对的对称差从172降至147。以上只是结构描述，不是语义得分。
2. **语义上不能笼统说更近：** s3/s7/s27/s54/s59等确实贴近参考，s32/s30/s16等却出现新的提前/滞后。全97句人工文本判断：候选对旧**优27/平61/劣9**，对原参考**优1/平52/劣44**。这些是文本分组审读，不是加权总体胜率，也不能把超预算参考当同约束真值。特别是少数严重回归不可被许多小词修复抵消。

候选与参考均满足新硬profile的完整关联组覆盖27句，其中对参考优1（s4）、平23、劣3（s26/s32/s57）。这说明**即使不依赖放宽预算，也存在未选到的更自然参考路径**。参考仍非golden：s4参考自己将净资产提前，s74/s88仍有明显语义错配。

## 2. 本轮规则与公平比较口径

候选明确使用新身份，不冒用旧v1：

- `netflix-audio-gap.zh-priority.v2` / `bilingual-monotonic-dp.v2`；profile SHA-256：`ad7b0af50a207d8fcf695d68de32dc559e514924257789729bc56d1a46330d79`。
- 中文一逻辑行16单位，中文栏完整Latin英文word计1；内部连字符/撇号保留，数字/其他标点沿用既有规则。此计数统一用于容量和中文CPS。
- 英文实际可排最多两行、每行42非空白字符，不能仅总量≤84；不可分源word不拆。三SRT共用cue/时间，英文与双语投影用同一纯排布函数；plan仍保留逻辑正文而非视觉lines。
- Latin词内、冻结组合序列、连续破折号/省略号组内硬禁切；jieba词、数字单位、跨词专名/局部短语等是软质量信号，不被误称语义硬门禁。
- 本地固定`jieba==0.42.1`，`HMM=False`，自带字典SHA-256 `7197c3211ddd98962b036cdf40324d1ea2bfaa12bd028e68faa70111a88e12a8`；adapter核验包/字典并提供offset spans，domain无IO，不联网下载、不静默fallback、不依赖可变/tmp缓存。
- D39词典序：不自然断点 → 应急断点 → 过短 → 中文CPS超额 → 跨句合并数 → cue数 → 比例偏差 → 确定性断点向量。7秒、源锚点、500ms总尾延长、gap、section/speaker/null、原始合并资格与覆盖守恒保持。
- codec显式`serialization_version=word-wrap-english-2x42.v2`，旧shape仍可解析，但不按新规则静默复用旧成功资产。

三方比较把**所有固定cut**统一重审新中文word计数、真实2x42可排性、硬字符边界、7秒及新计数下原始跨句合并资格；旧242和原153的断点、时间、原文件完全不改。原153只在新比较视图计算可能的英文行，不重写其原SRT。任何一方cue跨句，就将三方关联句合并成完整比较组（共83组），避免挑一合法cue遮住同组违规。

### 口径明确的全量指标

| 指标 | 旧242，按v2重审 | 候选224 | 原153，按v2重审 |
|---|---:|---:|---:|
| cue数 | 242 | 224 | 153 |
| 中文word单位>16 | 0 | 0 | 73 |
| 英文实际2x42不可排 | 0 | 0 | 5 |
| Latin/连续标点等硬边界违规cue | 15 | 0 | 0 |
| 任一v2硬不兼容cue | 15 | 0 | 73 |
| 新计数下合并资格违规 | 0 | 0 | 0 |
| `<834ms` | 2 | **9** | 0 |
| 中文CPS>9，**统一v2 word计数** | 11 | **17** | 4 |
| 英文CPS>17 | 95 | 81 | 39 |
| 时长min / median / p90 / max（ms） | 721 / 1878 / 3416 / 6838 | 420 / 1972 / 4014 / 6097 | 834 / 3321 / 5302 / 6826 |
| 可排为两行英文cue数 | 0 | 44 | 77（另5不可排） |

原153的5个英文不可排cue为a105/a116/a134/a136/a145，均同时中文超16，因此合并硬不兼容总数仍为73，不是78。

**旧历史口径不能混用：** SP-09旧计数下原153有98超容量、旧242中文CPS超9为12；这是存档事实。本轮重新审计得到原153的73、新计数下旧242中文CPS为11，不再沿用“98超限”断言，也不把旧12与候选17当同计数直接比较。CPS告警用整数比较，显示小数仅供阅读。英文源word内部切分三方都为0，不等于多词短语或汉语意群不拆。

候选9个过短cue：c19=420ms、c25=660、c28=653、c74=640、c89=680、c99=721、c165=561、c186=641、c222=780。其中c99（s41）和c222（s95）在旧稿已有同类短命题/短问句；另7个是本次新增短块，必须作为回归审阅，不能因最大时长/覆盖合法便忽略。

## 3. 代表性改善与回归（精确全文/坐标均在97句主交付）

| 句 | 实际观察 | 评价边界 |
|---|---|---|
| s3 | 候选c3=参考a3整句姓名/地名，修旧Nebraska配Moe Spence | 新word计数下参考已合法；改善也来自新预算口径，不全归成本。 |
| s4 | 先1999，后完整公司/净资产/0.5% | 比参考a4只公司名就给净资产更对应，是参考自身错误的反例。 |
| s5 | Hathaway不再断字；新c6已接手但中文仅这意味着，c7才补接手 | 专名改善与时序后移相抵，不能判全面进步。 |
| s6 | Buffett Limited Partnership完整；c11完整连续48年英文却只配算在内 | 硬词边界修复不等于语义；参考a9仍超中文16，也不能据此放过错配。 |
| s7/s27/s54/s59 | 整体切法贴近/等同参考，长期股东/专名/问句更自然 | 明确成功例，但不代表其余句。 |
| s13 | 双破折号完整，却新增But、because独立短cue | 比旧5cue变6cue，切换/时间回归，参考也部分超容量。 |
| s16 | 未来年份英文提前并入旧下跌结论块，寿命插语配未来，之后才补寿命 | 比旧更严重的跨块滞后，不能用标点完整抵消。 |
| s29 | c72仅I called I就显示软饮料/剃须刀，c73才英文业务 | 英文词组保护压过了双语对应，明确回归。 |
| s30 | c74仅And配而事实是，它们现在，640ms | 语义提前、过短及中文高CPS同现；旧完整s30+s31路径仍合法。 |
| s32 | c77仅But certain other factors便显示损害业务，c78才hurt | 旧/参考合法而更对应，是目标函数偏好坏语义的强见证。 |
| s47 | 有价证券不再有／价拆字，比较与词组更完整 | 局部成功；不宣称全语义/出版质量。 |
| s57 | 仍描述／了、the悬前块，和旧路径相同 | 参考described后切在新profile合法，本轮未解决此已知可改善点。 |
| s60 | 认为和双破折号完整；但or modify/reduce已配我们认为，we perceive在后块 | 新的词完整性不构成语义解；参考大块仍超中文预算。 |
| s74 | 风／险修成完整重大风险，并略后移 | 末perceive risks仍配心甘情愿涉足；参考也错，二者皆非golden。 |
| s79 | any castle you have配剃须刀片，列表语义提前 | 后半有局部改善，前半仍明显错位，8cue本身不说明更好。 |
| s81 | 英文末its castle配中文护城河 | 关系对象仍错；See's Candy完整不能掩盖该回归。 |
| s88 | 候选沿旧五块，primary criterion配保持宽度、great business配无法跨越 | 固定译序逆转未修；参考三块同样有末cue错位，少cue不算胜。 |
| s90 | 今年不拆，却把比较谓语高挪到because所在末cue | 词完整/语义滞后相抵，记平；原153整句仍不可排且超中文，不可直接替换。 |

## 4. 三个固定现成路径的精确成本归因

`audit_cost/READOUT.v1.md`、`results_v1/fixed_path_costs.{json,md}`提供s30/s32/s57只读证据。作者只逐cue重算给定旧/新/参考边界与成本，不调用DP求解/候选枚举、不搜索新断点；成本统一按v2计时，原文件不改。负责人已独立复跑到`audit_cost/lead_results_v1/`，输出逐字节一致。只是指定三例的目标函数诊断，不是全片语义评分。

- **s32：** 候选/旧/参考完整句都硬合法、不自然断点均0；应急断点候选0、旧1、参考1，因此第2维已经决定候选获胜。`factors|hurt`有1941ms源词gap，被当`english_pause`；但英语没有hurt时中文已损害业务。候选比例偏差26/105≈0.247619，明显劣于旧2/165≈0.012121和参考31/1155≈0.026840，后置比例维无权翻盘。不是容量或cue数迫使错位。
- **s30+s31：** 候选与旧都硬合法、同为3cue；应急候选1、旧4先决胜。候选即使有1个过短、中文CPS超额81/16=5.0625、比例191/600≈0.318333，也压过旧无过短/无CPS超额的组。参考a53中文25>16，不能拿它作合法总体竞争路径。
- **s57：** 候选=旧路径，参考也硬合法；应急候选1、参考2。候选`the|extraordinary`有880ms gap被当pause，参考`described|the`40ms被判emergency。jieba把描述、了分作独立token，不自然断点成本均0。参考比例偏差也更大，所以**仅把比例提前并不能保证这条已给定参考路径胜出**。

真正暴露的是：高优先级“停顿/应急类别”可压倒短cue/CPS/跨语对应，而词法启发式并不保护一般谓语、定冠词、体貌助词依附。word gap不是静音或语义从句证明。代码按目标函数选中，不等于文本质量合格；也不能据这三例就未经验证替换成另一套简单排序。

## 5. 隔离、真实workflow与性能

唯一archive_core工作区函数构建`candidate-v2/workspaces/cnbc_2000_morning`。复制小型既有上游；video/audio为指向正式文件的链接，只有只读使用，未chmod或写穿链接。派生transcription manifest只重基`records.path`到新规范工作区，全部原sha/cache/provenance保留，原manifest字节不改；此路径重基在`preparation.v1.json`明确记录，不伪装重新生成上游。

真实默认本地composition（固定jieba、ffprobe、pysubs2）运行：

- 第一次`succeeded`：**194.410秒**，发布224-cue plan/三SRT/report/success manifest；不是plan-only实验。
- 第二次`reused`：**0.780秒**，**0 staging/publish写入**，六输出bytes/mtime不变、上游不变。
- 额外独立检查公共plan输入/manifest链、1564词与2912中文字符恰好覆盖、speaker/null、源时间与profile、三份SRT真实pysubs2读回、中文一行/英文≤2×42及英文换行确在源word边界。
- 负责人又独立`reused→reused`、三方重算与97句审读join；`lead_comparison_v1`、`lead_review_v2`与主输出逐字节相同。正式33文件/SP-09历史139文件hash/size/mtime_ns均未变。

首跑约3分14秒明显不是交互级延迟，应作为性能限制保留；复用无需重规划。没有修改规则兜底、自动降级或另写切分器。`code_checkpoint.v1/`保留41个小型源/测试/requirements截面，明确标注是当时点快照，开发可能已开始，**不伪称完整任务前干净before**。

## 6. 验证、复跑与历史环境限制

可追溯入口：`tests/srt_processing/candidate_runner.py`；10项新增离线测试覆盖opt-in、缺输入、独立准备/拒覆盖、原件快照、真实fake-media工作流生成复用、三投影、84总量仍不可两行、中文word计数、硬Latin断点、只读参考与完整Markdown join。全套离线及负责人复跑已通过1329项，live5项不运行；本轮`git diff --check`通过。

已有候选工作区只复用、所有新结果须唯一命名：

```sh
PYTHONPATH=src .venv/bin/python -m tests.srt_processing.candidate_runner --run --compare --result-name workflow.RECHECK.json --comparison-name comparison_RECHECK
PYTHONPATH=src .venv/bin/python -m tests.srt_processing.candidate_runner --review-notes output/cue-evaluation/20261022-candidate-v2/manual_notes.v2.jsonl --comparison-name comparison_RECHECK --review-name review_RECHECK
PYTHONPATH=src .venv/bin/python output/cue-evaluation/20261022-candidate-v2/audit_cost/audit_fixed_paths.v2.py --output output/cue-evaluation/20261022-candidate-v2/audit_cost/UNIQUE_RECHECK
```

**不要在既有目录重复`--prepare`或删除旧run。** fresh候选必须用新experiment-root，先复制保护快照作同一受保护源证据，再明确`--prepare --run --compare`；媒体链接和派生manifest路径另记录。

**历史SP-09复跑限制：** 旧实验脚本动态import当前`rules`。当前源码升v2后，不能无版本隔离地照旧README命令重新得到旧v1计数/计时/指标；原139工件仍作为当时运行的冻结证据保留，不修改旧工具迁移，也不假装旧命令在新环境仍等价。本次新三方工具明确用v2审计，并保留旧口径原始文件。

## 7. 给用户的决定点

1. 可认可候选的隔离可复现性、两行英文/按word计数契约与硬专名/标点保护能力；**不能把技术通过扩大成语义或出版质量通过**。
2. 不建议现在定版224切法：重点看s32/s30/s16/s29/s81、9个短cue，以及s57仍未改善。若继续改目标函数，应另起规则版本、固定这批工件，再做同一97句全量回归，不按几个坏例偷偷调本轮结果。
3. 原153仍有73 cue违反新硬profile，不能直接发布；它既提供更自然意群参考，也含s4/s74/s88自身错误。固定译序逆转需显式承认契约/人工语义审查边界，不重译/重排藏进SRT模块。

本轮交付的是**可审阅候选+完整对照与失败证据**。最终规则取舍、是否继续修，留待用户看完97句对照决定。

文字版本：当前v2仅将过短cue说明精确定位到c99/s41、c222/s95；v1保留，不改变数据、224切法或97句审读。

## 8. 负责人最终交付验收（2026-10-22 23:17 CST）

负责人已审查候选规则/公共契约/投影/工作流，通读全部97句候选正文与逐句判断；独立完整离线1329 passed / 5 deselected、新增runner10项、持久双复用、三方重算、97行审读join与三例固定路径成本复算均通过。数据、Markdown及成本输出与开发/审计交付逐字节一致，受保护33+139文件均未变。

SP-10/11/12现按**候选实现、技术集成与完整比较交付**accepted，不接受本版为最终语义/阅读/出版质量通过。保留224冻结版本及全部成功/回归证据，下一步由用户审阅后决定。
