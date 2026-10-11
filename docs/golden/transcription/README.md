# Transcription real golden harness

本目录定义 TR-06 的真实 WhisperX golden 入口、候选 QA policy、人工参考标注格式和不可变运行
记录格式。这里的 JSON 模板只是数据契约，不是已经完成的评测结果。

## 安全门控

`scripts/run_transcription_golden.py` 默认只做本地输入校验。真实运行同时要求：

1. 完成的 plan（不能直接使用带 `<...>` 的模板）；
2. 三类本地样本：CNBC 清晰单人、CNBC 多 speaker、YouTube 老录音/噪声；
3. 每个样本已有 canonical `video.mp4` 和有效 `download_manifest.json`，CNBC 另有
   `chapters.json` 及 SHA-256；
4. 每个样本的人工 reference 至少标注 policy 要求的词时间，并标出全部人工句末；
5. `RUN_TRANSCRIPTION_GOLDEN=1`；
6. `HF_TOKEN`/`HUGGING_FACE_HUB_TOKEN`，或在模型已完整缓存后显式设置
   `HF_HUB_OFFLINE=1`；token 值绝不写入记录；
7. 一个全新的输出 workspace。harness 发现任何 transcription 工件就拒绝运行，且从不启用
   overwrite。

默认 `pytest` 不会调用入口，也不会导入或加载 WhisperX/pyannote 模型。`preflight` 只读取本地
文件、包 metadata 和 ffmpeg 版本：

```bash
.venv/bin/python scripts/run_transcription_golden.py \
  --plan /absolute/path/to/completed-plan.json \
  --preflight-only
```

确认样本授权、磁盘空间、模型下载/缓存和运行成本后，才运行：

```bash
RUN_TRANSCRIPTION_GOLDEN=1 HF_TOKEN='...' \
  .venv/bin/python scripts/run_transcription_golden.py \
  --plan /absolute/path/to/completed-plan.json \
  --record-dir /absolute/path/to/new-record-directory
```

已有完整本地缓存且禁止联网时改用：

```bash
RUN_TRANSCRIPTION_GOLDEN=1 HF_HUB_OFFLINE=1 \
  .venv/bin/python scripts/run_transcription_golden.py \
  --plan /absolute/path/to/completed-plan.json \
  --record-dir /absolute/path/to/new-record-directory
```

每个 sample 产生一个新文件，使用独占创建，已存在同名记录时拒绝覆盖。记录包含：仓库 revision、
WhisperX/pyannote/faster-whisper/alignment/sentence detector 身份、设备和全部结果相关参数；词时间
误差、未对齐/插值比例、官网融合覆盖、冲突类型、句界 precision/recall；耗时、进程峰值 RSS 和
GPU 峰值是否缺测。v1 harness 不在进程内可靠采集非 CPU GPU 峰值，使用 GPU 时必须用平台工具
外部采集，并在人工评审记录中补充；不得把 `null` 当作 0。

## Policy 状态

`qa-policy.v1.json` 是**候选 policy**。阈值已版本化，方便首轮真实评测保持输入不变，但尚无真实
运行记录支持其成为基线。三类样本全部运行、人工检查记录审核且门禁通过前，不得把 TR-06 的
golden 验收标为完成。任何阈值、模型版本或关键参数变动都要创建新 policy 版本，不能改写既有
运行记录。

## 2026-10-08 本机只读盘点

- 可用：`.venv` Python 3.11.16、WhisperX 3.8.5、pyannote.audio 4.0.7、Torch 2.8.0、
  faster-whisper 1.2.1；`/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg` 9.0.1，包含 `ass` 与
  `subtitles` filters。
- 阻塞：仓库内没有 CNBC/YouTube 音视频样本；没有 `HF_TOKEN` 或 token 文件；默认
  Hugging Face/Torch/Whisper cache 目录不存在。
- 因此本次没有运行真实模型、没有联网或下载模型，也没有生成或伪造 golden 结果。
