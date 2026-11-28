# NB-17 融合标点权威性与句界恢复

状态：**已完成，负责人独立验收通过**（2026-11-28）。用户明确授权子 agent 实现、负责人亲自验收；未提交或推送。

## 契约与输入

必读根 AGENTS、对应模块 AGENTS、[ADR-0017](../decisions/0017-sentence-boundary-evidence.md)。工作树已有的句界改动属于本轮基线，不得回滚。固定实际 v7 输入为 `output/cnbc-2020-adr0017-20261127/run-boundaries-v7-3/cnbc_2020_part{1,2}`，当前结果 734 / 1,137 句。词 ID、真实例子、保护断点以 ADR 为准。

融合正文的标点具有最终权威性；`asr_only` 的独有和冲突保留两种来源都同等有资格切句。官网句号不得新增融合稿没有的句界，官网关联范围不得抑制融合句末。域名、姓名首字母、缩写、省略号例外按融合正文处理；停顿与 ASR 分段不参与句界，可靠换人、文档章节、文末收尾仍生效。不得调整 Cass/Kass 等融合选稿裁决。

## T1：融合跨句组合的独立词时间

- 实现子 agent 负责 `src/transcription/application/fusion.py`、`domain/fusion.py` 及必要的融合契约纯规则和定向融合测试。不得修改句界应用层、句界测试、公共 BoundarySource 枚举，避免与 T2 冲突。
- E11 当前 `See's. And` 合成一个词条；选中候选本来已有 `see's 1550965–1551350`、`and 1551451–1552485` 的独立时间。只在组合中跨过有效句末的必要情况下发布独立词条，保持文字、候选取舍和源 ID 保序完整；不得用原 `a / season.` 的词边界对应这两个官网词，也不得按字符均分时间。
- 选择最小数据契约，明确多对多来源如何在独立词条间完整、唯一地记账。必要时扩展契约并更新缓存身份，禁止凭空赋予无声学证据的词时间。单词替换、金额、正常同句组合不被扩范围改写。若确实缺少可用证据，报告负责人，不硬拆。
- 测试至少覆盖真实 `See's. And` 形态、无有效逐词时间不发布假切分、正常复合金额不拆、序列化及来源对账。交回测试结果、改动契约与剩余风险。不能运行真实模型、联网、覆盖输入、提交推送。

## T2：按最终融合正文切句及典型反例测试

- 可与 T1 并行开发，最终集成依赖 T1 的独立词条。允许改 `src/transcription/application/sentences.py`、`domain/sentences.py`、必要的 editorial 纯规则；`src/archive_core/interfaces/transcription.py` 的边界来源枚举及其直接契约测试；对应 `tests/transcription/` 句界/编辑标记测试和 `tests/orchestration/integration/offline/transcription/` 的必要联动断言。先读 archive_core 模块规则。不得改融合实现或扩大到 chunking/翻译/渲染。
- 移除官网词表文本替代 `word.text`、官网原句末投影和覆盖屏蔽在标点裁决中的作用。先按现有证据分离保留的 CNBC 编辑长破折号，再对同一份最终正文判断句界；E10 `it?—` 应切，`but— Our` 不因破折号或停顿切。
- 去除停顿/segment 对切点及来源分类的影响；文末无标点明确收尾，政策和缓存身份升版。保留公共 DTO、manifest 校验、原子发布与复用门槛，不保留死分支或旧配置兼容。
- 无可靠身份保持未知。E01 问题必须与回答分开，问题不得被标 Buffett；无需新增引语身份推断系统。
- 保好补充：同章内最近可靠 speaker 仅为换人检测前向记忆，不能反向给未知问题填标签，跨章清空。真实 `Greg, would you like to add anything → Really nothing to add, Warren.` 仍需切，邀请句保持未知也可；新测试覆盖同章保留、跨章清空及没有前位身份时不盲切。
- 每类典型反例取至少一句真实例子，夹具必须离线自包含，不能依赖被忽略的 output：ASR-only 句末（真实多词与冲突保留）、问答+未知标签、编辑符号后的问号、融合逗号/官网句号保持、融合句号/官网连续照切、独立词后的 See's 句末、域名/姓名缩写、长短间隔不变、明确换人、章节、无标点文末及长句。可参数化覆盖 ADR 全部 E/P/Q/C 边界。
- 既有断言若与已确认新契约冲突，应给出新旧断言为何改变的说明；不得为了绿测削弱无关来源、时序或复用检查。子 agent 只运行定向离线测试，不做真实阶段、提交或推送。

## 负责人独立验收

1. 保存实施前工作树与工件指纹，审查两名实现子 agent 的实际 diff 和必要的联动改动。
2. 独立执行 `.venv/bin/python -m pytest tests/ -q -m 'not live'`，全部通过才可交付。
3. 在新目录用冻结 v7 声学输入及已保存评分（含 `run-boundaries-v7-3/new_acoustic_evidence_cnbc_2020_part1.jsonl`）回放新融合输出与新句界。未知评分记录立即报告，不静默造证据；仅必要时核对本轮本地模型授权，不跑 ASR/全片对齐/下载/翻译/渲染。
4. E01–E11、P01–P14、Q01–Q03 共 28 处指定反例逐一通过；C01 与 Q04–Q06 连续。以 ASR/官网来源 ID 追踪新增词粒度，不能用变化后的 `w*` 或 `s*` 号假定对应。
5. 检查旧结果全部断点：每个新增/移除的断点记录原文、位置、理由。原有合理句号、换人、章节、域名/姓名内部连续、20 ms 句号、but—Our 连续都必须保住。对拿不准的实际断法才问用户。
6. 核对正文、时间、来源覆盖完整、公共 DTO、句章覆盖、原输入 hash/mtime/inode 不变以及同进程和新进程复用零模型调用、零产物改写。记录回放路径与限制。
7. 更新 transcription 模块指南、PROGRESS、ADR/任务验收证据。真正完成后把 ADR 与任务归档，保留未核听及出版质量限制。不可自行提交或推送。

## 交付证据

子 agent 分别交回改动路径、定向命令/结果、来源契约说明、未解决事项。负责人记录完整离线结果、逐例断点表、所有边界变动审查及实际工件链接；技术验收不自动等同于全片核听或出版验收。

## 第一轮负责人审查（2026-11-28）

`output/cnbc-2020-adr0017-20261128/run-accepted-1` 两场生成 744 / 1,154 句，32 个 ADR 目标通过，原融合正文除 E11 以外逐词字段保持；同进程和新进程缓存零评分、零工件改写。但负责人审读全部断点变动后退回 T2：同章前向 speaker 记忆把新回答的纯 ASR-only 前缀错误归给前位，产生 `uh ｜ Thank you`、`Okay, ｜ thank you`、`Well, ｜ I agree…`、`Okay, ｜ Absolutely` 四处额外切分。本轮产物是未通过诊断，不能称最终验收。

修复要求：当前源句尚未出现可靠来源上下文时，不能仅凭上一句说话人把未知 ASR-only 前缀定成前位讲话。保住同章有来源的 Greg 邀请句换人，新增 ASR-only 回答前缀回归；修复后新目录重放、重新审读全部边界及独立运行完整离线套件。

## 第二轮最终验收（2026-11-28）

- T1 实现子 agent `fusion_word_granularity` 交付跨句词条发布及匹配身份 v8，四个融合定向套件 **110 passed**。T2 实现子 agent `sentence_rules` 交付句界 v3、统一边界来源、必要夹具联动及典型反例测试，五个定向套件 **202 passed**。辅助 agent `acceptance_runner` 只编写忽略目录的取证脚本；负责人亲自执行、复核，未以其摘要代替验收。
- 负责人独立执行 `.venv/bin/python -m pytest tests/ -q -m 'not live'`：**3010 passed / 1 skipped / 6 deselected，264.17 秒**。
- 新根 `output/cnbc-2020-adr0017-20261128/run-accepted-2`：**743 / 1,151 句**，28 个目标切点及 4 个连续样例全部通过。负责人审读全量 30 个新增、7 个取消边界，全部旧有效融合句末保留；7 个取消点依融合无句末的既定契约处理，不恢复官网标点。
- 四个首轮回答前缀误切已消除，新增对应回归；Greg 无标签邀请接话仍切，问题不反向获得回答人身份。未知标签保持未知。
- Part1 全部融合词去 ID 后逐字段不变；Part2 仅 E11 拆为 `See's. / And` 两条真实时间，其余去 ID 后逐字段不变。章节、注释、来源对账、公共 DTO、原输入指纹和时序检查通过。
- 同进程和新进程融合/句界复用零新评分、零管线产物改写；回放只查找保存的模型返回，零新模型加载/调用、零联网/ASR/全片对齐。原 v7 工件未修改。
- [负责人验收报告](../../../output/cnbc-2020-adr0017-20261128/run-accepted-2/负责人验收.md) · [逐例与全量断点审查](../../../output/cnbc-2020-adr0017-20261128/run-accepted-2/验收审查.md) · [完整离线记录](../../../output/cnbc-2020-adr0017-20261128/run-accepted-2/full_offline_suite.json) · [独立工件检查](../../../output/cnbc-2020-adr0017-20261128/run-accepted-2/owner_independent_checks.json)。未核听全片，不代表整条字幕管线出版验收。

## 自包含典型测试映射

| 类型 | 代表真实句子 / 场景 | 测试 |
| --- | --- | --- |
| 正式融合句末，包括词形冲突和专名 | E01–E09、P01–P14、Q01–Q03，26 个真实句子参数 | `test_adr0017_real_fused_sentence_endings` |
| 两类 asr_only 不被来源范围屏蔽 | `This question comes from David Cass.`，分别为冲突保留和官网完全没有 Cass | `test_adr0017_asr_only_sentence_end_survives_official_span` |
| 问答与未知身份 | `lower-middle class? ｜ Well, I certainly think…` | `test_adr0017_question_unknown_speaker_does_not_acquire_answer_identity` |
| 官网标点不能覆盖融合逗号或句号 | `2009, they…` / `we wish it. everybody…` | `test_adr0017_reference_punctuation_cannot_override_fused_text` |
| 问号加编辑符号 | `what did he call it?— the stock market study` | `test_adr0017_editorial_question_is_split_before_publishing` |
| 独立词时间与跨句组合 | `See's. ｜ And…` | 融合 `test_cross_sentence_substitution_publishes_real_token_times_and_unique_sources`；句界 `test_adr0017_separately_timed_sees_and_begins_next_sentence` |
| 明确接话与章内前向来源 | `Greg, would you like to add anything → Really nothing to add, Warren.` | `test_adr0017_same_chapter_forward_speaker_preserves_greg_handoff` |
| 不拆纯 ASR 回答前缀 | `Okay, thank you`、`Well, I agree`、`Okay, Absolutely`、`uh Thank you` | `test_adr0017_asr_only_answer_prefix_is_not_assigned_to_previous_turn` |
| 间隔与分段不影响 | `but Our Our position…`，20 / 2,000 ms | `test_adr0017_but_our_continuation_and_punctuation_ignore_gap` |
| 既有保好与缓存 | 域名、姓名首字母、Mr.、省略号、换人、章节、长句、无标点文末、发布失败和复用 | 同文件既有回归及 sections/workflow 离线集成；旧 pause policy 明确拒绝 |

以上测试位于 `tests/transcription/test_transcription_sentence_boundaries.py` 与 `test_transcription_official_transcript_fusion.py`；不依赖被忽略的 output。完整测试夹具联动只更新已替换的边界枚举/缓存政策参数，没有改变翻译、chunking、渲染业务实现或削弱其业务断言。
