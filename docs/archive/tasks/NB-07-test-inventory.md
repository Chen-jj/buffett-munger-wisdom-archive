# NB-07 集成测试逐 nodeid 基线与迁移记录

> 2026-11-17归档说明：逐nodeid测试迁移与盘点已交付；明示退役、未等价断言及历史失败记录原样保留。 原路径`docs/tasks/NB-07-test-inventory.md`；原状态、历史不commit/push约束及验证结果属于当时记录。后续入口：[NB-12](NB-12-chunking-quality-iteration.md) / [ADR-0013](../decisions/0013-typed-chunking-quality-and-regression.md)。

- 盘点基线：2026-11-05（Asia/Shanghai）。以下每文件计数是开工时状态；实际迁移见末尾记录与 inventory.json。
- 依据：ADR-0008 §6；真实 FS/codec/library/production composition、集成 runner 支持均归编排，纯 DTO/算法/全部外部边界 fake 的单用例留模块。
- 基线：`.venv/bin/python -m pytest tests/ --collect-only -q`，2586 collected（62 test files）；完整运行基线由负责人记录为2580 passed / 6 skipped。
- 分类：1935 个 unit，651 个 integration；参数化实例逐项记录，未以文件名推断全文件职责。
- 机器清单：[inventory.json](../../../tests/orchestration/integration/inventory.json)，包含每项原/目标nodeid、函数行号、源文件SHA-256、理由、fixture参数、门控及迁移状态。

## 分类边界与迁移注意

- acquisition 单 parser＋fake HTTP 留模块；crawler→registry→usecase→真实writer组合迁移。
- transcription 单 service 的 MemoryStore/fake provider 测试保留；完整多服务workflow使用真实 RuleBasedSentenceBoundaryDetector，归跨层集成。JSONL/report真实stream adapter单列迁移。
- translation application 名称不代表unit：现有所有workflow都使用真实LocalPrompt/Checkpoint/ArtifactStore，须迁移；Codex fake process仍实际写private协议文件。
- srt workflow/handler以MemoryStore/FakeCodec/FakeSegmenter边界注入为unit；production factory、真实pysubs2/FS/jieba另迁。
- rendering 纯ASS转义/假字体表/假Pillow测量仍unit；真实pysubs2、regex grapheme、Pillow像素构造和本地FS另迁。
- 默认离线不存在真实子进程的现有process_bytes测试：runner均fake，保留unit，不能因模块名盲迁。
- helpers 当前有从 test_*.py import 的关系：迁移时须将共享fixture最小提取到support，并更新引用；模块unit不得反向import编排integration helper。
- `test_live_fixture.py`、历史candidate/projection等虽含纯函数case，但测试对象为集成基础设施，随runner迁入编排；旧profile/planner专属断言待新版替换审计，不能保留旧生产路径来凑绿。
- 旧显式外部场景共6 nodeids（network3 + ASR1 + provider1 + local-media1）；新门控打开缺依赖须fail，不skip。

## 每文件计数

| 原文件 | unit | integration |
|---|---:|---:|
| `tests/acquisition/test_acquisition_artifacts.py` | 1 | 5 |
| `tests/acquisition/test_acquisition_cnbc_live.py` | 0 | 1 |
| `tests/acquisition/test_acquisition_crawlers_offline.py` | 10 | 2 |
| `tests/acquisition/test_acquisition_domain_application.py` | 11 | 0 |
| `tests/acquisition/test_acquisition_infrastructure_offline.py` | 24 | 0 |
| `tests/archive_core/test_archive_core_contracts.py` | 28 | 0 |
| `tests/archive_core/test_rendering_contracts.py` | 188 | 0 |
| `tests/archive_core/test_subtitle_contracts.py` | 128 | 0 |
| `tests/archive_core/test_translation_contracts.py` | 31 | 0 |
| `tests/infrastructure/test_infrastructure_adapters.py` | 11 | 11 |
| `tests/infrastructure/test_process_bytes.py` | 7 | 0 |
| `tests/media_download/test_media_download_contracts.py` | 30 | 17 |
| `tests/media_download/test_pipeline_acquisition_to_media_download_live.py` | 0 | 2 |
| `tests/srt_processing/test_boundaries.py` | 31 | 0 |
| `tests/srt_processing/test_candidate_runner.py` | 0 | 10 |
| `tests/srt_processing/test_candidate_v3_runner.py` | 0 | 9 |
| `tests/srt_processing/test_codec.py` | 0 | 84 |
| `tests/srt_processing/test_composition.py` | 0 | 2 |
| `tests/srt_processing/test_cross_layer.py` | 0 | 48 |
| `tests/srt_processing/test_inputs.py` | 88 | 0 |
| `tests/srt_processing/test_interfaces.py` | 11 | 0 |
| `tests/srt_processing/test_local.py` | 7 | 15 |
| `tests/srt_processing/test_planner.py` | 82 | 0 |
| `tests/srt_processing/test_ports.py` | 18 | 0 |
| `tests/srt_processing/test_probe.py` | 35 | 0 |
| `tests/srt_processing/test_rules.py` | 71 | 0 |
| `tests/srt_processing/test_sample_runner.py` | 0 | 17 |
| `tests/srt_processing/test_segmentation.py` | 3 | 1 |
| `tests/srt_processing/test_two_way_projection.py` | 0 | 9 |
| `tests/srt_processing/test_workflow.py` | 136 | 0 |
| `tests/subtitle_rendering/test_acceptance_architecture.py` | 21 | 0 |
| `tests/subtitle_rendering/test_acceptance_cross_layer.py` | 0 | 141 |
| `tests/subtitle_rendering/test_acceptance_faults.py` | 0 | 107 |
| `tests/subtitle_rendering/test_ass.py` | 26 | 18 |
| `tests/subtitle_rendering/test_composition.py` | 0 | 7 |
| `tests/subtitle_rendering/test_ffmpeg.py` | 31 | 0 |
| `tests/subtitle_rendering/test_fonts.py` | 35 | 7 |
| `tests/subtitle_rendering/test_inputs.py` | 175 | 0 |
| `tests/subtitle_rendering/test_integration_local.py` | 0 | 1 |
| `tests/subtitle_rendering/test_layout.py` | 181 | 0 |
| `tests/subtitle_rendering/test_local.py` | 1 | 10 |
| `tests/subtitle_rendering/test_pixel.py` | 0 | 30 |
| `tests/subtitle_rendering/test_probe.py` | 95 | 0 |
| `tests/subtitle_rendering/test_sample_runner.py` | 0 | 21 |
| `tests/subtitle_rendering/test_workflow.py` | 75 | 0 |
| `tests/transcription/test_archive_core_transcription_contracts.py` | 65 | 0 |
| `tests/transcription/test_integration_live.py` | 0 | 1 |
| `tests/transcription/test_live_fixture.py` | 0 | 7 |
| `tests/transcription/test_transcription_audio_vad_asr.py` | 25 | 0 |
| `tests/transcription/test_transcription_forced_alignment.py` | 35 | 0 |
| `tests/transcription/test_transcription_observability.py` | 28 | 2 |
| `tests/transcription/test_transcription_official_transcript_fusion.py` | 31 | 0 |
| `tests/transcription/test_transcription_sections.py` | 17 | 0 |
| `tests/transcription/test_transcription_sentence_boundaries.py` | 22 | 0 |
| `tests/transcription/test_transcription_workflow.py` | 0 | 11 |
| `tests/translation/test_codex_cli_preflight.py` | 34 | 0 |
| `tests/translation/test_codex_cli_provider.py` | 5 | 36 |
| `tests/translation/test_integration_live.py` | 0 | 1 |
| `tests/translation/test_openai_responses_adapter.py` | 23 | 0 |
| `tests/translation/test_translation_application.py` | 0 | 13 |
| `tests/translation/test_translation_composition.py` | 15 | 4 |
| `tests/translation/test_translation_domain.py` | 44 | 1 |

## 用户已授权的整文件旧路径移动/移除清单

下列文件全部collected cases归集成，迁移后应移除旧路径；负责人已于2026-11-05转达用户明确批准下列最终29条整文件/helper旧路径迁移/移除；授权不涉及input/output或新生成资产。最终已核对仅下列29个测试/助手旧路径移除。
- `tests/acquisition/test_acquisition_cnbc_live.py`
- `tests/media_download/test_pipeline_acquisition_to_media_download_live.py`
- `tests/srt_processing/test_candidate_runner.py`
- `tests/srt_processing/test_candidate_v3_runner.py`
- `tests/srt_processing/test_codec.py`
- `tests/srt_processing/test_composition.py`
- `tests/srt_processing/test_cross_layer.py`
- `tests/srt_processing/test_sample_runner.py`
- `tests/srt_processing/test_two_way_projection.py`
- `tests/subtitle_rendering/test_acceptance_cross_layer.py`
- `tests/subtitle_rendering/test_acceptance_faults.py`
- `tests/subtitle_rendering/test_composition.py`
- `tests/subtitle_rendering/test_integration_local.py`
- `tests/subtitle_rendering/test_pixel.py`
- `tests/subtitle_rendering/test_sample_runner.py`
- `tests/transcription/test_integration_live.py`
- `tests/transcription/test_live_fixture.py`
- `tests/transcription/test_transcription_workflow.py`
- `tests/translation/test_integration_live.py`
- `tests/translation/test_translation_application.py`

集成helper同迁，旧路径也需确认：
- `tests/transcription/live_fixture.py`
- `tests/transcription/live_runner.py`
- `tests/srt_processing/sample_runner.py`
- `tests/srt_processing/candidate_runner.py`
- `tests/srt_processing/candidate_v3_runner.py`
- `tests/srt_processing/two_way_projection.py`
- `tests/srt_processing/acceptance_fakes.py`
- `tests/subtitle_rendering/sample_runner.py`
- `tests/subtitle_rendering/acceptance_support.py`

混合文件仅抽取归集成case、保留unit，不需移除整个旧文件。若实现时发现新增孤儿文件，先增补确认，不自动延伸授权。

## 开工盘点验证（历史）

- inventory机械复核：2586原nodeid恰好一次、参数化完整、对应62原文件；记录源hash及真实函数范围。
- 开工盘点时未执行迁移、未修改 assert、未移除旧入口、未生成媒体。
- 目标nodeid为拟定路径，需迁移执行后实际collection逐项核对；不能将此清单当作已迁移或断言已验收。
- 新契约将替换旧schema/句级翻译/比例planner，必须在实施时逐项填替换nodeid与理由，仍保留覆盖、时间、溯源、发布失败和复用有效断言。


## 2026-11-06 翻译与旧公共契约迁移

- 实测 collection 映射207条：54迁至编排、75按现行契约替换、78隔离测试保留。每条都有实际
  `new_nodeid`、状态、理由；迁移不依赖旧句级生产实现。旧原子回滚删除行为替换为混合代次失败/保全。
- 原两份完整入口在已确认名单内，移动 `test_translation_application.py` 与 `test_integration_live.py`；
  Codex private 文件协议、实际 prompt 资源和生产配置组装按 case 拆分。纯 provider SDK mock、前置校验、
  规划、结果、cache 规则仍是隔离单元。共享fixture在非 `test_*.py` helper，不反向导入编排集成。
- provider live 现为 `RUN_ORCHESTRATION_INTEGRATION=1` +
  `ORCHESTRATION_INTEGRATION_SCENARIOS=provider_contract`；旧环境变量不触发，开启后无依赖是失败。
- 定向276 passed / 1 skipped；skip为真实provider默认未开启。其他模块迁移和完整真实样片另验收。

## 2026-11-06：NB-02/NB-05 负责范围的迁移记录

原 SRT/rendering 与对应 core 字幕/渲染契约共 **1975** 个 nodeid：860 同路径保留/适配、
416 移到编排集成、651 逐条关联新版替换验证、45 退役旧算法/候选专属断言、
当时3项旧探测器原始输出形状断言不与 parser 等价；下文已补齐。
所有非空 actual_nodeid 均对当前 pytest collection 核验；替换理由在 inventory 的
contract_disposition。相同新测试可覆盖若干旧专属形状案例，不能把映射解读为测试数量等量。

- 真实轻量 SRT codec、FS、composition 迁到 offline/srt_processing；旧验证过的原子发布、
  投影回读、显式覆盖、bytes/mtime 不变、篡改/重签与输入证据门禁用现行最终稿重验。
- 真实轻量 ASS、regex adapter、pixel 像素与FS、独立SR-06故障/对抗链迁到 offline/rendering；
  假端口 workflow、纯布局/语法/架构仍留隔离测试。共享 fixture 不再从另一 test_*.py import。
- 真渲染 replay 归 local_media，使用现行 full-fresh 的同源工作区；显式开关缺前置即失败。
  旧SRT candidate/v3/sample、旧SR-07 runner按授权退役，无兼容入口。历史两方静态投影
  不依赖生产旧契约，保留在 historical_replay，历史报告及静态夹具保留。
- 定向 **1540 passed / 1 skipped**（关闭的 local_media），另新增 ASR provider ID 不是
  切点/合法 ASR-only 无 fusion 的回归定向 **194 passed**（与前数不可累加）。
  全仓库最后集成结果由负责人独立记录。

### 2026-11-06：SRT 孤儿探测器清理

用户另行明确批准移除 `src/srt_processing/infrastructure/probe.py`，仅删除此文件；
`tests/srt_processing/test_probe.py` 原路径保留，改测公共 PTS 对 SRT 预算及未知/短 gap 的影响。
实际解码 argv、时长、源媒体指纹与异常由 `tests/media_download/test_media_boundary.py`
用 fake process/evidence 隔离复验，无外部进程或文件 IO；真实适配器运行仍归编排集成。
孤儿清理时，35个旧节点中32项已有对应；3项原始JSON类型和多流响应门禁随后在实际PTS适配器
补齐。容器或所选视频流的原始duration必须为JSON字符串（拒绝整数2、布尔True），
`-select_streams v:0`响应必须恰好一个视频流对象；不禁止源文件含多个视频流。
定向先复现5失败，加入门禁后媒体边界、公共facade及runner定向61 passed；35项映射齐全。
未改变合法时长或PTS计算、已发布DTO、来源绑定及现行复用路径。版本门禁仍由rendering探测器验证。
三套定向（SRT/实际 PTS/渲染探测）131 passed；完整默认离线 2334 passed / 7 skipped
（9.83s）。未触及媒体、帧、模型和新生成工件。

## 2026-11-06：全量机械验收及 runner 保护范围

- 基线2586个唯一nodeid、62文件；2541个条目映射到当前collection中实际存在的目标，45个有理由退役；
  0重复、0 pending、0缺失目标。当前收集2351项。测试/助手旧路径移除集合与用户批准的29项完全一致，
  未把已另行授权的生产孤儿文件混入测试授权。编排外无遗留集成runner、旧开关或反向导入集成fixture。
- 独立门控测试7项：network 3、asr 1、provider_contract 1、local_media 1、full_fresh 1。两个network下载
  场景只跑真实来源网络并用stub验证下载契约，不冒称yt-dlp；完整真实执行结果另见NB-08。
- 编排runner补19项离线保护/门禁回归，包含同内容同mtime的词法软链接换靶、悬空链接、同basename保全、
  空锁文件hash、上游/成片污染、只改mtime、额外文件、零写/零调用、坏子进程状态/JSON/返回码。
  保护集区分词法链接和目标的证据；verify整次保护快照可处理0字节锁。旧对应项已逐条更新到实际新nodeid。
- 仍不能把映射等同旧断言：旧SRT样片runner五项逐文件前置提示以及三项非法CLI资产参数不再有原入口；
  现行来源链/资产类型门禁与只读缺产物拒绝保留，但不声称按旧路径逐一故障注入或保留旧错误字符串。
  旧候选独占JSON助手、容量预检stdout形状及旧固定fixture的样本基线退役；分别保留fresh拒绝已有根、
  只读计划不生成、缺现行前置不构造编排，见逐项`contract_disposition`。
- 最终离线：`RUN_ORCHESTRATION_INTEGRATION=0 ORCHESTRATION_INTEGRATION_SCENARIOS='' .venv/bin/python -m pytest tests/ -q`
  → **2344 passed / 7 skipped（10.23s）**。跳过项为关闭的显式外部场景。本轮不执行live、不改正式工件。
