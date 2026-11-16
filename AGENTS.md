# AGENTS.md

巴菲特与芒格智慧档案的离线媒体资产管线：抓取元数据 → 下载视频 → ASR 转写 → 翻译 → 双语字幕 → 烧录渲染 → 人工评审。完全本地运行。这是一条可复现的长视频处理管线，不是视频平台、CMS 或云服务。

## 当前状态（先读这里）

> 2026-11-17（Asia/Shanghai）：按用户新授权整理文档：NB-00～NB-10共11份技术交付/固定实验/诊断记录已移入[任务归档](docs/archive/tasks/README.md)；ADR-0007以superseded未实施历史归档，ADR-0008～0012以已实施技术方案归档，未被替代的契约继续生效，[总方案ADR-0008](docs/archive/decisions/0008-local-orchestration-and-integration-tests.md)仍是行为入口。
> 当前目录仅保留[NB-12](docs/tasks/NB-12-chunking-quality-iteration.md)、[ADR-0006](docs/decisions/0006-subtitle-rendering-ass-and-burn-in.md)与[ADR-0013](docs/decisions/0013-typed-chunking-quality-and-regression.md)的未完成质量验收/迭代；归档不把历史未通过改成通过。诊断样片已技术交付，整体语义/出版仍NOT PASSED，未核听。
> 用户已明确授权**全部本地代码、测试、文档累计改动commit并push**，由负责人完成最终验收/敏感信息扫描及git操作；忽略的output、模型、视频不提交。此前各阶段“不commit/push”属于历史约束，已被本次明确授权取代；不回滚既有dirty、不删除内容或资产，不重跑昂贵阶段。完整原文/路径/哈希保全映射见[归档清单](docs/archive/2026-11-17-document-relocation.json)。

> 2026-11-15（Asia/Shanghai）：[NB-12](docs/tasks/NB-12-chunking-quality-iteration.md)/[ADR-0013](docs/decisions/0013-typed-chunking-quality-and-regression.md)的84字符、统一typed DP及最小保护已实现为policy v8；comparison-v1～v9与US精确证明已留证。最后完整离线2873 passed / 7 skipped（13.39s），负责人独立2873 / 7（13.00s）。新根实际Stanza 46次/165 chunks，完整9字段plan精确等cached v9；14份输入/NB09原库存及201份source保全。
> 用户明确允许英文/词时/上下文/术语/初译外发已登录Codex服务（不发视频音频）后，原require_escalated正常获准；此前CreateProcess前拒绝保留为历史，不绕过。真实初译4次、编辑10次且10窗口均首请求采纳，已发布166 cue权威最终稿/173条真实warning，SHA `36721b9d5686438f3522c5301ee9e1408ff5ff2c08ee1d8ba6d9171ea5ed274f`；没有重跑ASR/对齐或修改源词/时间。
> 负责人及独立agent全97句/166cue文本审读已完成：s16/s18/s88等好切法保住，s60原say|five和780ms短尾已由编辑实际修复，不能再当作final残余。仍有c69中文“每天”比per day提前4042ms，不能通过整体语义同步；c66/69“8盎司装”计量口径风险、c61 I would原偏好部分未满足及其它措辞/口语精度项明确披露。术语20项沿用，JET源残余不猜成Ajit Jain；旧c70/c114用户允许项不强制改。
> 负责人已实际复用source/translation/postprocessing三阶段，全reused、0 provider/analyzer/writes，正文/checkpoint不变。现仅放行**诊断候选样片**供用户复审，不通过整体字幕或出版质量，不再改prompt/重置额度/手改最终稿；诊断候选已实际烧录623秒/166cue，视频SHA `12092104058edb3b7dffa5a1dc307b6ea14c61184824e346c68d324677da4514`；像素/字形/ASS/媒体技术检查0error、217warning（权威173＋ASSgap44），五阶段同/新进程复用0调用/0改写，音轨packet hash与源完全相同。负责人已目视3原像素tile共18帧并额外看frame018原640×360，未见这些帧裁切/缺字/tofu/中英重叠；非全面观看/连续播放，未核听。c162双破折号按offset10拆成两行各一“—”是新披露rendering换行残余，本轮不修；profile与NB09完全相同。旧样片仍是旧策略/术语身份，不冒称已应用新规则。
> 运行/复用证据完成后，负责人已明确开放最终doc-only窗口，仅同步模块指南/根文档，生产.py/测试/模型/权威稿不改且与v9算法身份区分；dirty改动及所有旧/失败媒体、工件、账本保留，不删除/覆盖、不commit/push。负责人仅调度/验收，以下14/13日记录保留为当时事实。

> 2026-11-14（Asia/Shanghai）：[NB-12](docs/tasks/NB-12-chunking-quality-iteration.md)/[ADR-0013](docs/decisions/0013-typed-chunking-quality-and-regression.md)的84字符项目容量、完整句Stanza统一typed DP、最小保护及二阶评价已实现；US单生产负责人独立完整离线2658 passed / 7 skipped（14.21s），cached97与冻结US非policy完整plan/指标/有序评分精确证明已通过（仅实现等价），不是源语或出版质量通过。
> comparison-v1～v5的80/84×旧新评分、四消融、全97句/1569词why及冻结源码已持久化；s16参考四屏和so/And归属已改善，但s6/7/13、what kind/of、terms/of、up/and down等仍有残余，整体质量尚未通过。
> B/U/S/US两因子2×2隔离试验已完成；负责人批准US两原则作为唯一生产目标（未知普通2、普通句法等级先于CPS），typed v4及有序字段身份已落盘，稳定完整离线及与冻结US精确证明已过；证明后才另开CF/question四项修复（最终guard2684 passed / 7 skipped、comparison-v5已留证），随后独立NomOf一般软附着已实现为typed v6并完整离线2723 passed / 7 skipped（13.66s），新comparison-v6已留证；负责人独立2723/7并审全165 cue后，确认多数NomOf改善但s94新virtually|all及s18/s68/s60局部单位缺陷仍阻断。仅新授权五项局部scope/小单位切片typed v7实施中，向量/阈值不变，不混US归因或硬护全部noun-of。此有限选择不代表整体质量通过，不由自动分数决定上线。
> 本轮未调用provider、ASR/词对齐或新渲染；旧样片仍为旧策略/术语身份，不能冒称已应用新规则。后续新根仅通过adoption绑定冻结媒体/转录，不伪称生产前四阶段fresh/reused；真实翻译/样片仍待质量审读放行。
> 既有dirty改动及所有旧/失败资产保留，不删除/覆盖、不commit/push；负责人仅拆解/调度/验收/回归，编码仍由子agent实施。下方13日计划及历史验收保留为当时记录。

> 2026-11-13（Asia/Shanghai）：[ADR-0013 有类型切分与防退化迭代](docs/decisions/0013-typed-chunking-quality-and-regression.md)及[NB-12任务](docs/tasks/NB-12-chunking-quality-iteration.md)已获用户授权进入实现，设计/基线已由负责人验收，子agent编码进行中；尚无通过的新算法实验或新样片。
> 目标为项目84字符逻辑cue容量、完整句Stanza统一DP、最小保护/typed边界/cue特征、分层罚分与有界奖励，并经80/84×旧新评分、多解保好/反例/未见集与逐轮消融验证。
> 开工生产为80/逗号优先v4，新实现尚待离线/质量回归；84替代逻辑cue的80，显示换行/字号/像素继续归rendering，不新增单行门禁或声称Netflix84字符单行合规。
> 负责人仅拆解/调度/验收/回归，代码由子agent实施；已先验收计划，编码按阶段实施。既有dirty改动/媒体/转录及失败资产保留，新候选及真实翻译/编辑/烧录只写新根，不重跑ASR/词对齐、不覆盖/删除、不commit/push。
> 本次负责人实测离线基线2450 passed / 7 skipped（12.69s）；不是新算法、核听或出版质量通过，真实结果随后按NB-12更新。

> 2026-11-08（Asia/Shanghai）：[NB-10 逐cue反馈溯源](docs/archive/tasks/NB-10-cue-feedback-diagnosis.md)核对用户新增18项问题。
> NB-09“整体同档”是此前审核判断，不能作为这些逐cue问题已通过的结论；切分、逐屏对应及口语修订仍待改进。
> 本轮仅新增 underlying value→内在价值、net worth→净资产、Ajit Jain→阿吉特·贾恩及默认资源匹配测试；未改chunking/prompt、未调用provider或重生成样片。
> 现存样片仍为NB-09旧术语身份，不能冒称已应用新表或直接按新配置复用；原资产保留。
> 最新完整离线2450 passed / 7 skipped；默认术语20项，7份关键现存产物hash与NB-09相同，未把离线通过写成逐cue质量通过。

> 2026-11-07（Asia/Shanghai）：[NB-09 编辑质量迭代](docs/archive/tasks/NB-09-editorial-quality-iteration.md)已完成本次固定样片的文本/排版验收，完整离线2448 passed / 7 skipped。
> 英文chunk正常容量80字符，安全逗号优先、必要时Stanza；后处理直接替换为现有translation内的有界双语编辑生成（180源词/50初稿cue、每批最多3次持久额度），不是自动语义评分或发布门禁。
> 已扩充人物/公司/数学优势术语、官方证据See's拼写；中文词界软择优、数量单位与包装语法独立排版，SRT/ASS仍共享唯一权威正文和时间。
> 真实623秒/163 cue新成片已生成；负责人及独立agent全97句复审为整体与独立参考同档，不是逐句全面更好；177条权威警告、39条ASS间隔及措辞风险保留。
> 同/新进程九阶段全复用、84项保护集不变、昂贵调用和阶段改写0；本人已实际静音播放抽查，未核听或取得人类出版签字。新成片及审核见NB-09，所有失败/旧工件原样保全；不commit/push。

> 2026-11-06（Asia/Shanghai）：新版已实现，集中迁移后完整离线 2361 passed / 7 skipped。
> 真实 CNBC 链路从空根启动，经保留故障和阶段恢复，发布 623 秒 / 275 cue 正式烧录样片。
> 用户批准的原有中文起首省略号例外已验证；未改稿、字号或时间。
> 同进程与独立新进程九阶段全复用，昂贵调用和阶段改写均为0，78项保护集不变。
> 本人已播放抽查；文本语义残余已披露，核听未验证，人类出版签字未取得。
> 新真实产物及质量状态见 [NB-08](docs/archive/tasks/NB-08-full-fresh-acceptance.md)。
> 开工基线2580 passed / 6 skipped；下文旧候选和已清理产物的历史记录不是本次验收。
> 负责人只拆解、调度、验收与回归，编码交子 agent；不 commit/push。授权移除仅限已确认旧路径。

> 2026-11-05任务整理：SR-00、SR-07及runner设计交接已归档，保留技术交付及质量未通过记录；
> 无关且未实施的SA-00已删除。docs/tasks仅保留当前入口导航，旧任务状态不再作为待办。

> 2026-11-05 更新：用户明确授权删除旧集成及候选评估产物，已清空 output 下 cue-evaluation、
> subtitle-rendering-integration、transcription-integration 三个目录（458 文件、8 符号链接）。
> 历史段落中的保留要求、465份资产及旧文件可复核性是当时记录，已被本次授权取代。
> 编排模块完成后必须从空产物工作区完整跑采集到成片，再逐阶段审核和验证复用；当前未重跑昂贵阶段。


> 新双语链路的 ADR-0009～0012 行为设计已接受、未实施；ADR-0008 已同步新阶段依赖。
> 现有转录词时间保留，编辑标记单独传递；英文分块 → 上下文初译 → 局部修订与排时 → SRT/ASS。
> 指标超标可带 warning 发布；实际重叠、源覆盖和来源链错误仍阻断。样片 agent 回归不新增自动语义门禁。
> 仅更新设计，现有生产代码及历史资产不变。未来直接替换旧契约/算法，不做旧版兼容或双路径；
> 旧产物清理以本节最新授权为准。总方案入口为 ADR-0008，实施 agent 须逐阶段审查真实产物及样片声音/字幕。

仓库正处于迁移中期。动手前先核实现实，不要假设某个模块能用。

> 状态最后核对：2026-11-17（Asia/Shanghai）。**每次完成编码任务后，若实现状态或本文件中的事实发生变化，必须在同一次提交中更新本节（含核对时间）。**

> [ADR-0010源语chunking](docs/archive/decisions/0010-source-chunking.md)的行为与归属设计已接受，**未实施**：
> 归现有`srt_processing`，消费完整英文句子及词时间；42字符/20 CPS、先裁超长再并超短，
> 不换行/不借时间。初次裁切采用本地Stanza、不调用LLM；CPS不触发裁切但限制合并。
> 跨原句gap<500ms是用户指定的项目回退规则，核查未找到可直接采用的行业上限，不称为Netflix规定。
> 两轮分组后只读估算中文阅读预算，尾端最多预估延长500ms；不改时间，实际排时留给后处理。
> 本轮只更新设计/指南，未下载或运行模型、未改生产算法/配置/公共schema、未生成新字幕或媒体。
> 模型版本、公开接口及实现验证仍待开展；不影响下文现有v3及旧资产状态，ADR-0007/0008仍未接受。
> 本轮完整离线复验2580 passed / 6 skipped；465份资产条目大小/mtime/链接值不变，未做媒体全量hash复核。

> 用户要求先搁置原语义方案，按[业界调研](docs/reviews/2026-10-28-industry-bilingual-subtitle-pipelines.md)
> 重新比较流水线。已查阅专业制作规范、2026含英中/财经域论文与开源关键代码；优先验证
> 字幕模板约束下的上下文翻译及联合生成，不预设新增独立semantic_alignment模块。
> 这是研究建议，不是方案接受或实验通过；ADR-0007/0008及SA-00保持未实施，旧依赖不直接执行。
> 本轮只更新文档，未跑候选/外部项目、未重跑昂贵阶段/迁移测试/生成新片；完整离线
> 2580 passed / 6 skipped，465份input/output全部证据不变，92份Markdown本地链接0断链。

> [语义同步研究设计](docs/reviews/2026-10-24-bilingual-semantic-alignment-design.md)已交付：
> GPT未读旧plan独立审读9/97句、82组word/中文范围；负责人逐项复算一致。四例已追踪，
> 12帧旧片显示核查通过；30秒尾词仍待核听，86秒另有官网But the被排除的局部覆盖候选，
> 不据此重跑或否定整体transcription。ADR-0007语义证据/联合规划与ADR-0008编排/集成测试
> 唯一归属均为proposed；SA-00（旧 SA-00 未实施任务已按用户要求移除；现行入口为 ADR-0008）
> 记录带依赖切片。未改生产算法、未迁移/删除测试、未生成新样片或运行新样片agent回归。
> 本轮完整离线2580 passed / 6 skipped；465份input/output的hash/size/mtime/链接目标未变。
> 当前各模块实现/质量状态不变；所有后续实验与实现须先获批准，不能将草案视为接受。

> 文档已整理：[导航](docs/README.md)。ADR-0001..0005、TA/SP历史任务和已验收SR-01..06
> 已归档；TA-10仍为superseded而非通过。归档不撤销未被替代的公共契约，也不把候选质量写成定版。
> 当时状态：ADR-0006、SR-00及SR-07仍进行中（任务现已按本节最新整理说明归档）。SR-01..06已accepted，渲染公共契约、纯布局、字体/ASS/
> 像素/媒体适配器、工作流与独立对抗测试均已实现。完整离线最近验收为2580 passed / 6 skipped。
> 同源623秒/163-cue双语样片已持久交付，succeeded→reused→reused、逐cue像素、媒体QA与零写/
> 上游不变通过；负责人另独立复用和20帧审图，**不是完整听音或人类质量签字**。
> 用户实际播放发现中文与英语讲话的语义不同步，故SR-07最终验收未通过，ADR-0006不归档为完成。
> 用户进一步确认其观察中音轨/英文单词时间准确，当前重点是中文优先切分+比例分配的语义错位；
> 保留transcription与全部旧资产，先探索新方案，不重跑ASR、不直接调DP权重或改时间掩盖问题。
> [复审证据](docs/reviews/2026-10-24-rendering-technical-and-semantic-review.md)与
> [新agent探索prompt](docs/prompts/bilingual-semantic-alignment-exploration.md)记录当前事实和边界。
> 用户批准的ASS百分秒投影、U+2060可逆显示控制及发布顺序修订仍以ADR-0006为准。
> 本次整理后复验：2580 passed / 6 skipped，84份Markdown本地链接0断链；未新增语义修复算法。
> 后续顺序仍为rendering→orchestration→CLI→Web UI；不能把技术样片交付写成语义或出版质量通过。

> 用户另要求简化阅读稿，已新增全97句v3/agent两方对照（历史产物已授权删除；原路径：`output/cue-evaluation/20261023-candidate-v3/two_way_v1/all_97_sentences.md`）。
> 仅投影已冻结正文/时间并标明跨句共用关系，不重切或新增质量评价；负责人独立重算MD/JSONL字节一致。
> 两方展示回归9项，当时完整离线 **1404 passed / 5 deselected**；以下1395为此前v3实施验收时点结果。

> 2026-10-23补记：当前默认已是候选v3，SP-13/14已通过负责人技术验收，完整离线
> **1395 passed / 5 deselected**。中文只在停顿标点/句末切；16单位/7秒/9CPS均软目标，
> 不另设10秒硬上限；英文实际2×42及覆盖/时间/溯源门禁保留。独立CNBC生成163 cues，
> 负责人再次`reused → reused`，六输出bytes/mtime不变、复用0写；原正式33、SP-09 139、
> v2 111及只读偏好测量15文件未变，没有重跑ASR/translation/provider。
> 中文非停顿cut0、短cue0；中文长度/7秒/CPS告警81/9/18，不能把软目标告警当硬错误。
> S17节奏/中英错位、S22未保留已认可切法及S48/S74/S88等残余仍在；SP-15全97句/33偏好
> 对照已交付并由负责人独立复算、审读验收。中文偏好23满足/4允许变体/5部分/1未满足，
> 双语节奏总体18/2/12/1；**不建议质量定版**，非音画/像素/出版签字通过。
> [本轮报告](docs/reviews/2026-10-23-cue-candidate-v3.md)包含逐句入口、失败与成本原因。
> 下文v1/v2数字是历史结果，旧资产不覆盖。

历史开工基线（新版事实见本节置顶及 NB-00）：

| 状态 | 模块 |
|---|---|
| 已实现 + 离线测试 | `archive_core`、`acquisition`、`media_download`、`infrastructure` |
| 已实现 + 离线测试 + CNBC 真实集成测试 | `transcription` |
| 已实现 + 离线测试；Codex CLI 真实集成在本次 prompt 修正前已通过 | `translation` |
| 已实现 + 离线跨层验收 + CNBC 真实技术集成（非出版级质量背书） | `srt_processing` |
| 技术实现/真实样片已交付；用户发现双语语义同步问题，最终验收未通过 | `subtitle_rendering` |
| 仅脚手架（分层目录 + AGENTS.md，无代码） | `cli`、`orchestration`、`webui` |

- 遗留管线（`run.py` step0–4 + Web 评审应用）已在提交 `cc9df50` 中删除。开工前没有 CLI 或生产编排入口；当前由上述公开编排运行，CLI/Web UI仍不在本轮范围。ADR-0001 与其实现任务已完成并归档到 `docs/archive/`。
- 文档入口为`docs/README.md`；进行中ADR在`docs/decisions/`，已实现ADR/任务在`docs/archive/`。
  归档不自动使决策失效，但历史任务不再作为现行路线图；此前两份路线图已由用户删除，不得恢复。
- 尚无 lint/typecheck/CI。离线 pytest 套件是唯一的验证门槛；另有少量 `live` 标记测试，包括
  acquisition→media_download 真实网络测试，以及 `RUN_TRANSCRIPTION_INTEGRATION=1` 门控的真实
  WhisperX 集成测试。本地 CNBC 2000 上午场连续第 6、7 节样本可从空 `output/` 自动准备，并在
  唯一的 integration workspace 跑通至含两个 section 的 `source_alignment.json`；第二次运行按
  manifest 复用全部 transcription 工件。translation 的 provider-neutral workflow、OpenAI
  Responses adapter、Codex CLI ChatGPT adapter 及显式 provider composition 已通过离线 fake/mock
  测试；仓库配置默认选择 `codex-cli-chatgpt`，保留 OpenAI 作为显式备选且绝不自动 fallback。
  TA-10 OpenAI live gate 已被 ADR-0005 取代且未运行；TA-16 已使用 ChatGPT 登录和
  `codex-cli 0.154.0` 完成真实双 section 翻译、人工质量检查及第二次零调用正式复用验收。
  当前 `translation.zh-hans.v1` prompt 已直接修正 `go— ahead` 被机械翻成“请——继续”的问题
  并加入 live fixture 回归门禁；修改后已通过离线测试，尚未重跑真实 gate，历史工件由 prompt
  SHA-256 与当前内容区分。
  transcription 不再提供 reference-based Golden Live 入口；未来全管线连通性由 orchestration
  集成测试负责。
- ADR-0003 的公共字幕契约、确定性双语 planner、双链输入门禁、本地适配器、三份 SRT 投影、
  manifest 驱动复用与 manifest-last 发布已实现，SP-01..08（含 SP-08A）已完成历史v1技术验收；当时完整离线套件为
  **1220 passed / 5 deselected**。历史缺译文阻断已由用户明确授权的 SP-08A 解决：现有 Codex
  CLI translation 流程完成97句/2 sections、2次生成调用，正式译文持久保留、第二次零调用；
  未重跑 ASR。CNBC 字幕真实入口生成242 cues并立即复用，独立新进程再次复用；六输出
  bytes/mtime 不变、0写入，19份上游文件未变。SRT 本身完全不调用 provider。
- 负责人/agent 已完成 CNBC 文本内容审读，但**不是人类签字、语义对齐或出版级字幕质量通过**，
  未观看音画或验证像素/烧录。c3/c4 人物地名错位、c183“风/险”语义提前、c142–147“认/为”
  及破折号/专名拆分等已知比例/应急限制保留，详见 [SP-08](docs/archive/tasks/SP-08-real-sample-and-final-status.md)。
  在当时v1代码环境中，保留规范工件后可独立运行字幕样本入口复用，无需 ASR/translation 或其他模块 live 测试；当前候选路径/冲突说明见下文。
  完整离线 pytest 仍是代码改动门槛。
- 用户于2026-10-22授权先修一版再审阅，该轮规则为**历史候选v2，不是最终质量定版**（当前v3见上文）：
  中文一逻辑行16单位、中文内Latin word计1；英文最多两行各42，真实按word排布而非仅总容量84。
  固定`jieba==0.42.1`随包词典/HMM=False，词典hash进入profile；新边界/D39/codec身份均版本化，
  旧v1 profile/codec仍可读但受控冲突，绝不静默复用或覆盖。完整离线已为**1329 passed / 5 deselected**。
- 候选隔离工作区`output/cue-evaluation/20261022-candidate-v2/workspaces/cnbc_2000_morning/`
  真实生成224 cues，194.410s；随后复用及负责人独立`reused → reused`均0写、bytes/mtime不变。
  原正式33文件与SP-09的139份参考/证据文件未变，没有重跑ASR/translation/provider。
  全97句三方对照见[SP-12](docs/archive/tasks/SP-12-candidate-v2-comparison.md)；候选短cue从旧2增至9，
  中文CPS按统一新口径从旧11增至17，且有s30/s32等新语义错位，**不得宣称质量全面改善**。
- 旧CNBC规范目录保留v1字幕；当前v3代码对其直接运行原sample_runner应受控冲突，不再承诺
  原地直接复用。候选复跑用`tests.srt_processing.candidate_runner --run`并指定从未存在的
  `--result-name`；需要三方对照时加`--compare --comparison-name`唯一新目录。旧SP-09脚本动态
  import当前rules，无v1代码环境隔离不能复现历史计数；历史工件原样保留，新比较显式按v2重审。
- 当前v3独立工作区为`output/cue-evaluation/20261023-candidate-v3/workspaces/cnbc_2000_morning/`，
  复跑用`tests.srt_processing.candidate_v3_runner --run --result-name <唯一新文件>`；四方比较按
  v3硬/软政策明确重审，不能混用历史v1/v2容量指标或把153参考当合法golden。阶段本身仍只消费
  已有正式alignment/译文，不依赖先跑其他模块集成测试。
- `webapp/app.db` 是已被 gitignore 的遗留残留，忽略它。

## 开工规则

1. 动某个模块前，先读该模块的 `src/<module>/AGENTS.md`；大型任务前再读相关 ADR 与任务文档。
2. 说"做完了"之前必须跑质检（见「构建、测试与验证」），离线测试套件全绿才算完成；没跑测试不得声称完成。
3. 一次只做一小块可验证的改动，不同时大范围修改多个模块，不顺手重构无关代码。

## 环境与工具链（已知的坑）

- **仅支持 Python 3.11**（3.12 可接受）。WhisperX/PyTorch 技术栈不能可靠支持 Python 3.13+。
- **用 `ffmpeg-full`，不是 `ffmpeg`**（Homebrew）。字幕烧录需要 libass 支持的 `ass`/`subtitles` 视频滤镜。`ffmpeg-full` 是 keg-only：
  ```bash
  export PATH="/opt/homebrew/opt/ffmpeg-full/bin:$PATH"
  ```
- 做媒体工作前先验证外部工具：
  ```bash
  ffmpeg -hide_banner -filters | awk '$2 == "ass" || $2 == "subtitles"'   # 必须两个都列出
  yt-dlp --version && ffprobe -version
  ```
- 首次真实使用 ASR 会下载 Whisper 模型文件（按配置为 `large-v3`）——很慢，缓存它，别跟它较劲。
- `config.yaml` 存放非敏感运行时配置（包括翻译 API key 的环境变量名、下载、字幕样式、WhisperX、抓取礼貌性）。**绝不提交真实 API key**。

## 管线数据流（ADR-0008）

```text
acquisition → media_download（需要时显式派生） → transcription（词时间、编辑标记）
 → srt_processing（英文候选块、只读预算） → translation（上下文分批初译）
 → translation（有界修订、最终排时、权威双语稿）
 → srt_processing（三SRT导出） → subtitle_rendering（同一权威稿、ASS/烧录）
```

`archive_core` 定义公共工件/溯源；`orchestration` 组装执行、授权、恢复和复用，集中集成验收。
本轮不建 CLI/Web UI。基础实现/验收历史见 [NB-00](docs/archive/tasks/NB-00-implementation-map.md)，当前质量状态以 [NB-12](docs/tasks/NB-12-chunking-quality-iteration.md) 及本节最新记录为准。

## 模块地图

- `src/archive_core/` —— 共享领域原语：资产身份、规范文件名、路径策略、`manifest.v1`、溯源。
- `src/acquisition/` —— 网页分析、爬虫、逐字稿提取、元数据规范化、抓取礼貌性规则。
- `src/media_download/` —— 媒体 URL 解析、yt-dlp 下载编排、校验和/溯源采集。
- `src/transcription/` —— 音频提取、VAD、ASR、词级对齐、逐字稿融合、英文句界。*（已实现 +
  离线测试 + CNBC 真实集成测试）*
- `src/srt_processing/` —— 英文候选块、只读预算、权威稿校验、三份 SRT 投影与可恢复发布。
- `src/translation/` —— 上下文分批初译、checkpoint、有界双语修订与最终排时。
- `src/subtitle_rendering/` —— SRT/ASS 样式、烧录渲染、ffmpeg 命令规划、渲染元数据。*（SR-01..06已验收，真实样片已交付，最终验收未通过）*
- `src/webui/` —— 本地评审 UI 边界、目录契约。*（脚手架）*
- `src/cli/` —— 命令解析、面向人的命令、进度显示。*（脚手架）*
- `src/orchestration/` —— 管线组装、依赖、授权、恢复、复用与集中集成验收。
- `src/infrastructure/` —— 共享技术适配器：配置、文件系统、进程执行、HTTP、日志、工具发现。

跨模块 import 规则：功能模块只依赖共享 `archive_core` 与 `infrastructure`，不得互相 import。
ADR-0008 的唯一例外是 `orchestration.infrastructure.composition` 允许导入各功能模块显式公开的
`interfaces` factory/command；编排 domain/application 不使用该例外，任何生产代码不得依赖 tests。

## 架构

- 按能力组织，不按步骤编号组织。步骤式命名（如 `step3_translate`）禁止出现，临时迁移 shim 除外。
- 每个模块分四层：
  - `domain/` —— 纯概念与规则。禁止网络客户端、CLI 框架、`subprocess`、重文件系统操作、UI 代码。
  - `application/` —— 用例与模块内工作流协调。可依赖 `domain/` 和抽象端口；绝不直接依赖具体外部服务。
  - `infrastructure/` —— HTTP、ffmpeg、yt-dlp、ASR 库、翻译服务、文件系统等外部系统的适配器。
  - `interfaces/` —— CLI/Web/orchestration 使用的 DTO、命令处理器、展示器、序列化器。
- 跨模块只能通过契约 import：
  - ✅ `from src.archive_core.interfaces.manifest import ...`
  - ❌ `from src.acquisition.infrastructure.http_client import ...`（在 `media_download` 中这样写）
- 资产工作区契约由 `archive_core.application.build_asset_workspace()` 唯一定义，别处不得自创路径规则。规范文件名与 manifest schema 定义在 `src/archive_core/domain/artifacts.py` 和 `src/archive_core/interfaces/manifest.py` —— 同样以代码为唯一事实来源。任何写文件的模块必须定义期望的文件名、元数据和幂等行为。
- 每个昂贵阶段（抓取、下载、ASR、翻译、渲染）必须可恢复且由 manifest/溯源驱动。**绝不用"文件存在"当作完成判据。**
- CLI 和 Web UI 保持薄：校验输入、调用 application 服务、渲染结果。业务规则（媒体处理、爬虫逻辑）不得放进去。
- 外部工具/API 一律隔离在适配器之后，保证测试套件离线可跑（无网络、无 yt-dlp、无 ffmpeg）。
- 优先小步可验证的迁移，不做大规模重写。当某次改动改变了模块的架构意图、公开契约或阶段目标时，必须在同一次改动中更新该模块的 `AGENTS.md`。

## 构建、测试与验证

```bash
# 安装（Python 3.11）
python3.11 -m venv .venv && . .venv/bin/activate
python -m pip install -r requirements.txt -r requirements-dev.txt

# 完整离线套件（验证门槛）
python -m pytest tests/ -q

# 单个模块的测试
python -m pytest tests/test_acquisition_domain_application.py -q

# 标记为 `live` 的测试需要真实网络 —— 除非明确要求，否则跳过
python -m pytest tests/ -q -m "not live"

# 架构健全性检查：实现前确认模块指南存在
fd '^AGENTS\.md$' src --max-depth 3 | sort
```

## 关键约束

- 不引入云持久化、后台 worker、Web 框架或数据库，除非某个具体工作流确实需要。
- `domain/` 和 `application/` 层不得包含 OpenAI/Whisper/yt-dlp/ffmpeg 的特定厂商逻辑。
- CLI 和 Web UI 不得持有业务规则。
- 未校验 cue 数量一致性、时间轴单调性和文件溯源前，不得将生成字幕视为权威。
- 绝不静默覆盖昂贵的生成资产（ASR/翻译/渲染）。必须有显式覆盖策略或工件版本化。
- 绝不在没有用户明确确认的情况下删除生成资产或源媒体资产（`input/`、`output/`）。
- 实现某个模块切片时，不要顺手重构无关代码。

## 补充文档

- 模块指南：`src/<module>/AGENTS.md`（11 份）—— 动某个模块前先读对应那份。
- 已接受决策：`docs/decisions/`；已完成的 ADR 与任务：`docs/archive/`。
- `README.md` 是面向人的快速上手（安装、工具链设置）；架构规则在本文件和各模块指南中。
- 规则冲突时的优先级：`src/<module>/AGENTS.md` > 本文件 > `docs/` 规划文档。但本文件「关键约束」中的安全规则始终有效，模块指南不得覆盖。
