# 语义证据契约与可执行实验协议（设计稿）

- 状态：proposed；未增加 ArtifactType、DTO、provider、planner 或测试入口。
- 配套：[根因与方案](2026-10-24-bilingual-semantic-alignment-design.md)、
  [ADR-0007](../archive/decisions/0007-bilingual-semantic-alignment.md)、
  [编排 ADR-0008](../archive/decisions/0008-local-orchestration-and-integration-tests.md)。
- 下述名字/JSON是待冻结的契约提案，不是当前代码已接受的工件格式。模型审阅资料与真实样片
  放在获批后的 gitignored 唯一实验目录，不提交生成资产；本轮文档中的审读摘录用于解释设计。

## 1. 三种关系不要混为一个 fragment

| 层 | 保存什么 | 允许什么 | 不证明什么 |
|---|---|---|---|
| 语义图 | 源/译文节点、对应边、作用域/上下文、遗漏/歧义 | 交叉、多对多、同一支持词被多边引用、非连续源范围 | 可保序显示、时间正确、模型判断正确 |
| 共同显示块 | 顺序块、每语言消费范围、允许合并边界、证据/评审hash | 合并语义原子；只在明确可分边界拆 | 不能仅因节点coverage完整就称同义 |
| 定时cue | 合法块组合、word锚点、逻辑正文、时间调整方法 | 确定性时间/容量与有限延长 | 不替代语义复审或听音 |

语义“支持边覆盖”与显示“消费守恒”是两套校验。前者可一词多义、多词一译；后者英文词、
被选译文的规范字符按顺序恰好显示一次。不能为图的度数守恒复制词，也不能为显示保序删掉交叉边。

## 2. 公共工件及最小绑定

拟由 archive_core 登记以下规范名，所有输出由 `build_asset_workspace(asset_id, new_output_root)`
生成。输入在 origin workspace 验证，异根绑定按ADR-0008，不重写旧manifest。

| 文件 | 提议 schema / 用途 |
|---|---|
| semantic_alignment.json | `semantic-alignment.graph.v1`，冻结语义图与候选共同显示块，无最终时间 |
| semantic_alignment_review.json | `semantic-alignment.review.v1`，独立审阅、问题、覆盖与决定 |
| semantic_alignment_report.json | `semantic-alignment.report.v1`，机械发现/成本计数/失败原因 |
| semantic_alignment_manifest.json | `semantic-alignment.manifest.v1`，阶段技术成功、整套证据与身份 |
| translation_revision.json（仅显式改译支路） | `translation.revision.v1`，父译文与新变体逐句变更理由/溯源 |

manifest 的 `status=succeeded` 只表示语义阶段技术工件完整。`review.disposition` 另取
`pending / approved_for_experiment / accepted / rejected`，并绑定**精确 graph SHA**。
生产消费需 `accepted` 且无未关闭关键问题；候选研究渲染需 `approved_for_experiment` 和明确profile。
不能把 pending 当 warned success 送入生产，也不能为了兼容旧DTO假造 proportional mapping_method。

输入证据至少含：asset ID、origin workspace identity、transcription manifest、source alignment、
translation manifest/result 的 path/size/hash；改译支路再绑定父/新 translation result 与 revision
manifest。graph引用具体输入hash，review绑定graphhash，manifest绑定graph/review/reporthash。
provider/prompt改变或译文改变不得命中旧key，reviewer改变只重审，不强制重生成旧graph。

## 3. 具体图示例：s17的译序交叉

这里是**有意缩略的schema示例**，不是可直接发布的完整JSON；省略的顶层证据须由正式实现补全。
英文范围端点word ID均包含；中文为sentence-local Unicode codepoint半开范围。

```json
{
  "schema_version": "semantic-alignment.graph.v1",
  "asset_id": "cnbc:2000:morning",
  "text_view": "fixed-layout-whitespace.v1",
  "sentence_id": "s17",
  "source_nodes": [
    {"id": "e1", "spans": [{"first_word_id": "w268", "last_word_id": "w271"}]},
    {"id": "e2", "spans": [{"first_word_id": "w272", "last_word_id": "w274"}]},
    {"id": "e3", "spans": [{"first_word_id": "w275", "last_word_id": "w287"}]}
  ],
  "target_nodes": [
    {"id": "z1", "start_offset": 0, "end_offset": 8},
    {"id": "z2", "start_offset": 8, "end_offset": 26},
    {"id": "z3", "start_offset": 26, "end_offset": 33}
  ],
  "links": [
    {"id": "l1", "source_node_ids": ["e1"], "target_node_ids": ["z3"], "kind": "predicate", "boundary_effect": "co_display"},
    {"id": "l2", "source_node_ids": ["e2"], "target_node_ids": ["z1"], "kind": "qualifier", "boundary_effect": "co_display"},
    {"id": "l3", "source_node_ids": ["e3"], "target_node_ids": ["z2"], "kind": "claim", "boundary_effect": "co_display"}
  ],
  "issues": [{"code": "target_order_crossing", "link_ids": ["l1", "l2", "l3"], "status": "needs_review"}]
}
```

对应文本分别为 `It's been a fluke,` ↔“只是碰巧而已。”，`to some degree,`↔“从某种程度上说，”，
后续命题↔“我们的内在价值一直没有出现下滑年份，”。这不是三个可直接保序显示的cue。
“碰巧”与命题的指代作用域需再审，示例边不是模型已通过的语义证明。

非连续/多对多关系举例（真实s74）：w1169–w1171与w1175–w1176共同支持“我们不会有意地…涉足”；
中间 w1172–w1174 对应中文插入的“或心甘情愿地、自愿地”。正式图可用多个源span及多个目标
node ID表示关系，不能取最小/最大word构成一条连续链接、吞掉中间词而不留其独立关系。
具体中文offset以[独立审读](2026-10-24-independent-bilingual-semantic-audit.md)冻结表为准。

### 3.1 ID、字符与coverage

- source节点是既有w IDs的分区；source span按源顺序排列，不重编号、不重推时间。非连续节点
  间可穿插其他节点，但总词消费分区仍恰好一次；链接可引用节点集合。
- target节点按所选完整句译文形成不重叠完整分区；标点/空白明确归属，不凭strip后长度守恒。
- 保存 raw translation SHA、每句raw text SHA、normalized text SHA和 `text_view` 版本，以及
  raw↔normalized offset map；范围只能用于声明的view。新变体用自己的offset，不沿用旧offset。
- links至少区分对应、上下文、作用域、源无词面对应、目标语法显化。语义无词面对应不表示源词
  可从显示中删除；无法解释的遗漏/增义是issue，不自动标成null-link合格。
- `boundary_effect=co_display` 的关键意义不得分在不同显示块；`context_only` 可跨块但要保存
  允许continuation的理由和review。不能把所有语法依赖强制合并，也不能把否定作用域降成context逃避门禁。
- section/speaker/null从上游查得并核验，模型不生成/修补标签；禁止跨section或混合不同已知speaker。

作用域须有typed记录而非只有自由文本：例如 `scope_id / kind=negation|condition|comparison /
operator_source_node_ids / governed_source_node_ids / operator_target_node_ids /
governed_target_node_ids / boundary_effect / evidence_link_ids`。s74的共同否定要显式关联
三个意愿副词与涉足；s22关联程度的否定要指明管辖的关系及列表，不仅统计“不”的出现次数。
schema只能验证引用/类型/完备声明；作用域是否判断正确仍由独立审读验收。

### 3.2 从图到可显示块

先针对co_display链接检查候选边界是否把某一意义的两语言支持分到两侧；交叉时合并两语言
相应连续区间，并把被包围的中间节点纳入，重复直到闭合。不是仅做有向SCC，也不是分别切好再比例配对。
闭合块可以再按**已评审可分的子关系**细化，不能只因为太长而机械切它。
所有可显示块按两语言的显示顺序恰好一次消费；一个块可多片段，但句边界与speaker保留。
基础时间由其实际连续消费的首词start/末词end导出，不能用不连续支持集合的hull掩盖未消费词。

确定性srt阶段在这些允许边界内求可行组合；CPS/节奏/长度仅在语义可行集内排序。
当前pause-only、EN2×42、section/speaker、延长规则均以明确profile校验。无解返回
`semantic_display_infeasible` 与最小冲突集合（链接、容量、停顿约束），不回退比例算法。
跨句组合仍沿v3救援资格：首fragment原始<834ms且在下一源词/媒体边界内合法单独延长后仍短，
每个被跨越的原始句间gap<500ms，所有后继fragment完整消费其原句两语言；不能偷下一句开头，
CPS高本身不赋予资格。语义相关不是放宽该规则的授权；若新方案确需改变，须另profile/明确批准。

## 4. 译文变体、身份与审核

固定译文首轮不变。若选择B/C，translation新用例以完整section/句为上下文接收源块要求，输出
独立完整 `translation_result.json` 变体及revision sidecar，仍不决定最终cue/time。
revision至少记录 parent result SHA、每句 old/new text SHA、变更源word IDs、请求hash、原因、
生成identity和审阅决定；所有句子完整保留，未改句字节不变，拒绝信息删减/数字否定改变。
新译文是新的输入版本，不要求与旧中文逐字符守恒，但要求对英文的意义完整性独立验收；
下游显示只对**被选的新版本**做字符守恒。保留旧译文及全部历史manifest，不更新其签名。

模型溯源保存 provider、实际model/可得revision、generation parameters、prompt version/bytes SHA、
响应schema version/SHA、tokenizer/aligner/dictionary identity（如使用）、调用ID（可空）、usage
（可空）、request/input hashes和chunk ownership表。无法得知服务端revision则明示unknown，
冻结输出可复用但不承诺重新调用字节相同。自报confidence为可空观测值，绝不用于自动放行。
独立review保存 reviewer实际identity/prompthash、只读输入列表、blind-to-candidate标识、
覆盖句/锚点、具体finding、disposition和理由；“第二个GPT同意”不等于人类事实认证。
每个issue应包含 `issue_id / severity / graph_sha256 / anchor_or_scope_ids / status=open|resolved|waived /
resolution_evidence_refs / resolver_identity / decision_policy_version`；关闭凭证绑定具体修订图/复核记录，
旧图上的resolved不能自动继承到新图。accepted要求关键问题均有可核验关闭凭证；非关键waiver
也需明确授权理由，不能单改顶层disposition绕过问题列表。人类release决定仍在另一个轴。

## 5. 成本、checkpoint与失败语义

1. semantic阶段先按section给足上下文；首次实验9句、扩展97句。大文档可预先确定完整句owned
   window＋只读重叠context，边界/ownership进入请求hash；超限显式失败，不静默丢context。
   该分窗能力只属于新semantic用例，不改变translation v1的完整section请求规则。
2. `cache_key = SHA256(canonical inputs + owned/context IDs + text_view + provider/model/parameters
   + prompt bytes/version + response schema + aligner identity + policy)`；review用独立key再绑定graphhash。
3. 结构/coverage合格的单请求可存私有candidate checkpoint，即使语义待审；stage完成与review
   accepted另判。损坏/拒答/截断结果不可当有效checkpoint；诊断可留独立失败记录，不做正式输出。
4. 显式设置请求/attempt/token预算与超时；不知道实际tokens就记null，不推测为0；本轮不承诺价格。
   9句初试建议最多一轮生成＋一轮独立复核，另一次修订须人工批准，禁止自循环“生成直到通过”。
5. 只对原请求的临时连接/限流错误有限重试；schema/coverage/语义无解不自动repair/fallback。
   输出candidate、review和正式发布分离，失败保留证据，report写失败不覆盖旧成功代次。
6. 同一新workspace排他串行；正文临时写/回读后manifest-last。文件发布失败保留残留，旧成功
   manifest不能证明混合代次成功；不自动rollback或删除。输入/profile变更新run/root，默认冲突只读。
7. 冻结输入、输出、review/profile相同的复用必须0 provider/0 planner/0 encode/0 stage写；
   新的一次编排审计receipt可写到新run目录，但不能把此写入叫“全运行零写”。严格验证模式连receipt也不写。

## 6. 实验阶梯：本轮做了什么、下一轮怎样执行

| 实验 | 输入与操作 | 隔离/批准 | 产物与停止条件 |
|---|---|---|---|
| E0 已执行 | 9句原始对应；4反馈追踪；旧片12帧；公共DTO/证据只读核验 | 无昂贵调用/重规划 | 独立审读、根因报告；30s/86s听音未闭合 |
| E1 待批准 | 独立审读全部97句；标关键锚点和允许语义块，不看旧cuts | 新冻结review，不改旧参考 | 每句status与理由、复核分歧；参考不是golden |
| E2 待批准 | 相同9句对比A GPT、E aligner/hybrid；B上下文分块翻译；C联合生成；D独立窗口纸面候选 | 预算/固定模型/唯一新root先冻结；原译文不写回 | 冻结各原始提议；机械可行性/语义/成本分别计；一轮失败不靠调权掩盖 |
| E3 待批准 | 候选对全部97句及**未参与调参的新样本**运行 | 不在旧97句上挑胜后再改公式；新样本先登记 | 按类型/句公开全部结果与失败，不只看4例 |
| E4 待批准 | 新编排集成使用获选冻结semantic/translation版本→srt→真实render | 依赖ADR/实现/离线通过；授权烧录完整623秒 | 持久新样片、所有sidecars、来源receipt、同进程/新进程复用 |
| E5 待批准 | 非作者agent独立审查E4输出；人类完整播放 | 先冻结review，再揭示候选结论；读实际产物不抄runner报告 | 机器证据、文本/帧/音画能力范围分别签；人类未签则非出版通过 |

未调参样本建议预登记另一来源/不同问答，含数字单位、否定作用域、译序交叉、长专名、
speaker/null、无sections、快速讲话与长停顿。先清点已有合法工件；缺输入就报告缺失并申请
独立准备预算，不重跑本次transcription、不用合成样本冒充真实泛化。合成对抗题只测机械契约。

### 6.1 预先冻结的指标/判据

以下为**实验建议阈值**，不是已经批准的新生产政策。不能在看候选结果后改阈值来过关。

- **机械硬门禁**：输入/工具身份、所有word/所选中文字符覆盖、无重排/错句、section/speaker/null、
  时间单调/无重叠/媒体边界、首末词锚点、最多500ms总延长、EN实际2×42、当前中文pause-only、
  v3跨句救援资格及后继整句完整消费、SRT/plan回读、ASS投影≤5ms、安全区与中英各≤2视觉行/
  共≤4行。新政策只能另profile显式比较。
- **关键锚点**：独立审读登记专名、数字单位、否定、主体/谓语、条件/转折及scope；每一项有
  source span、target span、允许的完整语义窗口及证据，不是字符串列表。计划必须100%登记/审阅，
  不允许未关闭关键漏译/增义/极性或跨错cue问题；人工/模型分歧记pending，不当通过。
- **提前/滞后**：对每锚点记录 `visible_start - source_support_start`、
  `visible_end - source_support_end`、支持区间被正确中文可见区间覆盖的比例。报告signed值、
  中位/p95/最大及具体句，不把较大块内的名称提前显示都判错，也不让合并整句把偏差指标洗成0。
  先按独立标注的“允许完整语块窗口”判错；此外关键锚点晚>250ms、早>1000ms列强制复核项，
  不是未校准的自动语义硬阈值。4例必须逐项闭合，不以平均值掩盖。
- **尾词提前消失**：逻辑end不得早于末词end；ASS量化单列，实际帧按覆盖区间而非只比较帧PTS。
  每个关键尾词的局部听音标注若可得，成片可见区间不得先于确认发音结束（量化/帧容差单列）。
  30s目前仍unknown，必须补核听；86s若无源支持，标upstream_coverage_review，不生成假时间。
- **gap/闪烁**：逐边界列原词gap、逻辑gap、ASSgap、实际相邻帧状态；0~两帧及不能合法收紧
  的gap遵守当前规则，不截词腾间隔。记录所有<834ms、阅读期间过密换屏，连续播放再判断闪烁。
- **阅读/自然语块**：中文16/7秒/9CPS、英文17CPS均逐cue报告；最差例、告警分布和语义闭合
  共同审读，不以减少cue数或告警为胜出；没有新增10秒硬帽。标点/否定悬挂由独立语义审读判断。
- **像素/媒体**：逐cue真实libass非空alpha/字体身份/安全区、最宽/最长/四行/底部复杂画面；
  全片probe、全部音频stream与packet payload/PTS/duration、视频PTS/时长；静帧不能证明音画同步。
- **保全/复用**：所有旧资产和输入（包括链接目标）SHA/size/mtime前后相同；首次成功→同进程→
  独立进程复用，stage写/生成调用/编码均0；中断/错hash/混合代次必须失败。新workspace不得覆盖旧样片。

### 6.2 比较与胜出规则

先过滤机械不合法方案，再比较关键意义错误/未决数、逐锚点时差和自然语块；随后比较阅读/像素、
完整性和成本。改译方案单列翻译质量与变更成本，不与固定译文假称同约束胜出。独立窗口单列
不同步换屏次数、并发状态行数和重复阅读负担。容量/标点放宽的方案另列，不混入旧profile通过率。
若无候选同时达到质量与显示预算，结论必须是“需取舍/无解”，而非选最低错误率后宣称完成。

### 6.3 独立agent样片回归协议

未来review agent不参与候选生成/调参，使用两阶段输入包：A只给原始source alignment/所选完整
译文及其来源hash，不给semantic graph、plan、cue/SRT、receipt结论或成片；先独立列语义对应/
问题并冻结审读hash。B再给真实编排receipt、输入/输出公共工件、所有候选证据和成片路径，
对照候选块。独立重算来源链、投影、reuse/protection计数，不能只读 `status=succeeded`。
核看全部cue文本、所有边界帧/风险片段、最长与四行等；对音频
若有实际处理能力就记录核听区间、工具、时间锚点，否则明确“未听音”，交人类完成整片播放。
结果分 `chain_technical / semantic_text / visual_sample / audio_sync / human_release` 五轴，
每轴pass/fail/pending/not_run；任何后两轴未完成都不得写“整体质量通过”。
