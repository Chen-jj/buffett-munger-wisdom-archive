# SP-06 — 工作流、显式复用覆盖与薄接口

- **Status:** accepted
- **Owner:** inputs 子开发 agent；仅技术负责人标记accepted
- **Module:** srt_processing/application + interfaces + composition
- **Decision coverage:** ADR-0003 §4–5、§10–13、§14.5
- **Depends on:** SP-03、SP-04、SP-05
- **Depended on by:** SP-07

## 范围与验收标准

- 串联独立输入门禁/probe/planner/全文QA/投影回读/report/manifest；公开command/outcome/handler及生产composition，不实现CLI/rendering。输出仅canonical六份，succeeded/reused/failed及安全错误/路径/cue与warning计数。

- 全套不存在才生成；完整manifest全部输出size/hash/可解析性及输入/规则/probe/codec身份一致才复用，不重写正式文件。部分/损坏/过期=artifact_conflict；overwrite=true才重生本阶段，绝不修改上游。

- 临时五份输出全部QA后逐文件替换，成功manifest最后；失败report尽力写且不掩盖原始错误，无checkpoint/资产锁。混合代次不能凭旧成功manifest通过。

- 用内存fake store/probe/codec/clock测试完整生成/复用/所有身份变化冲突/显式覆盖/每个发布点与失败report故障/上游bytes不变。协调统一exports，更新模块指南离线状态但保留真实样本待验收。

## 验证与交接

```bash
.venv/bin/python -m pytest tests/srt_processing/ -q -m "not live"
.venv/bin/python -m pytest tests/ -q -m "not live"
git diff --check
```

记录实际命令/结果、API与未解决问题，再交负责人复验。先读根与模块AGENTS，保留用户已有ADR/指南修改；不得删除文件/资产，不作无关重构。

## 开发交接（2026-10-21）

### 实现范围与精确 API

- 新增 `application/workflow.py`、`interfaces/workflow.py`、`infrastructure/composition.py`
  与模块/四层统一 exports；保留 SP-01–05 已验收的 DTO、planner、ports、inputs、probe、codec、
  local API 不变。未改上游模块、根状态或 ADR，未作 Git 提交。
- `SrtProcessingWorkflow(*, artifacts, probe, codec, clock, output_root="output",
  planner=plan_subtitles).execute(*, asset_id, transcription_manifest_path,
  translation_manifest_path, overwrite=False) -> SrtProcessingRunResult`。
- `SrtProcessingRunResult` 字段为 `status, plan_path, manifest_path, report_path,
  english_srt_path, chinese_srt_path, bilingual_srt_path, cue_count, warning_count`。
- `SrtProcessingCommand(asset_id, transcription_manifest_path, translation_manifest_path,
  overwrite=False)`；`SrtProcessingCommandHandler(workflow).handle(command)` 返回
  `SrtProcessingOutcome`，包含同名结果字段，以及 `error_category/error_message`。
  失败字段不作为权威输出，路径为 null；文案固定，不泄漏内部异常或本地路径。
- `build_srt_processing_handler(*, output_root="output", ffprobe_executable="ffprobe",
  artifacts=None, probe=None, codec=None, clock=None)` 返回 handler；默认明确组装本地四个
  adapter，可注入观测/fake，无自动 fallback，构造过程不运行工具。
- application 错误类别为 `artifact_conflict/planning_failed/projection_failed/
  publication_failed/srt_processing_failed`；既有输入门禁保留 `input_invalid/media_invalid`。

### 发布、复用及失败策略

成功生成先分别验证两条输入链、同源视频与 probe，再调用 planner，并独立重新分析 plan。
三份固定投影与成功 report 全部生成、暂存、回读和 QA 后才逐个发布；成功 manifest 最后单独
暂存、回读、发布。JSON 使用 application 标准库确定性序列化，不反向 import infrastructure。

复用严格绑定五个输入证据、完整 profile/规则、media、probe 与 codec 身份，验证五个输出
实际 bytes 的 size/SHA-256，重新解析公共 plan、执行 domain 硬 QA、逐条比较三份投影并检查
固定序列化、重算成功 report 与 manifest summary。复用零 planner/clock 调用、零正式写入。

默认部分/损坏/过期输出是只读 conflict；已有本阶段输出时，其他默认失败也不会擅自写入
failed report。只有正式六份全不存在，或显式 overwrite，才尽力写 failed report；其二次错误
不掩盖原错。失败不删除暂存文件、回滚正文或改写旧 manifest；下次完整证据校验拒绝混合代次。

### 实际验证

- `.venv/bin/python -m pytest tests/srt_processing/test_workflow.py tests/srt_processing/test_interfaces.py tests/srt_processing/test_composition.py -q -m "not live"`
  → **128 passed**。
- `.venv/bin/python -m pytest tests/srt_processing/ -q -m "not live"` → **473 passed**。
- `.venv/bin/python -m pytest tests/ -q -m "not live"` → **1168 passed, 5 deselected**。
- `git diff --check` → 通过。
- 测试覆盖全部六个 stage/read/publish 故障点（包含 manifest 自身），暂存篡改、五输入/五
  输出证据与版本身份变化、重签名但语义篡改的 plan/SRT/report、完整复用不重写、显式覆盖、
  原上游 bytes 不变、混合代次拒绝，以及失败 report 暂存/发布二次失败不掩盖原错。
- workflow 测试全部使用内存 store、fake codec/probe、固定 clock；未运行媒体工具、网络、
  ASR 或翻译。独立生产 adapter 测试仍由 SP-05 负责。

已同步 `srt_processing/AGENTS.md` 的离线实现状态；真实 CNBC 样本与跨模块/对抗验收尚待
SP-07/08，不宣称 ADR-0003 整体已落地。当前无未解决编码阻断，等待负责人独立验收。

## 技术负责人验收（2026-10-21）

负责人已完整审查workflow、handler、composition与exports，并复验srt模块 **473 passed**、完整离线 **1168 passed / 5 deselected**；diff check通过。另有planner独立只读review及128项定向复验无阻断。双链输入、完整复用身份、暂存QA、全部发布故障和失败report保护符合ADR，SP-06 accepted，放行SP-07。
