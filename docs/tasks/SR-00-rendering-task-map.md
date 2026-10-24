# ADR-0006 rendering 任务图与负责人验收

- **Status:** in_progress
- **Owner:** 技术负责人（只写任务/验收文档、调度和运行验收，不编写实现或测试代码）
- **决策来源:** `docs/decisions/0006-subtitle-rendering-ass-and-burn-in.md`
- **开工基线:** 2026-10-23，`.venv/bin/python -m pytest tests/ -q`：1404 passed / 5 skipped，5.74s。
- 用户已确认“两份ADR”为口误，本次只落实ADR-0006。已读0003作为现有输入契约，不重开已完成SP线。
- 当前：SR-01..06已验收并归档；SR-07技术样片已交付，但用户人类播放发现语义同步问题，最终未通过。

## 顺序与所有权

箭头表示负责人技术验收前置后，才允许开始后置实现。共享目录不用并行提交；每个agent只编辑自己获派文件。

```text
SR-01 公共契约 -> SR-02 profile/纯布局 ─┬─> SR-03 字体/ASS ─┐
                                     └─> SR-04 媒体适配器 ┼─> SR-05 workflow
                                                        └───────> SR-06 离线验收 -> SR-07 真实样片
```

|任务|依赖|主要所有权|状态|
|---|---|---|---|
|[SR-01](../archive/tasks/SR-01-public-rendering-contracts.md)|无|archive_core工件、公共DTO与测试|accepted|
|[SR-02](../archive/tasks/SR-02-profile-and-layout.md)|SR-01|rendering/domain、profile配置及测试|accepted|
|[SR-03](../archive/tasks/SR-03-fonts-and-ass.md)|SR-01/02|fonts/ass adapter、相关测试|accepted|
|[SR-04](../archive/tasks/SR-04-media-adapters.md)|SR-01/02|probe/ffmpeg adapter、必要共享process扩展、相关测试|accepted|
|[SR-05](../archive/tasks/SR-05-workflow-and-publication.md)|SR-01/02/03/04|ports/inputs/workflow/local/composition/interfaces、测试|accepted|
|[SR-06](../archive/tasks/SR-06-offline-acceptance.md)|SR-05|独立跨层/对抗/故障注入测试|accepted|
|[SR-07](SR-07-real-sample-acceptance.md)|SR-06|本地runner、显式集成测试、真实样片/验收报告|in_progress|

## 共同约束

- 先读根及对应模块AGENTS；遵守ADR，不跨功能模块import私有实现。不做orchestration/CLI/Web UI。
- 保留开工已有AGENTS、rendering指南、未跟踪ADR-0006；不reset、不删除文件、不提交生成媒体。
- 不自动重跑下载、ASR、translation/provider或SRT planner；不修改上游或历史v1/v2/参考资产。
- 精确字体/hash/face，无fallback、静默缩字/改正文/改cue时间；默认测试用fake，不依赖外部工具/系统字体。
- 正式输出五份、严格零写dry-run、证据驱动零写reuse、显式overwrite、manifest-last。
- 任何必须变更ADR的矛盾先上报，不以测试通过为由降低门禁。开发agent不自行标accepted。
- agent交付：文件清单、设计/接口、定向测试命令/结果、剩余风险。负责人看diff并独立复跑才accepted。
- agent不提交git；根/模块状态由负责人串行协调更新；未通过真实门槛不得写“模块已实现”。

## 最终验收

1. 所有任务逐项复验，完整`.venv/bin/python -m pytest tests/ -q`全绿，diff check通过。
2. 同源CNBC：2 sections / 97 sentences / 163 cues / 完整623秒；真实production handler、实际字体/libass/软件编码/ffprobe。
3. 持久五份规范输出，首次succeeded、同进程及独立进程reused；正式输出bytes/mtime一致、reuse零写/零编码、上游及链接目标不变。
4. 报告给绝对样片路径、大小/hash/时长/输入来源与指纹、逐cue像素/媒体QA和已知字幕残余。
5. agent视觉/音画检查与人类播放签字明确区分；没有人类播放证据就不宣称该门槛已过，更不得称出版级通过。

## 负责人验收记录

- 用户已批准ASS百分秒显式投影并更新ADR第12.1节：权威毫秒不改，最近10ms half-up、差值≤5ms，投影不合法受控失败。
- SR-01已分派render_contracts；SR-03/04由render_font_ass/render_media提前只读调查，未提前实现。
- 用户已批准预检前暂存ASS和版本化U+2060可逆显示控制；ADR已同步，dry-run零写与manifest-last不变。
- SR-01负责人已审公共契约/证据/原毫秒守恒/ASS投影/深层重签反例；独立定向188 passed，完整1592 passed / 5 skipped，diff check通过。放行SR-02，尚未实现rendering生产workflow或样片。
- SR-02经Unicode分类identity预审修复后独立181 passed、完整1773 passed / 5 skipped，已accepted。放行SR-03/04并行，SR-05只能提前只读设计，不实现。
- 用户批准成功report在编码后媒体QA通过才构造/暂存；ADR第18节已修正，正式发布/manifest-last顺序不变。
- SR-04负责人独立复验新增测试133 passed、完整合并树2019 passed / 5 skipped，已accepted；SR-03待验收，SR-05仅设计已审。
- SR-03负责人已查看实际literal显示对抗图，审字体/ASS/像素实现，独立116 passed、完整2022 passed / 5 skipped（6.23s），accepted。放行SR-05，之后仍需SR-06/07完整门槛。
- 2026-10-24 10:10 CST用户要求继续：上一批agent因使用额度中断，SR-05仍只有设计、没有生产代码；负责人恢复基线2022 passed / 5 skipped（6.36s）。重新分派workflow_dev实施SR-05，offline_qa与sample_dev分别只读准备SR-06/07，后置编码仍等待前置accepted。
- 10:36 CST：SR-05经负责人代码审查、独立只读预审与定向268/完整2290 passed / 5 skipped验收accepted；放行offline_qa实施SR-06独立跨层/对抗测试，SR-07仍只读设计。
- 10:51 CST：SR-06负责人独立269 passed、完整2559 passed / 5 skipped（12.10s），审独立LocalStore/真实ASS/重签前置自验/故障commit-point与offline guard，accepted；放行SR-07编码与首次真实样片。
- SR-07技术交付：同源623秒/163cue全片、163实际像素预检、两次0写复用、上游保护集不变，
  负责人独立完整2580 passed / 6 skipped、真实集成1 passed。用户实际播放发现双语语义同步
  问题，最终验收未通过，不能关闭本任务图或归档ADR-0006。见[复审报告](../reviews/2026-10-24-rendering-technical-and-semantic-review.md)。
- 2026-10-24文档整理：已实现ADR-0002..0005及TA/SP/SR-01..06归档；当前问题交给
  [新agent探索prompt](../prompts/bilingual-semantic-alignment-exploration.md)，没有直接实施新算法。
