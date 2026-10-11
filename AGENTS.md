# AGENTS.md

巴菲特与芒格智慧档案的离线媒体资产管线：抓取元数据 → 下载视频 → ASR 转写 → 翻译 → 双语字幕 → 烧录渲染 → 人工评审。完全本地运行。这是一条可复现的长视频处理管线，不是视频平台、CMS 或云服务。

## 当前状态（先读这里）

仓库正处于迁移中期。动手前先核实现实，不要假设某个模块能用。

> 状态最后核对：2026-10-11 17:28 CST。**每次完成编码任务后，若实现状态或本文件中的事实发生变化，必须在同一次提交中更新本节（含核对时间）。**

| 状态 | 模块 |
|---|---|
| 已实现 + 离线测试 | `archive_core`、`acquisition`、`media_download`、`infrastructure` |
| 已实现 + 离线测试 + CNBC 真实集成测试 | `transcription` |
| 仅脚手架（分层目录 + AGENTS.md，无代码） | `cli`、`orchestration`、`srt_processing`、`translation`、`subtitle_rendering`、`webui` |

- 遗留管线（`run.py` step0–4 + Web 评审应用）已在提交 `cc9df50` 中删除。目前**没有 CLI 入口，管线无法端到端运行**。按 `docs/tasks/README.md` 的任务依赖图逐模块重建功能。
- 当前技术入口：`docs/tasks/README.md`（任务依赖）和 `docs/decisions/`（已接受 ADR）。此前两份
  路线图已由用户删除，不得恢复或继续把它们当作现行文档。
- 尚无 lint/typecheck/CI。离线 pytest 套件是唯一的验证门槛；另有少量 `live` 标记测试，包括
  acquisition→media_download 真实网络测试，以及 `RUN_TRANSCRIPTION_INTEGRATION=1` 门控的真实
  WhisperX 集成测试。本地 CNBC 2000 上午场第 3 节样本可从空 `output/` 自动准备，并在唯一的
  integration workspace 跑通至 `source_alignment.json`；第二次运行按 manifest 复用全部
  transcription 工件。transcription 不再提供 reference-based Golden Live 入口；未来全管线
  连通性由 orchestration 集成测试负责。
- `webapp/app.db` 是已被 gitignore 的遗留残留，忽略它。

## 开工规则

1. 动某个模块前，先读该模块的 `src/<module>/AGENTS.md`；大型任务前再读相关 ADR 与任务文档。
2. 说"做完了"之前必须跑质检（见「构建、测试与验证」），离线测试套件全绿才算完成；没跑测试不得声称完成。
3. 一次只做一小块可验证的改动，不同时大范围修改多个模块，不顺手重构无关代码。

## 环境与工具链（已知的坑）

- **仅支持 Python 3.11**（3.12 可接受）。WhisperX/PyTorch 技术栈不能可靠支持 Python 3.13+。
- **用 `ffmpeg-full`，不是 `ffmpeg`**（Homebrew）。字幕烧录需要 libass 支持的 `ass`/`subtitles` 视频滤镜。`ffmpeg-full` 是 keg-only：
  ```bash
  export PATH="/opt/homebrew/opt/ffmpeg-full/bin:$PATH"
  ```
- 做媒体工作前先验证外部工具：
  ```bash
  ffmpeg -hide_banner -filters | awk '$2 == "ass" || $2 == "subtitles"'   # 必须两个都列出
  yt-dlp --version && ffprobe -version
  ```
- 首次真实使用 ASR 会下载 Whisper 模型文件（按配置为 `large-v3`）——很慢，缓存它，别跟它较劲。
- `config.yaml` 存放运行时配置（翻译服务凭据、下载、字幕样式、WhisperX、抓取礼貌性）。**绝不提交真实 API key** —— 只放占位符。

## 管线数据流（目标态）

```text
acquisition ─→ media_download ─→ transcription ── source_alignment.json ─┬─→ translation
（网页抓取/         （yt-dlp）      （WhisperX + 词级对齐/句界）             │   （句级翻译）
 结构化逐字稿）                                                         │        │
                                                                        │        ▼
                                                                        └─→ srt_processing
                                                         translation_result.json ─┘
                                                                                │
                                                                                ▼
                                                               subtitle_rendering（libass/ffmpeg）

archive_core：资产身份、路径、公共 schema、manifest、溯源
orchestration：可恢复任务计划 · cli/webui：薄接口 · infrastructure：共享适配器
```

各阶段状态：实现到 `transcription` 为止；transcription 已通过离线测试与当前 CNBC 真实集成
验收。其下游仍是脚手架。

## 模块地图

- `src/archive_core/` —— 共享领域原语：资产身份、规范文件名、路径策略、`manifest.v1`、溯源。
- `src/acquisition/` —— 网页分析、爬虫、逐字稿提取、元数据规范化、抓取礼貌性规则。
- `src/media_download/` —— 媒体 URL 解析、yt-dlp 下载编排、校验和/溯源采集。
- `src/transcription/` —— 音频提取、VAD、ASR、词级对齐、逐字稿融合、英文句界。*（已实现 +
  离线测试 + CNBC 真实集成测试）*
- `src/srt_processing/` —— 结构化句子到 cue 的规划、SRT 投影/解析、双语合成与 QA。*（脚手架）*
- `src/translation/` —— 完整英文句子翻译、分批、术语/风格策略、服务适配器与结果校验。*（脚手架）*
- `src/subtitle_rendering/` —— SRT/ASS 样式、烧录渲染、ffmpeg 命令规划、渲染元数据。*（脚手架）*
- `src/webui/` —— 本地评审 UI 边界、目录契约。*（脚手架）*
- `src/cli/` —— 命令解析、面向人的命令、进度显示。*（脚手架）*
- `src/orchestration/` —— 管线组装、可恢复工作流、依赖排序、故障恢复。*（脚手架）*
- `src/infrastructure/` —— 共享技术适配器：配置、文件系统、进程执行、HTTP、日志、工具发现。

跨模块 import 规则：`archive_core`（领域契约）与 `infrastructure`（技术适配器）是仅有的两个允许被其他模块 import 的模块；功能模块的内部实现不得被跨模块 import。

## 架构

- 按能力组织，不按步骤编号组织。步骤式命名（如 `step3_translate`）禁止出现，临时迁移 shim 除外。
- 每个模块分四层：
  - `domain/` —— 纯概念与规则。禁止网络客户端、CLI 框架、`subprocess`、重文件系统操作、UI 代码。
  - `application/` —— 用例与模块内工作流协调。可依赖 `domain/` 和抽象端口；绝不直接依赖具体外部服务。
  - `infrastructure/` —— HTTP、ffmpeg、yt-dlp、ASR 库、翻译服务、文件系统等外部系统的适配器。
  - `interfaces/` —— CLI/Web/orchestration 使用的 DTO、命令处理器、展示器、序列化器。
- 跨模块只能通过契约 import：
  - ✅ `from src.archive_core.interfaces.manifest import ...`
  - ❌ `from src.acquisition.infrastructure.http_client import ...`（在 `media_download` 中这样写）
- 资产工作区契约由 `archive_core.application.build_asset_workspace()` 唯一定义，别处不得自创路径规则。规范文件名与 manifest schema 定义在 `src/archive_core/domain/artifacts.py` 和 `src/archive_core/interfaces/manifest.py` —— 同样以代码为唯一事实来源。任何写文件的模块必须定义期望的文件名、元数据和幂等行为。
- 每个昂贵阶段（抓取、下载、ASR、翻译、渲染）必须可恢复且由 manifest/溯源驱动。**绝不用"文件存在"当作完成判据。**
- CLI 和 Web UI 保持薄：校验输入、调用 application 服务、渲染结果。业务规则（媒体处理、爬虫逻辑）不得放进去。
- 外部工具/API 一律隔离在适配器之后，保证测试套件离线可跑（无网络、无 yt-dlp、无 ffmpeg）。
- 优先小步可验证的迁移，不做大规模重写。当某次改动改变了模块的架构意图、公开契约或阶段目标时，必须在同一次改动中更新该模块的 `AGENTS.md`。

## 构建、测试与验证

```bash
# 安装（Python 3.11）
python3.11 -m venv .venv && . .venv/bin/activate
python -m pip install -r requirements.txt -r requirements-dev.txt

# 完整离线套件（验证门槛）
python -m pytest tests/ -q

# 单个模块的测试
python -m pytest tests/test_acquisition_domain_application.py -q

# 标记为 `live` 的测试需要真实网络 —— 除非明确要求，否则跳过
python -m pytest tests/ -q -m "not live"

# 架构健全性检查：实现前确认模块指南存在
fd '^AGENTS\.md$' src --max-depth 3 | sort
```

## 关键约束

- 不引入云持久化、后台 worker、Web 框架或数据库，除非某个具体工作流确实需要。
- `domain/` 和 `application/` 层不得包含 OpenAI/Whisper/yt-dlp/ffmpeg 的特定厂商逻辑。
- CLI 和 Web UI 不得持有业务规则。
- 未校验 cue 数量一致性、时间轴单调性和文件溯源前，不得将生成字幕视为权威。
- 绝不静默覆盖昂贵的生成资产（ASR/翻译/渲染）。必须有显式覆盖策略或工件版本化。
- 绝不在没有用户明确确认的情况下删除生成资产或源媒体资产（`input/`、`output/`）。
- 实现某个模块切片时，不要顺手重构无关代码。

## 补充文档

- 模块指南：`src/<module>/AGENTS.md`（11 份）—— 动某个模块前先读对应那份。
- 技术任务入口：`docs/tasks/README.md`；已接受决策：`docs/decisions/`。
- `README.md` 是面向人的快速上手（安装、工具链设置）；架构规则在本文件和各模块指南中。
- 规则冲突时的优先级：`src/<module>/AGENTS.md` > 本文件 > `docs/` 规划文档。但本文件「关键约束」中的安全规则始终有效，模块指南不得覆盖。
