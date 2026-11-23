# NB-05 权威最终稿导出与渲染接入

> 2026-11-17归档说明：权威稿导出/渲染接入技术交付及后续NB-08真实恢复已留证；渲染整体质量仍未通过。 原路径`docs/tasks/NB-05-final-export-rendering.md`；原状态、历史不commit/push约束及验证结果属于当时记录。后续入口：[NB-12](NB-12-chunking-quality-iteration.md) / [ADR-0013](../decisions/0013-typed-chunking-quality-and-regression.md)。

状态：待开发；2026-11-05。依赖 NB-04，公共字段见 NB-01。

- srt_processing 旧中文优先比例planner生产入口直接替换为最终稿校验/投影；不调用LLM、不拆并、不移时、不从初译中文字符范围推断最终中文。
- SRT与rendering共同消费FinalBilingualDraftDTO，绑定source_chunks/初译/后处理manifest/媒体完整证据链。
- 三SRT共用编号和最终毫秒，中文上英文下；无样式、无辅助标记泄漏；回读逐cue比较。逻辑正文无显示换行；渲染不从SRT反推内容。
- 所有长度/CPS/显示时长warning可继续发布；实际重叠/越界/词覆盖/来源链硬失败。不得因换到渲染又套旧2x42硬预算或旧中文16硬预算。
- rendering保留精确字体/glyph、布局、实际libass逐cue像素、媒体安全、流映射/音频copy、manifest-last与零写复用。
- ASS按既定最近百分秒half-up投影，原稿毫秒不改；投影正时长/不越界/无实际重叠仍硬门禁。用实际PTS检查投影后两帧，不足/未知warning，不二次移时。
- 旧DTO/profile/codec多版本解析/旧planner不作为运行路径留下；有效布局/覆盖/故障/复用断言保留并适配新输入，旧算法偏好golden替换须inventory理由。

验收：新稿→三SRT/ASS严格一致，wordID/中文/时间无损；warnings/量化/重叠边界，损坏/混合代次，真实字体/像素/媒体适配器既有门禁不削弱。针对性测试后完整离线，真实生成由NB-08统一驱动。

2026-11-05 用户另行确认删除四个旧生产孤儿实现：domain/planner.py、domain/boundaries.py、domain/rules.py、infrastructure/segmentation.py（均位于src/srt_processing）。已按该确切清单移除；没有扩展到其他生产文件或新媒体资产。

2026-11-06：生产单套切换及定向验证完成。SRT 输出为三份逻辑行投影、严格报告和 manifest；
rendering 用同一稿件布局与烧录，ASS 投影复验实际帧数并分别报告短 gap/未知。原旧公共
`SubtitlePlanDTO`、比例字符范围、v1/v2/v3 profile/codec 多版读取已直接移除。
单元和真实轻量 FS/codec 集成定向：1540 passed / 1 skipped（关闭的显式 local_media）。
旧 SR-06 对抗/故障断言迁往 orchestration/integration/offline/rendering；
新版真实样片及复用回归仅由 NB-08 的实际记录证明。未提交/推送，未删除新媒体/模型资产。

2026-11-06 追加授权：移除独立旧平均帧率探测器
`src/srt_processing/infrastructure/probe.py`，不再作为 SRT 能力。仅删除该获批生产文件；
SRT 消费媒体阶段的 decoded PTS。实际 PTS 解析器和已产出工件均未改，旧测试文件改写保留。

2026-11-06 真实恢复阻塞修复：NB-08 的 forced alignment 有 1571 个声学词；
融合多对一后，权威 canonical 词为 1569 个。旧渲染输入门禁误把后者当作转录报告的
`aligned` 计数。现使用已验指纹的融合前工件分别复算 `aligned` 和 `interpolated`，
比例分母为该工件总词数；保留 canonical 非空和最终稿完整覆盖及所有来源门禁。
旧代码的两项合法多对一红测复现拒绝；修正后五项新回归全通过，另覆盖重签错计数、
超比例拒绝和 1/4 插值阈值边界。
渲染定向 1151 passed；完整离线 2339 passed / 7 skipped（9.75s）。
未写真实工作区或执行烧录；实际恢复由负责人验收。

2026-11-06 真实恢复补记：
- 用户确认的 cue 起首省略号例外已实施，布局身份 `pixel-wrap.v2`；只保留权威中文稿首码点
  U+2026，不放宽视觉换行产生的行首、省略号 ASCII 形式、其他标点、字号、字体、安全框或时轴。
  布局与公共计划复验共用例外规则。先复现 5 红；新增与窄范围回归 15 项通过。
- 实际渲染越过布局、像素预检和编码后，ASS 短 gap 告警定位曾错用投影的两个 gap 边界。
  现仍用投影区间实际 PTS 判告警，报告定位绑定左 cue 原始毫秒；投影区间与计数/未知
  保留在诊断。两个红测复现报告拒绝，修正后都通过。未由开发 agent 写入或烧录真实资产。
- 两项修正合并后默认完整离线：2361 passed / 7 skipped（10.88s）；`git diff --check` 通过。
  实际恢复/成片仍以 NB-08 负责人验收为准。
