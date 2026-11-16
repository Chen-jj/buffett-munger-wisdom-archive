# Transcription 测试指南

2026-11-06：模块目录仅保留隔离单元/纯契约测试。跨层工作流及真实写盘观察测试位于
`tests/orchestration/integration/offline/transcription/`，ASR真实场景唯一入口为
`tests/orchestration/integration/live/transcription/test_cnbc_transcription_live.py`。

默认验证：`.venv/bin/python -m pytest tests/ -q`；无网络、ASR、真实FFmpeg、provider。
运行真实ASR需仓库依赖、ffmpeg-full、yt-dlp及已缓存或明确可访问的WhisperX/pyannote模型。
完整真实集成使用NB-08的full_fresh；仅测真实转录时：

```bash
PATH="$PWD/.venv/bin:/opt/homebrew/opt/ffmpeg-full/bin:$PATH" \
RUN_ORCHESTRATION_INTEGRATION=1 ORCHESTRATION_INTEGRATION_SCENARIOS=asr \
.venv/bin/python -m pytest tests/orchestration/integration/live/transcription/test_cnbc_transcription_live.py -q -s
```

显式开启后缺预条件失败。可设`ORCHESTRATION_ASR_OUTPUT_ROOT`指定此前不存在的持久目录；
默认`output/orchestration-integration/NB08-asr-only/`。旧env不触发新测试。不清理或覆盖旧资产。

ASR场景走公开生产入口获取父媒体并派生CNBC 2000上午场选择窗35:01–45:24（绑定章节6/7，裁切末尾比官网章界多1秒），同源资产
`cnbc:2000:morning-ch6-7`；不依赖先跑其他测试、私有裁切或旧output。
验证全部工件、双section连续覆盖、章界verified、report无error及六层命中零写/bytes/mtime保持。
历史HLS准备函数仅余纯fixture契约测试，不能执行旧媒体准备。技术测试不代表核听或出版验收。
