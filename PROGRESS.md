# 项目进度与交接

最近核对：**2026-11-23（Asia/Shanghai）**。代码核对基准：`9cb6c38`。这是给下一轮 agent 的短交接，不是任务流水账；流程规则见 [AGENTS.md](AGENTS.md)，细节和历史证据见 [文档索引](docs/README.md)。

## 已实现、已验证

| 范围 | 当前状态 | 证据 |
|---|---|---|
| 本地生产管线 | 采集、下载/显式派生、转录、英文分块、初译、双语编辑排时、SRT 导出和 ASS 烧录已实现。单资产编排提供 plan / run / resume / verify，真实 CNBC 已从空工作区经恢复跑通，九阶段同进程/新进程复用时为零昂贵调用、零阶段改写。 | [ADR-0008](docs/archive/decisions/0008-local-orchestration-and-integration-tests.md) · [NB-08 验收](docs/archive/tasks/NB-08-full-fresh-acceptance.md) |
| 最新固定样本迭代 | 生产切分是 `english-typed-cue-dp.v8`（84 字符逻辑 cue，上屏布局由 rendering 负责）；comparison-v9 是实验编号。英文 165 块，真实初译和编辑后发布 166 cue 的唯一权威稿及 623 秒诊断样片；五阶段复用为零昂贵调用、零阶段改写。未重跑 ASR/词对齐。 | [ADR-0013](docs/archive/decisions/0013-typed-chunking-quality-and-regression.md) · [NB-12 最终验收](docs/archive/tasks/NB-12-chunking-quality-iteration.md#2026-11-15负责人目视范围与验收后doc-only收尾) |
| 面向用户的入口 | `src/cli/` 和 `src/webui/` 仍是脚手架，没有可用的 CLI 或评审 Web UI；不在当前实施队列。 | [CLI 指南](src/cli/AGENTS.md) · [Web UI 指南](src/webui/AGENTS.md) |

翻译配置默认使用 `codex-cli-chatgpt`；`openai-responses` 是显式备选，不自动回退。历史外发授权不自动延续。

## 未通过 / 未验证

- **整体字幕语义同步和出版质量未通过。** NB-12 已审读全部 97 句，但 c69「每天」比源文 `per day` 提前 4.042 秒；c66/c69「8 盎司装」有计量表述风险；c162 双破折号跨行是独立的布局问题。详见 [NB-12](docs/archive/tasks/NB-12-chunking-quality-iteration.md)。
- 样片仅供诊断复审。像素、字形、ASS 和媒体技术检查无错误；负责人只抽看 18 帧，未全片连续观看、未核听、未取得人工出版签字。音轨与原轨 packet hash 一致，不等于核听。
- 样片是本地忽略产物，不随 Git 分发：`output/orchestration-integration/NB12-20261113-frozen-source-v1/cnbc_2000_morning-ch6-7/video_中文字幕.mp4`。

## 当前队列与下一步

[方案目录](docs/decisions/README.md)没有待审 ADR，[任务目录](docs/tasks/README.md)没有活跃实施任务。NB-12 本轮技术交付已收尾，质量问题仍开放，未自动排入开发。下一步是用户复审现有诊断片，优先确认 c69 的跨屏错位和实际听看结果；要继续修正时，先确认范围与验收标准，再建新 ADR / 任务。当前不重跑昂贵阶段、不改权威稿或重置额度。

## 最近验证

- 2026-11-23：文档整理后离线套件 **2873 passed / 1 skipped / 6 deselected**（排除 live）。未重新生成或核听样片。
- 2026-11-15：NB-12 最终验收记录为 **2873 passed / 7 skipped**；真实取证范围和已知限制见归档。此结果不代表字幕质量通过。

维护方式参考 Anthropic 的 [Effective harnesses for long-running agents](https://www.anthropic.com/research/effective-harnesses-for-long-running-agents)：原文用 `claude-progress.txt` 配合 Git 历史跨会话交接；本仓库采用工具无关的 Markdown 文件 `PROGRESS.md`。只留最近核对日期、已验证结果及其证据、未完成或被阻塞的事项和明确下一步；完整决策与实验过程留在 ADR、任务、归档和 Git。
