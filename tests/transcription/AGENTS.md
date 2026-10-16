# Transcription 测试指南

## 默认验证

- 使用 Python 3.11。
- 默认测试必须离线运行，不访问网络，不加载 WhisperX/pyannote 模型：

  ```bash
  python3.11 -m pytest tests/transcription/ -q -m "not live"
  ```

- 除非用户明确要求真实集成验证，否则不要运行 `live` 测试。

## CNBC 真实集成测试

入口：`tests/transcription/test_integration_live.py`。

运行前需要：

- Python 3.11 依赖已安装；
- `ffmpeg-full` 和 `ffprobe` 可用；
- NLTK `punkt_tab` 已安装；
- 本机已登录 Hugging Face，或所需模型已完整缓存并启用离线模式。

```bash
.venv/bin/hf auth whoami
.venv/bin/python -m nltk.downloader punkt_tab
RUN_TRANSCRIPTION_INTEGRATION=1 \
  .venv/bin/python -m pytest tests/transcription/test_integration_live.py -q -s
```

未设置 `TRANSCRIPTION_INTEGRATION_PLAN` 时，测试会调用
`tests/transcription/live_fixture.py`，准备 CNBC 2000 上午场连续第 6、7 节
`35:01`～`45:24` 的 canonical 上游输入，再运行真实 transcription。这只是 live fixture
准备，不是 orchestration 驱动的完整 acquisition → rendering 集成测试。

默认 workspace：

```text
output/transcription-integration/cnbc_2000_morning/
```

可用 `TRANSCRIPTION_INTEGRATION_OUTPUT_ROOT` 指定另一个隔离 output root；只有已自行准备兼容
plan 时才设置 `TRANSCRIPTION_INTEGRATION_PLAN`。媒体、模型和运行产物必须留在 gitignore 的
output workspace，不得提交。真实验收必须从空的 integration workspace 开始；若默认 workspace
已经存在，按仓库安全规则取得用户明确确认后才能清理，不能复用旧样本或静默覆盖。

## Live 验收

测试必须验证从 `video.mp4`、`download_manifest.json` 和 `chapters.json` 生成：

```text
audio.wav
vad.json
raw_asr.json
aligned_asr.json
transcript_fusion.json
source_alignment.json
transcription_manifest.json
transcription_report.json
transcription.log
```

- 从空 workspace 首次运行不得命中 transcription cache。
- 同一次测试会对该 workspace 再运行一次，必须命中 `audio`、`vad`、`raw_asr`、
  `aligned_asr`、`transcript_fusion` 和 `source_alignment` 六层缓存，且 canonical checksum
  保持不变。
- `source_alignment.json` 必须包含两个按顺序、连续且完整覆盖 sentences 的 section，标题依次为
  `"There's nothing magic about a one-year period"` 与
  `We want a "mathematical edge in every transaction"`。第 6→7 节交界必须由 verified 句界闭合；
  若原位置没有更直接的 verified 信号，则应为 `document_section_change`。
- report 必须为 `succeeded` 且 error 为 0。
- 该测试验证真实管线连通性和工件契约，不把输出声明为人工真值，也不维护 reference-based
  Golden Live。
