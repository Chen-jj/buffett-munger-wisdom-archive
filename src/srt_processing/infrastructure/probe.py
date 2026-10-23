"""Injectable ffprobe adapter for average frame rate and conservative duration."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_FLOOR
import json
import re
from typing import Callable

from infrastructure.infrastructure.process import ProcessResult, run_process
from srt_processing.application.ports import MediaProbeResult


class FfprobeMediaProbe:
    def __init__(
        self,
        *,
        executable: str = "ffprobe",
        process: Callable[..., ProcessResult] = run_process,
        timeout: float = 30.0,
    ) -> None:
        self.executable = executable
        self.process = process
        self.timeout = timeout

    def probe(self, video_path: str) -> MediaProbeResult:
        version_result = self.process(
            [self.executable, "-version"], check=True, timeout=self.timeout
        )
        if not version_result.ok or version_result.dry_run:
            raise ValueError("ffprobe version detection failed")
        version_lines = version_result.stdout.splitlines()
        if (not version_lines or not version_lines[0].startswith("ffprobe version ")
                or not version_lines[0].removeprefix("ffprobe version ").strip()):
            raise ValueError("ffprobe version output is invalid")
        version = version_lines[0].strip()
        result = self.process(
            [self.executable, "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=avg_frame_rate:format=duration", "-of", "json", video_path],
            check=True,
            timeout=self.timeout,
        )
        if not result.ok or result.dry_run:
            raise ValueError("ffprobe media inspection failed")
        data = json.loads(result.stdout)
        if not isinstance(data, dict):
            raise ValueError("ffprobe output must be an object")
        streams = data.get("streams")
        if not isinstance(streams, list) or len(streams) != 1 or not isinstance(streams[0], dict):
            raise ValueError("ffprobe did not return the selected video stream")
        rate = streams[0].get("avg_frame_rate")
        if not isinstance(rate, str) or re.fullmatch(r"[0-9]+/[0-9]+", rate) is None:
            raise ValueError("ffprobe average frame rate must be a positive rational")
        numerator, denominator = (int(part) for part in rate.split("/"))
        format_data = data.get("format")
        if not isinstance(format_data, dict):
            raise ValueError("ffprobe format duration is missing")
        duration_value = format_data.get("duration")
        if not isinstance(duration_value, str):
            raise ValueError("ffprobe duration must be a decimal seconds string")
        try:
            duration = Decimal(duration_value)
            if not duration.is_finite() or duration <= 0:
                raise ValueError("ffprobe duration must be finite and positive")
            duration_ms = int((duration * 1000).to_integral_value(rounding=ROUND_FLOOR))
        except InvalidOperation as error:
            raise ValueError("ffprobe duration is invalid") from error
        return MediaProbeResult(duration_ms, numerator, denominator, version)
