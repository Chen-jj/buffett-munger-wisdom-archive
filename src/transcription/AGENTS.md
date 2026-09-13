# transcription AGENTS.md

## 模块定位

`transcription` 负责音频提取、ASR、句级时间戳，以及英文字幕生成。

## 职责

- 从已下载媒体中提取或定位音频。
- 运行 ASR，直接产出带句级时间戳的英文分段。
- 生成保时序的英文 SRT 与句级对齐元数据。
- 模型/设备选择保持显式且可复现。

## 分层规则

- `domain/`：音频资产、ASR 句级分段、句级时间、文本融合策略。
- `application/`：extract-audio、transcribe-session、fuse-transcript-text、generate-english-srt 用例。
- `infrastructure/`：ffmpeg 音频提取、faster-whisper/WhisperX 适配器、模型加载、临时文件处理。
- `interfaces/`：CLI 命令处理器、进度报告、面向 orchestration 的转写摘要。

## 技术方向

- 把 Whisper/Faster-Whisper/WhisperX 视为可替换的提供方。
- 长时模型工作不得放进 CLI 处理器。
- 持久化足够元数据，以解释某个 SRT 由哪个模型与哪些设置产出。
