# 技术任务：transcription WhisperX 词级 forced alignment

- 任务 ID：`TR-03`
- 优先级：`P1`
- 影响模块：`transcription`
- 依赖：`TR-02`
- 被依赖：`TR-04`、`TR-05`、`TR-06`
- 对应决策：[ADR-0001](../decisions/0001-transcription-sentence-level-alignment.md) §7
- 状态：已实现

## 目标

把 raw ASR segments 变成原视频时间轴上的词级 `aligned_asr.json`，显式处理未对齐词并阻止
坏时间轴流入下游。

## 实现范围

- 定义 `ForcedAligner` 端口与 WhisperX alignment adapter；application 不依赖 provider 对象。
- 输出稳定 word/segment ID、表面文本、整数毫秒、`alignment_score` 和 `timing_source`。
- 标点附着相邻 word；不持久化字符级时间。
- 仅对少量、双侧可靠锚定、时间充足且原因可解释的未对齐 word 做插值。
- 插值 word 的 `alignment_score=null`，记录左右锚点和 `timing_source=interpolated`。
- 连续大段未对齐、缺单侧锚点、幻觉、越界、倒退或重叠均明确失败；v1 不自动修复重叠。
- 持久化 `aligned_asr.json`、详细事件、report 更新和相关 cache key。

## 非目标

- 不融合官网逐字稿。
- 不把 alignment score 当 ASR 正确率或跨模型概率。
- 不生成句子或 SRT。

## 验收标准

- exact alignment、数字/符号未对齐、安全插值和不可恢复范围均有离线 fixture。
- `0 <= start_ms < end_ms`、单调、音频边界、文本非空和稳定 ID 有硬校验。
- 每个 raw ASR lexical word 要么可追溯到 aligned word，要么有明确失败/finding，不能静默丢失。
- 插值、未恢复、重叠等产生 ADR 规定的稳定事件并进入汇总。
- cache key 包含 raw ASR hash、alignment model identity 和 interpolation policy。
- fake aligner 可离线测试，默认测试不加载模型。
- `python -m pytest tests/ -q -m "not live"` 全绿。
