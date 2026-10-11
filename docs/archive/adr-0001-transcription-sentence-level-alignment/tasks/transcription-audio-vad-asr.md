# 技术任务：transcription 音频提取、pyannote VAD 与 WhisperX ASR

- 任务 ID：`TR-02`
- 优先级：`P1`
- 影响模块：`transcription`
- 依赖：`AC-01`、`TR-01`
- 集成依赖：`MD-01` 完成后才能把真实 `media_download` 工件作为已验证输入
- 被依赖：`TR-03`、`TR-06`
- 对应决策：[ADR-0001](../decision.md) §6
- 状态：已实现

## 目标

把经过验证的 `video.mp4` 转换为持久化 `audio.wav`、`vad.json` 和 `raw_asr.json`，并保证
所有处理区间可映射回原视频绝对时间轴。

## 实现范围

- domain/application 定义 audio、VAD region、ASR segment、配置和端口；不导入 provider。
- ffmpeg adapter 生成 16 kHz、mono、signed 16-bit PCM `audio.wav`，记录版本和参数。
- WhisperX adapter 使用 pyannote VAD、Whisper `large-v3`、`language=en`、
  `task=transcribe`；正式 profile 质量优先。
- 持久化 VAD region、padding、cut-and-merge 到原视频的时间映射及 raw ASR segments。
- 为开发测试提供显式小模型 profile，但不得与正式 profile 共用完成状态或缓存键。
- 所有文件经 canonical workspace 解析、checksum 和原子写；默认不覆盖成功昂贵工件。
- 通过 `TR-01` 发出阶段事件和汇总。

## 非目标

- 不做 forced word alignment、官网逐字稿融合或句界恢复。
- 不做 speaker diarization。
- 不执行真实模型的默认离线测试。

## 验收标准

- fake extractor/VAD/ASR 可离线跑通完整 application 用例。
- ffmpeg 命令计划精确约束目标音频格式，并可在不运行 ffmpeg 时测试。
- VAD 合并后的每段音频都能无损映射回原视频毫秒区间。
- 固定英文、transcribe task、正式/开发 profile 和 cache key 有测试。
- 输入 manifest/checksum 无效时在调用 ffmpeg/WhisperX 前失败。
- cache hit 不重复调用昂贵 provider；配置或模型变化使缓存 stale。
- 未显式授权时不覆盖 `audio.wav`、`vad.json` 或 `raw_asr.json`。
- provider 版本/模型首次下载行为在 README 或实现说明中写清，但离线测试不联网。
- `python -m pytest tests/ -q -m "not live"` 全绿。
