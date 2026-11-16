# srt_processing AGENTS.md

## 当前职责（2026-11-15，Asia/Shanghai）

本模块有两个独立、单套生产用例，来源与顺序见 ADR-0008：
- ADR-0010 英文源语 chunking：验证 canonical alignment/视频/媒体帧证据，两轮分组、只读预算，
  发布 source_chunks.json、source_chunking_report.json、source_chunking_manifest.json。
- ADR-0012 权威最终稿导出：验证最终稿、连续源词覆盖、初译及上游 manifest/hash，精确投影
  English/Chinese/Bilingual 三份 SRT（双语中文上英文下），发布 export report 和成功 manifest。
  不生成第二份权威 plan、不分块/改译/移时、不调用模型。显示换行和像素适配归 rendering。

## NB-12最新验收（2026-11-15，验收后doc-only）

已实现并交付诊断候选的技术样片，不是整体语义/出版质量通过。policy typed v8、实际Stanza 46次/165 chunks与cached v9完整9字段精确一致；最后完整离线2873 / 7，源词/时间不改。真实初译/编辑后166 cue，三SRT与623秒成片同一权威稿；同/新进程五阶段复用0昂贵调用/0阶段改写，未重跑ASR。
全97文本复审确认s16/s18/s88保好、s60旧短尾已由编辑修复；仍有c69中文每天提前4042ms等残余，不能由技术门禁或warning数签认语义。负责人只目视18抽帧（非全部cue/连续播放），未核听。c162双破折号跨视觉行拆开属rendering，不改本模块源语边界。
本段仅为所有冻结实验/真实运行/复用证据完成后获批的文档状态同步；生产.py、测试、模型、权威稿与样式均不改，不回签旧manifest的代码快照身份。下面保留分轮实现依据；当前结论以本段及NB-12最新记录为准。

## 英文源语 chunking

- NB-12 / ADR-0013 已实现并技术交付（质量未过）：英文 Unicode code points 含空格/标点，项目逻辑容量84字符/cue、20 CPS、834–7000ms；显示换行/字号/像素仍归 rendering，不新增单行门禁。当前代码及定向测试不代表全97句/未见集/新样片质量已通过。
- 只容量或最长时长违规触发完整句 Stanza 与统一DP；逗号不独立先试，数字逗号及已知最小保护不切。CPS/超短本身不触发新裁切；不可解保留整句及真实warning，不删词或借时间。
- 适配器保存有类型边界与半开结构跨度，domain局部计费：强依附/混接与<250ms工程闪现为高影响、一般结构单列，再比较超短数量/缺口、普通边界等级（未知默认2）、CPS负担、cue数、有条件帧停顿、相邻字符节奏与贴顶风险，最后稳定offset。诊断多标签按每个实际cut及其左右cue表现最高级收费一次，不按单cue全max合并不同cut，也不全局set重复/漏计。
- objective-v1四组固定源实验后，负责人已授权将US作为唯一生产目标：未知ordinary回普通2、普通语法等级先于CPS，policy为`english-typed-cue-dp.v4`；ordered `SCORE_FIELDS`及其policy身份是报告字段顺序的唯一来源。不提供运行时B/U/S/US分支；旧实验仅由测试侧冻结源码重放。此选择不代表问句核心、名词附着等残余或整体源语质量通过，尚未放行真实provider/新样片。
- US实现已在独立`production-us-proof-v1`精确等于冻结objective US的全部非policy字段、实际指标及有序评分，证明不等于源语质量通过。随后独立CF/question阶段已落地：`clause.interrogative`为低档、`noun.clause`为一般结构，policy/ranking为typed v5，US字段顺序/阈值不变；adapter四guards及类型契约已定向/完整离线验证，实际97句文本质量仍待独立审读，不新增全部名词of硬保护。
- CF最终完整question guard已离线验证并完成独立comparison-v5回放，整体质量仍未通过。随后另开NomOf软附着：NP/NML/WHNP/QP下有名词/数量/WH头或all/most/some量词的直接of-PP标`attachment.nominal-of`一般档，policy/ranking typed v6；不删候选/扩硬保护、不改VP prep-of/非of PP，不混scope/短ADVP。US有序字段、排序与阈值不变，本轮实际分组质量待v6验证。
- v6后局部scope/小单位五项已实现为typed v7：最小no-matter-WH核心由adapter hard护，attachment.coordination/scope/frequency/temporal四tag为一般soft。仅获批三项ADVP、NP/QP量词、限定times NP、数量时间+from now结构；US字段/向量/阈值不变。2026-11-15稳定完整离线2795 / 7及comparison-v7已留证，负责人确认no matter what/virtually all改善，但are|not related与currently|exist仍阻断源语质量，不能以mapping/pytest通过替代文本验收。
- v7复审后仅授权adapter-only两类最小predicate core：同VP copular be经simple RB/纯RB ADVP到ADJP起首直接JJ*（ADJP内仅同类局部副词前缀），hard止首adj、不递归/跨标点/CC/PP/clause/PRN；已确认VP补语的无marker单子S/SBAR纯wrapper链，末端S无NP/旧S，单叶ADVP紧接VP首直接VB*，hard仅adverb+verb。独立句、if/WH/question/supplement、长插入ADVP及非be负例保留；domain/tag/policy typed v7不变，adapter protection/ranking身份独立升级，实际编排与样片的显式bundle verify绑定当前identity。完成稳定全套/独立comparison-v8与97句复审前不放行provider/新渲染，不扩大say|five或合法长PP取舍。
- adapter-only两predicate core已完整离线2848 / 7并完成comparison-v8，源语仍因related|to等未过；随后仅授权ADJP直接JJ/JJR/JJS head后的直接PP beforePP标attachment.adjectival一般soft，policy/ranking为typed v8。不跨comma/CC/clause/PRN、不借深ADJP/其它祖先head，不影响VP/NP-owned PP或无adj头，不新增hard；长PP容量需要时可切。US有序字段/阈值与源词/时间不变，稳定全套及独立comparison-v9/全97复审前不放provider；say|five及尾PP780ms是真实披露取舍，不扩本片。
- DP状态(first_offset, previous_first_offset)保留上一cue范围，正确计算左右cue根因与相邻字符差；它只是节奏代理，实际时长/CPS落差另报。旧窄三块候选已含统一DP，撤下其独立gap择优分支；短cue救援须严格改善同一完整分组目标（含左右外邻居），不为帧间隔拆坏结构。
- 实际PTS停顿工程档0–3帧绝对中性、4–8收益1、9+收益2，结构适合且罚分同档才参与，单切点总收益封顶2。相对log1p帧median/MAD仅原句内>=8个有效gap且MAD>0、z初档2/3；跨句gap只有固定档，救援沿原句统计，不改成全片MAD。未核听不推断呼吸/强调，2秒不是修辞识别器。
- 合并四项指标全达标，不能跨 section、不同已知 speaker 或经 null 桥接；跨原句只合完整原句且 gap <500ms。
  合格候选与原分组按同目标完整比较，严格改善才采纳，稳定offset决胜；未解警告不掩盖。保留每个源词与声学锚点。
- Stanza 以精确 token 字符跨度映射到 canonical word，不在词内切，不用辅助编辑标记评分。
  已分析句 ID 和可保护范围进入公开结果；缺模型、映射不确定、实际时间轴错误均失败，不 fallback。
- 模型固定 Stanza 1.11.0 与 ELECTRA-large constituency；显式准备：
  `PYTHONPATH=src .venv/bin/python -m srt_processing.infrastructure.prepare_stanza <bundle>`。
  跟踪的 model lock 固定处理器与依赖文件 SHA-256，正式用例只读已准备模型，不联网。
- 使用实际 decoded video PTS 保留两帧；只读估算最多可借 500ms 且不越 7 秒、媒体末尾或下一源词。
  缺帧相邻块估算 0。估算永不改变基本窗；中文 16 单位是独立软目标，不把建议当交付门禁。

## 导出、分层与复用

- domain 只计算纯分组、指标和只读预算；application 验证源链及发布；infrastructure 持有
  Stanza/pysubs2、本地文件能力；interfaces 暴露 SourceChunkingCommand、SrtProcessingCommand、
  显式 factory 和只读 verify。
- 导出仍用锁定 pysubs2 1.8.1，逐cue回读检查精确文本、时间、编号；不得把上游软指标升级为
  硬门禁。文本不可精确序列化、词覆盖/来源/越界/实际重叠错误必须失败。
- 工作区由 archive_core 定义。manifest-last；占用的部分、损坏、混合代次只读冲突，无兼容 loader。
  成功复用重新验证严格 DTO、字节、hash、策略和报告；不运行句法模型，不改写任何正式输出。
- 模块只保留隔离单元/纯契约；真实FS/codec/组装测试归 orchestration/integration。历史候选
  算法及 runner 已退役，归档证据不代表当前样片验证。真实完整运行见 NB-08。
