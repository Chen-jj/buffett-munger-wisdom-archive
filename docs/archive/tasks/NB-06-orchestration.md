# NB-06 生产公共入口、媒体派生与同步编排

> 2026-11-17归档说明：生产编排/公共入口技术交付及NB-08真实恢复/复用已留证；不把未核听或语义问题改为通过。 原路径`docs/tasks/NB-06-orchestration.md`；原状态、历史不commit/push约束及验证结果属于当时记录。后续入口：[NB-12](../../tasks/NB-12-chunking-quality-iteration.md) / [ADR-0013](../../decisions/0013-typed-chunking-quality-and-regression.md)。

状态：生产开发与默认离线验证已交付（2026-11-06 Asia/Shanghai）；负责人真实运行及音画/语义审核另记 NB-08。

## 范围

1. acquisition/interfaces 公共 command/factory，receipt 绑定规范 meta/media_ref/chapters/transcript 的路径/大小/hash、请求身份与来源；复用验证完整receipt，不因meta存在跳过。
2. media_download/interfaces 公共 factory，保留现有下载验证。真实 CNBC 章节样本需正式媒体派生命令：显式父源、选择范围、派生资产ID、父源hash/时间映射与派生manifest，章节正文范围与派生媒体一致。不能把旧 live_fixture 代码改目录后称生产链；下载/派生属于明确生产用例。
3. orchestration 只 import 各功能模块 interfaces 的明确factory/command（生产例外仅infrastructure/composition）；domain/application不import业务模块。AST允许清单验证，不import tests。
4. 同步单资产 DAG：acquisition→download/derive→transcription→source_chunks→initial_translation→bilingual_postprocess→srt_export→subtitle_rendering。
5. plan_asset/run_asset/resume_asset/verify_run；命令有目标、allowed_actions、调用预算和resume_run_id。plan/verify不构造模型、不网络、不probe、不写目录/log/receipt；缺授权blocked。
6. 运行期OS advisory排他锁，保留锁文件，竞争asset_busy；重新hash防止TOCTOU。receipt不是阶段完成证明，复用必须逐阶段内容/manifest验证。
7. 阶段失败阻断后继，不额外重试模型，不删除失败/旧资产；不广播overwrite。复用阶段输出0写/0ASR/0provider/0encoder；新run receipt写入独立统计。

## 验证

- fake StagePort 单元：DAG、授权/预算拒绝、目标截断、失败传播、恢复、只读0写0外部调用。
- 离线集成：生产公开factory组装但昂贵边界fake；hash失效范围、损坏/部分/混合代次、串资产/越界、锁冲突、中断；有效缓存不重跑。
- full-fresh：统一显式门控 RUN_ORCHESTRATION_INTEGRATION=1 + 场景allowlist。开启缺依赖非零而非skip。产物持久保留，生产公开入口从空workspace自行准备全链。
- 首轮后同进程、新进程复用：全阶段hash/mtime与调用/写入计数，receipt写另列；verify整次0写。

## 交付证据

完整新工件、样片绝对路径/hash/时长、运行plan/receipt/input bindings、调用/写入计数和工具身份。
负责人逐阶段全文审核后，另交非作者agent回归。语义/视觉/核听/人类release独立状态，不用succeeded替代。

## 生产入口与工程落点

- `orchestration.interfaces.build_pipeline_handler()` 返回同步编排；公开 `plan_asset / run_asset / resume_asset / verify_run`。
- `PipelineCommand` 显式声明源资产、目标资产、来源locator、根目录、目标阶段、授权阶段列表及最大执行阶段数。阶段预算不是模型token账单；provider内容重试由各自阶段约束。若不裁切，`selection=None` 且源/目标资产一致，下载后发布同一媒体边界工件。样本限定360p不是通用派生限制。
- 裁切为公开 `MediaDerivationCommand`，从完整已验证父MP4精确选择时段，并选用同源完整章节。保留父资产；派生视频编码、AAC零基时间轴及容差、父/子hash和源偏移记录在派生manifest。实际解码PTS以微秒保存；不以平均帧率证明两帧。无有效帧证据的直接资产用null，不借相邻间隔。
- 执行用父/子workspace顺序advisory锁，计划无锁零写。前次 run 只提供恢复链；重验所有阶段manifest/内容。恢复拒绝变换source/locator/root/selection，允许调整target/授权。静态verify无生成调用、无探测工具；执行复用允许只读工具身份/媒体探测。
- `pipeline_runs/<run_id>/` 保存plan、开工bindings及run receipt；成功receipt的final_bindings为实际验证后的全链。调用计数取真实process/ASR adapters和各provider/分析workflow观测，artifact_files_changed基于文件大小/mtime，不冒充系统写操作次数；独立验收另对保护集sha/mtime复算。run receipt计数不计入阶段输出写入。
- transcription完整缓存命中后复验原log/report/manifest及原始成功报告，不重新发布。原“第二次生成的日志行数等于内存events数”改成“第二次不写、原日志保持字节一致”，保留内存events独立、各层cache hit和QA断言。

## 验证记录

- 生产facade/派生父链/锁 + fake编排授权、预算、恢复及只读：14 passed。
- 新契约、转录全workflow、上述编排验证定向：74 passed。上游迁移后完整离线快照：2260 passed / 7 skipped（12.17s）。
- NB-08 runner门控：`RUN_ORCHESTRATION_INTEGRATION=1 ORCHESTRATION_INTEGRATION_SCENARIOS=full_fresh`。未开启默认skip；开启缺预条件失败。首次→同进程→独立进程→verify与明确resume使用同一验收路径。

样本来源核对：2026-11-06负责人只读复核官网的嵌入章节时间，第6节[2101,2430)、第7节[2430,2723)秒；
本次生产命令沿历史样本明确选择[2101,2724)秒，包含官网第8节开始后的1秒，不称为官方章节精确并集。
尾1秒是否包含下一章讲话由NB-08实际产物/核听确认；不为掩盖范围问题删除词、改译或覆盖已有资产。
