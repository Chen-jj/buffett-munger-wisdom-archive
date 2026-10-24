"""Canonical software encoding and transparent libass frames via shared processes."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Callable

from archive_core.interfaces.rendering import RenderProfileDTO, RenderStreamMappingDTO, RenderToolsDTO
from infrastructure.infrastructure.process import (
    ProcessBytesResult, ProcessResult, run_process, run_process_bytes,
)


class RenderAdapterError(RuntimeError):
    def __init__(self, category: str, diagnostic: str) -> None:
        self.category = category
        self.diagnostic = diagnostic[:2048]
        super().__init__(category)


@dataclass(frozen=True)
class TransparentFrame:
    rgba: bytes
    stderr: str
    width: int
    height: int


def escape_filter_path(path: str) -> str:
    """Escape both AVOption and filtergraph parsers, not a shell."""
    if not isinstance(path, str) or not path or any(ord(char) < 32 for char in path):
        raise ValueError("filter path must be nonempty and contain no control characters")
    option = "".join("\\" + char if char in "\\': " else char for char in path)
    return "".join("\\" + char if char in "\\'[],; " else char for char in option)


def _ass_filter(ass_path: str, fonts_dir: str, *, alpha: bool = False) -> str:
    return (f"ass=filename={escape_filter_path(str(ass_path))}:fontsdir={escape_filter_path(str(fonts_dir))}"
            + (":alpha=1" if alpha else ""))


class FfmpegRenderer:
    def __init__(self, *, executable: str = "ffmpeg", process: Callable[..., ProcessResult] = run_process,
                 binary_process: Callable[..., ProcessBytesResult] = run_process_bytes,
                 timeout: float = 3600.0, preflight_timeout: float = 60.0,
                 maximum_log_bytes: int = 1_048_576) -> None:
        self.executable, self.process, self.binary_process = executable, process, binary_process
        self.timeout, self.preflight_timeout, self.maximum_log_bytes = timeout, preflight_timeout, maximum_log_bytes

    def _log(self, stderr: str) -> str:
        if len(stderr.encode("utf-8")) > self.maximum_log_bytes:
            raise RenderAdapterError("render_failed", "FFmpeg diagnostic log exceeded its limit")
        return stderr

    def _text(self, command: list[str] | tuple[str, ...], *, cwd: str | None = None,
              timeout: float | None = None, allow_failure: bool = False) -> ProcessResult:
        try:
            result = self.process(command, cwd=cwd, timeout=timeout or self.preflight_timeout)
        except (OSError, RuntimeError, KeyboardInterrupt) as exc:
            raise RenderAdapterError("render_failed", "FFmpeg execution interrupted or failed") from exc
        self._log(result.stderr)
        if result.dry_run or result.returncode == 127:
            raise RenderAdapterError("tool_unavailable", result.stderr or "FFmpeg was not executed")
        if result.returncode == 124 or result.returncode < 0 or (not result.ok and not allow_failure):
            raise RenderAdapterError("render_failed", result.stderr or "FFmpeg exited unsuccessfully")
        return result

    def _binary(self, command: list[str], *, cwd: str | None = None) -> ProcessBytesResult:
        try:
            result = self.binary_process(command, cwd=cwd, timeout=self.preflight_timeout)
        except (OSError, RuntimeError, KeyboardInterrupt) as exc:
            raise RenderAdapterError("render_failed", "FFmpeg binary pipe interrupted or failed") from exc
        self._log(result.stderr)
        if result.dry_run or result.returncode == 127:
            raise RenderAdapterError("tool_unavailable", result.stderr or "FFmpeg was not executed")
        if not result.ok:
            raise RenderAdapterError("render_failed", result.stderr or "FFmpeg exited unsuccessfully")
        return result

    def tool_identity(self, *, pysubs2_version: str, ffprobe_version: str) -> RenderToolsDTO:
        """Read runtime identities; x264 emits zero frames into an in-memory MP4."""
        try:
            version = self._text([self.executable, "-version"]).stdout.strip()
            if not re.match(r"ffmpeg version (?:[0-9]+\.[^\s]+|N-[0-9]+-g[0-9a-f]+)(?:\s|$)", version):
                raise RenderAdapterError("tool_unavailable", "unknown FFmpeg version")
            filters = self._text([self.executable, "-hide_banner", "-filters"]).stdout
            encoders = self._text([self.executable, "-hide_banner", "-encoders"]).stdout
            if not all(re.search(r"^\s*\S+\s+" + name + r"\s", filters, re.MULTILINE) for name in ("ass", "subtitles")):
                raise RenderAdapterError("tool_unavailable", "FFmpeg requires ass and subtitles filters")
            if not re.search(r"^\s*V\S*\s+libx264\s", encoders, re.MULTILINE):
                raise RenderAdapterError("tool_unavailable", "FFmpeg requires the software libx264 encoder")
            # An empty seekable ASS deliberately fails after printing actual linked libass identity.
            libass = self._text([self.executable, "-hide_banner", "-loglevel", "verbose", "-f", "lavfi", "-i",
                                "color=size=2x2", "-vf", "ass=filename=/dev/null", "-frames:v", "0", "-f", "null", "-"],
                               allow_failure=True)
            api = re.search(r"libass API version:\s*(0x[0-9a-fA-F]+)", libass.stderr)
            source = re.search(r"libass source:\s*([^\r\n]+)", libass.stderr)
            if not api or not source or not re.search(r"[0-9]+\.[0-9]+", source.group(1)):
                raise RenderAdapterError("tool_unavailable", "unknown libass runtime version")
            libraries = [api.group(1), source.group(1).strip()]
            for name in ("Raster", "Shaper"):
                match = re.search(name + r":\s*([^\r\n]+)", libass.stderr)
                if match:
                    libraries.append(name + ": " + match.group(1).strip())
            x264 = self._binary([self.executable, "-hide_banner", "-loglevel", "verbose", "-f", "lavfi", "-i",
                                 "color=size=2x2", "-frames:v", "0", "-c:v", "libx264", "-f", "mp4", "-movflags",
                                 "empty_moov", "pipe:1"])
            core = re.search(r"264 - core ([0-9]+ r[0-9]+ [0-9a-f]+)(?:\s|$)", x264.stderr)
            if not core or len(x264.stdout) > 1_048_576:
                raise RenderAdapterError("tool_unavailable", "unknown libx264 runtime version")
            cpu = re.search(r"using cpu capabilities:\s*([^\r\n]+)", x264.stderr)
            x264_version = "core " + core.group(1) + ("; cpu: " + cpu.group(1).strip() if cpu else "")
            if (not re.fullmatch(r"[0-9]+\.[0-9]+[^\s]*", pysubs2_version)
                    or not re.match(r"ffprobe version (?:[0-9]+\.[^\s]+|N-[0-9]+-g[0-9a-f]+)(?:\s|$)", ffprobe_version)):
                raise RenderAdapterError("tool_unavailable", "unknown codec or ffprobe identity")
            return RenderToolsDTO(pysubs2_version, version, ffprobe_version, "; ".join(libraries), x264_version)
        except RenderAdapterError as exc:
            if exc.category == "tool_unavailable":
                raise
            raise RenderAdapterError("tool_unavailable", exc.diagnostic) from exc

    def build_command(self, *, video_path: str, ass_path: str, fonts_dir: str, output_path: str,
                      profile: RenderProfileDTO, mapping: RenderStreamMappingDTO = RenderStreamMappingDTO()) -> tuple[str, ...]:
        encoder = profile.encoder
        if Path(video_path).absolute() == Path(output_path).absolute():
            raise ValueError("render output must not replace source video")
        return (self.executable, "-nostdin", "-i", str(video_path), "-vf", _ass_filter(str(ass_path), str(fonts_dir)),
                "-map", mapping.video_selector, "-map", mapping.audio_selector, "-sn", "-dn",
                "-c:v", encoder.video_codec, "-crf", str(encoder.crf), "-preset", encoder.preset,
                "-pix_fmt", encoder.pixel_format, "-c:a", "copy", "-fps_mode:v", mapping.fps_mode,
                "-map_metadata", mapping.map_metadata, "-map_chapters", mapping.map_chapters,
                "-movflags", encoder.movflags, "-n", str(output_path))

    def render(self, command: tuple[str, ...], *, cwd: str) -> ProcessResult:
        if (not command or command[0] != self.executable or "-n" not in command
                or any(argument in command for argument in ("-y", "-shortest"))):
            raise ValueError("render requires the canonical no-overwrite command")
        return self._text(command, cwd=cwd, timeout=self.timeout)

    def render_transparent_frame(self, ass_path: str, fonts_dir: str, width: int, height: int, time_ms: int,
                                 *, cwd: str | None = None) -> TransparentFrame:
        if any(type(value) is not int for value in (width, height, time_ms)) or width <= 0 or height <= 0 or time_ms < 0:
            raise ValueError("frame dimensions and midpoint must be nonnegative integers")
        command = [self.executable, "-nostdin", "-hide_banner", "-loglevel", "debug", "-f", "lavfi", "-i",
                   f"color=color=black@0:size={width}x{height},format=rgba,trim=end_frame=1", "-vf",
                   f"settb=1/1000,setpts=PTS+{time_ms}," + _ass_filter(ass_path, fonts_dir, alpha=True),
                   "-frames:v", "1", "-pix_fmt", "rgba", "-c:v", "rawvideo", "-f", "rawvideo", "pipe:1"]
        result = self._binary(command, cwd=cwd)
        if len(result.stdout) != width * height * 4:
            raise RenderAdapterError("render_validation_failed", "transparent RGBA frame has an invalid byte count")
        return TransparentFrame(result.stdout, result.stderr, width, height)
