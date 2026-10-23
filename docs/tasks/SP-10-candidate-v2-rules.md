# SP-10 — cue质量候选v2：计数、边界与规划

- **Status:** accepted（候选实现技术验收；内容质量不定版）
- **Owner:** planner开发agent；技术负责人决策/验收，不直接编码
- **Depends on:** SP-09评估；与SP-11先冻结接口，再并行实施
- **Depended on by:** SP-12
- **Authorization:** 2026-10-22用户明确要求先修一版，再逐句对比独立agent稿，由用户继续决定。

## 候选行为（试验授权，不代表最终出版策略）

1. 中文一逻辑行，容量仍16计数单位；中文中每个英文单词计1。词内连字符/撇号（Coca-Cola、See's）保留，Berkshire Hathaway计2。布局空白计0，数字/其余标点保持既有规则；计数用于容量及中文CPS，不能一处按词、一处仍按字母。
2. 英文允许最多两行，每行42非空白计数。在源词边界上确实存在合法两行排布才可行，不能仅把容量改84。不可分单词>42须受控失败，不能切字母。
3. 识别中文词、中文内Latin词、数字单位、成组标点及英文局部短语/专名，区分硬文本单元保护与软词法偏好；应急退路及不可行原因可审计。不能只列本样本词表，不能宣称词法等于语义。
4. 优先完整词/专名/标点组；修订D39的可读性与切换/比例顺序，使微小字符比例收益不能任意压过词完整性/节奏。具体成本在实现前记录，并使用新版本身份，不偷用旧D39指纹。
5. 不重译、重排、删词或改词时间；7秒、834ms软目标、500ms总延长、gap、section/speaker/null、跨句合并资格与覆盖守恒沿用。固定译序的语义残余如实报告。
6. 本地分词若依赖固定词典，依赖与词典身份须固定并进入规则指纹；加载/IO在adapter，domain只接收纯数据。不得运行时联网下载或静默fallback，离线测试可注入fake。

### 实现前接口/成本确认

- 采用固定`jieba==0.42.1`随包词典、`HMM=False`；adapter实测并校验字典SHA256，engine/hash/mode完整进入候选profile。缺依赖/证据不符受控失败，绝无字符切分fallback。domain只消费分词跨度；workflow生成/复用均核对身份。
- 纯`wrap_english_text(text) -> str`在候选可行性、codec及workflow独立expected中共用；输出1或2行，各42，否则ValueError。不在plan加lines。
- 候选D39字典序：词/专名/数字单位软断裂 → 普通应急数 → 过短数 → 中文CPS超额 → 跨句边界数 → cue数 → 比例偏差 → 整路径tie。Latin词内/成组标点硬保护；中文词内为高优先软退路。这个排序是本轮可比较试验，不宣称语义匹配，也不预先承诺少cue。
- 公共profile新形状含英文行预算与分词身份；旧v1精确参数形状仍可读/原样回写，不补默认字段改变原hash。codec候选显式`serialization_version=word-wrap-english-2x42.v2`，旧缺字段形状仍可读但不能按新阶段复用。

## 范围与协作

负责规则、边界、planner及必要的分词端口/组装和单元/回归测试。与SP-11共享纯英文换行规则，plan仍存原逻辑正文/offset而不存视觉lines；SRT投影变化由SP-11负责。先验证正确性再做有证据的局部性能优化，不大范围重构。

全量原始正式工件和153-cue作者稿只读。新候选默认规则身份必须明确，旧工件不被静默复用或覆盖；最终ADR取舍待用户审阅。

## 开发交接（2026-10-22）

- 核心变更：`domain/rules.py`、`boundaries.py`、`planner.py`及导出；新增
  `application.ports.ChineseWordSegmenter`，`infrastructure/segmentation.py`与composition注入。
  未改archive_core DTO、codec或workflow；其投影/注入接线由SP-11负责。requirements增加pin，
  默认测试仍无网络、模型或媒体进程；真实原工作区和153cue参考未改动。
- API：`chinese_half_units(text)`直接对完整正文计数；`wrap_english_text(text)`固定1/2行，
  在合法断点中按两行计数差最小、同差选较早断点，不能合法排布即ValueError。
  `boundaries.hard_chinese_boundaries(text)`只返回硬可切offset；
  `chinese_boundaries(text, spans)`返回allowed与soft lexical_cuts。
- `plan_subtitles/validate_plan/analyze_plan`新增keyword `chinese_word_spans`，必须精确覆盖
  sentence IDs与每句规范中文分区；缺失/损坏受控失败，不偷偷用逐字fallback。workflow每次
  验证segmenter三键identity与profile一致，生成和复用均传同类证据，不重新DP来证明复用。
- Latin词内与重复破折号/省略号内部硬禁切；中文词、数字/中文数词加单位、英文局部专名/短语
  是软断裂，断点可同时累计中英两侧的局部违规。每句offset、所有源词及时间规则不改变。
- 精确新D39：`unnatural_breaks, emergency_breaks, too_short_cues, chinese_cps_excess,
  merged_boundaries, cue_count, position_deviation, whole_path_breakpoints`；CPS/比例仍Fraction。
  单句比例是整句累计位置；不把它当跨语言语义，不改保序与句尾锚点。
- 由于新计数不加性，候选/时间/物化按最终拼接正文直接计算；跨fragment`foo-`+`bar`计作一个
  word而不是分段和。不能把任意prefix差当容量证明；Latin内部断点也不能逃逸成零计数。
  所有候选仍进入同一稀疏DAG，无beam/CPS/比例窗口剪枝。

### 词典来源与固定身份

- 官方来源：[PyPI jieba 0.42.1](https://pypi.org/project/jieba/0.42.1/)，固定源码包SHA256
  `055ca12f62674fafed09427f176506079bc135638a14e23e25be909131928db2`；按包文档使用default精确
  模式与HMM=False，不加载用户词典或样本专用词表。
- 已通过工具实际安装`jieba==0.42.1`：第一次sandbox DNS失败，随后require_escalated安装成功。
  运行时核对包版及随包`dict.txt` 5071852 bytes / SHA256
  `7197c3211ddd98962b036cdf40324d1ea2bfaa12bd028e68faa70111a88e12a8`。
- 独立Tokenizer从核验bytes经固定loader建立内存词典，避开jieba默认可变/tmp marshal缓存，
  没有运行时联网/下载/持久缓存。engine/hash/mode全部进入profile，整体SHA256为
  `ad7b0af50a207d8fcf695d68de32dc559e514924257789729bc56d1a46330d79`。
- 分词误差与未登录词会保留软退路，不承诺正确识别所有汉语词、专业术语或专名。

### 实际验证

- 核心定向规则/planner/边界/词典/composition：**159 passed**（2.03s）。包括独立穷举oracle
  更新为实际2x42可排与新D39顺序；候选顺序扰动、non-greedy、硬不变量和原gap矩阵保留。
- 新增组合标记/emoji、连字/撇号、两行总量80却不可排、数字/中文数词单位、长词典误分软退路、
  缺证据/缺包/错版本/改词典失败、完整substring与跨fragment非加性计数等回归。
- `.venv/bin/python -m pytest tests/ -q -m "not live"` → **1329 passed, 5 deselected**（6.03s）。
  `git diff --check`通过。未运行ASR/translation/provider或修改正式output。
- 初版3000字回归出现107s重复Unicode扫描并停止pytest；依据该证据增加有界纯LRU字符分类、
  完整正文计数与wrap缓存，不变更候选/成本。最终定向2.03s；未见16词/74中文字合成句+真实
  jieba spans规划约2.05s。真实97句耗时由SP-12在隔离workspace独立记录，不预先背书。
- Runtime/profile/cost已冻结并通知SP-12；只读旧产物与参考的逐句比较、最终质量取舍仍待验收。

## 验收

- 中文英文word计数（连字/撇号/Unicode组合/与数字标点混排）、完整区间计数与候选/物化一致。
- 2x42实际可排/不可排、长单词、词/专名/数字/成组标点、未知词应急路径。
- s90/s57/s32、s6/s60回归及未见样本；保留s74/s88残余，不样本硬编码。
- 完整覆盖/词时间/合并/DP确定性、版本冲突及完整离线pytest通过；不得删除资产或自动commit。

## 负责人验收（2026-10-22）

已审查计数/边界/词典adapter/DP与成本顺序，独立完整离线1329 passed / 5 deselected；SP-12真实224-cue生成/复用、负责人独立复用与97句比较通过。硬计数、2x42、Latin/成组标点保护符合本轮候选规则；s30/s32等新语义回归及s57未改善明确保留。此验收接受实现可供用户比较，不接受当前目标函数为最终质量策略。三条现成路径成本已独立复算，证实高优先emergency类别可压过更好语义/短cue等后续维度，未按个例继续调本版。
