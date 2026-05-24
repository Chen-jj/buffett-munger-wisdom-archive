"""
Step 2: 英文字幕时间轴对齐
使用 faster-whisper 做英文转写，再用 WhisperX forced alignment 生成精确时间轴。
默认直接输出 ASR+forced-alignment 的英文 SRT，不再尝试把网页 transcript 硬映射到音频上。
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import yaml


NORMALIZE_FIXES = {
    "â\x80\x94": "—",
    "â\x80\x99": "’",
    "â\x80\x9c": "“",
    "â\x80\x9d": "”",
    "â\x80\xa6": "…",
    "â\x80\x93": "–",
    "Â": "",
}


def load_config():
    config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def extract_audio(media_path: Path, audio_path: Path):
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-i", str(media_path),
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", str(audio_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg audio extraction failed: {result.stderr}")
    return audio_path


def clean_text(text: str) -> str:
    for bad, good in NORMALIZE_FIXES.items():
        text = text.replace(bad, good)
    return text.strip()


def format_timestamp(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds % 1) * 1000))
    if millis == 1000:
        secs += 1
        millis = 0
    if secs == 60:
        minutes += 1
        secs = 0
    if minutes == 60:
        hours += 1
        minutes = 0
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def write_srt_segments(segments: list[dict], srt_path: Path):
    lines = []
    for i, seg in enumerate(segments, 1):
        lines.append(str(i))
        lines.append(f"{format_timestamp(seg['start'])} --> {format_timestamp(seg['end'])}")
        lines.append(seg['text'])
        lines.append("")
    srt_path.parent.mkdir(parents=True, exist_ok=True)
    srt_path.write_text("\n".join(lines), encoding="utf-8")


def transcribe_with_faster_whisper(audio_path: Path, model_name: str, device: str, compute_type: str, *, local_files_only: bool = False, beam_size: int = 2) -> list[dict]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("faster-whisper is not installed. Precise subtitle timing requires faster-whisper ASR plus WhisperX forced alignment.") from exc

    print(f"  → Loading faster-whisper model: {model_name} on {device}", flush=True)
    model = WhisperModel(model_name, device=device, compute_type=compute_type, local_files_only=local_files_only)

    print(f"  → Transcribing with faster-whisper (beam={beam_size})...", flush=True)
    segments, info = model.transcribe(
        str(audio_path),
        language="en",
        vad_filter=False,
        condition_on_previous_text=False,
        beam_size=beam_size,
        word_timestamps=False,
    )

    result = []
    for seg in segments:
        text = clean_text(seg.text or "")
        if not text:
            continue
        result.append({"start": float(seg.start), "end": float(seg.end), "text": text})

    language = getattr(info, "language", "en")
    probability = getattr(info, "language_probability", 0.0)
    print(f"  → ASR language: {language} ({probability:.3f})", flush=True)
    print(f"  → ASR segments: {len(result)}", flush=True)
    return result


def aligned_segments_to_srt_segments(aligned_segments: list[dict]) -> list[dict]:
    precise = []
    prev_end = 0.0
    for seg in aligned_segments:
        text = clean_text(seg.get("text", ""))
        start = float(seg.get("start", 0.0) or 0.0)
        end = float(seg.get("end", 0.0) or 0.0)
        if not text:
            continue
        start = max(start, prev_end)
        end = max(end, start + 0.05)
        precise.append({"start": start, "end": end, "text": text})
        prev_end = end
    if not precise:
        raise RuntimeError("WhisperX returned no aligned subtitle segments")
    return precise


def align_audio_with_whisperx(audio_path: Path, srt_path: Path, config: dict) -> Path:
    whisperx_config = config.get("whisperx", {})
    model_name = whisperx_config.get("model", "large-v3")
    device = whisperx_config.get("device", "cpu")
    compute_type = whisperx_config.get("compute_type", "int8")
    local_files_only = bool(whisperx_config.get("local_files_only", False))
    beam_size = int(whisperx_config.get("beam_size", 2))

    if not audio_path.exists():
        raise FileNotFoundError(f"Audio not found: {audio_path}")

    try:
        import whisperx
    except ImportError as exc:
        raise RuntimeError("WhisperX is not installed. Precise subtitle timing requires WhisperX forced alignment.") from exc

    asr_segments = transcribe_with_faster_whisper(
        audio_path,
        model_name=model_name,
        device=device,
        compute_type=compute_type,
        local_files_only=local_files_only,
        beam_size=beam_size,
    )

    print("  → Loading WhisperX alignment model...", flush=True)
    audio = whisperx.load_audio(str(audio_path))
    model_a, metadata = whisperx.load_align_model(language_code="en", device=device, model_cache_only=local_files_only)

    print("  → Running WhisperX forced alignment...", flush=True)
    aligned = whisperx.align(asr_segments, model_a, metadata, audio, device, return_char_alignments=False)
    precise_segments = aligned_segments_to_srt_segments(aligned["segments"])
    write_srt_segments(precise_segments, srt_path)
    print(f"  ✅ Precise alignment complete: {len(precise_segments)} subtitle segments", flush=True)
    print(f"  ✅ Output SRT: {srt_path}", flush=True)
    return srt_path


def align_media_with_whisperx(video_path: Path, output_dir: Path, config: dict, *, audio_path: Path | None = None, srt_path: Path | None = None) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    if audio_path is None:
        audio_path = output_dir / "audio.wav"
    if srt_path is None:
        srt_path = output_dir / "english.srt"

    if audio_path.exists():
        print(f"  → Reusing audio: {audio_path}", flush=True)
    else:
        print(f"  → Extracting audio from video: {video_path}", flush=True)
        extract_audio(video_path, audio_path)

    return align_audio_with_whisperx(audio_path, srt_path, config)


def align_year(year: int, config: dict | None = None):
    if config is None:
        config = load_config()

    output_dir = Path("output") / str(year)
    metadata_path = output_dir / "metadata.json"
    if not metadata_path.exists():
        print(f"❌ No metadata found for {year}. Run step0_crawl first.")
        return

    with open(metadata_path, encoding="utf-8") as f:
        metadata = json.load(f)

    for session_name in metadata["sessions"]:
        sess_dir = output_dir / session_name
        video_path = sess_dir / "video.mp4"
        audio_path = sess_dir / "audio.wav"
        srt_path = sess_dir / "english.srt"

        if srt_path.exists():
            print(f"  ⏩ SRT already exists: {srt_path}")
            continue
        if not video_path.exists():
            print(f"  ❌ Video not found: {video_path}. Run step1_download first.")
            continue

        print(f"🎯 Aligning {year} {session_name}...", flush=True)
        align_media_with_whisperx(video_path, sess_dir, config, audio_path=audio_path, srt_path=srt_path)


def main():
    parser = argparse.ArgumentParser(description="Align audio with precise subtitle timeline")
    parser.add_argument("--year", type=int)
    parser.add_argument("--video")
    parser.add_argument("--audio")
    parser.add_argument("--output")
    args = parser.parse_args()

    config = load_config()
    if args.year is not None:
        align_year(args.year, config)
        return

    if not args.output or (not args.video and not args.audio):
        parser.error("Either provide --year, or provide --output + (--video or --audio)")

    srt_path = Path(args.output)
    if args.audio:
        align_audio_with_whisperx(Path(args.audio), srt_path, config)
    else:
        align_media_with_whisperx(Path(args.video), srt_path.parent, config, srt_path=srt_path)


if __name__ == "__main__":
    main()
