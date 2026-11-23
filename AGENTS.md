# AGENTS.md

巴菲特与芒格智慧档案是可复现的本地媒体处理管线，不是视频平台、CMS 或云服务。工件在本机落盘；采集、下载和外部翻译 provider 可能联网。

## 开工先读

1. 读 [PROGRESS.md](PROGRESS.md)，检查 `git status --short` 和近期提交，确认现状与本轮授权，不从旧报告恢复待办。
2. 读将涉及的 `src/<module>/AGENTS.md`、对应 ADR 和任务；[文档导航](docs/README.md)列出入口，[ADR-0008](docs/archive/decisions/0008-local-orchestration-and-integration-tests.md)是总方案。模块规则可细化根规则，不得放宽安全约束。
3. 先说明假设、歧义和验收方式；关键行为不清楚时先确认。一次只做一个可验证切片，不改无关代码。

## Agent 工作流

| 角色 | 职责 |
|---|---|
| **方案讨论 agent** | 把讨论稿 ADR 放进 [docs/decisions](docs/decisions/README.md)，标注「提议」，写明背景、备选与取舍、影响范围、验收标准和待决项。验收标准必须可复现：明确基线输入或工件、复现与验证步骤、可观察的通过条件，以及不能退化的行为和对应保好样例。讨论不改生产或测试代码；用户确认方案后才标注「已接受」，设计确认不等于批准 live 或外发。 |
| **开发负责人 agent** | **不写或修改生产代码、测试代码。** 仅将已接受且获准实施的 ADR 拆成 [docs/tasks](docs/tasks/README.md) 的可验收任务，写明依赖、分工、可改路径、不可改项、验证命令和预期证据；按依赖调用实现子 agent。没有子 agent 工具时说明阻塞，不自行代写。 |
| **实现子 agent** | 只做派发的任务，按模块契约做最小改动和定向验证，交回 diff、测试结果、剩余风险及实际工件位置；不自行扩范围、跑未授权的真实阶段或提交/推送。 |

负责人亲自审查 diff、独立运行完整离线套件并依据任务逐条验收；不合格退回子 agent 修正，不以其摘要代替验证。涉及真实样片时，取得授权后按 ADR-0008 逐阶段审查工件并安排独立回归，分别记录实际播放、画面抽查和核听范围。技术交付、语义同步和出版质量分开判定，不因此新增运行时语义门禁。

交接时更新 [PROGRESS.md](PROGRESS.md) 的核对日期、已验证结果、阻塞和下一步；模块架构或公开契约变化时，同一改动更新模块指南。结束的任务、已实施或被替代的 ADR 移入 `docs/archive/`，保留未通过项和证据链接；未被替代的归档契约继续生效。Git 提交或推送仅在本轮明确授权后由负责人执行；提交格式为 `type([module]): <英文短描述>`（`feat`、`fix`、`chore`、`refactor`）。

## 管线与架构

```text
acquisition → media_download（可显式派生）→ transcription（词时间、编辑标记）
→ srt_processing（英文分块、只读预算）→ translation（上下文初译 → 有界编辑与排时）
→ srt_processing（三份 SRT）→ subtitle_rendering（同一权威稿、ASS 与烧录）
```

- `archive_core` 定义公共工件、工作区和溯源；工作区由 `build_asset_workspace()` 定义，规范文件名及 manifest 以代码为准。`infrastructure` 提供共享技术适配器。`orchestration` 负责组装、依赖、授权、恢复与复用，集中放置集成验收。CLI / Web UI 保持薄，不承载业务规则。
- 按能力组织，不按步骤编号。各模块分四层：`domain` 是纯规则；`application` 通过抽象端口协调用例；`infrastructure` 隔离 I/O、厂商工具和 API；`interfaces` 暴露 DTO、命令与工厂。
- 功能模块只通过共享 `archive_core` 与 `infrastructure` 明确暴露的契约依赖；不相互导入。唯一例外是 `orchestration.infrastructure.composition` 可导入功能模块公开的 `interfaces`。生产代码不得依赖测试。
- 昂贵阶段以 manifest、输入身份和溯源驱动恢复/复用，不能以文件存在判完成。SRT / ASS 共享唯一权威双语稿；校验 cue 数量、时间单调性及来源后才消费。保持单一生产链路，不恢复旧版兼容。
- 不引入云持久化、后台 worker、Web 框架或数据库，除非具体工作流确实需要。

## 安全与验证

- 不经用户明确确认不删除文件，尤其是 `input/`、`output/` 中的媒体和工件；不静默覆盖昂贵产物，不回滚他人改动。需要重新生成时用新工作区或显式覆盖策略。
- 真实联网测试、模型下载、provider 调用、渲染及向外部服务发送素材前，核对本轮具体授权。旧授权不自动延续；密钥不进仓库，忽略的输出、模型、媒体不提交。
- 默认 Python 3.11（可用 3.12，不用 3.13+）。安装见 [README.md](README.md)；媒体任务先确认 `yt-dlp`、`ffprobe` 和 `ffmpeg-full`（libass 的 `ass` / `subtitles` 滤镜）可用。ASR 首次真实运行可能下载模型。
- 代码交付门槛：`python -m pytest tests/ -q -m "not live"`。未运行或未通过，不能声称验收完成。集成测试在 `tests/orchestration/integration/`；默认不跑 live。搜索用 `rg`，找文件用 `fd`。
