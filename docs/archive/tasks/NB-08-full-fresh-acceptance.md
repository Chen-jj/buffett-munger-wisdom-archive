# NB-08 全新真实集成、复用与样片审核

> 2026-11-17归档说明：固定样本真实技术闭环/样片/复用实验已交付；语义残余、未核听及无人类出版签字不变。 原路径`docs/tasks/NB-08-full-fresh-acceptance.md`；原状态、历史不commit/push约束及验证结果属于当时记录。后续入口：[NB-12](../../tasks/NB-12-chunking-quality-iteration.md) / [ADR-0013](../../decisions/0013-typed-chunking-quality-and-regression.md)。

状态：真实生产技术链路经恢复完成、样片已发布；2026-11-06（Asia/Shanghai）。启动前负责人完整离线 2260 passed / 7 skipped，最终 2361 passed / 7 skipped。
首轮生产 run `20261105T181558-57a5dbc3148e`；逐阶段见 [负责人审核](../../reviews/2026-11-06-new-bilingual-pipeline-self-review.md)。

## 固定样本与执行

- 目标：CNBC 2000 上午场第6/7节，派生 `cnbc:2000:morning-ch6-7`；选定原媒体 35:01–45:24，核对本次新采集章节来源与时间范围。
- 新根 `output/orchestration-integration/NB08-20261106-fresh-v1/`；首次前确认不存在，规范资产目录由 archive_core 构造。完整下载父资产，派生由公开生产命令完成，不复用旧 output，不用测试私有裁切或重签。
- 由负责人执行全新集成：真实采集/yt-dlp、FFmpeg派生、WhisperX、Stanza、配置选定的真实翻译/修订provider、三SRT、libass烧录。缺依赖/调用失败/正确性失败据实保留；优先用经过验证的缓存恢复，禁止用fake冒充或覆盖成功工件。
- 交付生产入口/pytest实跑命令、有效门控、配置及工具/模型身份、每阶段状态和绝对路径/hash。跟踪首次完成→同进程复用→新进程复用，统计各阶段昂贵调用和阶段文件写入，run receipt写另列。verify另证整次只读。

## 负责人审核与独立回归

1. 采集/下载/派生：全新官方来源、资产身份、父视频hash及派生时间映射，原视频与派生音视频流；不得假称旧样片。
2. 转录：检查每句、词覆盖与时间、逐标记官网token证据、修正/口语词；区分机械一致和听音核实。
3. 候选块：读每个断点，核专名、否定、从句，原词时间不动，预算与未解告警。
4. 初译：逐chunk对照原句、标题、术语、逐屏归属；修订：逐窗追踪数字、否定、条件/限定、分组、尝试计数及残余。
5. 最终稿/SRT/ASS：逐cue正文时间来源、末尾/两帧/警告、ASS量化/字体/像素与音视频安全。完整列出告警工件及数量，不隐去语义问题。
6. 视频：实际尝试播放并核听；记录覆盖时段、切屏、讲话意义、遮挡、闪烁和旧故障位置。不能听则 `audio_sync=pending`，不能以帧图/文本替代。
7. 自审完成后交非作者独立 agent 只读回归，提交各自报告，明确分歧和未验证范围。无语义自动门禁；未经人类签字不称出版质量通过。

- 最终生产 run `20261106T111813-59ffececf426`，前八阶段全复用、渲染一次编码；失败报告/暂存原样保留。
- 正式样片：`/Users/drchan/Codebase/buffett-munger-wisdom-archive/output/orchestration-integration/NB08-20261106-fresh-v1/cnbc_2000_morning-ch6-7/video_中文字幕.mp4`；623秒、275 cues；SHA-256 `ac007b4f9b90b77855feb7c815d9b4923a8b6d85654174e50d1668f657ec88a8`。
- 同进程 `20261106T112032-253beb5efa11`、新进程 `20261106T112050-427c550a13f9` 全复用，阶段零改写/零昂贵调用，78项保护集不变，verify零写。
- [负责人自审](../../reviews/2026-11-06-new-bilingual-pipeline-self-review.md) 包含逐阶段证据与本人实际播放覆盖；[独立报告](../../reviews/2026-11-06-new-bilingual-pipeline-independent-review.md) 单列非作者复审。未核听、未作人类发布签字，语义残余及302条权威稿告警、122条ASS投影间隔告警不隐去。

## 实跑命令与结果

从仓库根执行（真工具已在本机准备）：

```sh
.venv/bin/python -m pytest tests/ -q
PATH="$PWD/.venv/bin:/opt/homebrew/opt/ffmpeg-full/bin:$PATH" \
  RUN_ORCHESTRATION_INTEGRATION=1 ORCHESTRATION_INTEGRATION_SCENARIOS=full_fresh \
  .venv/bin/python -m pytest tests/orchestration/integration/live/test_full_fresh_pipeline.py -q -s
```

默认离线最终 2361 passed / 7 skipped（10.79s）；真实 pytest 首轮 `provider_failed`，后续使用同一新根的生产恢复入口。最后只渲染的回归以 `tests.orchestration.integration.runners.full_fresh.command` 组装命令，
把 `resume_run_id` 绑定上次保留的失败 run，限定 `allowed_actions=('subtitle_rendering',)` 和 `max_stage_executions=1`，用 `build_pipeline_handler().resume_asset(..., expected_plan_sha256=plan.sha256)` 执行；再由 `verify_generated_sample` 运行同进程、独立新进程及只读校验。该次命令退出0，详情见实际 `integration_evidence.json`。不要对已有工作区使用 full-fresh 重建。
