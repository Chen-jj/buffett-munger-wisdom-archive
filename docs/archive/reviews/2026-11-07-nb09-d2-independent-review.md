# NB-09 D2 独立复审：文本与参考稿同档次，最终媒体技术核验通过

日期：2026-11-07（Asia/Shanghai）。审核者：未参与 D2 算法或提示词实现的独立 agent。

## 当前结论与范围

**已独立审读全部 97 个源句及 D2 的 163 个最终 cue。就这段固定样本的文本忠实度、逐屏意义和整体编辑水准而言，D2 已达到与冻结独立稿大体相当的候选水平。** 这不是“每句都比参考好”，更不是零残余、声画同步或人类出版签字。此前 v2 的否定限定、财经术语和机械修订引入的明显断裂已消除；本版仍有下述精确措辞及节奏取舍。

本报告与[此前 v2 的负面复审](2026-11-07-nb09-v2-independent-review.md)分开保留，不撤回旧结论、不把新版本改善写回旧产物。审核只读取实际文件，没有调用 provider，没有编辑字幕、时间、manifest、模型账本或生产代码。

文本结论绑定下列权威稿及 SRT hash。仅渲染的词内/数字单位换行修复已完成，最终媒体补核见末节。本 agent 独立查看了 248、294、540 秒的最终帧，并确认它们与最终 MP4 重取帧的 RGB 像素完全一致；**没有独立播放或核听视频**。负责人对若干时段的静音播放不等于本 agent 独立动态/音频验收。

## 实际工件与版本边界

当前实际资产目录：[NB09-20261107-iteration-v2/cnbc_2000_morning-ch6-7](/Users/drchan/Codebase/buffett-munger-wisdom-archive/output/orchestration-integration/NB09-20261107-iteration-v2/cnbc_2000_morning-ch6-7)。该路径曾用于不同的明确版本，必须结合 hash，不以“同一路径存在”判为同一稿。

本次对应[下游重算证据](/Users/drchan/Codebase/buffett-munger-wisdom-archive/output/subtitle-editorial-comparison/NB09-D2-refresh-preserved-v1/refresh_evidence.json)，其记录是 `downstream_refresh`、不是再次从空根生成；上游由此前真实空根运行产生，本轮复用。该证据内 `/workspace` 是**重算前的旧 v2 取证副本**（旧稿 hash `6f4e36…`），不是 D2 的固定副本。绝对 manifest 路径没有搬迁重签；不能用该旧副本冒称本次结果。

对照：[冻结 175-cue 独立稿](/Users/drchan/Codebase/buffett-munger-wisdom-archive/output/subtitle-editorial-comparison/NB08-reference-v1/reference.cues.json)。其本身也有超时长、快读、风格和不确定专名，不是无误 golden。D2 与它共用声学词锚；源稿唯一已知拼写差异仍是官网证实的 `Seas`→`See's`，时间未动。

## 独立机械核对

- 公开 `SourceChunkPlanDTO`、`ChunkTranslationResultDTO`、`FinalBilingualDraftDTO` 的源链与覆盖校验均通过。1,569 个源词保序、恰好一次，无漏词或重复词 ID。
- 三份 SRT 均为 163 条，逐 cue 回读中文/英文、start/end 与同一权威稿一致。源时间锚与覆盖通过，实际时间无重叠或媒体越界；最短 560ms、最长 6783ms，无超过 7 秒的 cue。
- 后处理报告记录 10 批真实请求、各 1 次请求即采纳；`editorial_generation=completed`、`semantic_review=not_run`。这证明实际执行与有限请求，不证明自动语义审查或语义门禁通过。
- 保留 177 条实际 warning：中文长度 70、英文 CPS 54、非重叠两帧不足 40、中文 CPS 8、基本最短显示不足 3、英文容量 2。没有用改善语义为理由伪报这些指标通过。
- 两条超过 80 字符的英文 cue：s63/c108 为 108 字符，s67/c114 为 89 字符。二者换取条件/金额和“数学优势”整组同屏，在用户允许软指标取舍的前提下属可解释编辑选择；实际字体/版面另核，字符数本身不保证可排。

## 关键问题已在实际 D2 中修复

| 范围 | 实际复审结论 |
|---|---|
| s11，c19–c20 | c19 不再提前显示 0.5%；c20 才说「以比0.5%更亮眼的成绩收官吗」，反问、数值和比较保留。中文句法跨屏，但不交换条件/结果。 |
| s16，c28–c31 | c28 为完整条件起手「比如，如果把所有半年期都拿出来看」，不再尾挂孤立「我」。后续「我知道其中有不少／是下跌的」仍需跨屏读，意义及“假如活得够久”限定完整，未把过往下跌和未来假设改反。 |
| s22，c39–c41 | 两个相关后项都明确「并不完全相关」，最后用「能否实现」，不再加强为完全无关或收窄为何时实现。 |
| s34，c62–c63 | 70%以上与全球业务分母同屏；后屏只给按金额计，恢复了此前 v2 数值/市场分离前的连贯性。 |
| s39，c68–c71 | 8%和伯克希尔同屏，8000万份、每份8盎司、每天及经济利益各有归属，不再留下「其中8%计入」孤屏。措辞“所有”的风险另列。 |
| s47，c79–c81 | 虽然最终编辑将第一界从源逗号前移到 `stretch / is that`，三屏各能接续理解；公司持有的证券与超过净资产的比较整屏保留。它不是原 42 字符规则下的孤立公司名。 |
| s63–s64，c108–c110 | 地震假设、10亿美元损失、考虑签保单、约一周、超过10亿美元及原保险风险完整；s63同屏避免否定及条件错屏。 |
| s67，c114 | 「希望确信自己在每笔交易中都有数学上的优势」保留优势概念，不再只是“有胜算”。 |
| s73–s74，c123–c126 | 双重否定后明确“事实上，我们会”；主动/自愿不冒险和“企业可能发生重大变化”的风险范围完整。 |
| s75，c127 | 不确定性落在“你们以前可能听我谈过”，比参考稿把“大概”落到讲者是否讲过更精确。 |
| s81/s83，c139/c142–c143 | 喜诗糖果术语命中；鳄鱼、鲨鱼、食人鱼与游过去攻城的结果分成两个完整意义组，421ms 原词间隙不变，s84单独保留，不再预先出现“游过去”或重复后果。 |
| s90/s94 | 利润未必高于去年、偶有不高，以及“所有——准确说几乎所有”的收回均明确保留。 |

其余源句也已逐句审读，未发现新增的数字数量级、货币单位、否定反转、条件遗漏或限定反转。人名 Greg Blevins、Moe Spence、Chuck Huggins 等未核实名称保留拉丁文，是当前术语政策下可接受的选择，不强行称音译必然更好。JET、FLM 仍来自不确定源稿，未伪称已核听或已证实为其他专名。

## 残余问题：精度与可读性，不隐藏为“全优”

1. **s39/c68，244555–246617ms，w618–w628：** `for the account of Berkshire` 译为「其中8%归伯克希尔所有」。就后续8000万份饮料及经济利益的比喻，观众可以理解为经济份额归属；但“所有”可能让人误读为对实物饮料的直接所有权。专业编校更宜「其中8%计在伯克希尔名下／是伯克希尔的经济份额」。这是精确措辞风险，不是已证明数值错算；c71的“相关经济利益归……”保留经济层面的解释。
2. **s70/c119，455297–457298ms：** `We try to look at businesses …` 译「我们会考察眼下经营良好的企业」。省去了“尽量/力求”的尝试语气；没有译成“只考察”或“保证”，不构成确定性或排他性反转，仍建议可加“尽量”。
3. **s88/c149–c151，563267–579921ms：** 「对于这种护城河及其能力／也就是保持宽度、令人无法跨越的能力／我们视其为优秀企业的首要标准」。核心维持宽度、不可跨越和首要标准都在，但“能力”重复且主语较生硬；参考稿更顺。属口语编辑不足，不是遗漏。
4. **s18/c34–c35：** 中文“几次”在c34出现，而英文 `a few times` 位于c35。全句忠实且两个词组只隔20ms源间隙，但这是定量限定跨屏前置，不能宣称所有中文成分都严格位于对应英语词组屏内。参考稿的词范围把它同前组显示，D2若追求逐屏精确还能改善。
5. **仍有有意保留的短屏和跨屏句法：** s9的短回应、s80的问题起手、s95呼名及 s58比较宾语等不都达到最理想的独立屏阅读。它们没有漏义、重复断言或极性倒置；不得为消除 warning 删掉呼语、篡改源时间或悄悄缩减信息。

这些残余不足以重现旧版的明显错屏/反义，也不证明每条都需新增模型调用。独立参考本身存在不同的同类风格取舍；本版的整段文本候选可以接受，同时保留上述可编校项，而非宣称逐句全面胜出。

## 固定正文与最终媒体 hash

| 工件 | SHA-256 |
|---|---|
| [source_alignment.json](/Users/drchan/Codebase/buffett-munger-wisdom-archive/output/orchestration-integration/NB09-20261107-iteration-v2/cnbc_2000_morning-ch6-7/source_alignment.json) | `2e9fe1dfb65fdd28585d8f8a0c1a8bb6946424fe38b9119a88c51717112f3925` |
| [source_chunks.json](/Users/drchan/Codebase/buffett-munger-wisdom-archive/output/orchestration-integration/NB09-20261107-iteration-v2/cnbc_2000_morning-ch6-7/source_chunks.json) | `ba2f91fb7c988a2a1bb6e38f1b9558fd34f748bd24f4ad1f898cf7c819bdd0c8` |
| [translation_result.json](/Users/drchan/Codebase/buffett-munger-wisdom-archive/output/orchestration-integration/NB09-20261107-iteration-v2/cnbc_2000_morning-ch6-7/translation_result.json) | `a02448f0f35e9448504e80e9629d3b563b7f88f14fd5263d549819b827409429` |
| [final_bilingual_draft.json](/Users/drchan/Codebase/buffett-munger-wisdom-archive/output/orchestration-integration/NB09-20261107-iteration-v2/cnbc_2000_morning-ch6-7/final_bilingual_draft.json) | `06bbcea7a2af4e1c92753676037d221c94ffd0c7808fc4360b881539e0d404d9` |
| [bilingual.srt](/Users/drchan/Codebase/buffett-munger-wisdom-archive/output/orchestration-integration/NB09-20261107-iteration-v2/cnbc_2000_morning-ch6-7/bilingual.srt) | `33e2d54ef5326b65710c40d4bda21e84467e76cd46265e9cabbbabfd6ad802dd` |
| [bilingual.ass](/Users/drchan/Codebase/buffett-munger-wisdom-archive/output/orchestration-integration/NB09-20261107-iteration-v2/cnbc_2000_morning-ch6-7/bilingual.ass) | `0ade56fdfd02d087f3c7ef835c5621e8f8d981834ecbbbd6a8fce924add72225` |
| [最终烧录视频](/Users/drchan/Codebase/buffett-munger-wisdom-archive/output/orchestration-integration/NB09-20261107-iteration-v2/cnbc_2000_morning-ch6-7/video_中文字幕.mp4) | `75b8a1eae0a7fecd621fd5095fdbdbfdc7ba76f6ac2f180c3816999764d33ca3` |

## 最终仅渲染回归与复用补核（21:31–21:34，Asia/Shanghai）

- 独立重新计算上表 hash；权威稿、初译、source chunks 和 SRT 均与文本审读版本相同。重新运行公开 DTO 源链验证，1,569 词保序覆盖、163 cue 无实际重叠、三份 SRT 正文/时间精确回读均通过。渲染 plan 的中英文 SHA-256、每条 start/end 与权威稿一致；163 个 ASS event 的百分秒投影时间与 plan 完全一致。
- [仅渲染刷新证据](/Users/drchan/Codebase/buffett-munger-wisdom-archive/output/subtitle-editorial-comparison/NB09-D2-renderfix-preserved-v1/refresh_evidence.json)记录 translation、bilingual_postprocessing、srt_export 全复用，provider 调用与 SRT 写入均为 0，仅 subtitle_rendering 执行；`upstream_unchanged=true`、`unexpected_changes=[]`。取证副本的历史路径仍不重签为新运行工件。
- 最新[集成及复用证据](/Users/drchan/Codebase/buffett-munger-wisdom-archive/output/orchestration-integration/NB09-20261107-iteration-v2/integration_evidence-20261107T084723-eb03734d3d48.json)：`20261107T084723-eb03734d3d48`、同进程 `20261107T084742-1ab6c65d4494`、独立新进程 `20261107T084801-3299beff5676` 三份回执均有九阶段 reused、全部计数 0、无工件改写。独立对当前 84 个保护条目逐项复算 hash/大小/mtime，全部与记录一致；记录的只读 verify 也为不变。
- ffprobe 实测最终文件为 H.264、640×360、623.000000 秒，AAC 音轨 623.000000 秒。独立解码源视频和最终视频的音频 PCM hash 均为 `cd969c191f3f960c13e224ed5b5a88edd6e7622e2b6c3293c04bdaacb5f03030`。这是音轨未改变的技术证据，不是已核听或已确认原发音/语义同步。
- 独立查看最终保存帧，并从最终 MP4 相同时间重新提取逐像素比较：
  - [248.0 秒](/Users/drchan/Codebase/buffett-munger-wisdom-archive/output/subtitle-editorial-comparison/NB09-D2-final-review/media/248.0.png)：数字/单位「8盎司装」完整留在同一中文视觉行，不再在 8 与单位之间断开；英文为两行、在画面安全范围内。
  - [294.0 秒](/Users/drchan/Codebase/buffett-munger-wisdom-archive/output/subtitle-editorial-comparison/NB09-D2-final-review/media/294.0.png)：中文「有价证券价值」中的「价值」完整，断点在其后，不再拆为「价／值」；中英文分别两行，字幕未覆盖人物面部。
  - [540.0 秒](/Users/drchan/Codebase/buffett-munger-wisdom-archive/output/subtitle-editorial-comparison/NB09-D2-final-review/media/540.0.png)：攻打城堡的完整结果同屏，中文一行、英文两行；该静态时刻未见裁切/遮挡。
- 最终渲染报告：succeeded、0 error，实际字体/字形、ASS 往返、逐 cue 像素预检和输出媒体检查均记录通过；36 个四行 cue，最大宽 575px、高 126px。216 条 warning = 177 条上游告警 + 39 条 ASS 投影间隔不足；本 agent 没有独立重做整段逐 cue 像素预检，只独立核看上述三帧及其与成片的一致性。

**最终独立结论：本段 D2 的文本候选与参考稿整体同档次，最终成片的来源、三 SRT/ASS 投影、媒体基本安全及复用证据通过独立核对；保留本文精确措辞和节奏残余。** 三帧与技术检查不能替代动态播放、核听、疑似专名确认或人类出版签字；本报告不把这些范围写成已通过。
