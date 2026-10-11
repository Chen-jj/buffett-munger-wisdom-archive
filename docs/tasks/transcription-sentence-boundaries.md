# 技术任务：transcription 本地句界恢复与 source_alignment

- 任务 ID：`TR-05`
- 优先级：`P2`
- 影响模块：`transcription`、`archive_core` 公共 DTO 的消费
- 依赖：`TR-03`、`TR-04`
- 被依赖：`TR-06`、translation、srt_processing 后续任务
- 对应决策：[ADR-0001](../decisions/0001-transcription-sentence-level-alignment.md) §9、§10
- 状态：已实现 + 离线测试（2026-10-08）

## 目标

从融合后的 timed words（或无官网路径的 aligned ASR words）恢复完整英文 sentence，并通过
硬门禁发布唯一 canonical `source_alignment.json`。

## 实现范围

- 高可信官网区域采用经例外规则校验的 `. ? !` 句界。
- speaker 变化强制结束 sentence；paragraph 变化只作弱信号。
- YouTube/未匹配区采用 Whisper 标点、本地 sentence detector、词间停顿与 ASR segment
  弱提示；v1 不引入 NeMo 或 LLM。
- 处理缩写、小数、姓名首字母、问句、跨 ASR segment 和一个 segment 多句等情况。
- 不因字幕行宽/阅读速度机械切句；异常无标点长文本只按版本化 fallback policy 处理。
- sentence 保存首尾 word ID、冗余整数毫秒、text、可选 speaker、text source、
  boundary source/status。
- 使用枚举式 provenance，不生成未经校准的浮点 confidence。
- 对 `source_alignment.json` 执行公共 DTO 全部硬不变量并原子发布。

## 非目标

- 不翻译。
- 不规划 subtitle cue，不生成 SRT。
- 不猜测 YouTube speaker。
- 不实现字幕阅读速度或行宽规则。

## 验收标准

- 官网标点、speaker change、paragraph 弱信号、Whisper 标点+停顿和 fallback 均有测试。
- 多 ASR segment 合成一句、单 segment 拆成多句有测试。
- 每个有效 word 恰好被一个 sentence 连续覆盖；无缺失、重复或跨 speaker sentence。
- sentence 冗余时间严格等于首尾 word 时间，text 可按公共规则由 words 重建。
- `speaker_label` 有值和 `null` 均可往返；无可靠来源时不会猜测。
- fallback 超过 policy 门禁时失败并保留诊断，但不发布 canonical。
- `source_alignment.json` 是本任务唯一 canonical 内容输出；无 SRT 产物。
- `python -m pytest tests/ -q -m "not live"` 全绿。

## 实现结果

- `transcription.domain.sentences` 固定 `sentence-boundary.v1` policy、标点例外与 fallback
  publication gate；缩写、小数和姓名首字母不会被误判为官网句末。
- `SentenceBoundaryService` 严格验证 official fusion 或 aligned-ASR identity 两条输入路径，综合
  speaker、paragraph、ASR punctuation、本地 detector、pause 与 ASR segment 弱信号，并为每句
  写入枚举式 boundary provenance。
- `RuleBasedSentenceBoundaryDetector` 是默认纯本地、无网络、无模型下载的 detector adapter；端口
  可由后续 golden 评测替换，但 provider identity 和完整 policy 都进入 sentence cache key。
- canonical 写入前构造并反序列化 `SourceAlignmentDTO`，由公共 DTO 执行全部硬不变量；fallback
  超门禁会发出逐句诊断与失败事件，不写 `source_alignment.json`。
- 成功 cache record 名为 `source_alignment`；命中必须同时验证 cache key、canonical path、size、
  SHA-256 与可解析公共 DTO。规则变化只使句界与 canonical 输出 stale，替换需要显式 overwrite。
- 离线测试覆盖官网标点例外、speaker 强制边界、paragraph 弱信号、ASR 标点+pause、detector、
  fallback 门禁、跨 segment 单句、单 segment 多句、official/identity 消费、DTO 发布、事件与缓存。

验证结果（2026-10-08）：

```text
python -m pytest tests/test_transcription_sentence_boundaries.py -q
13 passed

python -m pytest tests/ -q -m "not live"
311 passed, 3 deselected
```
