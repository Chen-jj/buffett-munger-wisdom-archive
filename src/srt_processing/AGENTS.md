# srt_processing AGENTS.md

## 2026-10-24 人类播放反馈与探索边界

ADR-0003及已完成SP任务已归档，候选v3的技术/实验accepted状态不撤销，但不代表语义质量通过。
用户播放真实烧录样片后确认其观察中的英文词时间准确，主要问题是中文优先分块后按比例分配
英文，造成专名/谓语等跨cue错位。当前尚未接受新的语义对齐方案；禁止将讨论直接变成新默认
算法、重跑ASR或静默改译/改时间。先按[探索prompt](../../docs/prompts/bilingual-semantic-alignment-exploration.md)
研究需要修改哪些旧契约/约束，当前LLM禁令和公共契约仍有效，不能绕过。

## 2026-10-23 用户确认的候选v3（技术与比较交付通过，非最终质量定版）

本节覆盖下文v1/v2冲突规则。用户确认中文只在停顿标点或句末切cue，逗号可选；中文16单位
改软目标，7000ms改显示时长warning目标，**没有另一个10秒硬上限**；9CPS仍只warning，
不能为达标破坏完整语块。S34接受中文自然分块优先，不要求逐cue中英语义严格对应；S19
可独立一cue或逗号两cue，S20独立一cue。英文实际2×42、中文一逻辑行、完整文本/词覆盖、
源锚点、非重叠、section/speaker/null、媒体末尾与最多500ms总延长等硬门禁保留。

精确通用算法和v3公共profile已冻结，由子开发agent实施；负责人只拆解/审查/验收不编码。
[SP-13](../../docs/archive/tasks/SP-13-candidate-v3-pause-planner.md)核心技术已accepted，完整离线
**1395 passed / 5 deselected**，负责人独立复跑且三个domain源码指纹一致。规则/边界/planner
定向184 passed，包含独立全路径暴力oracle、非贪心与候选顺序扰动，不以测试代替语义验收。
[SP-14](../../docs/archive/tasks/SP-14-candidate-v3-contracts.md)提供契约/跨层接入；
[SP-15](../../docs/archive/tasks/SP-15-candidate-v3-comparison.md)隔离真实集成/全97句对照已完成负责人验收。
真实163 cues生成→复用及负责人独立零写复用通过，四方数据及六份手工审读表独立重算字节一致。
中文非停顿cut0、短cue0，中文长度/7秒/CPS告警81/9/18；33句中文偏好23满足/4允许/5部分/
1未满足，双语节奏18/2/12/1。S17/S22/S48/S74/S88/S94等残余明确披露，不建议质量定版，
也不是音画/像素/出版签字通过。旧v1/v2/153参考均不覆盖，不重跑ASR/translation。
详见[本轮报告](../../docs/reviews/2026-10-23-cue-candidate-v3.md)。

- 当前默认profile为`netflix-audio-gap.zh-priority.v3`，算法`bilingual-pause-dp.v3`，边界
  `chinese-pause-closed.v3`，成本`d39-pause-rhythm-rational.v3`；计数/词典/视觉codec仍沿v2。
  v3用`chinese_target_half_units=32`与`target_duration_ms=7000`明确软目标；旧v1/v2精确shape/hash
  可读且原样回写，不注入新字段，与当前规则不符的旧输出不能静默复用或覆盖。
- 中文只可在完整停顿组后或句末切：中文/ASCII逗号、顿号、分号、冒号、句号/问叹号、完整
  省略号、em/en dash、重复hyphen组。单hyphen、Latin词内、组合序列、数字/Latin内部句点、
  数字内部comma/colon不可切。停顿/闭引号右括号/空格可交错成组，整组归前块；不把外逗号
  留给下一cue。纯helper为`chinese_pause_boundaries()`；没有非标点应急fallback。
- 完整路径固定九层字典序：内部中文分号跨越→局部词/专名/数字单位/英文function-word悬挂
  →最终过短cue→跨句边界→中文节奏→英文无标点word切口→比例偏差→word-gap弱罚→完整断点。
  中文节奏为`Σ[1+(2*max(0,h−32)/32)^2]`（h为实际完整正文半单位），自含每cue切换成本1。
  20/23单位整句不因16而必拆，长的有可选逗号时可分块；这不是24或其他新硬容量。
  分号为软首项，不可切时允许保留并定位warning。9CPS/7秒均不进入DP成本，不为达标破坏语块。
- 跨句仅救援第一fragment原始<834ms且合法单独延长后仍过短的情况；所有后继fragment必须
  完整消费其原句中英，不偷下一句开头。后继可非短句；原每gap<500ms、section/known-speaker
  集合/null与英文实际2×42门禁保留。可延长至834ms则不跨句，CPS本身不赋予合并资格。
- 新warning为`reading.chinese_length`（half_units/target_half_units）、`timing.target_duration`
  （最终显示duration_ms/target_duration_ms）及`planning.strong_pause_retained`（semicolon_count），
  均带cue/sentence定位并在复用时重算；summary schema不变。16/7秒可超，仍只能共用最多500ms
  延长且不得越媒体末尾/下一源词。无合法pause-only/英文2×42完整路径时受控失败，不改字/序/时间。
- 规则是版本化启发式，不保证agent语义选择；S34等固定译序与共享单调时间轴的局部双语
  不同步仍需报告。真实比较前不因看到样本而调成本，不把少cue或测试全绿视为出版质量通过。

## 2026-10-22 用户授权候选v2（技术验证通过，质量待审阅）

用户要求先修一版并逐句对照SP-09的153-cue独立agent稿，再决定最终策略。候选约定见
[SP-10](../../docs/archive/tasks/SP-10-candidate-v2-rules.md)、[SP-11](../../docs/archive/tasks/SP-11-candidate-v2-projection.md)、
[SP-12](../../docs/archive/tasks/SP-12-candidate-v2-comparison.md)。本节覆盖下文v1的一行英文/半宽Latin及D39旧规则，
下文保留的242-cue技术验收是历史v1事实，不是候选v2已通过证明。

候选代码已通过完整离线1329 passed / 5 deselected；隔离CNBC224 cues真实生成与复用通过，
负责人独立复用/三方重算/97句审读均已进行。旧正式33文件与SP-09的139份文件未变，
但短cue9、中文CPS新口径17及s30/s32等语义回归明确保留；这不是内容质量或最终策略通过。
旧规范目录保留v1输出，当前代码直接对其运行旧sample_runner会受控冲突。候选复跑使用
`tests.srt_processing.candidate_runner`和唯一新结果/比较路径，不能覆盖旧资产。

- 中文仍一行16单位；中文内English word计1，词内撇号/连字符保留，数字/其他标点沿旧计数，空白0。
- 英文最多两行，每行42；必须存在word边界的合法排布，不以总量84替代逐行校验。
- 逻辑plan仍无视觉lines；英文/双语SRT采用同一确定性文本行预算换行，不宣称字体/像素排版通过。
- 固定本地jieba词典、HMM=False，版本/hash/mode进入profile；IO在adapter，domain消费span，不联网或fallback。
- Latin词/成组标点保护及中文分词/专名/数字单位质量信号、新D39顺序均版本化；语义重排残余仍须报告。
- 旧v1 profile/codec形状仍可读且原样回写，但与新身份冲突；不自动覆盖旧正式工件。仅独立实验工作区生成。
- 不重跑上游、不重译/重排/改时间，原覆盖/时间/speaker/section/合并约束不变。最终规则取舍待用户审阅。

## 模块定位与当前状态

`srt_processing` 负责从已验证的英文词级 alignment 与整句中文翻译生成统一双语 cue plan，
再投影为 SRT；不为 translation 准备 SRT 文本单元。

截至 2026-10-21 10:11 CST，公共契约、输入门禁、确定性 planner、ffprobe/pysubs2/store
适配器及 manifest-last workflow 已实现，SP-01..07 已通过负责人审查、跨层/对抗验收与
完整离线套件（1220 passed / 5 deselected）。正式决策见
`docs/archive/decisions/0003-srt-processing-input-boundary.md`（ADR-0003）。历史缺译文阻断已由用户
授权的 SP-08A 解决，正式工件已持久保存。CNBC 双 section 真实技术集成生成242 cues，
`succeeded → reused` 后独立新进程再次 `reused → reused`；六输出bytes/mtime不变、0写入，
19份上游文件不变。负责人/agent内容审读已完成；SP-08已由负责人完成最终文档验收并标记accepted。

**上述不是人类签字、语义对齐或出版级字幕质量通过，未观看音画或做像素/ASS/烧录验收。**
c3/c4人物地名错位、c183“风/险”语义提前、c142–147“认/为”及破折号拆分、中文栏英文专名
拆分等比例/应急限制均保留，具体证据见
[SP-08](../../docs/archive/tasks/SP-08-real-sample-and-final-status.md)。不宣称全片字幕质量过关。

## 已实现入口与运行边界

### 2026-10-22 历史候选v2（SP-10/11；当前冲突规则以上节v3为准）

用户授权在不重译、重排或修改词时间的前提下修复一版，再与冻结153-cue参考逐句比较。
该轮默认profile为`netflix-audio-gap.zh-priority.v2`，算法/计数/边界/成本版本与hash均已改变；
上文242-cue真实验收是历史v1记录，不代表本候选已获出版级或最终产品质量认可。

- 中文一行16单位；每个完整Latin英文word计1，Coca-Cola/See's等词内连字/撇号保留；数字与
  其他标点沿旧规则，空格0。容量、中文CPS、合并资格与物化统一用完整实际正文计数，不能
  将非加性word计数错误分摊到每个字符或相加跨fragment计数。
- 英文最多2行、每行42非空白计数；完整word超过42受控失败，总量<=84仍须确实可按word
  边界放进两行。纯`wrap_english_text()`共用于规划、codec和回读expected；选择合法均衡断点
  是固定预算排版，不是句法/像素换行。plan仍只有原逻辑正文，绝不保存lines。
- 本地`jieba==0.42.1`随包dict.txt SHA256为
  `7197c3211ddd98962b036cdf40324d1ea2bfaa12bd028e68faa70111a88e12a8`，固定default/HMM=False。
  包版、字典hash和mode进入profile；adapter只加载已核验bytes，不使用全局变更或/tmp缓存，
  缺依赖/字典错误不fallback。domain只接收完整句级span分区，workflow生成/复用均核验身份。
- Latin词内、组合序列、成组破折号/省略号不可切；jieba词内、数字单位、英文专名/紧密短语
  等是软保护。长词或词典误分仍保留高代价应急路径，不把词法识别说成语义证明。
- 候选字典序为：局部词/专名/数字单位断裂数→普通应急数→过短数→中文CPS超额→跨句边界数
  →cue数→累计比例偏差→完整断点序列。微小比例改善不再压过切换数；少cue仍不等于语义正确。
- 7秒、834ms软目标、500ms共享延长、原始gap单次分类、section/speaker/null与跨句资格不变。
  原v1正式工件和冻结参考只读，旧身份不能按v2静默复用/覆盖；新候选在隔离workspace生成。

开发侧完整离线复验为1329 passed / 5 deselected；候选运行规则已冻结供SP-12独立比较。
不以这一测试结果或尚未完成的比较宣称全部97句质量通过。

- 公共接口为 `SrtProcessingCommand(asset_id, transcription_manifest_path,
  translation_manifest_path, overwrite=False)` 和 `SrtProcessingCommandHandler.handle()`；
  outcome 区分 `succeeded/reused/failed`，返回六份规范路径、cue/warning 数与受控错误文案。
- `infrastructure.build_srt_processing_handler()` 显式组装本地 adapter，也允许注入
  store/probe/codec/clock 供离线测试和验收观测。构造过程不探测视频；没有 CLI 或端到端入口。
- 复用重新验证五项输入、全部输出证据、规则/profile/media/probe/codec 身份、plan 硬 QA、
  三份投影读回及报告重算；不重新规划、调用 clock 或改写正式文件。
- 五份正文/报告先全部同文件系统暂存并回读 QA，再逐个原子发布，成功 manifest 最后发布。
  保留失败暂存文件与旧 manifest，不自动清理或回滚；混合代次通过完整证据校验拒绝接受。
- 默认 artifact conflict 完全只读；输入/生成失败也不能覆盖已有本阶段输出或成功 report。
  只有六份正式输出全不存在，或调用方显式 overwrite，才尽力写 failed report；写入失败不掩盖原错。
- 单资产并发、checkpoint、ASR/翻译重跑、视觉排版和渲染均不属于本模块。
- `PYTHONPATH=src .venv/bin/python -m tests.srt_processing.sample_runner --run` 是显式本地样本验收入口，只消费现有
  canonical 工件，不下载或补跑上游；不是 CLI 或全管线入口。CNBC正式输入及六份字幕输出
  已保留在 `output/transcription-integration/cnbc_2000_morning/`，该目录是历史v1输出；当前v2直接
  运行会受控冲突，候选改用上文独立workspace/runner验证复用，仍不需ASR/translation或其他
  模块live测试；完整离线pytest门槛仍需保留。
- SP-08A是用户明确授权的样本准备例外：只通过既有Codex CLI translation生成两section正式
  译文，不改生产实现/配置，不重跑ASR。SRT workflow和本地字幕入口仍完全不调用provider。

## 职责

- 分别验证 transcription/translation manifest 与正式工件，再交叉校验 source alignment SHA-256。
- 验证规范视频与 transcription 同源，由 ffprobe adapter 获取平均帧率和媒体时长。
- 使用本地确定性动态规划生成中英单调比例 cue；中文主导，禁止 LLM、翻译 provider 和重译。
- 规划 cue 拆分、受限跨句合并、字符容量与结束时间调整，不修改上游 word/sentence/译文。
- 以 `subtitle_plan.json` 为唯一权威字幕工件，固定投影 English/Chinese/Bilingual 三份 SRT。
- 三份共用 cue 数量与时间，生成后重新解析并对照 plan；编号是最终 cue 的顺序，不保持旧 cue 切分。
- 产出独立 report 和 manifest，使用 manifest 驱动复用；冲突需显式 overwrite，无 checkpoint。

## 核心规划与时间规则（v1/v2历史；当前冲突规则以上节v3为准）

- profile 是代码内版本化常量；当前候选英文总预算84但须满足2x42实际word排布，中文容量16。
  中文Latin word=1，数字/半角标点保持半宽，空格不计；英文仍逐普通非空白字符计数。
- 中文9 CPS主导优化和延长，英文17 CPS只报告。所有 CPS 超标均只 warning，无绝对 CPS 硬上限。
- 最短834ms，先尝试合法合并再延长，仍不足 warning；最大7000ms与字符容量是硬门禁。
- 禁止跨 section，cue 内非空 speaker 标签至多一种；允许 null/null、已知/null，保留原 null。
  不能通过 `BUFFETT -> null -> MUNGER` 间接合并不同已知 speaker。
- 跨句候选要求至少一个单元原始过短或中文 CPS 超目标，每个原始句间停顿<500ms，合并后合法。
- 开始锚定首词，结束可延长，但最短时长/CPS/gap共用最后一个源词结束后最多500ms的总额度。
- gap 按调整前原始值分类；长 gap 不为美化而延长，但可为可读性延长。800ms延长500ms后剩
  300ms合法，不二次收紧。短 gap 尝试收紧至两帧，做不到 warning；0～两帧且不重叠则保留。
- 重叠是硬时间轴错误，不能作为 gap 美化处理；不得截掉讲话来腾两帧间隔或突破视频/硬边界。
- ffprobe平均帧率只作近似并警告；word间隙不宣称静音。禁止读取transcription私有VAD或检测镜头。

## 视觉与输出边界

- 字符容量与本候选固定英文2x42的word边界换行归本模块；字体/字号、画面像素排版、ASS与
  烧录归`subtitle_rendering`，不把固定计数换行当作视觉适配证明。
- plan保存逻辑中英正文、word/中文字符范围、片段speaker和时间方法，不保存视觉lines数组或findings。
- 候选英文SRT按同一纯函数输出1或2行；中文保持一逻辑行；双语中文在上，后接1或2行英文。
  三份共用cue/时间；plan不写入导出换行，不能从SRT行数反推权威语言或范围。
- speaker与section标题不显示；无样式标签；UTF-8无BOM、LF、末尾换行。
- `pysubs2`只在adapter出现，负责读写与回读验证；已锁`pysubs2==1.8.1`以兼容Python3.11。
- rendering消费公共plan，不从SRT反推权威数据；findings放report，方法放plan，执行时间放manifest。

## 分层规则

- `domain/`：双语片段/cue/plan、profile、finding及纯断点、DP、合并、时间调整、容量和覆盖规则。
- `application/`：输入门禁、workflow、复用、投影编排、失败与manifest-last发布；只依赖端口。
- `infrastructure/`：ffprobe、pysubs2、文件/指纹和原子写入适配器，外部调用可注入fake。
- `interfaces/`：command/outcome/handler及摘要，不泄漏pysubs2对象，不持有字幕业务规则。
- 公共plan/manifest/report DTO、工件类型及规范文件名由 `archive_core` 定义。
- 禁止跨模块import transcription/translation内部实现；仅消费公共契约。

## 验证与发布

- 当前v3硬门禁包括身份/指纹、完整文本与word覆盖、无错配/重叠/越界、英文实际2×42、
  中文停顿边界和原始合并资格、投影回读一致；中文16/显示7秒/CPS是告警目标而非硬门禁。
- 相同输入、profile、算法与工具版本的plan/SRT应字节一致；未知/损坏/过期工件不能因存在而跳过。
- 全部临时输出QA后逐文件原子替换，成功manifest最后写；不宣称多文件整体事务。
- 下游验证整套输出证据，混合代次不能因旧成功manifest仍存在而被接受；失败不静默清理资产。
- 默认测试使用fake store/probe/process，不联网、不运行ffprobe或模型；落实ADR的gap与speaker回归矩阵。
- 当前实现状态变化时在同一改动更新本文件；只有完整离线套件通过才可声明实现完成。
