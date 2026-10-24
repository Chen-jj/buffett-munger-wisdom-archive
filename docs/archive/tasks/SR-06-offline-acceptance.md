# SR-06 — 独立跨层、对抗与故障注入

- **Status:** accepted
- **Owner:** offline_qa（非SR-05作者的独立开发/测试agent）
- **Depends on:** SR-05 accepted
- **Depended on by:** SR-07

## 范围与验收

只新增独立测试；实现bug报原所有者修复，不在测试任务顺手改生产实现。逐项核ADR第20.1节，真实公共DTO+本地store+ASS codec与fake昂贵端口跨层，制造重签hash后内容/offset/时间/报告/identity篡改，不能仅靠最外层hash错冒充深层防护。全发布点注入故障、manifest-last、旧成功保护、bytes/mtime/clock/编码计数、dry-run/reuse零写。

核架构不跨模块import、无shell/fallback/自动昂贵阶段/文件删除，默认pytest不触发真实工具。开发者跑新增测试和完整`.venv/bin/python -m pytest tests/ -q`；负责人独立复跑并审diff，发现缺陷则退回任务，不削弱ADR。

## 独立只读设计（2026-10-24，保留设计阶段记录）

本节仅记录测试设计。SR-05 尚未 accepted；未新增测试或生产代码，未运行真实工具，未修改
`output/`，未提交 git。待负责人明确放行后，再按实际稳定接口实施以下独立验收。

### 验证边界与假设

- 使用真实公共 DTO、纯 domain 布局重算、`LocalRenderArtifactStore`（以最终实现名为准）和
  `Pysubs2AssCodec`；文件位于 pytest 临时工作区。完整输入链由测试 fixture 显式构造，
  不调用其他功能模块 planner/provider/workflow，也不依赖 SR-05 作者的 fake store。
- 仅 font/measurer、grapheme、probe/tool identity、像素采样、encoder 和 clock 使用确定性
  fake。guard 阻止 subprocess/network 及真实字体读取，证明默认验收不隐式执行外部工具。
- 生产 bug 只报告原所有者修复；测试任务不顺手改生产代码或降低预期。
- 若注入发生在 manifest 构造之前，失败应为 clock=0；若已经进入最后 manifest 构造，后续
  stage/readback/publish 失败允许 clock=1，不把晚期失败误报为违反 dry-run/reuse 零 clock。

### 跨层与零副作用矩阵

1. fresh `planned/render`、`succeeded/render`、`planned/reuse`、`reused/reuse`；真实 JSON/ASS
   回读和四份正文 evidence 与最终 manifest 一致。独立 handler 实例复用；正式五文件和上游
   文件 bytes/size/mtime_ns 快照不变，store 写入、clock、pixel、encode 调用均符合状态语义。
2. fresh dry-run 不能创建 workspace/staging；已有套件 dry-run 不更新 mtime；显式
   dry-run+overwrite 只规划 render，不执行像素或编码、不写诊断。reuse 不为展示而伪造 argv。
3. 五份正式输出分别测试部分、空文件、损坏、错 generation 与悬空 symlink 占位。默认
   conflict 不写入、不调用 clock/pixel/encode；overwrite 只替换 rendering 规范输出。
4. 有效的新 input/profile/font/tool 身份与旧套件不符为 conflict；无效上游链为 input_invalid。
   旧成功套件下的字体、布局、ASS、像素、编码、probe 失败不得以 failed report 覆盖旧成功
   report/manifest，输入和未发布的旧输出保持原样。
5. fake encoder 在编码期间修改一个已验证上游文件；发布前 fingerprint 复核必须拒绝，
   无成功 manifest。测试仅变更临时 fixture，明确区分被注入修改与生产造成的额外写入。

### 重签后仍需深层拒绝

每个反例先重算所有受影响外层 size/SHA，使测试确实穿过外层 evidence gate，再断言稳定
错误与零写，而不是仅断言某层 hash 不匹配。

- 上游：词/句/译文 fragment offset、speaker/section、原 cue 毫秒、alignment 与 translation
  绑定、transcription cache/record 内部链、成功 report 摘要跨层不一致。
- 既有 render plan：选择 DTO 可解析、正文可完全重建但非确定性胜出的合法断点，或伪造仍
  落在安全区域内的测量宽高/预计 bbox；同步重建 canonical ASS、report 摘要和 manifest
  evidence，仍必须由真实 domain 重算拒绝，不能仅以 plan JSON 与 ASS 不符拒绝。
- 既有 report：修改像素中点、行数、安全区域 bbox、font/styles 标志、cue 顺序/完整性或
  summary；同步重签 report evidence 与 manifest summary，仍必须机械交叉检查拒绝。
- ASS：在正确 plan 下加入非 canonical header/style/controls、纯文本控制注入或视觉断点
  变化，重签 ASS evidence 后仍由真实 codec round-trip 拒绝。原文包含反斜线、大括号、
  `\\N`、HTML 类文本的正常用例应在真实 codec 下保真，不靠将这些文本一律拒绝过关。

### 全发布点故障与残留

分别在 staging 创建、ASS stage/readback、pixel、plan stage/readback、encode、staged probe/
媒体 QA、report stage/readback、四份正文 evidence、输入再验、plan/ASS/video/report 逐项
publish、clock、manifest 构造/stage/readback/publish 注入故障。使用真实 local store 的
最小包装或文件操作 monkeypatch 记录实际顺序，不用 fake store 自证发布行为。

- 成功 manifest 只允许最后发布；在任何早期失败后均不可被视为完整成功或 reused。
- 允许已原子发布的正文留下部分新代，但下一次默认调用必须 conflict；旧 manifest 不能
  使新旧混代通过。失败不能通过删除残留、回滚昂贵资产或覆盖旧成功 report 掩盖事实。
- staged 残留保留；诊断失败不能覆盖原错误类别，公共错误文案不泄漏路径/命令/stderr。
- 无旧套件时允许规范 failed report；该 report 本身使下一次默认调用 conflict，必须显式
  overwrite；dry-run 和 conflict 路径始终不得写 failed report。

### 架构 AST 与默认离线验收

- 检查 rendering domain/application 不 import concrete adapter、Pillow/pysubs2/subprocess
  或其他功能模块内部；interfaces 不持布局/复用/媒体业务规则；生产进程仅用共享适配器。
- 检查生产渲染路径无 shell、硬件编码、`-y`、fallback、自动 ASR/provider/planner 或文件
  删除；测试 guard 与现有 argv 单元测试共同覆盖，避免仅靠字符串搜索作架构证明。
- 实施后先运行独立新增测试，再运行完整 `.venv/bin/python -m pytest tests/ -q`，保存
  命令/计数/耗时与 `git diff --check`；负责人独立复跑通过后才可标 accepted、放行 SR-07。

## 独立开发交付（2026-10-24；待负责人验收）

SR-05 accepted 后负责人已明确放行实施。只新增以下四份独立测试/fixture 文件，未改生产实现、
SR-05 作者测试、共享状态或 `output/`，未删除文件或提交 git：

- `tests/subtitle_rendering/acceptance_support.py`：独立本地证据链和公开 DTO fixture，真实
  `LocalRenderingArtifactStore` 的可观测子类、真实 `Pysubs2AssCodec`、纯 domain 和完整
  grapheme adapter；昂贵 font/probe/pixel/encoder/clock 明确注入 fake。没有复用 SR-05 的
  `WorkflowCase` 或 fake store；公用契约 fixture 只提供 DTO 数据，逐项重签和交叉核验。
- `tests/subtitle_rendering/test_acceptance_cross_layer.py`：真实发布/新 handler 复用、strict
  dry-run、全部五输出损坏/部分/悬空链接、全部18上游文件破损、合法新身份先于无解布局
  conflict、深层上游混代、非胜出合法视觉断点/测量/bbox重签、report像素和摘要重签、ASS
  重签与原文显示控制保真、显式 overwrite 不改 symlink 目标。
- `tests/subtitle_rendering/test_acceptance_faults.py`：真实 mkdir、stage、两次 readback、
  staged/published evidence、四正文及 manifest 每个 publish 故障；clock/manifest构造、
  staged及post-rename实际损坏、昂贵阶段失败旧成功保护、有界诊断失败、编码期输入变更。
- `tests/subtitle_rendering/test_acceptance_architecture.py`：AST 验证分层/跨模块边界、无私有
  shell runner/自动删除/硬件编码，handler 仅调 execute，renderer 使用共享 argv 进程端口。

关键深层反例中，变更后的 plan/public report/manifest 均可通过公共 DTO 交叉验证，canonical
ASS 也可真实 encode/validate；全部外层 size/SHA 已重签后，workflow 仍因独立确定性重算而
拒绝。report 中点/行数/安全范围/字体/样式/完整性/summary 与捏造 warning 也在重签后拒绝。
各只读场景同时检查整个临时树（含 staged 残留和 symlink）的 bytes/mtime 与写端口计数，
不是仅断言最终 status。

commit-point 已按负责人批准口径实施：manifest rename 成功后回执或最终读回异常，当前调用
返回 publication_failed 但不删除或回滚已完成工件；下一调用须通过整套证据零写 reused。
真正 post-commit 内容损坏则下一调用 artifact_conflict。晚期 clock/manifest 故障允许已调用
clock一次；dry-run/reuse和早期失败仍零调用。失败 report 不能替换旧成功 report；已合法发布
的新**成功** report不为回滚旧代而删除。

### 开发者验证

```bash
.venv/bin/python -m pytest tests/subtitle_rendering/test_acceptance_cross_layer.py \
  tests/subtitle_rendering/test_acceptance_faults.py \
  tests/subtitle_rendering/test_acceptance_architecture.py -q
# 269 passed

.venv/bin/python -m pytest tests/ -q
# 2559 passed / 5 skipped

git diff --check
# passed
```

本轮未发现确定的生产缺陷，未向原所有者要求修生产代码。首次 AST 测试曾误把 renderer 中
显式拒绝 `-y`/`-shortest` 的 guard 字面值当成启用参数；已修正测试只检查命令构造方法，
保留生产拒绝 guard。完整离线通过不代表真实系统字体/libass/样片或出版级质量验收；SR-07
仍须由负责人技术验收本任务后单独放行。

## 负责人验收（2026-10-24 10:51 CST）

已审独立fixture/真实LocalStore与ASS、重签反例先自验合法再检查深层拒绝、全发布点故障与commit-point、离线/架构guard。负责人独立定向269 passed、完整2559 passed / 5 skipped（12.10s），diff check通过。SR-06 accepted，放行SR-07；没有把fake昂贵端口的绿色结果视为真实样片已通过。
