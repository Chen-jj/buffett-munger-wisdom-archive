# SP-03 — 双语候选、动态规划与全文QA

- **Status:** accepted
- **Owner:** planner 子开发 agent；仅技术负责人标记accepted
- **Module:** srt_processing/domain
- **Decision coverage:** ADR-0003 §7–8、§11、§14.2–3
- **Depends on:** SP-01、SP-02
- **Depended on by:** SP-06

## 范围与验收标准

- 按sentence_id关联words/译文/section/speaker，正常与应急断点，局部保护姓名/数字单位/紧密短语，不拆word或组合序列。

- 真正确定性稀疏DP：单调累计比例、句尾强制对应、跨句独立fragment、D39八项字典序与完整路径tie-break，整数/有理数公式固定测试。仅按硬约束和可证明支配剪枝，不因CPS剪掉唯一路径。

- 跨句候选：至少一个原始片段短于834或中文CPS>9，每个原始句间停顿<500，同section且全部非空speaker至多一种；不能以null串联不同speaker。调用SP-02同一时间函数预估/物化。

- 覆盖长短句/无标点/语序重排/499与500ms/全部speaker组合/section/单word超容量失败/高CPS成功、非贪心反例、候选顺序扰动、D39优先级、全文与时间QA。不得构造全文稠密矩阵。

## 验证与交接

```bash
.venv/bin/python -m pytest tests/srt_processing/test_planner.py tests/srt_processing/test_rules.py -q -m "not live"
git diff --check
```

记录实际命令/结果、API与未解决问题，再交负责人复验。先读根与模块AGENTS，保留用户已有ADR/指南修改；不得删除文件/资产，不作无关重构。

## 开发交接（2026-10-21）

本任务仅新增 `src/srt_processing/domain/planner.py` 与
`tests/srt_processing/test_planner.py`，保留已验收SP-01/02规则；未改core、上游、资产、依赖
或配置，未作Git提交。

### 精确 API

- `plan_subtitles(alignment, translation, *, source_alignment_sha256,
  translation_result_sha256, video_sha256, media) -> PlanningResult`，输入/内容全部为公共DTO。
  结果字段为 `plan`、`findings`、`summary`、`cost`；最后一项精确D39成本仅供调用方验收，
  不写入权威plan或manifest。调用方不能提供任意profile/阈值。
- `validate_plan(plan, alignment, translation) -> None` 重验公共覆盖/文本/speaker/section门禁、
  固定rules身份、容量/7秒、每个原始片段的跨句资格，以及同一时间/断点规则可重建性；不重跑
  DP证明已有plan最优。`analyze_plan(plan, alignment, translation)` 先执行相同验证，返回
  `(findings_tuple, summary)`，供workflow对照持久化report。报告无语义或静音证明。
- `PlanningError(ValueError)` 提供 `.code`：`planning_failed` 或
  `plan_validation_failed`，无合法完整路径绝不返回部分plan。
- `D39Cost` 为按八项声明顺序比较的冻结对象，`.plus()` 精确累加完整前缀成本/断点序列。

### 固定公式、规则与可证明剪枝

- 状态为 `(已消费全局word数量, 当前sentence中文字符位置)`，句尾两侧强制对应并把下一句
  中文位置重置为0。所有边同时向前消费两种正文；跨句各自保存尾/完整中间句/首fragment。
- D39前七项依次累加：应急边界数（中英各自计数）、局部不自然边界数、最终过短cue数、
  `max(0,500*h/d-9)`、`abs(Eprefix*Ztotal-Zprefix*Etotal)/(Etotal*Ztotal)`、
  跨越sentence边界数、cue数。第四/五项使用Fraction；零加权全文无比例证据时第五项为0。
  第八项按整条路径 `(全局word结束位置, 该sentence中文结束字符位置)` 序列比较，不只比末边。
- 普通正常边界表：英文 `. ! ?`、`; :`、`, — – --`、源word间隔>=250ms；中文同类中英文
  标点及顿号；否则为应急。sentence完整末尾是正常锚点。局部保护只检查ASCII首字母大写
  相邻名称、ASCII数字/百分比加固定单位表，以及固定紧密词组表；只计D39第二项，不硬剪枝。
  正常标点的句末/分号/逗号等级记录方法，不加入D39以外的隐藏目标；不保证分号优于逗号。
- 仅创建可达状态字典，按word向前处理；英文42/中文32半单位与7000ms前缀超限后单调停止，
  section、完整非空speaker集合或任意源句gap>=500ms也可安全停止扩展。无CPS/比例窗口剪枝。
- 同一状态只保留字典序最佳前缀：后续候选完全由状态和原始输入决定，时间也由下一未消费词
  锚点决定；前七项可加。到同一状态的严格递增word断点路径不可能互为严格前缀，追加相同
  后缀不会反转第八项顺序，因此该支配剪枝不丢更优完整路径。
- 跨句资格逐fragment使用未延长源词时长/CPS，至少一项原始阅读问题；逐个原始句gap、section
  和完整speaker集合全部校验。`null`原样保存。候选预估、最终物化和复验均调用SP-02同一函数。

### 验证证据

- 独立小文档全路径穷举oracle不调用生产候选/时间/计数/成本函数；7组案例核对全部八项成本
  与完整断点。明确非贪心反例：三个20字符词、各100ms、词gap300ms、中文`甲乙，丙丁戊`；
  DP路径`((1,3),(3,6))`最终过短1条，局部贪心`((2,3),(3,6))`过短2条。
- 候选倒序仍产生相同plan字节、findings和成本；D39每一前项不能被后项反转、完整路径
  tie-break、中文源范围空白/组合序列、重新排序但总长度相同的篡改均有反例。
- 包含tail/full/prefix三fragment、499/500/800ms、每个被跨越gap、全部speaker/null链、section、
  标题排除、源句健康但候选尾片段过短、仅原始中文CPS资格、单word容量/7秒/全文无解、
  高CPS唯一合法路径、ASR segment不影响分段、重验伪造时间/method/rules/容量。
- 3000中文字符的无解单句只调用16个容量内候选构造，验证硬容量稀疏限界而非全文稠密矩阵。
- 实际命令与最终结果记录在下方；未运行网络、媒体程序、ASR或翻译，无未解决阻断。

### 实际验证结果

- `.venv/bin/python -m pytest tests/srt_processing/test_planner.py tests/srt_processing/test_rules.py -q -m "not live"`
  → **110 passed**（planner 56、rules 54）。
- `.venv/bin/python -m pytest tests/ -q -m "not live"`
  → **1040 passed, 5 deselected**（包含并行任务已落盘测试）。
- `git diff --check` → 通过。

## 技术负责人验收（2026-10-21）

已逐段审查候选/稀疏DP/支配剪枝/全文QA，并核对独立oracle、非贪心反例、D39优先级与候选倒序测试；另有独立子agent只读审查及16小图穷举，无阻断。负责人复验 **110 passed**，完整离线 **1040 passed / 5 deselected**，diff check通过。SP-03 accepted，SP-06全部依赖已满足。
