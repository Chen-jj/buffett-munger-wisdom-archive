# 项目进度与交接

最近核对 **2026-11-28（Asia/Shanghai）**。流程规则见 [AGENTS.md](AGENTS.md)，细节和历史证据见 [文档索引](docs/README.md)。

## 已实现、已验证

| 范围 | 当前状态 | 证据 |
|---|---|---|
| 本地生产管线 | 采集、下载/显式派生、转录、英文分块、初译、双语编辑排时、SRT 导出和 ASS 烧录已实现。单资产编排提供 plan / run / resume / verify，真实 CNBC 已从空工作区经恢复跑通，九阶段同进程/新进程复用时为零昂贵调用、零阶段改写。 | [ADR-0008](docs/archive/decisions/0008-local-orchestration-and-integration-tests.md) · [NB-08 验收](docs/archive/tasks/NB-08-full-fresh-acceptance.md) |
| 全帧 PTS 扫描 | `ffprobe -show_frames` 取消 300 秒时限，使用实际帧时间戳继续排时与校验。模拟 301 秒扫描生成了边界文件并零次重新下载，重复运行复用证据。 | [ADR-0014](docs/archive/decisions/0014-pipeline-timeouts.md) · [NB-13 验收](docs/archive/tasks/NB-13-pipeline-timeouts.md) |
| CNBC 2020 融合与句界 | 按整句锚点选稿，移除按词数断句、fallback 发布门槛和日志 500 字符限制。两场复用原声学工件在独立位置完成重跑和对照。 | [ADR-0015](docs/archive/decisions/0015-cnbc-transcript-fusion-and-sentence-boundaries.md) · [NB-14 验收](docs/archive/tasks/NB-14-cnbc-fusion-sentence-replay.md) |
| CNBC 2020 带词时间融合 v3 | 两场复用 NB-14 声学输入并隔离回放，产出 15,492 和 20,404 个融合词。对比核验覆盖编码、数值等价、同窗 CTC、时间和来源。实际执行止于融合，复用回查零声学调用、零工件改写。 | [NB-15](docs/archive/tasks/NB-15-cnbc-timed-transcript-fusion.md) · [独立验收](output/cnbc-2020-adr0016-20261126/run-fusion-2/独立验收.md) |
| CNBC 2020 官网优先融合 | `run-fusion-3` 复用两场 `run-fusion-2` 冻结输入，仅运行融合。产出 15,512、20,414 个词及 189、168 处差异。时间、来源、输入保护和缓存复用通过。 | [NB-16](docs/archive/tasks/NB-16-cnbc-fusion-official-priority.md) · [前后审阅](output/cnbc-2020-adr0016-20261126/run-fusion-3/融合前后审阅.md) |
| CNBC 2020 融合标点句界 v3 | 按最终融合标点切句、两类 asr_only 同等资格、先分离编辑符号，停顿留 chunking；融合 v8 为 See's./And 发布真实独立词时间。两场 743 / 1,151 句，28 个反例与 4 个连续样例通过，首轮前缀误切修复。 | [ADR-0017](docs/archive/decisions/0017-sentence-boundary-evidence.md) · [NB-17](docs/archive/tasks/NB-17-fused-punctuation-sentence-boundaries.md) · [负责人验收](output/cnbc-2020-adr0017-20261128/run-accepted-2/负责人验收.md) |
| 最新固定样本迭代 | 生产切分是 `english-typed-cue-dp.v8`（84 字符逻辑 cue，上屏布局由 rendering 负责）；comparison-v9 是实验编号。英文 165 块，真实初译和编辑后发布 166 cue 的唯一权威稿及 623 秒诊断样片；五阶段复用为零昂贵调用、零阶段改写。未重跑 ASR/词对齐。 | [ADR-0013](docs/archive/decisions/0013-typed-chunking-quality-and-regression.md) · [NB-12 最终验收](docs/archive/tasks/NB-12-chunking-quality-iteration.md#2026-11-15负责人目视范围与验收后doc-only收尾) |
| 面向用户的入口 | `src/cli/` 和 `src/webui/` 仍是脚手架，没有可用的 CLI 或评审 Web UI；不在当前实施队列。 | [CLI 指南](src/cli/AGENTS.md) · [Web UI 指南](src/webui/AGENTS.md) |

翻译配置默认使用 `codex-cli-chatgpt`；`openai-responses` 是显式备选，不自动回退。历史外发授权不自动延续。

## 未通过 / 未验证

- **整体字幕语义同步和出版质量未通过。** NB-12 已审读全部 97 句，但 c69「每天」比源文 `per day` 提前 4.042 秒；c66/c69「8 盎司装」有计量表述风险；c162 双破折号跨行是独立的布局问题。详见 [NB-12](docs/archive/tasks/NB-12-chunking-quality-iteration.md)。
- 样片仅供诊断复审。像素、字形、ASS 和媒体技术检查无错误；负责人只抽看 18 帧，未全片连续观看、未核听、未取得人工出版签字。音轨与原轨 packet hash 一致，不等于核听。
- 样片是本地忽略产物，不随 Git 分发：`output/orchestration-integration/NB12-20261113-frozen-source-v1/cnbc_2000_morning-ch6-7/video_中文字幕.mp4`。

## 当前队列与下一步

ADR-0017 已完成并归档，当前没有活跃实施任务。最新实际工件位于 `output/cnbc-2020-adr0017-20261128/run-accepted-2`，融合身份 `monotonic-local-dp.v8`，词数 15,504 / 20,400；句界身份 `sentence-boundary.v3`，句数 743 / 1,151。v8 保留用户确认的 v7 选稿裁决，仅将 E11 的跨句组合拆成有真实逐词时间的两个词条。原 v7 基线及全部旧产物保留。[实际输入与输出](output/cnbc-2020-adr0017-20261128/run-accepted-2/replay_receipt.json)

负责人已逐项审查新增30个、取消7个断点：28个为ADR反例，另2个为可靠换人；7个取消点均为融合正文无句末时由官网补出的断点，按用户确认契约取消。所有既有有效融合句末断点保留，域名、姓名、章节、20ms句号、but Our连续、Greg接话及4个ASR-only回答前缀保住。典型例子已进入自包含离线测试。未核听全片，技术通过不扩展为整条管线出版质量通过。

既有融合留出样例及长达3.458秒的 `The—` 词区间仍待内容复核，不自动排入开发；不继续推进用户明确忽略的 Cass/Kass 取词问题。[ADR-0018](docs/archive/decisions/0018-cnbc-fusion-official-priority.md) · [NB-16](docs/archive/tasks/NB-16-cnbc-fusion-official-priority.md)。

NB-12 本轮技术交付已收尾，质量问题仍开放，未自动排入开发。用户复审 NB-12 诊断片时优先确认 c69 的跨屏错位和实际听看结果；要继续修正时，先确认范围与验收标准，再建新 ADR / 任务。当前不重跑昂贵阶段、不改权威稿或重置额度。

## 最近验证

- 2026-11-28：NB-17 负责人完整离线 **3010 passed / 1 skipped / 6 deselected**；第二轮两场实际回放32/32逐例通过。独立复核所有有效融合句末、来源身份、完整覆盖及原输入指纹；同进程/新进程复用零新评分与改写，回放零模型调用。首轮未知回答前缀误切已退回子agent修正并新增回归。[最终验收](output/cnbc-2020-adr0017-20261128/run-accepted-2/负责人验收.md)
- 2026-11-28：仅修订 ADR-0017 的融合标点权威性、例子及验收条件，撤销按官网补切逗号和按官网续说合并融合句号的要求；文档一致性与链接核验通过。未改生产或测试代码，未重跑模型、句界或完整离线套件。
- 2026-11-27：实际发布 v7 融合及当前句界，两场公共 DTO、词时间和来源保持、原工件指纹、融合与句界缓存零改写复用通过。复用记录评分并补算一个本地 CTC 窗口，无新 ASR、全片对齐或联网下载；未核听全片，本轮未修改生产或测试代码。[回执](output/cnbc-2020-adr0017-20261127/run-boundaries-v7-3/replay_receipt.json)
- 2026-11-27：固定 `run-fusion-3` 实际 v6 融合词对照两版句界。提交版两场因 fallback 门槛失败，工作树版成功发布 734 / 1,137 句并零改写复用。负责人独立复核输入和结果来源、词时间及 DTO，全离线 **2956 passed / 1 skipped / 6 deselected**。[审查与回执](output/cnbc-2020-adr0017-20261127/run-boundaries-1/审查结论.md)
- 2026-11-27：融合提交候选的完整离线套件 **2954 passed / 1 skipped / 6 deselected**。隔离验证覆盖实际问题回归、融合 v3 来源接线及冻结金额的内存重放。[NB-16 提交前整理](docs/archive/tasks/NB-16-cnbc-fusion-official-priority.md#合并前整理与回归)
- 2026-11-27：NB-16 金额修复完整离线套件 **2953 passed / 1 skipped / 6 deselected**，定向验证 **125 passed**。用两场冻结输入和保存的声学返回在内存验证三处定稿，覆盖来源、时间、复用及原工件指纹。[验证结果](docs/archive/tasks/NB-16-cnbc-fusion-official-priority.md#2026-11-27-完整金额定稿修复)
- 2026-11-26：NB-16 完整离线套件 **2948 passed / 1 skipped / 6 deselected**。两场 `run-fusion-3` 各通过 45 项独立工件检查，确认全部 357 处差异对应实际发布词。原输入和旧融合指纹一致，融合复用零声学调用、零改写。[前后审阅](output/cnbc-2020-adr0016-20261126/run-fusion-3/融合前后审阅.md)
- 2026-11-26：NB-15 修订版完整离线套件 **2924 passed / 1 skipped / 6 deselected**。两场最终回放各通过 33 项独立工件检查，分别有 148、196 处正文、时序或 ASR 映射变化。原声学文件、基线章节和旧融合哈希复核一致。[最终独立验收](output/cnbc-2020-adr0016-20261126/run-fusion-2/独立验收.md)
- 2026-11-26：NB-15 编码修复完整离线套件 **2892 passed / 1 skipped / 6 deselected**。两场库存正文的清洗幂等，Part1 `didn’t` 匹配 `aw1450` 并复用原时间。原输入和旧融合哈希与 NB-14 回执一致。[NB-15](docs/archive/tasks/NB-15-cnbc-timed-transcript-fusion.md)
- 2026-11-26：Part1 `lethal / many` 允许共有词移动时，`many` 的词平均分更高。固定窗口及四个切点微调窗口的整段 CTC 均支持 `lethal`，与用户核听倾向一致。原工件未改写。[同窗诊断](docs/archive/decisions/0016-cnbc-timed-transcript-fusion.md#lethal--many-同窗诊断)
- 2026-11-25：NB-14 完整离线套件 **2891 passed / 1 skipped / 6 deselected**。实际 Part1、Part2 完成隔离重跑，独立工件回归 35 项通过。审阅正文含词级时间待核内容，重跑结果未重新核听。
- 2026-11-24：修复范围收窄到全帧 PTS 扫描后，离线套件 **2874 passed / 1 skipped / 6 deselected**。真实长片未重跑。
- 2026-11-23：文档整理后离线套件 **2873 passed / 1 skipped / 6 deselected**（排除 live）。未重新生成或核听样片。
- 2026-11-15：NB-12 最终验收记录为 **2873 passed / 7 skipped**；真实取证范围和已知限制见归档。此结果不代表字幕质量通过。

维护方式参考 Anthropic 的 [Effective harnesses for long-running agents](https://www.anthropic.com/research/effective-harnesses-for-long-running-agents)：原文用 `claude-progress.txt` 配合 Git 历史跨会话交接；本仓库采用工具无关的 Markdown 文件 `PROGRESS.md`。只留最近核对日期、已验证结果及其证据、未完成或被阻塞的事项和明确下一步；完整决策与实验过程留在 ADR、任务、归档和 Git。
