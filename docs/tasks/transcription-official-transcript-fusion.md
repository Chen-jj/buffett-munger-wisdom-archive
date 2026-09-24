# 技术任务：transcription 本地融合官网英文逐字稿

- 任务 ID：`TR-04`
- 优先级：`P2`
- 影响模块：`transcription`
- 依赖：`TR-03`、`AQ-01`
- 被依赖：`TR-05`、`TR-06`
- 对应决策：[ADR-0001](../decisions/0001-transcription-sentence-level-alignment.md) §8
- 状态：待实现

## 目标

把 `aligned_asr.json` 与可选结构化 `chapters.json` 做本地、单调、可解释的融合，利用官网
拼写/标点而不把未经音频验证的编辑文字强贴到时间轴。

## 实现范围

- 从公共 DTO 读取 chapter、paragraph、可选 speaker；不解析 CNBC 专用字符串。
- 对 ASR/official token 建立保留 surface 的规范化表示，覆盖大小写、标点、数字、百分比、
  货币、连字符和 contraction 的版本化规则。
- 先寻找顺序一致的 n-gram 锚点，再在局部窗口做动态规划。
- 实现 exact、normalized exact、substitution、ASR-only、official-only、one-to-many 和
  many-to-one 映射。
- 保留已声学对齐的 ASR-only words。
- official-only token 只有在双侧锚定窗口内局部 forced alignment 成功后才能加入；失败时
  排除并记录。
- 对已证明语义等价的一对多/多对一使用单 token 一侧显示文字，并按 ADR 合并/继承时间。
- 持久化 `transcript_fusion.json`，记录全部映射、未采用内容、取舍和事件。
- 没有 `chapters.json` 时提供明确的 identity/no-official 路径，供 `TR-05` 使用。

## 非目标

- 不使用 LLM。
- 不生成 sentence 或 subtitle cue。
- 不根据 token 数量盲目认定语义等价。
- 不把 chapter title、speaker label 或舞台说明当 spoken words。

## 验收标准

- Buffett/Munger/See's、年份、百分比、货币、contraction 等 fixture 覆盖所有映射类型。
- ASR-only 被保留并 warning；official-only 恢复和排除都有局部声学 fake 测试。
- 无可靠单调双侧锚点的大区域明确失败，不发布伪造映射。
- 每个输出 timed word 保留完整 `asr_word_ids`、`official_token_ids`、match/text/timing source。
- surface adjustment、替换、折叠、保留、恢复、排除和失配均产生稳定详细事件；CLI 过滤由
  `TR-01` 验证。
- 官网 checksum 或 normalization/matching policy 变化使 fusion cache stale，但不使 ASR/
  alignment cache stale。
- `python -m pytest tests/ -q -m "not live"` 全绿。
