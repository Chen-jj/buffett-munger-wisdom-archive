# ADR-0007：显式双语语义证据与确定性联合字幕规划

> 2026-11-17归档说明：superseded历史候选，未实施；按被替代路线归档，不冒称技术或质量完成。 原路径`docs/decisions/0007-bilingual-semantic-alignment.md`；原状态、历史不commit/push约束及验证结果属于当时记录。后续入口：[NB-12](../../tasks/NB-12-chunking-quality-iteration.md) / [ADR-0013](../../decisions/0013-typed-chunking-quality-and-regression.md)。

- 状态：**superseded / 历史候选，已由 ADR-0008～0012 的路线替代，未实施**。
- 2026-10-28补记：用户要求先搁置本方案、重新调研业界。独立语义模块与固定译文后对齐不再是
  预设主线；与字幕模板约束的上下文翻译、联合生成等路线比较后再决定。本ADR保留为历史候选，
  不按下文直接实施。最新依据见[业界调研](../../reviews/2026-10-28-industry-bilingual-subtitle-pipelines.md)。
- 日期：2026-10-24。
- 影响：`archive_core`、拟新增 `semantic_alignment`、`translation`、`srt_processing`、
  `subtitle_rendering`；编排接入见[ADR-0008](0008-local-orchestration-and-integration-tests.md)。
- 依据：[研究报告](../../reviews/2026-10-24-bilingual-semantic-alignment-design.md)、
  [独立原始文本审读](../../reviews/2026-10-24-independent-bilingual-semantic-audit.md)、
  [契约/实验](../../reviews/2026-10-24-semantic-contract-and-experiments.md)。

本文以下保留历史推导，不是当前实施规范；从 [ADR-0008](0008-local-orchestration-and-integration-tests.md) 进入现行方案。

## 1. 背景与问题

用户观察中英文音轨/词时间准确，而中文停顿优先＋比例词范围映射造成公司名、主干、否定等
跨cue漂移。独立审读发现固定中英译序交叉：s17、s22、s48、s74、s88等不能仅靠反转优先语言
修复。约30s尾词与86s源覆盖候选缺口须另核听，不能宣称一套语义算法已解释/修好所有反馈。

当前 `subtitle.plan.v1` 的 `mapping_method` 只接受 `monotonic_proportional.v1`；fragment
双语非空、单调恰好一次覆盖。translation v1只产完整句译文，不产句内对应；srt禁止LLM。
这些现行约束继续有效，直到本ADR被接受并完成版本化实施。

## 2. 提议决策

采用“固定译文语义证据先行”的A路线，保留B上下文分块翻译作为**显式译文变体**支路：

```text
source_alignment（正确词锚点，保留不变） ───────┐
       └─ translation（完整句/section，不改旧译文）┤
                                                v
                       semantic_alignment：模型/aligner提议语义图
                              → 确定性结构校验 → 独立review → 冻结
                                                |
                              无可行显示闭包 → needs_review
                              （获批可请求translation新变体，重新对齐/审阅）
                                                |
                                                v
                       srt_processing：共同语义允许边界内联合规划
                              → word时间锚定 → 三SRT/新plan
                                                |
                                                v
                       subtitle_rendering：只排版/像素/ASS/烧录
```

### 2.1 能力归属

| 模块 | 新增或保持的责任 | 明确禁止 |
|---|---|---|
| archive_core | 公共语义图/审核/证据引用；plan/manifest新版本；规范名/异根输入绑定 | 导入功能模块；按模型分数决定语义正确 |
| semantic_alignment（新） | provider-neutral语义提议、上下文ownership、checkpoint、审核与冻结 | 改源词时间、发最终cue时间、覆盖原译文 |
| translation | v1保持；获批后新用例产完整句保义变体及父版本/逐句revision | 从单句碎片独立无上下文翻译、静默缩译、自己调时间 |
| srt_processing | 消费冻结语义块及审核；在允许集内确定性规划/时间/投影/发布 | LLM/provider、字数比例fallback、伪造semantic状态 |
| subtitle_rendering | 识别新plan，继续无正文/时间修改的布局/验证 | 自己重译、把多对多图转成另一套cue修上游 |
| orchestration | 授权、依赖、输入版本选择、串行/恢复/运行证据 | 语义判断、文本切分、重复实现阶段复用规则 |

独立阶段比直接扩translation更清晰：对齐可消费冻结旧译文、单独复核/失效，不强迫每次重译；
比把LLM塞进srt更符合确定性/离线规则。代价是新增一个能力模块及公共契约，不只改几项DP成本。

### 2.2 语义与显示关系

语义图允许非连续、多对多、交叉和上下文关系。共同显示块另证明连续保序消费；关键同义/
否定作用域关系不能被边界割开，纯context关系不强迫整段合并。交叉闭包过大则报告无解。
模型只引用既有word IDs/译文ranges，不生成毫秒；确定性阶段从消费首末词计算时间。
详见契约文档，不以“所有节点有边”或confidence阈值代替独立语义判断。

### 2.3 默认取舍建议（待批准）

1. 先共享双语cue，保留EN实际2×42、字体/像素安全、section/speaker/null与源时间硬门禁。
2. 先保留原译文，允许合并为可显示语义块。16/7秒/9CPS仍告警；合并也须审过度提前揭示。
3. 固定译文＋旧pause-only无解则 `semantic_display_infeasible`，不降级；下一轮获批比较保义
   改译。是否允许无标点语义切口单独确定，当前不放宽，不以“推荐”当已授权。
4. 独立语言窗口是另一个大契约版本，不作为兜底。它不能自动同时满足固定中文顺序、即时支持
   与三SRT同cue，必须独立读者实验后再决定。

跨句仍仅按v3短首fragment救援：原始<834ms且单独合法延长仍短、每原句间gap<500ms、
后继整句完整消费；不能把“语义相关”当新增跨句资格。任何放宽另立profile并获批准。

## 3. 版本化与兼容

- 提议新增 `semantic-alignment.graph/review/report/manifest.v1`；完整形状冻结后再编码。
- 提议 `subtitle.plan.v2`、`srt-processing.manifest.v2`（新增语义/审核输入）及相应新profile；
  cue使用诚实的 `mapping_method=reviewed_semantic_blocks.v1`，引用graph/reviewhash与block IDs。
  不在v1严格字段集合偷偷加字段或仅扩枚举而不绑定输入。
- rendering新消费分支验证plan v2/语义证据；render plan/manifest若需新直接输入字段则升v2，
  不放松v1解析器。ASS文字转义、百分秒half-up策略与既有样式默认不变。
- v1/v2/v3历史profile/旧plan/manifests继续只读可解析、原样往返；旧资产按旧身份验算，不自动
  迁移、重签或覆盖。新方案在唯一新output root，revision不替换旧translation_result。
- 图结构合格可技术成功，review状态另存；只有对应profile允许的review状态才可消费，
  quality/release状态不因成功manifest自动升级。候选实验与生产发布分开。

## 4. 昂贵调用、失败与持久复用

模型/aligner版本、prompt bytes/schema、所有owned/context输入hash、参数进入生成key；审核key
独立绑定graph与reviewer。生成输出冻结后复用不再调模型，审阅修订不必重生成图。
临时故障有限原请求重试，结构/语义失败不自动repair；预算耗尽、拒答、覆盖缺失、交叉无解、
review pending/rejected均阻止生产消费，无静默provider/比例fallback。
发布采用同文件系统暂存、回读、manifest-last；冲突默认只读，残留保留，不能删除历史资产。
严格reuse要求阶段输出0写/0生成/0编码；编排新增审计receipt的写入需与阶段零写分开统计。

## 5. 对旧决策的拟议变更范围

| 旧决策 | 仅在接受/实施后改变什么 | 保持什么 |
|---|---|---|
| ADR-0002 | 增显式subtitle variant用例/word-ID语义要求输入；不改v1路径 | 完整句/上下文翻译，原译文保留，provider隔离 |
| ADR-0003 | 用显式审阅语义块取代比例对应；新plan/输入与profile | srt无LLM、确定性时间/覆盖/发布；旧版本仍可读 |
| ADR-0006 | 增新plan/证据消费；未来独立窗口须另决策 | rendering不改正文/时间，像素/媒体/ASS与音频copy规则 |

S34历史中文自然优先的明确豁免不被本草案偷偷撤销；新profile是否重新评审该豁免由用户决定。
本ADR不包含转录算法修改；86s局部源覆盖若经核听确认，仅另立后续上游问题。

## 6. 验收、替代方案与未决项

先完成E1/E2冻结实验，再实施最小切片；全97句＋未调参样本、关键锚点、独立review、完整音画、
零写复用/全部历史不变都必须单列结果。样片必须从编排集成产出并由非作者agent复核，
人类完整播放未通过就不能以技术绿色关闭SR-07。依赖见SA-00（旧 SA-00 未实施任务已按用户要求移除；现行入口为 ADR-0008）。

不选：反转优先语言但仍比例；调DP权重当语义证明；LLM直接发时间/SRT；97句手工patch；
把全部长句整句显示而忽略容量；把模型confidence/第二次同意当签字。A/B/C/D/E完整比较见研究报告。

接受前需用户确认：固定译文无解是否允许保义变体；共享窗口及是否允许无标点语义切口；
实验范围/预算与人类质量责任。未确认前只有研究结论，没有新的生产算法授权。
