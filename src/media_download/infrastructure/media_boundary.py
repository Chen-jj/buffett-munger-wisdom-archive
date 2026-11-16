"""Actual decoded video PTS evidence, never average-frame-rate inference."""

from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
import json

from archive_core.interfaces.bilingual import MediaBoundaryDTO
from infrastructure.infrastructure.artifacts import evidence


FFMPEG = "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"
FFPROBE = "/opt/homebrew/opt/ffmpeg-full/bin/ffprobe"


def probe_video_boundary(path, process):
    result = process([FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_frames",
                      "-show_format", "-show_streams", "-show_entries",
                      "frame=best_effort_timestamp_time:format=start_time,duration:stream=width,height,start_time,duration",
                      "-of", "json", str(path)], check=True, timeout=300)
    decoded = json.loads(result.stdout)
    streams = decoded["streams"]
    if not isinstance(streams, list) or len(streams) != 1 or not isinstance(streams[0], dict):
        raise ValueError("ffprobe must return exactly one selected video stream")
    stream = streams[0]
    container = decoded["format"]
    container_duration = container["duration"]
    stream_duration = stream.get("duration", container_duration)
    if not isinstance(container_duration, str) or not isinstance(stream_duration, str):
        raise ValueError("ffprobe duration must be a JSON string")
    origin = Decimal(container.get("start_time", "0"))
    duration = min(Decimal(container_duration), Decimal(stream_duration)
                   + Decimal(stream.get("start_time", "0")) - origin)
    duration_ms = int((duration * 1000).to_integral_value(rounding=ROUND_FLOOR))
    frames = decoded["frames"]
    pts = None
    if frames and all("best_effort_timestamp_time" in frame for frame in frames):
        timestamps = tuple(int(((Decimal(frame["best_effort_timestamp_time"]) - origin) * 1000000)
                               .to_integral_value(rounding=ROUND_HALF_UP)) for frame in frames)
        if 0 <= timestamps[0] and timestamps[-1] < duration_ms * 1000 and all(
                left < right for left, right in zip(timestamps, timestamps[1:])):
            pts = timestamps
    return MediaBoundaryDTO(evidence(path).sha256, duration_ms, pts), stream
