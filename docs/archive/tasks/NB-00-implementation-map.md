# NB-00 新双语流水线实施与验收地图

> 2026-11-17归档说明：初版实施地图与技术迁移记录已交付；后续真实技术闭环见NB-08/NB-09。旧待验/失败记录保留，不将所有质量项判完成。 原路径`docs/tasks/NB-00-implementation-map.md`；原状态、历史不commit/push约束及验证结果属于当时记录。后续入口：[NB-12](../../tasks/NB-12-chunking-quality-iteration.md) / [ADR-0013](../../decisions/0013-typed-chunking-quality-and-regression.md)。

- 核对：2026-11-05（Asia/Shanghai）；负责人只拆解、调度、验收及回归，编码由子 agent 完成。
- 唯一行为入口：[ADR-0008](../decisions/0008-local-orchestration-and-integration-tests.md)，分段依据 ADR-0009～0012 与 ADR-0006。
- 本次用户已授权实现、真实下载/ASR/翻译/烧录；不 commit/push。不执行 ADR-0007/SA-00，不新增 semantic_alignment。
- 保留开工时已有设计/归档改动，不删除任何文件或新资产；测试迁移需移除旧路径时单独取得确认。

## 开工基线（历史）

旧生产路径仍是 source alignment → sentence translation → 中文优先比例 planner → rendering。
新契约/算法未实现，orchestration 仅指南。acquisition/download 缺公共 facade；transcription 的生产组装在测试 runner。
旧 CNBC 623 秒准备包含测试私有 HLS 下载/裁切，不能冒充生产 E2E；需显式媒体派生用例。
基线命令 `.venv/bin/python -m pytest tests/ -q`：2580 passed / 6 skipped，13.07s。

## 依赖切片

| 切片 | 依赖 | 编码范围 | 验证/验收 |
|---|---|---|---|
| NB-01 | 无 | archive_core 当前单套公共契约、规范文件名/运行路径；transcription 编辑标记和公共 factory | 严格 schema/覆盖/重建/时间/来源；非目标破折号不变；针对性+完整离线 |
| NB-02 | NB-01 工程契约冻结 | srt_processing 源语 chunking、Stanza adapter/model identity、独立发布/复用 | ADR-0010 边界、保护/映射、两轮确定性、预算不移时；真实本地模型准备/验证 |
| NB-03 | NB-01/02 | translation 分批 chunk 初译、上下文/术语/标题、批 checkpoint | 49–51/连带句组/超50、严格响应、超预算不重试、复用 |
| NB-04 | NB-03 | translation 有界修订、实际帧证据、统一最终排时、持久请求额度 | ADR-0012 触发/窗口/权限/硬错与warning、三次上限含恢复、无累加延时 |
| NB-05 | NB-04 | srt_processing 权威稿验证/三 SRT；rendering 新输入链及 ASS 帧间隔 warning | 同一稿件文本时间、无重切改译移时；字体/像素/媒体/发布原门禁保留 |
| NB-06 | NB-01；组装依赖 NB-02～05 | acquisition receipt/facade、download facade/生产媒体派生、orchestration DAG/授权/plan/run/resume/verify/锁 | 只读0写、失效/并发/中断/混合代次/越界/预算；不 import 测试或功能私有实现 |
| NB-07 | 开工盘点；迁移随 NB-01～06 | 每个 collected nodeid inventory；集成唯一归 tests/orchestration/integration | 有效业务断言逐项追踪；模块只留隔离单元/contract；旧入口删除先确认 |
| NB-08 | NB-01～07 离线验收 | 编排生产入口 full-fresh、同进程/新进程复用、负责人自审及独立 agent 回归 | 全新持久工件/MP4；阶段 hash/文本全量审读；实际播放/核听范围；昂贵调用0及bytes/mtime |

每个切片：先冻结工程接口和验收用例 → 子 agent 最小实现 → 负责人读 diff/针对性复跑 → 完整离线 → 更新真实状态。
不为保持旧测试而保留旧生产算法或兼容 loader；替换的旧断言须登记理由。不以测试数量代替断言审计。

## 工程契约冻结要求

NB-01 先发布供其他 agent 使用的字段/入口说明；公共定义只由 NB-01 作者改动，避免并行冲突。
工件至少分开：canonical alignment/annotations、source chunks/预算、chunk 初译、最终双语稿、SRT 导出、rendering、pipeline receipts。
各阶段绑定真实输入 hash、当前政策/模型/prompt/provider 身份，manifest-last；旧形状明确拒绝。
英文正文/锚点始终由程序从源词重建；唯一最终稿不再约束为旧句译文字符切片。

## 验收记录（技术闭环）

- 基线：2580 passed / 6 skipped（13.07s）；Python 3.11.16；FFmpeg-full 9.0.1含ass/subtitles；Codex CLI 0.154.0。
- 文件移除授权：用户已同意NB-07列出的29个测试/helper路径迁移移除；另已同意移除列出的4个旧生产实现文件及后来单独确认的旧平均帧率适配器，未延伸至资产。
- full-fresh：2026-11-06首轮从空根真实开始，遇 provider 及渲染问题并保留失败记录；经恢复最终发布623秒/275 cue样片。最终只执行渲染，前八阶段全复用，后续同进程/独立新进程均九阶段全复用。
- 本人已审核采集、父/派生媒体、97句转录与23标记、275块候选；见 [负责人审核](../../reviews/2026-11-06-new-bilingual-pipeline-self-review.md)。初译/最终稿/三SRT亦已审；正式MP4已播放抽查，独立报告见 NB-08；audio_sync未验证，语义残余和human_release不标通过。

### 负责人切片复验

- NB-01：独立复跑 core/transcription 700 passed / 1 skipped（0.57s），已读新版DTO、计数/帧规则、编辑标记及接入diff；定向技术检查通过，旧契约退场仍依赖下游切换。
- NB-02：独立复跑23 passed（0.55s），已读纯规则及真实Stanza三例validation.json；模型真实推理已发生，非真实媒体字幕验收。
- NB-03：独立复跑21 passed（0.45s），已读组批/上下文/响应/工作流；旧测试仍待替换。
- 并行开发中完整离线：295 failed / 2409 passed / 6 skipped（15.81s），203个旧SRT输入链、92个旧句级翻译测试失败。日志 `/tmp/nb-after01-pytest.log`。这是尚未迁移完的真实中间结果，不能宣称整链完成或全绿。

- NB-04：独立复跑NB-03/04合计54 passed（0.56s）；已读机械试算/合并/窗口/接受规则及恢复ledger，要求补核窗外既有告警、恢复权限及请求范围。
- 2026-11-06 恢复时整套收集16处错误（15处旧SRT/渲染测试引用已删除接口，1处迁移同名入口冲突）；各编码 agent 继续迁移适配。新样片尚未生成，执行检查见 [NB-08](NB-08-full-fresh-acceptance.md)。

- 2026-11-06 本人完整离线复验：2344 passed / 7 skipped（9.65s），git diff --check通过。迁移盘点2586旧nodeid，2541映射，45明示退役；未等价的旧CLI断言见NB-07。
