# NB-09 v2 独立产物复审：技术链路通过，编辑质量仍未达独立稿水准

日期：2026-11-07（Asia/Shanghai）。审核者：非本轮生产算法作者的独立 agent。

**结论：不认定本版达到冻结独立稿或专业编辑发布水准。** 已修复若干实质错屏，且完整真实链路与两种复用有证据；但机械修订又引入了新的主语、归属对象断裂，s22 的否定限定和 s67 的财经措辞风险仍在。指标改善和可烧录不等于编辑质量通过。后续 D2 候选不属于本报告范围。

## 审核对象及保留方式

- 原运行根：[NB09-20261107-iteration-v2](/Users/drchan/Codebase/buffett-munger-wisdom-archive/output/orchestration-integration/NB09-20261107-iteration-v2)。原规范资产目录：[cnbc_2000_morning-ch6-7](/Users/drchan/Codebase/buffett-munger-wisdom-archive/output/orchestration-integration/NB09-20261107-iteration-v2/cnbc_2000_morning-ch6-7)。该目录将显式用于后续下游重算，不能仅凭同一路径认定仍是本版。
- 固定审计副本：[NB09-v2-v4-preserved](/Users/drchan/Codebase/buffett-munger-wisdom-archive/output/subtitle-editorial-comparison/NB09-v2-v4-preserved)，及其[保留证据](/Users/drchan/Codebase/buffett-munger-wisdom-archive/output/subtitle-editorial-comparison/NB09-v2-v4-preserved/preservation-evidence.json)。独立复算其中 90 个条目的 SHA-256、大小、mtime，全部与保留证据一致。
- 副本内 manifest 保留原绝对路径，**仅为取证快照，没有重签或改成可在新根运行的复用工件**。后续阅读本报告应优先使用副本和下列 hash。
- 文本参考：[冻结 175-cue 独立稿](/Users/drchan/Codebase/buffett-munger-wisdom-archive/output/subtitle-editorial-comparison/NB08-reference-v1/reference.cues.json)。该稿也是待编辑参考，不是声画/出版签字 golden。另对照 v1 的初译及最终稿，不以“比 v1 好”替代与源文核对。

## 实际审核和验证范围

审读全部 97 个源句的英文、初译、最终稿及与独立参考的差异，重点复核数字、否定、条件、比较、专名与逐屏归属。对 165 个最终 cue 做公开 DTO 来源链/覆盖验证及三份 SRT 精确回读。

- 源稿 1,569 个词保序恰好一次；全部 chunk 与初译 ID 一一对应。源稿与 NB-08 的唯一词差异为 w1322 `Seas` → 官网支持的 `See's`，起止时间、ASR ID 不变；对应 s81 正文重建，其余源句和顶层字段相同。
- `SourceChunkPlanDTO.validate_against_alignment`、`ChunkTranslationResultDTO.validate_against_inputs`、`FinalBilingualDraftDTO.validate_against_inputs` 均通过。
- 英文、中文、双语 SRT 共 165 条，编号顺序、正文及 start/end 与权威稿逐 cue 一致，无实际重叠或媒体越界。最短 560ms，最长 6783ms。
- [集成证据副本](/Users/drchan/Codebase/buffett-munger-wisdom-archive/output/subtitle-editorial-comparison/NB09-v2-v4-preserved/integration_evidence.json)记录完成 run `20261107T031920-260bd972e199`；同进程 `20261107T034534-25bacc75a649`、新进程 `20261107T034552-e02d7f2628e9` 均 reused。独立核对两份回执：每阶段昂贵调用/工件改写计数为 0，`observed_artifacts_changed=[]`；证据记录只读 verify 不变。

## 已确认的实质改善

| 范围 | 实物结论 |
|---|---|
| s11，c19/c20 | 0.5% 只在对应英语含该数值的 c20 出现；v1 的数字提前一屏已消除。反问和比较仍在。 |
| s47，c79–c81 | 两个源逗号分成 61/36/71 字符；有价证券及其超过净资产的比较同屏，译为「有价证券价值一直超过其净资产」。 |
| s63–s64，c108–c111 | 加州地震的假设、10 亿美元、超过 10 亿、约一周、考虑而非已签发，以及原保险风险均保留。s63 跨屏表达稍拗口，但未发现金额或条件反转。 |
| s74，c126–c128 | 末屏「企业可能会发生重大变化」恢复风险中的不确定性，不再是 v1 单屏的确定预测。 |
| s81，c141 | 官网支持的 See's 与现有声学词锚关联，中文「喜诗糖果」；不是翻译阶段猜测 ASR 拼写。 |
| s83，c144/c145 | 放入鳄鱼、鲨鱼、食人鱼与「别人想游过去攻打城堡就越来越难」各一完整屏；后屏从 537894ms 开始，前屏止于 537473ms，421ms 间隔。v1 的预先显示「游过去」及下一屏重复结果不再出现。s84 也未被拼入 s83 尾部。 |

## 仍阻止编辑质量等同的实物问题

### 1. s22 的限定范围被加强（实质忠实度问题）

- c40，w357–w366，137887–143873ms：英文 `and really is not totally connected to most business activities,`，中文保留「并不完全相关」。
- c41，w367–w379，145414–148875ms：承接同一限定的英文 `uh or the fruition of most investment ideas, or anything of the sort.`，中文变成「跟大多数投资想法**何时实现**或诸如此类的事情**也无关**」。
- `not totally connected` 不应在并列后项变成完全无关；`fruition` 的实现/见效也被收窄为“何时”。初译和最终稿相同，机械修订没有覆盖此实质风险。参考稿保持「也不是都和它相关」。可编辑方向是明确保留「能否实现」「也不完全相关」，而不是补新事实。

### 2. s16 的机械修订引入孤立主语（新增切分退步）

- 初译 k28 为「比如，把所有半年期都拿来看，」，下一屏从完整「我知道……」开始。
- 最终 c28，w225–w234，92619–95340ms：`if you took all the half-year periods, for example, I` →「比如，算上所有半年期，**我**」。
- c29，w235–w244，95960–98961ms 才开始「**知道**其中有一些是下跌的，而且」。它消除了一个机械触发，却把主语与谓语分开，并把“而且”悬在屏尾；相对初译和参考都是阅读退步。不能仅因触发计数 1→0 判为编辑通过。

### 3. s39 的 8% 与归属对象被拆开（新增切分退步）

- 初译同屏为「其中8%算在伯克希尔账上，所以」。
- 最终 c68，w618–w625，244555–245896ms：「其中8%计入」；c69，w626–w638，245936–250940ms 才从「伯克希尔账下，所以每天超过8000万份、每份8盎司的软饮料」接续。
- 数值没有丢失，也没有错算 8000 万份或 8 盎司；问题是百分比归属被切断，并把专名挤到后屏的数量说明里。参考稿及初译更清楚。

### 4. s67 的“优势”被弱化为“胜算”（术语/语义风险）

- c116，w1048–w1060，434486–438729ms：`we want to think that we've got a mathematical edge in every transaction.` →「我们希望每笔交易在数学上都有**胜算**」。
- 在此前保险风险与此后大量交易的期望结果语境下，`edge` 是有利的数学优势，不只是有获胜可能。v1 及参考均保留“数学上的优势”。此处建议恢复优势概念，不应仅为口语化改窄；这不是新增财务建议。

### 5. 可辩护但仍需编辑取舍的断点

- s34 的 70% 从原初译的完整全球刀片/剃须刀市场屏，变成 c62「吉列的份额超过70%」，c63 才给全球市场及按金额口径。两屏间真实有 1301ms 停顿，故不判为必错，但数值与分母分屏，不是仅靠空帧指标就能证明更好。
- s58 最终 c95 的主体和提升内在价值已合在一屏，较初译「伯克希尔及其」断开好；c96/c97 仍需把「至少和／计算净现值的能力同样重要」跨屏读完。意义完整，不把它列为遗漏。
- 正式保留 3 个低于 834ms 的 warning：c17 560ms「不过请讲。」、c139 640ms「那问题是：」、c163 800ms「查理？」。不删除呼语或伪造词时间来凑指标。

## 指标与样片证据的边界

最终权威稿/SRT 共 **154 条 warning**：中文长度 62、英文 CPS 56、非重叠两帧不足 32、显示过短 3、中文 CPS 1。后处理 23 个窗口、44 次实际请求，16 个采纳；请求数/采纳数不代表语义改善数。

渲染报告为 succeeded、0 个 error，实际字体/字形、ASS 往返、逐 cue 像素预检及输出媒体检查均标通过；32 个四行 cue，最大实测宽 575px、高 126px。报告额外列 31 个 ASS 投影间隔不足，合计 185 条 warning。以上是独立读取报告及正文/时间证据，**本 agent 未自行观看或核听实际视频，未独立复做像素检查或音频同步验证**。不能以文字、帧图或报告代替核听，也未取得人类出版签字。JET、FLM 等源稿疑似专名继续属于待核验上游限制，不应悄悄猜改或虚报已验证。

## 固定审计文件与 SHA-256

下表链接均指保留副本；原对应工件位于上述原规范资产目录。

| 工件 | SHA-256 |
|---|---|
| [source_alignment.json](/Users/drchan/Codebase/buffett-munger-wisdom-archive/output/subtitle-editorial-comparison/NB09-v2-v4-preserved/cnbc_2000_morning-ch6-7/source_alignment.json) | `2e9fe1dfb65fdd28585d8f8a0c1a8bb6946424fe38b9119a88c51717112f3925` |
| [source_chunks.json](/Users/drchan/Codebase/buffett-munger-wisdom-archive/output/subtitle-editorial-comparison/NB09-v2-v4-preserved/cnbc_2000_morning-ch6-7/source_chunks.json) | `ba2f91fb7c988a2a1bb6e38f1b9558fd34f748bd24f4ad1f898cf7c819bdd0c8` |
| [translation_result.json](/Users/drchan/Codebase/buffett-munger-wisdom-archive/output/subtitle-editorial-comparison/NB09-v2-v4-preserved/cnbc_2000_morning-ch6-7/translation_result.json) | `700c364bbc961e8debeb4b37f7fd351be0aaac2caef640c860b0205decbac7ac` |
| [final_bilingual_draft.json](/Users/drchan/Codebase/buffett-munger-wisdom-archive/output/subtitle-editorial-comparison/NB09-v2-v4-preserved/cnbc_2000_morning-ch6-7/final_bilingual_draft.json) | `6f4e36b4fec34e25f75489fb7a928bf62e30dfe4886e395ad84315a7560094c3` |
| [bilingual.srt](/Users/drchan/Codebase/buffett-munger-wisdom-archive/output/subtitle-editorial-comparison/NB09-v2-v4-preserved/cnbc_2000_morning-ch6-7/bilingual.srt) | `c5f2ba2d2c04240be2e7da8f855783bd8421f44decc943c9b1b31967ad2b59e7` |
| [bilingual.ass](/Users/drchan/Codebase/buffett-munger-wisdom-archive/output/subtitle-editorial-comparison/NB09-v2-v4-preserved/cnbc_2000_morning-ch6-7/bilingual.ass) | `7d21687fea993102ff66d622eeb97d77624ab3e5a2814461ebb35266792323f0` |
| [烧录样片](/Users/drchan/Codebase/buffett-munger-wisdom-archive/output/subtitle-editorial-comparison/NB09-v2-v4-preserved/cnbc_2000_morning-ch6-7/video_中文字幕.mp4) | `d851f5bff6522c39cdeb00df36047931c7352aa482ca022047bee749631eca13` |

本次只新增复审文档，没有改动代码、字幕、音视频、manifest 或修订账本，没有调用模型。下一候选须独立审核其实际产物，不能沿用本版技术通过来替代质量结论。
