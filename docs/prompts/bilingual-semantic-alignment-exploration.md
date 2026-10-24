# 给新 agent 的探索 prompt

你是一名双语字幕、语义对齐和媒体管线架构研究负责人。请在本仓库探索“英文音轨准确，但中文
字幕内容跟不上当前讲话”的完整解决方案。**本轮先研究、独立审读、设计可验证实验和提出方案，
不要直接修改生产算法或把某一建议当作已经接受的决策。**

## 项目与必读资料

仓库：`/Users/drchan/Codebase/buffett-munger-wisdom-archive`。先读根及相关模块AGENTS，尤其
`src/srt_processing/AGENTS.md`、`src/translation/AGENTS.md`、`src/archive_core/AGENTS.md`、
`src/subtitle_rendering/AGENTS.md`；如确需调查词时间，再读transcription指南。

再读：

- `docs/reviews/2026-10-24-rendering-technical-and-semantic-review.md`；
- `docs/archive/decisions/0002-translation-sentence-units.md`；
- `docs/archive/decisions/0003-srt-processing-input-boundary.md`，特别v3修订及其质量限制；
- `docs/decisions/0006-subtitle-rendering-ass-and-burn-in.md`；
- `docs/archive/tasks/SP-09-agent-reference-evaluation.md`、SP-13/14/15及其链接报告；
- `docs/tasks/SR-07-real-sample-acceptance.md`。

归档表示实现/实验任务已经结束，不表示其质量缺陷消失或公共契约已自动失效。历史agent参考
不是golden。不要先读旧planner/参考切法再把其结果包装成“GPT独立语义审阅”。

## 事实与问题

这是完全本地的离线媒体资产管线，不是平台、CMS或云服务。现有translation按完整英文句子/
section生成中文；srt_processing以中文自然停顿块为优先，使用单调比例分配英文词区间，
共用双语cue与时间。rendering只消费公共plan，不改正文、cue时间或上游词时间。

用户反复审看后确认：**他观察到的音轨与英文单词时间准确，transcription表现好；当前核心
问题是中文片段与英文词区间不构成语义对应。** 请以保留英文时间锚点为起点，不要通过重跑
ASR或移动正确的词时间掩盖语义错位。若发现反证，给局部可核验证据，不猜测。

真实样本为CNBC 2000上午场第6/7节，623秒、2 sections、97 sentences、163 cues。
工作区：`output/cue-evaluation/20261023-candidate-v3/workspaces/cnbc_2000_morning/`。
原始同源上游：`output/transcription-integration/cnbc_2000_morning/`。

阅读该工作区的`source_alignment.json`、`translation_result.json`、`subtitle_plan.json`和对应manifest；
样片为`video_中文字幕.mp4`（SHA256见复审报告）。只读保留所有现有工件。

用户前两分钟内的反馈：
1. 约00:23：Berkshire Hathaway已经读到，中文对应名称还在下一cue。
2. 约00:30：percent仍在读，字幕已消失。
3. 约00:36：you have已经读到，中文对应内容尚未显示。
4. 约01:26：but the已读，字幕尚未出现。

这些是秒级播放器截图/用户听音观察，不是假定已精确到帧的ground truth。第2/4类仍需核对
实际显示边界，不能用一个语义解释包办所有现象。没有直接处理音频/视频的能力时，明确区分
GPT文本语义审读、时间戳推导、实际抽帧、用户听音证据，不得宣称自己已听完或播放全片。

具体例子：s5旧c5英文已经包含`Berkshire Hathaway has`，中文名称在c6；s6旧c7英文已经包含
`you have had a run`，中文对应内容在c8。目标是同一时间窗表达同一意思，不是每个汉字逐字
跟读英文；专名、数字、否定、转折、主体/谓语尤其不能漂到错误cue。

## 请探索，而非直接套用的候选方向

- 完整句翻译后，GPT/模型生成英文word-ID区间与中文语义片段的多对多映射，再联合规划cue；
- 保留上下文的英文语义分块与分块翻译，不把孤立小片段逐条翻译造成上下文丢失；
- 联合生成可定时的中英语义块；
- 中英独立时间窗/不同cue边界，及其与双语共同显示、阅读负担和当前契约的冲突；
- 确定性aligner、GPT审阅工件或混合方案的实际优缺点。

不能只把“中文优先”反过来叫“英文优先”，但仍按字数比例配中文。不要继续微调DP权重来
假装获得了语义证明。对译序交叉，比较合并较大语义块、允许局部译序调整/重译、独立语言时间窗
等策略；明确各自损失与边界。若固定译文、共享短cue、自然中文停顿、严格语义对应和显示容量
无法同时满足，要给具体反例及需要放弃的约束，不能偷偷放宽。

## 交付要求

1. 根因模型与失败分类；逐项追踪四例到sentence/word IDs、中文范围、原cue与显示边界。
2. 在不读旧planner结果来决定切法的前提下，GPT独立审读原始中英句；先覆盖四例及S17/S22/
   S48/S74/S88等，再提出覆盖全97句和未参与调参样本的验证方案。审读依据和不确定性都要保存。
3. 比较至少三个可行架构，给推荐方案和取舍，不要求在这一轮强行实现完整修复。
4. 具体数据契约示例：英文词区间/中文片段、必要的非连续/多对多关系、原文/改译溯源、置信与
   待审状态、coverage与顺序、模型/prompt/schema版本、输入hash、持久复用与失败语义。
   模型自报confidence不是语义正确性的证明；不要把公共DTO机械校验等同于语义验收。
5. 明确能力归属：translation、独立对齐阶段或srt_processing？当前srt模块禁止调用LLM、
   公共mapping_method/词与中文范围守恒有既定约束；需要更改时提出ADR，不绕过模块边界。
6. 将模型语义产物与确定性时间/显示/发布校验分开；说明昂贵调用、checkpoint、成本、可恢复性、
   冻结输出、独立复核和不确定时阻断/交人工的方式。不允许静默回退比例映射后仍标语义通过。
7. 给可执行验收设计：关键语义锚点覆盖、提前/滞后、尾词提前消失、gap/闪烁、自然语块、字数/
   CPS/像素、安全区域、语义完整性/否定数字、整片播放、零写复用与全部上游不变。
   同时区分可机械自动化检查与必须由模型/人类语义判断的项目。
8. 形成研究报告、待讨论的ADR草案、带依赖的最小实施切片和仍需用户确认的少量决策。
   推荐方案必须能泛化，不把97句手工patch当成通用算法；同时也不能拒绝用独立手工参考验证算法。

## 安全与执行边界

- 先只读调查和写研究文档；小规模原型/新模型调用/真实重新烧录先提出实验计划，未经确认不执行昂贵阶段。
- 不重跑下载、ASR、translation/provider或SRT planner来准备输入，不使用合成数据冒充真实验收。
- 不覆盖/删除任何input/output、原译文、旧plan/SRT/ASS/成片、manifest、历史v1/v2/v3或参考稿。
- 后续获批实验必须使用唯一新隔离目录，保留真实来源，不伪造/re-sign上游manifest来掩盖改动。
- 默认离线测试不依赖外部服务；代码改动须跑完整`.venv/bin/python -m pytest tests/ -q`，
  真实集成显式门控。样片与模型产物不提交Git。未经要求不commit/push。
- 不做orchestration/CLI/Web UI，不恢复被删除的旧路线图，不把当前技术样片交付说成最终质量通过。
