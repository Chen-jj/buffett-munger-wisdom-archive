"""Pure historical HLS/sample contract regressions; no preparation or download entry."""

from __future__ import annotations

import argparse
import re
from typing import Sequence
from urllib.parse import urljoin

from acquisition.domain import Chapter, Transcript


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


def select_transcript_chapters(
    transcript: Transcript,
    chapter_numbers: Sequence[int],
) -> tuple[Chapter, ...]:
    requested = tuple(chapter_numbers)
    selected = tuple(
        chapter for chapter in transcript.chapters if chapter.number in requested
    )
    if tuple(chapter.number for chapter in selected) != requested:
        raise PreparationError(
            "expected exact ordered transcript chapters "
            + ", ".join(str(number) for number in requested)
        )
    return selected
