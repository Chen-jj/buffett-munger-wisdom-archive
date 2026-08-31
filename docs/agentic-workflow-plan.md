# Agentic 开发工作流规划（脑暴稿）

> 范围：如何让 AI coding agent（pi 为主，兼容 Claude Code / Codex 等 Agent Skills 标准工具）在本仓库高效、安全、可验证地干活。
> 前置事实：legacy 代码已删除（`cc9df50`），`src/` 13 模块脚手架 + 离线 pytest 套件就位；root 与 12 个模块级 `AGENTS.md` 已存在；**尚无** `.pi/` 配置、lint/type 工具、Makefile、CI。
> 姊妹篇：`docs/ai-workflow-refactor-plan.md`（媒体 AI 管线重构路线图）——本文档的 agentic 工作流就是执行那份路线图的"操作系统"。

---

## 1. 核心理念：把"人类约束"变成"机器可验证的约束"

Agentic 工作流的成败不在于 prompt 写得多花，而在于三件事：

1. **上下文工程**：agent 一进仓库就知道规则在哪、该读什么（progressive disclosure，不要一次性灌满）。
2. **验证闭环**：agent 每完成一步都能**自己跑命令验证**，不需要人类当裁判。验证越快越确定，agent 越强。
3. **护栏机器化**：昂贵资产保护、分层规则这类红线，用工具强制执行，而不是指望模型每次都记得 AGENTS.md 里的一句话。

本项目已有的资产盘点（哪些能直接复用）：

| 已有资产 | 作用 | 缺口 |
|----------|------|------|
| root `AGENTS.md` | 总规则、模块地图 | 缺"完成任务前必须跑 X"的硬规则 |
| 12 个模块 `AGENTS.md` | 模块级分层规则与 Phase 目标 | pi 只自动加载 root，模块级需 agent 主动读 |
| 离线 pytest 套件 + `live` marker | 验证闭环的地基 | 无 lint/type/架构契约检查，无单一入口命令 |
| `archive_core.manifest.v1` 等显式契约 | agent 可依据的数据契约 | 无 golden fixture 对比机制 |
| AGENTS 红线（不删 output/ 等） | 人类约束 | 无机器强制 |

---

## 2. 目标工作流全景

```
┌────────────────────────── 会话层（session hygiene）──────────────────────────┐
│ 一个任务 = 一个 session = 一个 git worktree/分支                              │
│ /tree /fork 做探索分支；任务完成即合流，session 可 /export 归档复盘             │
└──────────────────────────────────────────────────────────────────────────────┘
         │ 进入任务时
┌────────▼───────────────── 上下文层（context engineering）────────────────────┐
│ root AGENTS.md（自动加载）→ 模块 AGENTS.md（skill 指导按需读取）               │
│ /phase N 模板 → 加载管线重构路线图的对应阶段 + 验收标准                         │
│ docs/decisions/ ADR → 架构决策记录                                            │
└──────────────────────────────────────────────────────────────────────────────┘
         │ 动手时
┌────────▼────────────────── 能力层（skills & templates）──────────────────────┐
│ /slice <module> <capability>   实现一个模块切片的标准流程                       │
│ /verify                        跑全量验证门（agent 自我验证）                   │
│ /arch-review                   分层合规 + AGENTS 合规审查                      │
│ skill: subtitle-qa / backfill-manifest / new-adr ...                          │
└──────────────────────────────────────────────────────────────────────────────┘
         │ 每次工具调用时
┌────────▼────────────────────── 护栏层（extensions）──────────────────────────┐
│ tool_call 事件门禁：output/ cache/ 只读；.env/密钥文件禁写；危险命令拦截        │
└──────────────────────────────────────────────────────────────────────────────┘
         │ 声称完成前
┌────────▼────────────────────── 验证层（verify gate）─────────────────────────┐
│ scripts/verify.sh = pytest(offline) + ruff + mypy(渐进) + 架构导入契约 + 冒烟  │
│ 本地与 CI 同一套命令（消除"在我机器上能跑"）                                    │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. 分层设计详解

### 3.1 验证闭环（最高杠杆，先做）

Agent 能自我验证 = 人类只需要 review 结论而不是过程。落地物：

**`Makefile`（或 `scripts/verify.sh`）—— 唯一真相入口：**

```makefile
.PHONY: check test lint type arch smoke
check: test lint type arch smoke   ## agent 完成任务的默认动作

test:            ## 离线测试（默认排除 live）
	. .venv/bin/activate && python -m pytest tests/ -q -m "not live"
lint:
	. .venv/bin/activate && ruff check src tests
type:            ## mypy 渐进：先只查 archive_core，逐模块放开
	. .venv/bin/activate && mypy src/archive_core
arch:            ## 分层契约（见下）
	. .venv/bin/activate && python -m pytest tests/test_architecture.py -q
smoke:
	. .venv/bin/activate && python -c "import archive_core, acquisition, media_download"
```

**架构契约测试（`tests/test_architecture.py`）** —— 把 AGENTS.md 的分层规则变成可执行断言：

```python
# 规则示例（用 ast/grep 实现零依赖，或引入 import-linter）
# 1. domain/ 不得 import infrastructure/application/interfaces/subprocess/http 客户端
# 2. application/ 不得 import 各模块 infrastructure 具体实现
# 3. 跨模块只能经 archive_core 或对方 interfaces/application
# 4. src/<module>/ 下必须存在 AGENTS.md 且包含 "Layering Rules"
```

这一步的意义：**agent 重构时违反分层会直接红灯**，人类不需要逐行审。`ruff` + `mypy` 基线先宽松（`--exit-zero` 记录现状），随迁移收紧。

**CI（GitHub Actions）**：只跑 `make check`。agent 本地过了 CI 必过 → agent 敢自我声明完成。

### 3.2 上下文工程

**root `AGENTS.md` 增补三条硬规则（提议 diff，待你确认后落地）：**

```markdown
## Agent Working Rules（新增小节）
- 动 `src/<module>/` 前必须先读 `src/<module>/AGENTS.md`，与本文件冲突时以更严格者为准。
- 声称任务完成前必须运行 `make check` 且全绿；无法全绿时明确列出失败项与原因。
- 一次 session 只做一个可验证切片；跨模块改动拆成多次。
```

**pi 的加载机制要点**：pi 启动只自动拼接 root（及祖先）`AGENTS.md`，模块级的靠 skill/规则引导按需读取——这正是 progressive disclosure，12 个模块 AGENTS.md 不会撑爆上下文。

**ADR（`docs/decisions/NNNN-*.md`）**：凡是"为什么这么做"的决策（如缓存键设计、stage 状态机）写 ADR，agent 改到相关代码时会被 skill 引导先读 ADR。避免半年后 agent 用今天的上下文推翻当时的决策。

### 3.3 能力层：Prompt Templates + Skills

放 `.pi/prompts/`（pi 专属）与 `.agents/skills/`（跨 harness 通用，Claude Code/Codex 都认 Agent Skills 标准）：

| 名称 | 类型 | 用途 | 要点 |
|------|------|------|------|
| `/slice <module> <capability>` | template | 实现一个模块切片 | 流程：读模块 AGENTS.md → 写 domain → application（ports）→ infrastructure（可 mock）→ 测试 → `make check` → 更新模块 AGENTS.md（如契约变化） |
| `/verify` | template | 全量验证 + 失败归因 | 跑 `make check`，失败时先分类：断言失败/风格/类型/架构契约 |
| `/arch-review` | template | 变更合规审查 | 对 `git diff` 检查：分层、契约变化是否更新 AGENTS.md、是否引入网络依赖到 domain |
| `/phase <n>` | template | 执行管线重构路线图某阶段 | 读 `docs/ai-workflow-refactor-plan.md` 对应 Phase，产出任务切片清单 + 每片验收标准，逐片 `/slice` |
| `skill: subtitle-qa` | skill | 对 output/ 产物跑字幕校验 | 序号/时间轴/行长/术语脚本 + 报告格式 |
| `skill: new-adr` | skill | 起草 ADR | 模板 + 状态流转 |
| `skill: backfill-manifest` | skill | 存量产物补登 manifest | 只读扫描 + dry-run 报告（需人工确认才写入） |

skill 的 `description` 要写清"什么时候用"（pi 靠它决定加载时机），正文保持精简，细节放 `references/`。

### 3.4 护栏层：Extension（TypeScript）

`.pi/extensions/protect-assets/` —— 监听 `tool_call` 事件：

```typescript
export default function (pi: ExtensionAPI) {
  const PROTECTED_WRITE = [/^output\//, /^cache\//];
  const FORBIDDEN_WRITE = [/\.env$/, /(^|\/)secrets?\./];
  pi.on("tool_call", async (event) => {
    // write/edit/bash 请求命中 PROTECTED_WRITE → block 并提示需人工确认
    // 命中 FORBIDDEN_WRITE → 直接 block
    // bash 中的 rm -rf / 针对受保护目录的模式匹配 → block
    return { block: true, reason: "output/ 受 AGENTS 红线保护，需人工确认后手动执行" };
  });
}
```

把「Never delete generated or source media assets without explicit user confirmation」从一句提示变成机器闸门。注意 `.pi/` 资源在 project trust 之后才加载——这是合理的安全边界。

### 3.5 会话与多任务编排

观察到你已在多会话并行开发（本次会话期间另一会话删除了 legacy）。约定：

- **一个任务一个 worktree**：`git worktrees/`，分支名 `slice/<module>-<capability>`，避免两个 agent 在同一工作区互相覆盖。
- **session 命名**：`pi --name "slice-translation-checkpoint"`；探索用 `/fork`、回溯用 `/tree`（session 树本身保留全部历史，compaction 有损但 JSONL 可回看）。
- **任务简报**（任务的最小上下文单元）：目标一句话 + 涉及模块 + 验收命令（`make check` + 额外断言）。可以放 issue、放 `docs/backlog.md`、或直接 `/phase N` 生成。
- **消息队列**：agent 干活时用 Enter（steering）纠偏、Alt+Enter（follow-up）追加任务，别打断。

### 3.6 复盘与度量（轻量）

- 每个合流的任务在 session 里 `/export` 归档（可选入 git 的 `docs/sessions-index.md` 索引）。
- 周期性回答三个问题：验证门拦截了多少次违规（说明护栏有效）、人类平均干预次数/任务（趋降说明上下文工程有效）、哪个模块 agent 最容易跑偏（该模块 AGENTS.md 需补规则）。
- 失败案例沉淀回 AGENTS.md / skill —— **规则只在被违反的地方生长**。

---

## 4. 落地路线图

| 阶段 | 内容 | 交付物 | 验收 |
|------|------|--------|------|
| **A. 验证门**（先做，1 次会话） | Makefile + ruff/mypy 基线 + `tests/test_architecture.py` + CI | `make check` 全绿 | 故意在 domain 里 import subprocess → arch 测试红 |
| **B. 上下文** | AGENTS.md 增补硬规则；docs 索引 + ADR 模板 | 规则生效 | 新会话 agent 能复述"动模块前先读其 AGENTS.md" |
| **C. 能力层** | `/slice /verify /arch-review /phase` 模板 + `subtitle-qa`、`new-adr` skills | `.pi/prompts/` `.agents/skills/` | 用 `/slice translation batch-checkpoint` 完成真实切片 |
| **D. 护栏** | protect-assets extension + `.pi/settings.json` | tool_call 门禁 | agent 试图删 `output/` 被拦 |
| **E. 编排** | worktree 约定 + backlog + session 命名 | 文档 + 习惯 | 两个并行会话无冲突完成两个切片 |
| **F. 度量** | export 归档 + 周复盘 | 索引文档 | 能回答 §3.6 三问 |

阶段 A/B 是地基，C 之后 agentic 工作流开始"自举"——用 `/phase` 驱动 `docs/ai-workflow-refactor-plan.md` 的 Phase 0~6，每片都是 `/slice`。

---

## 5. 开放问题

1. **CI 平台**：仓库是否有 GitHub 远端？（决定 Phase A 的 CI 形态；纯本地则用 git pre-push hook 代替。）
2. **多 harness 兼容**：skill 放 `.agents/skills/`（通用）还是 `.pi/skills/`（pi 专属）？建议通用优先。
3. **mypy 引入节奏**：全仓一次到位 vs 随模块迁移逐个放开（建议后者，避免存量噪音淹没 agent）。
4. **护栏强度**：`output/` 完全禁写，还是允许写但禁删？（建议：禁删禁覆盖，写入需 `--force` 语义。）
5. **是否需要 sub-agent / plan-mode extension**：pi 官方哲学是按需自建。建议先靠模板纪律（先规划后动手）跑一段时间，痛点真实存在再建。

---

## 6. 与 AGENTS 约束的符合性自查

- 不引入云服务/数据库/后台 worker：✅ 全部是本地文件 + 现有工具链。
- CLI/Web 不承载业务规则：✅ skill/template 只编排流程，不写业务逻辑。
- 外部依赖隔离：✅ 护栏与验证门都在开发设施层，不进入 `src/`。
- 小步可验证迁移：✅ `/slice` 粒度 + `make check` 门。
