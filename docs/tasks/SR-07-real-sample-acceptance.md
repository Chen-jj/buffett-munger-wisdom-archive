# SR-07 — 同源 CNBC 真实烧录与持久样片

- **Status:** in_progress；技术样片交付通过，用户人类播放发现语义同步问题，最终验收未通过
- **Owner:** 集成开发agent；最终验收为技术负责人；人工播放由人类确认
- **Depends on:** SR-06 accepted

## 实施

按ADR-0006第20.2节实现tests/subtitle_rendering/sample_runner.py与本地集成测试、离线runner测试。runner显式--run，pytest用RUN_SUBTITLE_RENDERING_INTEGRATION=1；默认只读现有上游，不跑其他阶段。前置缺失返回非零precondition_missing/清单，显式测试失败不skip。生产composition/handler，真实字体/libass/ffmpeg/ffprobe，不能fake或合成媒体替代真实验收。

固定output/cue-evaluation/20261023-candidate-v3/workspaces/cnbc_2000_morning，同源transcription持久产物+SP-08A译文+v3 SRT；交叉hash、2 sections/97 sentences/163 cues；不可改写或重定位输入来过门禁。

## 真实验收顺序

1. 对所有原始上游、v3输入、链接目标及历史资产bytes/mtime快照，确认五份本阶段输出不存在；验证实际工具/font。
2. 负责人授权本任务后首次真实succeeded、完整623秒/163cue/音频持久MP4及四份sidecar，禁止-ss/-t短片。
3. 给绝对样片路径/size/SHA256/时长/cue数/manifest/report/输入来源证据；全部逐cue像素QA和成片probe通过。
4. 同进程reused、独立进程reused，五输出bytes/mtime不变、reuse写入和编码0；全部上游/历史不变。失败残留不删除、不擅自overwrite。
5. agent检查最长中英文/四行/专名/数字/首尾/复杂底部/S17/S22/S48/S74/S88，记录可验证画面和音画问题，不冒充人类观看。人类播放尚未确认则明确未通过该项。
6. 负责人独立复验完整离线pytest、证据/复用/媒体；根/模块指南与ADR实现状态如实更新。不把上游语义缺陷或技术通过写成出版质量通过。

## 验收记录

### 技术交付与负责人复验（2026-10-24）

runner、显式本地集成及离线runner回归已实现；负责人独立runner 21 passed、完整2580 passed /
6 skipped、真实env-gated集成1 passed。已生成完整623秒/163-cue规范样片和四份sidecar，
真实`succeeded → reused → reused`，两次复用0写/0像素采样/0内容编码，上游/历史/链接目标不变。
绝对路径、hash、媒体与保护集证据见[本轮复审报告](../reviews/2026-10-24-rendering-technical-and-semantic-review.md)。

### 人类播放未通过

用户实际播放反馈00:23/00:30/00:36/01:26附近的中文/讲话不同步，后续定位为英文词时间准确，
中文优先分块与比例映射无法保证语义对应。当前不再是“未播放待确认”，而是**已播放、最终未通过**。
尚无修复实现或修正版样片。新的完整方案在[探索prompt](../prompts/bilingual-semantic-alignment-exploration.md)
中交接，不能由rendering私改源cue消除。保留本任务和ADR-0006进行中，不归档为完成。
