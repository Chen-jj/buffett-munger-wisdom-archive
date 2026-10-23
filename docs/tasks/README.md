# ADR-0004 / ADR-0002 / ADR-0005 implementation task map

This directory decomposes the accepted decisions in
`docs/decisions/0004-transcription-source-sections.md`,
`docs/decisions/0002-translation-sentence-units.md`, and
`docs/decisions/0005-translation-codex-cli-chatgpt-provider.md` into
independently assignable, verifiable tasks.

## Shared rules

- Status values are `pending`, `in_progress`, `blocked`, `accepted`, and
  `superseded`. `superseded` preserves an uncompleted task whose intended work
  was replaced by a later accepted decision; it is not an acceptance result. A
  task agent changes only its own task status; the technical lead marks it
  `accepted` after reviewing the diff and test evidence.
- Before editing a module, the assignee must read its `src/<module>/AGENTS.md`
  (and `tests/transcription/AGENTS.md` for transcription tests).
- Preserve the user's existing uncommitted changes to ADR-0002, ADR-0004,
  ADR-0005, and `requirements.txt`. Do not reset, overwrite, or reformat them.
- Default verification is offline. A command marked **live gate** must never run
  merely as part of `pytest tests/ -q`; it needs the documented opt-in
  environment variable and external prerequisites.
- Generated media and model outputs remain under gitignored `output/` and are
  never committed. Deleting an existing generated workspace requires explicit
  user confirmation under the repository safety rule.
- No task may silently add backward compatibility for a `source_alignment.json`
  that lacks `sections`; both ADRs explicitly reject that shim.
- ADR-0005 adds Codex CLI without removing the accepted OpenAI Responses
  adapter. Provider selection is explicit, there is no fallback, and the two
  providers must never share checkpoints or formal artifacts across identities.
- After ADR-0005, all new real translation runs and live acceptance use only
  `codex-cli-chatgpt`. The superseded OpenAI live gate must not be run.
- The final acceptance gate is `python -m pytest tests/ -q -m "not live"`. A
  task may require this full gate even when it also has narrower tests.

## Required order and dependency graph

The order below combines ADR-0002 section 15 with ADR-0005 section 12. An arrow
means that the left task must be accepted before the right task starts.

```text
TA-01 public source-section contract
  -> TA-02 pure section derivation rules
  -> TA-03 transcription workflow/publication integration
  -> TA-03A restore provider-dropped trailing punctuation
  -> TA-04 transcription live-fixture migration [LIVE GATE]
  -> TA-05 public translation contracts
  -> TA-06 translation domain and request planning
  -> TA-07 translation application, checkpoints, publication, interfaces
  -> TA-08 OpenAI Responses adapter
  -> TA-09 configuration, module docs, status, full offline gate
       |-> TA-10 OpenAI translation integration [SUPERSEDED; terminal]
       `-> TA-11 provider-neutral generation parameters
  -> TA-12 process-runner stdin support
  -> TA-13 Codex CLI preflight and ChatGPT-auth safety
  -> TA-14 Codex CLI translation provider
  -> TA-15 explicit provider configuration, composition, and offline gate
  -> TA-16 Codex CLI translation integration [LIVE GATE]
```

There are intentionally no parallel implementation batches on this critical
path. This both follows the mandated migration sequence and prevents two agents
from editing `archive_core` exports, transcription sentence publication, or
translation package exports at the same time. Test-only investigation may run
in parallel, but it must not write shared files.

| Batch | Task | Module(s) | Depends on | Full offline suite? |
|---:|---|---|---|---:|
| 1 | [TA-01](TA-01-source-section-public-contract.md) | archive_core | none | yes |
| 2 | [TA-02](TA-02-transcription-section-rules.md) | transcription domain | TA-01 | no |
| 3 | [TA-03](TA-03-transcription-section-workflow.md) | transcription application | TA-02 | yes |
| 4 | [TA-03A](TA-03A-forced-alignment-trailing-punctuation.md) | transcription forced-alignment adapter | TA-03 | yes |
| 5 | [TA-04](TA-04-transcription-live-migration.md) | transcription live tests | TA-03A | yes, then live |
| 6 | [TA-05](TA-05-translation-public-contracts.md) | archive_core | TA-04 | yes |
| 7 | [TA-06](TA-06-translation-domain.md) | translation domain | TA-05 | no |
| 8 | [TA-07](TA-07-translation-application.md) | translation application/interfaces/local I/O | TA-06 | yes |
| 9 | [TA-08](TA-08-openai-responses-adapter.md) | translation infrastructure | TA-07 | yes |
| 10 | [TA-09](TA-09-configuration-and-status.md) | configuration/docs | TA-08 | yes |
| 11 | [TA-10](TA-10-translation-live-integration.md) | OpenAI translation live test | TA-09 | superseded; do not run |
| 12 | [TA-11](TA-11-provider-neutral-generation-parameters.md) | archive_core / translation contracts | TA-09 | yes |
| 13 | [TA-12](TA-12-process-runner-stdin.md) | infrastructure | TA-11 | yes |
| 14 | [TA-13](TA-13-codex-cli-preflight.md) | translation infrastructure | TA-12 | yes |
| 15 | [TA-14](TA-14-codex-cli-provider.md) | translation infrastructure | TA-13 | yes |
| 16 | [TA-15](TA-15-provider-configuration-composition.md) | translation configuration/composition/docs | TA-14 | yes |
| 17 | [TA-16](TA-16-codex-cli-live-integration.md) | translation live tests/final status | TA-15 | yes, then live |

## Technical-lead acceptance

For every task, review that every changed line traces to its scope, inspect the
diff for unrelated refactors, and rerun the task's commands. After TA-09 and
again after TA-15, rerun the entire offline suite. After each live-gated task,
record whether it ran,
which prerequisites were present, and the canonical checksum/cache-reuse
evidence. ADR-0002, ADR-0004, and ADR-0005 are implemented only after every
non-superseded listed task, including TA-03A and TA-11 through TA-16, is
accepted. A missing ChatGPT login, unsupported Codex CLI, or missing explicit
permission to clear a live workspace is a blocker, not permission to weaken the
gate or fall back to the OpenAI API.


# ADR-0003 implementation task map（2026-10-21）

本节为独立SP任务线，不重开已验收TA任务。用户确认仅实施ADR-0003，“两份ADR”是笔误。
负责人只拆解、分派、审查和运行验收，不直接编码。保留开工前已有ADR-0003和srt_processing指南改动。
状态核对：2026-10-21 10:11 CST；SP-01..08（含SP-08A）均已由负责人accepted；真实技术
集成、负责人/agent内容审读与最终文档验收已完成，保留下述质量边界。

箭头表示前序由负责人验收后才能开始后序；共享工作目录按任务文件所有权避免冲突。

```text
SP-01 ─┬─> SP-02 ─> SP-03 ──────────┐
       └─> SP-04 ─> SP-05 ──────────┼─> SP-06 ─> SP-07 ─> SP-08A ─> SP-08
            └───────────────────────┘
```

| 任务 | 依赖 | 模块 | 状态 |
|---|---|---|---|
| [SP-01](SP-01-public-subtitle-contracts.md) 公共字幕工件与严格DTO | 无 | archive_core | accepted |
| [SP-02](SP-02-profile-text-timing-rules.md) 固定profile、文本计数与纯时间规则 | SP-01 | srt_processing/domain | accepted |
| [SP-03](SP-03-deterministic-bilingual-planner.md) 双语候选、动态规划与全文QA | SP-01、SP-02 | srt_processing/domain | accepted |
| [SP-04](SP-04-input-gates-and-media-probe.md) 双链输入门禁、端口与ffprobe | SP-01 | srt_processing/application + infrastructure/probe | accepted |
| [SP-05](SP-05-srt-codec-and-local-store.md) pysubs2投影、回读及本地工件适配器 | SP-01、SP-04 | srt_processing/infrastructure | accepted |
| [SP-06](SP-06-workflow-reuse-publication.md) 工作流、显式复用覆盖与薄接口 | SP-03、SP-04、SP-05 | srt_processing/application + interfaces + composition | accepted |
| [SP-07](SP-07-integration-and-adversarial-acceptance.md) 跨层回归与可复现本地样本入口 | SP-06 | srt_processing tests + acceptance runner | accepted |
| [SP-08A](SP-08A-prepare-persistent-cnbc-translation.md) 用户授权补齐并保留正式译文 | SP-07 + 现有CNBC transcription成功工件 | 运行既有translation，无生产代码改动 | accepted |
| [SP-08](SP-08-real-sample-and-final-status.md) CNBC正式样本与最终状态 | SP-07、SP-08A | 验收与状态文档 | accepted |

## 共同门槛与记录

- 实际基线：2026-10-21，`.venv/bin/python -m pytest tests/ -q -m "not live"`：599 passed / 5 deselected，1.20s。
- 每项任务先读模块指南；开发agent跑各自测试并交证据，负责人复验后才accepted。SP-01/06/07/08要求完整离线套件。
- SRT实现/默认测试不新增网络、LLM或ASR调用，不实现rendering/CLI；rendering仅明确公共plan
  消费边界。SP-08A是用户明确授权的既有translation样本准备例外，不将provider加入SRT。
- 需要改变已确认ADR行为时先报负责人/用户，不自行降级或放宽门禁。
- 历史09:05：SP-08缺少匹配CNBC alignment的正式译文/manifest，用户要求记录并继续逻辑编码；不阻塞SP-01..07。
  真实样本未跑不得宣称最终完成；重跑transcription集成测试不会生成独立translation阶段的译文。
- 09:05时已完成离线实现与跨层/对抗验收，负责人完整离线复验 **1220 passed / 5 deselected**。
  当时实际运行 `PYTHONPATH=src .venv/bin/python -m tests.srt_processing.sample_runner --run`
  返回 `precondition_missing` / exit 2；准确缺少
  `output/transcription-integration/cnbc_2000_morning/translation_result.json` 和
  `output/transcription-integration/cnbc_2000_morning/translation_manifest.json`。
- 09:05当时待用户提供匹配正式工件目录或明确授权既有translation流程补齐，尚未重跑ASR/翻译或删除
  资产。真实字幕生成、第二次正式复用及内容抽检当时未执行，ADR-0003最终样本验收未完成；
  rendering仍是脚手架，离线临时合成样本不替代真实验收。

## 2026-10-21 用户授权补齐样本输入

用户选择方案2，新增 [SP-08A](SP-08A-prepare-persistent-cnbc-translation.md)：使用现有Codex CLI translation模块生成并持久保留CNBC正式译文，不重跑transcription。依赖为SP-07 → SP-08A → SP-08；SP-08恢复待验收，历史blocked记录保留。此为样本准备的明确授权例外，不把provider调用加入srt_processing，也不改变ADR-0003的规划/输入契约。未来字幕样本测试直接校验并复用正式工件；仍需运行规定的完整离线pytest门槛，而非上游live测试。

### 当前技术验证结果（2026-10-21 10:11 CST）

- SP-08A已accepted：97句/2 sections、2次既有Codex CLI translation生成调用；正式译文/
  manifest持久保存，第二次provider/process/exec均0，17份原文件未变，无生产代码或配置变更。
- SP-08首次真实`succeeded → reused`生成242 cues，99.7455s / 0.7465s；独立新进程再次
  `reused → reused`，0.7470s / 0.7328s。19份上游未变，六输出bytes/mtime一致且复用0写入。
  技术集成与负责人/agent内容审读已完成，完整离线复验仍为 **1220 passed / 5 deselected**。
- 这不是人类签字、语义对齐、出版级或像素/ASS/烧录质量通过。c3/c4人物地名错位、c183
  “风/险”语义提前、c142–147“认/为”/破折号与专名拆分等限制详见
  [SP-08](SP-08-real-sample-and-final-status.md)；不得宣称全片字幕质量过关，rendering仍为脚手架。
- 未来保留规范工件即可独立运行字幕样本入口验证/复用，不需要ASR、translation或其他模块
  live测试；完整离线pytest门槛仍保留。SP-08已由负责人完成最终文档验收并标accepted。


## 2026-10-22 中文切分质量复审

用户认为整篇cue切分质量差，新增[SP-09](SP-09-agent-reference-evaluation.md)：独立子agent仅按上游工件直接创作全量参考cue，再全量对照当前算法，分离算法、容量/显示预算和固定译文/共享时间轴契约的影响。历史SP-08仍只证明技术门禁，不把它视为中文可读性认可。此次是隔离实验，不修改生产代码/正式资产、不重跑ASR或翻译；修复方案待实验结论后确认。

SP-09已由负责人完成实验验收（2026-10-22）：97句153-cue参考与242-cue基线全量对照，98个参考cue超原容量，参考并非可发布golden；另验s6/s60/s90原预算手工见证，证明部分词/专名/标点裂开并非容量必然。完整离线1220 passed / 5 deselected，33正式文件未变。结论为**技术闭环已有，但cue可读性与局部语义质量需返工**；实验accepted不等于生产质量accepted。详见[评估报告](../reviews/2026-10-22-cue-agent-vs-dp.md)，本轮未实施修复。

## 2026-10-22 用户授权候选v2修复

用户明确要求英文最多2行、中文仍1行、中文内英文单词计1，并修边界后逐句与agent参考对比，最终取舍待其审阅。任务依赖：[SP-10](SP-10-candidate-v2-rules.md)（计数/边界/DP）与[SP-11](SP-11-candidate-v2-projection.md)（公共profile/投影）先冻结接口并行开发，再由[SP-12](SP-12-candidate-v2-comparison.md)跑隔离集成、完整97句三方对照与负责人验收。旧正式输出/参考稿不覆盖，不重跑上游；该试验授权不把候选字幕质量预先判为最终通过。

SP-10/11/12已完成候选技术与比较交付验收（2026-10-22 23:17 CST）。224 cues真实生成与持久零写复用、完整离线1329 passed / 5 deselected通过；33正式/139历史工件未变。全部97句的[对照报告](../reviews/2026-10-22-cue-candidate-v2.md)披露专名/标点改善、短cue2→9及语义回归，**不建议质量定版**；本版保持冻结，待用户审阅。旧153参考新规则重审为73 cue不兼容，不沿用旧98历史口径。

## 2026-10-23 用户反馈后的候选v3

用户确认中文自然停顿切分优先；S17在逗号切；S34接受逐cue中英语义不严格一致；7秒与9CPS都只告警，不设置新的10秒硬上限。中文16单位改软目标，英文实际2×42和原覆盖/时间/溯源门禁保留。负责人不编码，先审精确算法再分派实施。

```text
SP-12 + 用户反馈 -> SP-13（planner）<-> SP-14（公共契约/跨层QA）
                                      -> SP-15（隔离真实集成/全97句对照）
```

|任务|依赖|状态|
|---|---|---|
|[SP-13](SP-13-candidate-v3-pause-planner.md)|SP-12、用户澄清、SP-14接口冻结|accepted（候选技术）|
|[SP-14](SP-14-candidate-v3-contracts.md)|SP-12、SP-13接口冻结|accepted（候选技术）|
|[SP-15](SP-15-candidate-v3-comparison.md)|SP-13/14技术冻结后生成|accepted（候选技术与比较交付）|

SP-13/14/15均已由负责人完成候选技术/比较交付验收（2026-10-23 09:16 CST）：完整离线
1395 passed / 5 deselected，163 cues生成及独立零写复用，97句四方数据/六份审读表复算一致。
33反馈中文23满足/4允许/5部分/1未满足，总体双语节奏18/2/12/1；S17/S22等残余保留，
不建议质量定版。详见[报告](../reviews/2026-10-23-cue-candidate-v3.md)；没有样本后私调规则，
未覆盖旧候选/参考/正式资产，不把accepted写成33偏好全通过或人类出版签字。
