# SP-02 — 固定profile、文本计数与纯时间规则

- **Status:** accepted
- **Owner:** planner 子开发 agent；仅技术负责人标记accepted
- **Module:** srt_processing/domain
- **Decision coverage:** ADR-0003 §6、§9、§11、§14.4
- **Depends on:** SP-01
- **Depended on by:** SP-03

## 范围与验收标准

- 版本化profile稳定序列化/hash；中文布局空白折叠、组合序列边界、中文整数半宽计数与英文独立计数，固定Unicode边缘分类表。

- 同一个纯函数负责时间预估与物化：G=ceil(2000*q/p)，最短834、最长7000、中文9CPS/英文17CPS，500ms共享额度、媒体/下一语音边界与原始gap一次性分类；英文CPS只报告。

- 完整覆盖ADR §14.4矩阵，包括800/300/40/0/负gap、7秒/末条/媒体限制、非整数fps、长gap延长后不二次收紧。测试固定公式，domain不调用外部工具。

## 验证与交接

```bash
.venv/bin/python -m pytest tests/srt_processing/test_rules.py -q -m "not live"
git diff --check
```

记录实际命令/结果、API与未解决问题，再交负责人复验。先读根与模块AGENTS，保留用户已有ADR/指南修改；不得删除文件/资产，不作无关重构。

## 开发交接（2026-10-21）

实现仅新增 `src/srt_processing/domain/rules.py` 与
`tests/srt_processing/test_rules.py`；未修改公共 core、上游或资产。SP-03 尚未开工。

### 公开 API 与固定公式

- `PROFILE: SubtitleProfileDTO` 是唯一代码内参数档，包含全部17字段及250ms合理停顿阈值；
  `rules_identity()` 返回公共 `SubtitleRulesDTO`，完整参数由公共 sorted compact UTF-8 JSON
  编码计算 SHA-256。没有调用方 profile/阈值选项。
- `english_characters(text)` 独立计算非空白普通字符；`chinese_half_units(text)` 使用整数
  半字符单位。ASCII可见字符、冻结Unicode14 Latin字母/十进制数字、已分配半角日韩字符计1；
  全角Latin/数字、CJK、emoji及其他未知字符计2。冻结组合mark、VS、ZWJ、emoji modifier及
  布局空白计0。运行时不查询Unicode数据库。组合边界/布局规范直接消费SP-01机械helper。
- `two_frame_gap_ms(p,q) = (2000*q+p-1)//p`；不猜测无效帧率。
- `adjust_cue_timing(*, start_ms, base_end_ms, chinese_units, english_count,
  usable_duration_ms, gap_threshold_ms, next_start_ms)` 返回不可变 `TimingResult`，含
  `end_ms`、公共 `timing_adjustment`、`too_short`、精确Fraction中英CPS超额、`unclosed_gap`。
  同一纯函数供后续DP预估及物化，不增加第二套时间逻辑。
- 中文需求时长为 `max(834, ceil(500*chinese_units/9))`；读取/短gap需求取max而非相加；
  同时受500ms、7秒、媒体末尾及下一源词减G限制。原始0..G gap原样保留；原始长gap即使
  延长后剩300ms，也不二次分类/收紧或报告短gap失败。英文CPS只报告不延长。
- CPS超额精确为 `max(0, 500*h/d - 9)` 与 `max(0, 1000*e/d - 17)`；无硬CPS上限。

### 实际验证

- `.venv/bin/python -m pytest tests/srt_processing/test_rules.py -q -m "not live"`
  → **54 passed**，覆盖ADR §14.4完整矩阵、固定Unicode边缘、低帧率/非整数帧率及无效输入。
- `.venv/bin/python -m pytest tests/ -q -m "not live"`
  → **767 passed, 5 deselected**（包含共享工作区同时落盘的其他任务测试）。
- `git diff --check` → 通过。未运行媒体工具、网络、ASR或翻译；无未解决阻断。

## 技术负责人验收（2026-10-21）

已审查固定profile/Unicode计数、整数及Fraction公式、一次性gap分类/共享额度和完整回归矩阵；独立规则测试 **54 passed**，完整离线 **767 passed / 5 deselected**，diff check通过。SP-02 accepted，放行SP-03。
