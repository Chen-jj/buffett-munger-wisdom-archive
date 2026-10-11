# Transcription real integration

当前 transcription 模块只维护 CNBC 真实 live integration，不维护 reference-based Golden Live。
未来 acquisition → rendering 的完整跨模块连通性测试归 orchestration 模块。

## 测试入口

```text
tests/transcription/test_integration_live.py
```

默认 pytest 会跳过 live 测试。真实执行需要本机已登录 Hugging Face，或模型已经完整缓存并显式
启用离线模式；还需要 Python 3.11、ffmpeg-full 和 NLTK `punkt_tab`。

```bash
.venv/bin/hf auth whoami
.venv/bin/python -m nltk.downloader punkt_tab
RUN_TRANSCRIPTION_INTEGRATION=1 \
  .venv/bin/python -m pytest tests/transcription/test_integration_live.py -q -s
```

## 从空 output 开始

未设置 `TRANSCRIPTION_INTEGRATION_PLAN` 时，live 测试会使用
`scripts/prepare_cnbc_transcription_integration.py` 准备 CNBC 2000 上午场第 3 节 `11:48`～`21:40`：

- acquisition crawler 抓取页面、元数据和结构化官网逐字稿；
- media resolver 解析 CNBC HLS，下载所需 segments，并用 ffmpeg 生成 592 秒 `video.mp4`；
- artifact writer 生成 canonical `meta.json`、`media_ref.json`、`transcript.txt`、`chapters.json` 和
  `download_manifest.json`；
- 生成本次测试使用的 `integration_sample.json` 和 `integration-plan.json`。

这是 live fixture 准备，不是 orchestration 驱动的完整上游管线测试。测试输入准备完成后，才运行
真实 transcription。媒体和模型不提交 Git。

## 唯一 workspace

所有本次输入、中间产物和最终产物统一位于：

```text
output/transcription-integration/cnbc_2000_morning/
```

不再使用原来的 `transcription-golden-inputs`、`transcription-golden-calibration-inputs` 或
`transcription-golden-smoke` 目录。

测试解析并验证：

```text
video.mp4 + download_manifest.json + chapters.json
  → audio.wav
  → vad.json
  → raw_asr.json
  → aligned_asr.json
  → transcript_fusion.json
  → source_alignment.json
```

同时验证 `transcription_manifest.json`、`transcription_report.json` 和 JSON Lines
`transcription.log`。首次从空 workspace 运行必须没有 transcription cache hit；再次运行必须命中
`audio`、`vad`、`raw_asr`、`aligned_asr`、`transcript_fusion` 和 `source_alignment` 六层缓存。

如需使用另一个隔离目录，可设置：

```bash
RUN_TRANSCRIPTION_INTEGRATION=1 \
TRANSCRIPTION_INTEGRATION_OUTPUT_ROOT=/absolute/path/to/empty-output-root \
  .venv/bin/python -m pytest tests/transcription/test_integration_live.py -q -s
```

只有已经自行准备兼容 plan 时才需要设置 `TRANSCRIPTION_INTEGRATION_PLAN`。

## 当前验证结果

2026-10-11 从空 `output/` 实测：首次运行约 5 分钟并生成全部上游 fixture 与 transcription 工件；
第二次运行约 2 秒，六层 transcription cache 全部命中。最终 report status 为 `succeeded`，error 为
0。该测试验证真实管线连通性和工件契约，不把输出声明为人工真值。
