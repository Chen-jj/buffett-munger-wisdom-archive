# ADR-0008：新双语流水线总方案、编排与集成验收

> 2026-11-17归档说明：已实施的技术方案归档，未被后续ADR明确替代的现行契约继续生效；语义/核听/出版未通过不因归档改变。 原路径`docs/decisions/0008-local-orchestration-and-integration-tests.md`；原状态、历史不commit/push约束及验证结果属于当时记录。后续入口：[NB-12](../../tasks/NB-12-chunking-quality-iteration.md) / [ADR-0013](../../decisions/0013-typed-chunking-quality-and-regression.md)。

- 状态：**生产编排与集中测试已落地；真实端到端经恢复发布并通过两种复用，语义及核听不视为通过**（2026-11-06）。
- 更新：2026-11-05；本 ADR 是唯一方案入口，采用单套替换和逐阶段产物审核。
- 2026-10-28历史补记：原语义流水线方案依用户要求暂缓并重新比较；本ADR的集成测试唯一归属目标
  保留，具体阶段DAG、输入绑定和迁移顺序待[业界调研](../../reviews/2026-10-28-industry-bilingual-subtitle-pipelines.md)
  后的路线验证再定，不把旧草案依赖当作当前实施授权。
- 日期：2026-10-24；影响：`orchestration`、`archive_core`、各阶段公共入口及测试/指南。
- 需求：集成各模块测试与真实样片来源链；迁移完成后除编排外不保留集成测试；用其产物做独立
  agent全链回归。新路径的翻译与修订见[ADR-0011](0011-contextual-chunk-translation.md)和
  [ADR-0012](0012-bilingual-translation-postprocessing.md)。
- 本轮只设计；“先研究，不重跑昂贵阶段”优先于任何立即迁移/烧录的理解。

## 本次实施与验收入口

切片、验证与授权见 [NB-00](../tasks/NB-00-implementation-map.md)，真实运行见 [NB-08](../tasks/NB-08-full-fresh-acceptance.md)。
新版走生产公开入口，样本派生由媒体模块执行；派生及直接完整资产共用后续阶段。
启动前负责人离线 2260 passed / 7 skipped，最终 2361 passed / 7 skipped。真实新根经恢复发布623秒/275 cue样片，前序资产未改写；同进程及独立新进程零昂贵调用、零阶段改写。实际质量、失败历史和未核听范围见 NB-08。
下文关于设计阶段未运行、测试基线和已清理产物的陈述保留为当时记录。

> 2026-11-07 NB-09：在同一条生产路径上做编辑质量迭代，不增设语义运行时发布门禁。全局英文每 cue 80 字符及逗号优先见 ADR-0010；术语和质量回归见 [NB-09](../tasks/NB-09-editorial-quality-iteration.md)。NB-08 保留为不可改写的技术基线。

## 0. 方案入口与阅读顺序

本 ADR 汇总执行顺序、模块职责、替换政策及验收责任；不另建并行总方案。
算法行为由下表对应 ADR 决定，具体字段及实现任务不能反向改变已确认行为。

| 顺序 | 能力与负责人模块 | 行为依据 |
|---|---|---|
| 1 | archive_core：单套公共契约、工件身份与来源链 | 本节、ADR-0009～0012 |
| 2 | transcription：声学词锚、保守官网融合、分离官网编辑标记 | [ADR-0009](0009-cnbc-editorial-break-annotations.md)、[NB-09](../tasks/NB-09-editorial-quality-iteration.md) |
| 3 | srt_processing：源语候选块及只读预算 | [ADR-0010](0010-source-chunking.md) |
| 4 | translation：上下文分批初译与术语输入 | [ADR-0011](0011-contextual-chunk-translation.md) |
| 5 | translation：有限修订、最终分组和排时 | [ADR-0012](0012-bilingual-translation-postprocessing.md) |
| 6 | srt_processing：验证并导出；subtitle_rendering：布局烧录 | ADR-0012、[ADR-0006](../../decisions/0006-subtitle-rendering-ass-and-burn-in.md) |
| 7 | orchestration：集中集成测试、产物与样片审核记录 | 本 ADR §6～8 |

### 0.1 直接替换，不并存多套实现

项目未发布首个正式版本；实施时直接替换旧 schema、DTO、规则、输入校验及测试，不承诺旧版兼容。
只保留一套现行契约和生产流程，不保留旧 planner、旧句级翻译路径、双版本解析器、自动探测、
兼容 shim 或运行时 fallback。工件仍保存当前身份与 hash 供溯源和失效判断，不等于提供多版支持。
旧输入不符新契约应明确拒绝，不静默按新版解释；改变后的缓存不能靠文件存在直接复用。

2026-11-05 用户明确授权删除旧集成/候选评估产物。已清空 output 下的
cue-evaluation、subtitle-rendering-integration、transcription-integration 三个目录：
458 个普通文件和 8 个符号链接，包括旧下载媒体、ASR、译文、字幕、样片及评估结果。
仓库代码、静态测试夹具和文档记录保留；历史报告中的 hash/数量仅为当时记录，不再有原文件可复核。

编排完成后，从空产物工作区完整跑一次集成测试，依次生成采集、媒体、转录、英文分块、初译、
后处理、字幕和成片，不复用已删除的历史工件，不通过手工运行各模块测试准备输入。
这次完整运行包含真实下载、ASR、翻译及烧录；当前只执行清理与设计同步，不提前运行这些阶段。
首次完整生成后，再按同一批新工件验证同进程及新进程复用。重跑后的产物不会被本次删除授权
自动授权删除，后续清理仍需用户确认。

以下已核实现实及测试数量是历史盘点基线，不要求保留已被本方案替换的旧契约断言；
有效业务不变量继续覆盖，删除或改写的断言须列明替换理由，不能以去兼容为由削弱正确性测试。

## 1. 已核实现实与集成缺口

| 现有入口（仓库相对路径） | 当前真实覆盖 | 迁移后归属/保留断言 |
|---|---|---|
| tests/acquisition/test_acquisition_cnbc_live.py | 1994年份页→规范采集工件，1项 | integration/live/acquisition；发现/规范化/来源 |
| tests/media_download/test_pipeline_acquisition_to_media_download_live.py | CNBC 2000、YouTube各1项采集→下载 | integration/live/acquisition_download；真实registry/下载/manifest |
| tests/transcription/test_integration_live.py | CNBC 623秒→全部transcription/双section/六层复用，1项 | integration/live/transcription；原门禁逐项保留 |
| tests/translation/test_integration_live.py | synthetic:translation:live四句/两section，真实Codex，1项 | integration/live/provider_contract；**不能作为CNBC来源** |
| tests/srt_processing/sample_runner.py、candidate_runner.py、candidate_v3_runner.py | 消费已存真实上游、历史v1/v2/v3隔离/比较，非独立live pytest | integration/runners与historical_replay；旧资产/profile隔离，不重写历史 |
| tests/subtitle_rendering/test_integration_local.py、sample_runner.py | v3真实同源完整样片/逐cue像素/媒体/复用，1项 | integration/local_media；不把技术通过当语义通过 |

目前共6项显式外部集成pytest（5个文件），另有离线真实适配器/跨层集成，不能只按文件名迁移。
translation合成fixture的 `go— ahead` 回归需保留为显式provider契约场景，但不用于最终同源样片；
CNBC正式translation来源是SP-08A两次真实请求，与上述四句fixture不同。

`tests/transcription/live_fixture.py` 通过crawler/resolver＋requests下载HLS片段、ffmpeg裁切，
再写download manifest；不是生产 DownloadAssetVideoService 的完整调用。移动它不能凭空得到
完整 acquisition→media_download→rendering 生产端到端证明。必须明确是“真实派生fixture准备”。
新完整生产E2E另选无需测试私有裁切的合法短资产，或先批准正式媒体派生契约，不能伪装fixture。

现有入口不统一：transcription handler是`execute()`，translation/srt/rendering是`handle()`；
acquisition/media_download目前没有interfaces文件，transcription真实composition还在test runner中。
编排实现前需补最小公共facade/composition，不能跨模块import私有application/infrastructure凑通。
acquisition当前没有可直接当作阶段成功完成证明的通用manifest，需新增receipt或证据绑定，
不能仅凭meta.json存在跳过采集。

## 2. 提议架构与依赖规则

第一版只做单机、同步、单资产串行，不加数据库、worker、Web框架、云持久化或通用插件引擎。

```text
acquisition → media_download → transcription
 → srt_processing：英文候选块
 → translation：分批初译 → 双语修订与最终排时
 → srt_processing：验证并导出 SRT
 → subtitle_rendering：ASS 与烧录
 → 独立 agent 样片回归（非自动发布门禁）
```

新路径以 ADR-0009～0012 为行为依据，不执行 ADR-0007 的独立语义阶段。
阶段按用例而非模块名区分，两个 srt_processing 用例各有独立证据；媒体及上游工件经公开
来源绑定传入需要它们的阶段。合规 warning 不阻断依赖，硬错误不得当作成功。

- domain：有限阶段ID、依赖、执行/导入/只验证动作、失败传播和纯计划；不实现业务规则。
- application：`plan_asset / run_asset / resume_asset / verify_run`，消费 `StagePort`、
  `ArtifactVerifier`、`RunStore`、`AssetLock`、`Clock` 抽象；阶段adapter返回统一摘要。
- infrastructure/composition：显式注入各模块公共factory/handler、锁/receipt文件系统adapter。
- interfaces：typed命令/结果，供以后CLI/Web薄调用；本轮不建CLI/Web。

**需要批准的最小跨模块例外**：只有orchestration的stage adapter/composition可import各功能模块
`interfaces` 下稳定command/handler与显式public factory；domain/application仅依赖自身ports与
archive_core。public factory内部组装自身私有适配器，不把具体SDK对象泄漏给编排。
各功能模块之间仍不得互相import；不能让root规则的“仅core/infra可import”例外蔓延到任意调用方。
架构AST测试验证允许的目录/符号清单，禁止test runner成为生产composition依赖。

## 3. 命令、动作与授权

提议 `PipelineCommand`：asset_id、output_root、target_stage、input_bindings、
`mode=plan|execute|verify`、`allowed_actions`、budget、resume_run_id（可空）。不接收随意shell命令。
每阶段计划给出 `action=import_verified|verify_reuse|execute|blocked`、依赖证据hash、原因、
可能昂贵调用和授权需求。请求计划本身不构造模型/调用版本预检网络；静态只读验证与真实preflight分开。

- target之前缺昂贵输入不自动补跑：不在allowed_actions中即blocked，列缺失路径及费用类别。
- plan严格0写/0网络/0provider/0编码；真正工具probe另作为显式只读preflight动作。
- execute只调用已授权动作，先校验计划输入仍同hash；计划过期重新plan，不顺手运行新费用步骤。
- resume重新验证各完成阶段全部证据及identity，不以run receipt或文件存在决定跳过。
- verify严格只读；不创建run目录、不写log/receipt，不调用provider/planner/encoder。
- overwrite不从顶层一次性广播；默认false，冲突fail。每个待替换阶段及输入需独立授权，
  推荐新output root；本项目“不删除任何文件”的安全规则仍有效。

## 4. 运行记录、来源绑定与路径契约

### 4.1 Run状态不是阶段manifest的替代物

拟由archive_core定义 `pipeline.plan.v1`、`pipeline.run.v1` 和 `pipeline.input-bindings.v1`。
输出在新root经build_asset_workspace构造资产目录；run receipt在其专门的版本化运行子目录
（例如 `pipeline_runs/<run_id>/`，须由archive_core新增路径契约，不可先在runner自创）。
receipt至少含run/parent ID、asset、请求/计划hash、origin/imported证据、各阶段action、
状态 `pending/running/succeeded/reused/imported/failed/blocked`、结果manifest证据、调用/写入计数、
错误类别与时间。完成依赖以阶段证据再次校验，不信任receipt自报。

质量另有 `technical/semantic/visual/audio_sync/human_release` 状态，使用
`pass/fail/pending/not_run`；不能用run succeeded伪造人类release通过。
审核状态与执行状态分开。语义待审或发现语义问题须如实记录，不自动阻断正式产物输出；
硬正确性错误仍阻断，不把 warning 或 review pending 偷换成成功的质量签字。

### 4.2 从空工作区生成同源产物

首次完整集成在 archive_core 定义的工作区中生成全新产物，各阶段只消费同次运行中经验证的
上游公开工件。媒体、转录及字幕必须同源，阶段完成仍由 manifest、hash 和内容校验共同证明。
不建设旧资产导入、旧格式离线转换或兼容 loader 来恢复已删除产物，不重签旧 manifest。
后续恢复与复用只针对本方案生成的现行工件，不能把文件存在当成功。

旧 CNBC 623 秒样本的准备曾使用测试私有媒体裁切，不能直接冒充完整生产链路。新完整集成
应选可直接下载的适当完整资产；如继续用 CNBC 章节片段，应先在媒体模块建立显式派生用例，
由编排调用公共接口并保存原媒体与时间映射证据，不把裁切业务藏进测试 fixture。

## 5. 锁、失效、失败与恢复

- 先只支持一个资产workspace一个进程持有的OS advisory排他锁，锁文件保留不删；imported来源
  只读，不能通过链接回写。跨进程竞争立即报asset_busy；陈旧文件存在不等于锁仍被占用。
  锁在整个计划执行期持有，提供TOCTOU再hash；锁不是改写未配合旧工具的文件的许可。
- source alignment变化使translation、semantic、srt、rendering需重新验证/产生新版本；
  初译变化不使ASR或英文分块失效；后处理变化只影响其下游；字体/渲染profile变化不重跑翻译或后处理。
- 阶段自己负责checkpoint/retry和manifest-last；编排不额外重试一次模型以致费用翻倍。
  不把阶段failed report解析成阶段完成；不同handler的异常/结果由adapter映射，不修改其业务语义。
- 中断后有有效成功manifest才可verify_reuse；有部分输出/混合代次即conflict，保留所有残留。
  中途失败不继续后继、不中断成功前序资产，不自动回滚、不删除；新run记录父run及原因。
- 完整复用的**阶段输出** bytes/mtime不变、provider/ASR/内容编码/stage写均0；是否写新run receipt
  必须单独统计。真正“整次零写”用verify模式，不以新审计文件混淆零写口径。

## 6. 集成测试最终唯一归属

按用户要求采用严格口径：真实服务/模型/媒体集成，模块跨层workflow＋真实adapter，真实文件系统/
codec/library集成及生产composition连通性都归 `tests/orchestration/integration/`；不只是live测试。
模块目录只留下隔离单元/纯contract/架构测试（外部边界注入fake/mock）。**不能靠改名叫unit逃避迁移**。

建议目录：

```text
tests/orchestration/
  unit/                         # 纯DAG/授权/恢复，全部StagePort fake
  integration/
    inventory.json              # 旧nodeid→新nodeid/拆分/理由/fixture/门控
    offline/                    # 多模块fake昂贵边界、真实local/codec/store的集成
    local_media/                # 真font/libass/ffmpeg，无网络仍昂贵，显式门控
    live/                       # source/network/ASR/provider分场景门控
    runners/                    # 真实样本与历史v1/v2/v3重放、共用保全/receipt
    fixtures/                   # 新链路静态测试输入；非生产代码
```

### 6.1 离线集成迁移清单（按内容拆，不整文件盲挪）

| 当前文件/组 | 目标处理 |
|---|---|
| acquisition/test_acquisition_artifacts.py、test_acquisition_crawlers_offline.py | 真实writer/文件/多组件链移offline/acquisition；单parser＋fake HTTP单元留模块 |
| acquisition/test_acquisition_infrastructure_offline.py | 单adapter纯响应映射留；真实writer/组合链有则拆移 |
| media_download/test_media_download_contracts.py | 纯领域/假端口unit留；真实store/文件/组合workflow拆移offline/media_download |
| transcription/test_transcription_audio_vad_asr.py、forced_alignment、official_transcript_fusion、sentence_boundaries、workflow | 纯规则/fake单adapter留；真实LocalStore/工作流/多服务publication/cache连通性拆移offline/transcription |
| transcription/test_transcription_observability.py | 纯event/聚合留；真实JSONL sink/持久化联动拆移offline/transcription |
| transcription/live_fixture.py、live_runner.py、test_live_fixture.py | 测试专用部分及其全部回归迁入integration；可投产composition提取到模块公共factory，不让生产import tests |
| translation/test_translation_application.py、test_codex_cli_provider.py、test_translation_domain.py、test_translation_composition.py | fake port纯workflow/请求payload规则留；真实local prompt/checkpoint/store/provider进程协议串联/composition连通性拆移offline/translation |
| srt_processing/test_cross_layer.py、test_codec.py、test_local.py、test_segmentation.py | 真实FS/pysubs2/固定jieba包字典集成移offline/srt；纯算法/fake加载器case可留 |
| srt_processing/test_workflow.py、test_interfaces.py、test_composition.py | 单workflow/handler＋所有边界fake的unit留；实际多组件handler/codec/store组合拆移offline/srt |
| srt_processing/test_sample_runner.py、test_candidate_runner.py、test_candidate_v3_runner.py、test_two_way_projection.py及runner/projection helper | 属于集成基础设施的回归与历史比较一起迁移；不在旧路径保留包装入口 |
| subtitle_rendering/test_acceptance_cross_layer.py、test_acceptance_faults.py及acceptance_support | 整体移offline/rendering，所有重签/故障/manifest-last断言保留 |
| subtitle_rendering/test_ass.py、test_fonts.py、test_local.py、test_pixel.py、test_composition.py、test_sample_runner.py | 真库/FS/生产组装/runner集成拆移offline/rendering；纯字符串/假字体/假进程单元可留 |
| infrastructure/test_infrastructure_adapters.py、test_process_bytes.py | 真本地FS/真实子进程/配置读取集成拆移offline/infrastructure；fake runner参数映射单元留 |
| archive_core/*.py、transcription/test_archive_core_transcription_contracts.py | 纯DTO/版本/hash/纯路径函数仍为unit；如发现实际IO则逐case拆移；不因跨两个DTO而判集成 |

其余纯domain/输入门禁（fake store/probe）、mock SDK/process/preflight、layout/rules与AST架构
测试留对应模块。上表是已读源码后的迁移候选清单；实施第一片须对目前62个test文件的每个
collected nodeid完成inventory判定，不能据此声称已经逐项迁移/覆盖完全。
共享fixture搬到合适support模块，不从另一个test_*.py import helper；仅处理迁移产生的引用，
不借机重构生产代码。需移除旧入口/文件时依安全规则先取得确认，本轮没有删除。

### 6.2 集成矩阵与门控

| 模式 | 入口/输入 | 执行与质量边界 |
|---|---|---|
| 默认offline | 全套pytest；昂贵边界fake，真实轻量local/codec按需 | 无网络、ASR、provider、ffmpeg或系统字体；迁移前后离线断言不能减损 |
| local-media replay | 首轮新产物中的最终稿→render→reuse | 完整生成之后的增量复用测试，不替代首轮完整运行 |
| provider-contract live | 原四句合成fixture | 验证auth/prompt/protocol/复用，不混入CNBC发布链 |
| full-fresh live | 空产物工作区，从采集到最终视频 | 编排完成后的首轮完整验收；真实下载、ASR、翻译、烧录及逐阶段审核 |

统一提议门控 `RUN_ORCHESTRATION_INTEGRATION=1`＋场景allowlist（local_media/network/asr/provider）
及显式run plan。默认均关闭；显式开启后缺工具/凭据/源工件应失败并列出precondition，不能skip
造成假绿。旧RUN_REAL_NETWORK/RUN_TRANSCRIPTION_INTEGRATION/RUN_CODEX_CLI_TRANSLATION_INTEGRATION/
RUN_SUBTITLE_RENDERING_INTEGRATION不隐式触发新入口；迁移完成后移除旧启动路径并更新指南。

## 7. 逐阶段产物审核、样片交付与独立回归

编排集成必须产出完整新MP4/ASS/plan/reports/manifests、input bindings、run receipt、
保护集前后快照、调用/写入计数、工具身份与精确样片绝对路径/hash/时长；不能只留tmp_path。
先跑默认offline，再首次生成、同进程reused、独立新进程reused；首轮输出保留，后续复用不改上游或已有输出。
新cue数不是预设163，不能以强行保cue数掩盖新语义切分。

用户要求的“用该集成产出的样片再用agent验证”明确为后续验收：非作者agent先独立看原文译文，
再核真实输出链/关键意义/边界/像素/媒体/复用；报告实际看帧/核听覆盖，不能只抄runner结果。
无法听音则该轴pending，最终人类完整播放。回归如实报告，不新增语义自动发布门禁。详见[实验协议§6.3](../../reviews/2026-10-24-semantic-contract-and-experiments.md)。
旧样片已删除；不能用历史报告或图表冒充新样片回归。

### 7.1 实施 agent 的逐阶段审核责任

实现本方案的 agent 必须读取编排集成测试真实产物，不得只读 pytest 摘要或让测试自报质量。
对本次完整集成生成的每阶段产物逐项审核，包含重新产生的采集、媒体与转录。
新产物的文本内容按全样本审核，不只挑成功片段。每阶段记录路径/hash、覆盖范围、证据、问题及结论。

| 产物 | 实施 agent 必须核对 |
|---|---|
| 采集/媒体及导入证据 | 资产与章节同源、时间范围正确，新源媒体与派生关系可追溯 |
| 转录与编辑标记 | 词身份和时间保留、标记有官网来源、口语修正未被误删 |
| 英文候选块与预算 | 逐块读断点是否自然，专名/紧密短语是否断裂，源词覆盖和未解项是否诚实 |
| 初译及标题 | 逐块对照完整原句，检查忠实性、术语、数字/否定/条件及是否把意义移到别块 |
| 修订与最终双语稿 | 对照修订前后，核每个分组的双语归属、借时、重试次数及所有残余 warning |
| SRT/ASS与报告 | 正文/时间对应同一权威稿，标记不泄漏；量化和显示问题准确披露 |
| 最终视频与声音 | 实际播放，核字幕换屏与讲话意义、尾词覆盖、声音保留、可读性及遮挡/闪烁 |
| 复用结果 | 同进程及新进程复用没有重复昂贵调用，正式工件及历史来源未变化 |

视频审核须记录实际播放、听音与看帧的范围；能完整播放时审核整个样片，并重点核查旧故障位置。
若能力仅支持帧图而不能听音，不得宣称声画或语义同步通过；该轴记 pending，并明确交给可核听的
独立 agent 或用户完成。不能用文本或波形自动指标替代真实声音审核。

实施 agent 的审核不能由独立 agent 报告代替；完成后仍保留原要求的独立 agent 样片回归。
审核与独立回归报告属于实施交付，但不新增运行时语义门禁；发现语义问题不触发未授权的重译，
不隐藏问题或把未核范围写成通过。

## 8. 迁移完成的可机械验收条件

1. inventory覆盖迁移前所有collected nodeid，新旧对应/拆分理由与参数化实例可核对；离线语义断言
   不减少，不仅比较测试数量。老显式6项外部场景全部有新归属；历史文档记录保留，旧文件已删除；旧版专用 runner 不作为新生产入口保留，断言替换须有理由。
2. AST/路径与collection检查：编排外没有integration/live入口、真实外部调用或跨层实际组装测试；
   模块unit不import编排integration helper；未按integration命名的组合测试也被inventory捕获。
3. 默认全套offline通过；各显式场景分别门控，打开而缺依赖时非零；不存在“先手工跑另模块测试”
   的准备依赖。首轮 full-fresh 按计划生成上游；只验证/复用模式缺工件则阻断，不能静默改为昂贵全量运行。
4. 编排内的真实全链场景实际调用生产公共handler，不靠测试私有workflow替身；导入/派生fixture
   coverage准确标注，full-fresh与frozen-upstream不混称。
5. 首次/复用/失效/锁冲突/中断/混合代次/源asset串换/路径越界/预算拒绝矩阵通过；新样片独立agent
   逐阶段实施审核及独立回归报告交付；未核听/未接受的质量项保留未通过。
6. 根/模块AGENTS、tests/transcription/AGENTS与ADR-0006/SR-07当前入口说明在迁移同一改动更新；
   历史归档验收记录不伪改为新入口。旧文件移除须先得到明确确认。

## 9. 替代方案与边界

不选：只把live文件改目录（遗漏离线集成）；重新实现每个模块业务规则的“大runner”；
保留旧入口做shim（违背唯一归属）；直接让编排import功能模块私有实现；重签旧manifest；
从空output每次重跑ASR/provider才能测下游；仅靠run receipt判完成；云worker/数据库平台化。

本ADR不取消模块单元测试、不把所有测试搬到编排，也不把离线集成迁移解释成清理生成资产。
旧 SA-00 未实施任务已按用户要求删除；新任务从本 ADR 的用例依赖拆解，不恢复旧队列。
