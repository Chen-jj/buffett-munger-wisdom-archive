#!/usr/bin/env python3
"""Prepare the clipped CNBC input for the transcription live integration test."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import Any, Mapping, Sequence
from urllib.parse import urljoin


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from archive_core.application import build_asset_workspace
from archive_core.domain import AssetId
from acquisition.domain import AcquisitionTarget, Transcript
from acquisition.infrastructure import CnbcCrawler, LocalAcquisitionArtifactWriter
from media_download.domain import DownloadInput, DownloadedArtifact, MediaRef
from media_download.infrastructure import (
    LocalDownloadArtifactStore,
    Sha256ChecksumCalculator,
    build_default_resolver_registry,
)


DEFAULT_URL = (
    "https://buffett.cnbc.com/video/2000/04/29/"
    "morning-session---2000-berkshire-hathaway-annual-meeting.html"
)
DEFAULT_OUTPUT_ROOT = REPOSITORY_ROOT / "output" / "transcription-integration"
USER_AGENT = "buffett-munger-wisdom-archive/1.0"
SAMPLE_METADATA_SCHEMA = "transcription.integration-sample-input.v1"
INTEGRATION_PLAN_FILENAME = "integration-plan.json"
INTEGRATION_SAMPLE_FILENAME = "integration_sample.json"

INTEGRATION_RUNTIME = {
    "alignment_model": "jonatasgrosman/wav2vec2-large-xlsr-53-english",
    "alignment_model_version": "569a6236e92bd5f7652a0420bfe9bb94c5664080",
    "batch_size": 8,
    "beam_size": 5,
    "compute_type": "int8",
    "device": "cpu",
    "ffmpeg_path": "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",
    "ffprobe_path": "/opt/homebrew/opt/ffmpeg-full/bin/ffprobe",
    "interpolation": {
        "allowed_reasons": [
            "alignment_model_no_timing",
            "numeric_or_symbol",
            "out_of_vocabulary",
        ],
        "max_consecutive_words": 1,
        "max_window_ms": 1500,
        "min_anchor_alignment_score": 0.5,
        "min_word_duration_ms": 80,
        "version": "interpolation.v1",
    },
    "matching_anchor_ngram_size": 3,
    "official_min_alignment_score": 0.5,
    "official_min_anchor_alignment_score": 0.5,
    "vad_merge_gap_ms": 500,
    "vad_model": "pyannote/segmentation",
    "vad_model_version": "660b9e20307a2b0cdb400d0f80aadc04a701fc54",
    "vad_offset": 0.5,
    "vad_onset": 0.5,
    "vad_padding_ms": 250,
}


class PreparationError(RuntimeError):
    """Raised when the source cannot produce a safe integration input."""


def parse_timestamp(value: str) -> float:
    parts = value.split(":")
    if not 1 <= len(parts) <= 3:
        raise argparse.ArgumentTypeError("timestamp must be SS, MM:SS, or HH:MM:SS")
    try:
        numbers = [float(part) for part in parts]
    except ValueError as error:
        raise argparse.ArgumentTypeError("timestamp components must be numeric") from error
    if any(number < 0 for number in numbers) or any(
        number >= 60 for number in numbers[1:]
    ):
        raise argparse.ArgumentTypeError("timestamp components are out of range")
    seconds = 0.0
    for number in numbers:
        seconds = seconds * 60 + number
    return seconds


def select_hls_variant(master_text: str, master_url: str, max_height: int) -> str:
    variants: list[tuple[int, int, str]] = []
    lines = [line.strip() for line in master_text.splitlines() if line.strip()]
    for index, line in enumerate(lines[:-1]):
        if not line.startswith("#EXT-X-STREAM-INF:"):
            continue
        resolution = re.search(r"RESOLUTION=\d+x(\d+)", line)
        bandwidth = re.search(r"(?:AVERAGE-)?BANDWIDTH=(\d+)", line)
        uri = lines[index + 1]
        if resolution is None or uri.startswith("#"):
            continue
        variants.append(
            (
                int(resolution.group(1)),
                int(bandwidth.group(1)) if bandwidth else 0,
                urljoin(master_url, uri),
            )
        )
    eligible = [variant for variant in variants if variant[0] <= max_height]
    if not eligible:
        raise PreparationError(f"no HLS variant is at or below {max_height}p")
    return max(eligible, key=lambda variant: (variant[0], variant[1]))[2]


def select_hls_segments(
    playlist_text: str,
    playlist_url: str,
    start_seconds: float,
    end_seconds: float,
) -> tuple[float, tuple[str, ...]]:
    segments: list[tuple[float, float, str]] = []
    elapsed = 0.0
    pending_duration: float | None = None
    for raw_line in playlist_text.splitlines():
        line = raw_line.strip()
        if line.startswith("#EXTINF:"):
            pending_duration = float(line.split(":", 1)[1].split(",", 1)[0])
        elif line and not line.startswith("#") and pending_duration is not None:
            segments.append(
                (elapsed, elapsed + pending_duration, urljoin(playlist_url, line))
            )
            elapsed += pending_duration
            pending_duration = None
    selected = [
        segment
        for segment in segments
        if segment[1] > start_seconds and segment[0] < end_seconds
    ]
    if not selected:
        raise PreparationError("requested time range does not intersect the HLS playlist")
    if selected[0][0] > start_seconds or selected[-1][1] < end_seconds:
        raise PreparationError("requested time range exceeds the HLS playlist")
    return selected[0][0], tuple(segment[2] for segment in selected)


def _http_text(url: str) -> str:
    try:
        import requests
    except ImportError as error:
        raise PreparationError("requests is required to prepare CNBC media") from error
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    response.raise_for_status()
    return response.text


def _download_segments(urls: tuple[str, ...], output_path: Path) -> None:
    try:
        import requests
    except ImportError as error:
        raise PreparationError("requests is required to prepare CNBC media") from error

    def fetch(item: tuple[int, str]) -> tuple[int, bytes]:
        index, url = item
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
        response.raise_for_status()
        if not response.content:
            raise PreparationError(f"HLS segment {index} is empty")
        return index, response.content

    with ThreadPoolExecutor(max_workers=8) as pool:
        chunks = list(pool.map(fetch, enumerate(urls)))
    chunks.sort(key=lambda item: item[0])
    with output_path.open("xb") as stream:
        for _, chunk in chunks:
            stream.write(chunk)


def _render_clip(
    source_path: Path,
    output_path: Path,
    *,
    offset_seconds: float,
    duration_seconds: float,
    ffmpeg_path: str,
) -> tuple[str, tuple[str, ...]]:
    version = subprocess.run(
        (ffmpeg_path, "-version"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()[0]
    command = (
        ffmpeg_path,
        "-hide_banner",
        "-nostdin",
        "-n",
        "-i",
        str(source_path),
        "-ss",
        str(offset_seconds),
        "-t",
        str(duration_seconds),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        str(output_path),
    )
    subprocess.run(command, check=True)
    return version, command


def _write_json(path: Path, data: Mapping[str, Any]) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")


def prepare(args: argparse.Namespace) -> Path:
    if args.end <= args.start:
        raise PreparationError("end must be later than start")
    asset_id = AssetId("cnbc", args.group, args.item)
    output_root = args.output_root.expanduser().resolve()
    workspace = build_asset_workspace(asset_id, output_root)
    planned_paths = (
        workspace / "meta.json",
        workspace / "media_ref.json",
        workspace / "transcript.txt",
        workspace / "chapters.json",
        workspace / "video.mp4",
        workspace / "download_manifest.json",
        workspace / INTEGRATION_SAMPLE_FILENAME,
        workspace / INTEGRATION_PLAN_FILENAME,
    )
    existing = [path for path in planned_paths if path.exists()]
    if existing:
        raise PreparationError(
            "refusing to overwrite existing sample files: "
            + ", ".join(str(path) for path in existing)
        )
    workspace.mkdir(parents=True, exist_ok=True)

    target = AcquisitionTarget(
        asset_id=asset_id,
        fetch_url=args.url,
        hints={"year": int(args.group), "session": args.item},
    )
    result = CnbcCrawler(delay_seconds=0).fetch(target)
    if result.transcript is None:
        raise PreparationError("CNBC page did not provide a transcript")
    chapters = [
        chapter for chapter in result.transcript.chapters if chapter.number == args.chapter
    ]
    if len(chapters) != 1:
        raise PreparationError(f"expected exactly one transcript chapter {args.chapter}")

    media_input = DownloadInput(
        asset_id=asset_id,
        media_ref=MediaRef(
            kind=result.media_ref.kind,
            value=result.media_ref.value,
            extra=result.media_ref.extra,
        ),
    )
    media_url = build_default_resolver_registry().select(media_input).resolve(media_input)
    master_text = _http_text(media_url)
    variant_url = select_hls_variant(master_text, media_url, args.max_height)
    playlist_text = _http_text(variant_url)
    segment_start, segment_urls = select_hls_segments(
        playlist_text, variant_url, args.start, args.end
    )
    with TemporaryDirectory(prefix="cnbc-transcription-integration-") as temp_dir:
        source_segments = Path(temp_dir) / "source_segments.ts"
        _download_segments(segment_urls, source_segments)
        ffmpeg_version, ffmpeg_command = _render_clip(
            source_segments,
            workspace / "video.mp4",
            offset_seconds=args.start - segment_start,
            duration_seconds=args.end - args.start,
            ffmpeg_path=args.ffmpeg_path,
        )

    selected_result = replace(result, transcript=Transcript(chapters=tuple(chapters)))
    LocalAcquisitionArtifactWriter(root=output_root).save(selected_result)

    video_path = workspace / "video.mp4"
    checksum = Sha256ChecksumCalculator().sha256(str(video_path))
    artifact = DownloadedArtifact(
        asset_id=asset_id,
        media_kind=media_input.media_ref.kind,
        media_ref_value=media_input.media_ref.value,
        media_url=media_url,
        output_path=str(video_path),
        format_selector=f"HLS <= {args.max_height}p; source {args.start}-{args.end}s",
        size_bytes=video_path.stat().st_size,
        checksum_algorithm="sha256",
        checksum_value=checksum,
        downloader_name="requests+ffmpeg",
        downloader_version=ffmpeg_version,
        downloaded_at=datetime.now(timezone.utc).isoformat(),
        status="downloaded",
    )
    LocalDownloadArtifactStore().write_manifest(
        str(workspace / "download_manifest.json"), artifact
    )
    _write_json(
        workspace / INTEGRATION_SAMPLE_FILENAME,
        {
            "schema_version": SAMPLE_METADATA_SCHEMA,
            "asset": {
                "source": asset_id.source,
                "group": asset_id.group,
                "item": asset_id.item,
            },
            "source_url": args.url,
            "resolved_media_url": media_url,
            "variant_url": variant_url,
            "source_start_seconds": args.start,
            "source_end_seconds": args.end,
            "duration_seconds": args.end - args.start,
            "chapter_number": chapters[0].number,
            "chapter_title": chapters[0].title,
            "ffmpeg_command": list(ffmpeg_command),
            "video_sha256": checksum,
        },
    )
    chapters_checksum = Sha256ChecksumCalculator().sha256(
        str(workspace / "chapters.json")
    )
    _write_json(
        workspace / INTEGRATION_PLAN_FILENAME,
        {
            "schema_version": "transcription.integration-plan.v1",
            "run_id": "cnbc-transcription-integration",
            "output_root": str(output_root),
            "runtime": {
                **INTEGRATION_RUNTIME,
                "ffmpeg_path": args.ffmpeg_path,
                "ffprobe_path": str(Path(args.ffmpeg_path).with_name("ffprobe")),
            },
            "samples": [
                {
                    "id": "cnbc-2000-morning-chapter-03",
                    "kind": "cnbc_multi_speaker",
                    "asset": {
                        "source": asset_id.source,
                        "group": asset_id.group,
                        "item": asset_id.item,
                    },
                    "coverage_tags": [
                        "person_name",
                        "company_name",
                        "number",
                        "percentage",
                        "currency",
                        "cross_segment_sentence",
                        "multiple_sentences_one_segment",
                    ],
                    "chapters_sha256": chapters_checksum,
                }
            ],
        },
    )
    return workspace


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--group", default="2000")
    parser.add_argument("--item", default="morning")
    parser.add_argument("--chapter", type=int, default=3)
    parser.add_argument("--start", type=parse_timestamp, default=parse_timestamp("11:48"))
    parser.add_argument("--end", type=parse_timestamp, default=parse_timestamp("21:40"))
    parser.add_argument("--max-height", type=int, default=360)
    parser.add_argument(
        "--ffmpeg-path",
        default="/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    workspace = prepare(parse_args(argv))
    print(json.dumps({"status": "prepared", "workspace": str(workspace)}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (PreparationError, OSError, subprocess.SubprocessError) as error:
        print(f"CNBC integration preparation failed: {error}", file=sys.stderr)
        raise SystemExit(2)
