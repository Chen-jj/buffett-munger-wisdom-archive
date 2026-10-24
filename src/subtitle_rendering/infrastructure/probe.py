"""Strict, injectable media probing and conservative CFR/output validation."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from fractions import Fraction
import json
import re
from typing import Callable

from archive_core.interfaces.rendering import (
    RenderAudioStreamDTO, RenderChapterDTO, RenderMediaDTO, RenderTagDTO, RenderVideoStreamDTO,
)
from infrastructure.infrastructure.process import ProcessResult, run_process


class MediaProbeError(ValueError):
    """The media cannot be proved to satisfy the rendering contract."""


def _integer(value: object, name: str) -> int:
    if type(value) is int:
        return value
    if isinstance(value, str) and re.fullmatch(r"-?[0-9]+", value):
        return int(value)
    raise MediaProbeError(f"{name} must be an integer")


def _seconds(value: object, name: str) -> int:
    if not isinstance(value, str):
        raise MediaProbeError(f"{name} must be decimal seconds")
    try:
        number = Decimal(value)
        if not number.is_finite():
            raise MediaProbeError(f"{name} must be finite")
        return int(number * 1_000_000)
    except (InvalidOperation, ValueError, OverflowError) as exc:
        raise MediaProbeError(f"invalid {name}") from exc


def _rational(value: object, separator: str, name: str) -> Fraction:
    if not isinstance(value, str) or re.fullmatch(r"[0-9]+" + re.escape(separator) + r"[0-9]+", value) is None:
        raise MediaProbeError(f"invalid {name}")
    numerator, denominator = map(int, value.split(separator))
    if numerator <= 0 or denominator <= 0:
        raise MediaProbeError(f"{name} must be positive")
    return Fraction(numerator, denominator)


def _tags(value: object) -> tuple[RenderTagDTO, ...]:
    if not isinstance(value, dict):
        raise MediaProbeError("tags must be an object")
    if any(not isinstance(key, str) or not isinstance(item, str) for key, item in value.items()):
        raise MediaProbeError("tags must contain strings")
    return tuple(RenderTagDTO(key, value[key]) for key in sorted(value))


def _rotation(stream: dict) -> int:
    rotations = []
    tags = stream.get("tags", {})
    if "rotate" in tags:
        rotations.append(_integer(tags["rotate"], "rotation"))
    for item in stream.get("side_data_list", []):
        if not isinstance(item, dict):
            raise MediaProbeError("invalid side data")
        if "rotation" in item:
            rotations.append(_integer(item["rotation"], "rotation"))
        elif item.get("side_data_type") == "Display Matrix":
            raise MediaProbeError("display matrix has no interpretable rotation")
    if any(rotation % 360 for rotation in rotations):
        raise MediaProbeError("rotated video is unsupported")
    return 0


def parse_media(data: object) -> RenderMediaDTO:
    """Parse ffprobe JSON without guessing missing stream timing or coordinates."""
    try:
        if not isinstance(data, dict) or not isinstance(data.get("streams"), list) or not isinstance(data.get("format"), dict):
            raise MediaProbeError("probe must contain streams and format")
        streams, container = data["streams"], data["format"]
        if any(not isinstance(item, dict) for item in streams):
            raise MediaProbeError("invalid stream")
        indices = [_integer(item.get("index"), "stream index") for item in streams]
        if len(set(indices)) != len(indices):
            raise MediaProbeError("duplicate stream index")
        videos = [item for item in streams if item.get("codec_type") == "video"]
        if not videos or videos[0].get("disposition", {}).get("attached_pic", 0) != 0:
            raise MediaProbeError("no canonical main video stream")
        stream = videos[0]
        sar = _rational(stream.get("sample_aspect_ratio"), ":", "SAR")
        dar = _rational(stream.get("display_aspect_ratio"), ":", "DAR")
        if sar != 1:
            raise MediaProbeError("non-square pixels are unsupported")
        fps = _rational(stream.get("avg_frame_rate"), "/", "average frame rate")
        r_fps = _rational(stream.get("r_frame_rate"), "/", "reference frame rate")
        if fps != r_fps:
            raise MediaProbeError("variable or uncertain frame rate")
        video = RenderVideoStreamDTO(
            index=_integer(stream.get("index"), "video index"), codec_name=stream["codec_name"],
            width=_integer(stream.get("width"), "width"), height=_integer(stream.get("height"), "height"),
            sar_numerator=sar.numerator, sar_denominator=sar.denominator,
            dar_numerator=dar.numerator, dar_denominator=dar.denominator,
            fps_numerator=fps.numerator, fps_denominator=fps.denominator,
            r_fps_numerator=r_fps.numerator, r_fps_denominator=r_fps.denominator,
            start_time_us=_seconds(stream.get("start_time"), "video start"),
            duration_us=_seconds(stream.get("duration"), "video duration"),
            frame_count=None if stream.get("nb_frames", "N/A") == "N/A" else _integer(stream["nb_frames"], "frame count"),
            pixel_format=stream["pix_fmt"], rotation_degrees=_rotation(stream), tags=_tags(stream.get("tags", {})),
        )
        audio = []
        for item in sorted(streams, key=lambda value: _integer(value["index"], "stream index")):
            if item.get("codec_type") == "audio":
                default = _integer(item.get("disposition", {}).get("default", 0), "audio default")
                if default not in (0, 1):
                    raise MediaProbeError("invalid audio default disposition")
                audio.append(RenderAudioStreamDTO(
                    index=_integer(item["index"], "audio index"), codec_name=item["codec_name"],
                    sample_rate=_integer(item.get("sample_rate"), "sample rate"),
                    channels=_integer(item.get("channels"), "channels"), channel_layout=item["channel_layout"],
                    start_time_us=_seconds(item.get("start_time"), "audio start"),
                    duration_us=None if item.get("duration", "N/A") == "N/A" else _seconds(item["duration"], "audio duration"),
                    default=bool(default), tags=_tags(item.get("tags", {})),
                ))
        chapters = data.get("chapters", [])
        if not isinstance(chapters, list):
            raise MediaProbeError("chapters must be an array")
        return RenderMediaDTO(
            format_name=container["format_name"], duration_us=_seconds(container.get("duration"), "container duration"),
            start_time_us=_seconds(container.get("start_time"), "container start"), video=video,
            audio_streams=tuple(audio), video_stream_count=len(videos),
            subtitle_stream_count=sum(item.get("codec_type") == "subtitle" for item in streams),
            data_stream_count=sum(item.get("codec_type") == "data" for item in streams),
            tags=_tags(container.get("tags", {})),
            chapters=tuple(RenderChapterDTO(_integer(item["id"], "chapter id"),
                                           _seconds(item.get("start_time"), "chapter start"),
                                           _seconds(item.get("end_time"), "chapter end"),
                                           _tags(item.get("tags", {}))) for item in chapters),
        )
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        if isinstance(exc, MediaProbeError):
            raise
        raise MediaProbeError("invalid media fields") from exc


class FfprobeMediaProbe:
    def __init__(self, *, executable: str = "ffprobe", process: Callable[..., ProcessResult] = run_process,
                 timeout: float = 120.0) -> None:
        self.executable, self.process, self.timeout = executable, process, timeout

    def _call(self, arguments: list[str]) -> str:
        try:
            result = self.process([self.executable, *arguments], timeout=self.timeout)
        except (OSError, RuntimeError, KeyboardInterrupt) as exc:
            raise MediaProbeError("media probe execution failed") from exc
        if not result.ok or result.dry_run:
            raise MediaProbeError("media probe execution failed")
        if result.stderr.strip():
            raise MediaProbeError("media probe reported decoding or inspection errors")
        return result.stdout

    def version(self) -> str:
        version = self._call(["-version"]).strip()
        if not re.match(r"ffprobe version (?:[0-9]+\.[^\s]+|N-[0-9]+-g[0-9a-f]+)(?:\s|$)", version):
            raise MediaProbeError("unknown ffprobe version")
        return version

    def _json(self, arguments: list[str]) -> dict:
        try:
            data = json.loads(self._call(arguments))
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise MediaProbeError("invalid ffprobe JSON") from exc
        if not isinstance(data, dict):
            raise MediaProbeError("ffprobe JSON must be an object")
        return data

    def probe(self, path: str) -> RenderMediaDTO:
        data = self._json(["-v", "error", "-show_streams", "-show_format", "-show_chapters", "-of", "json", path])
        media = parse_media(data)
        decoded = self._json(["-v", "error", "-read_intervals", "%+#1", "-select_streams", "v:0",
                              "-show_frames", "-show_entries", "frame=media_type,width,height,pix_fmt", "-of", "json", path])
        frames = decoded.get("frames")
        if (not isinstance(frames, list) or not frames or not isinstance(frames[0], dict)
                or frames[0].get("media_type") != "video" or frames[0].get("width") != media.video.width
                or frames[0].get("height") != media.video.height or frames[0].get("pix_fmt") != media.video.pixel_format):
            raise MediaProbeError("main video cannot be decoded consistently")
        timing = self._json(["-v", "error", "-select_streams", "v:0", "-show_packets", "-show_entries",
                             "packet=pts,duration", "-of", "json", path])
        first_video = next(item for item in data["streams"] if item.get("codec_type") == "video")
        self._validate_packets(timing.get("packets"), first_video.get("time_base"), media.video)
        return media

    @staticmethod
    def _validate_packets(packets: object, time_base: object, video: RenderVideoStreamDTO) -> None:
        if not isinstance(packets, list) or not packets:
            raise MediaProbeError("missing video packet timing")
        tick = _rational(time_base, "/", "time base")
        expected = Fraction(video.fps_denominator, video.fps_numerator) / tick
        timestamps = []
        for packet in packets:
            if not isinstance(packet, dict):
                raise MediaProbeError("invalid video packet")
            timestamps.append(_integer(packet.get("pts"), "packet PTS"))
            if _integer(packet.get("duration"), "packet duration") != expected:
                raise MediaProbeError("variable or uncertain packet duration")
        timestamps.sort()
        if any(right - left != expected for left, right in zip(timestamps, timestamps[1:])):
            raise MediaProbeError("variable or uncertain presentation cadence")
        if video.frame_count is not None and len(timestamps) != video.frame_count:
            raise MediaProbeError("packet count differs from frame count")
        if abs(timestamps[0] * tick * 1_000_000 - video.start_time_us) >= 1:
            raise MediaProbeError("packet PTS differs from video start")
        actual = (timestamps[-1] - timestamps[0] + expected) * tick * 1_000_000
        frame_us = Fraction(1_000_000 * video.fps_denominator, video.fps_numerator)
        if abs(actual - video.duration_us) > frame_us:
            raise MediaProbeError("packet timing differs from video duration")


_MUX_TAGS = {"encoder", "major_brand", "minor_version", "compatible_brands", "handler_name", "vendor_id"}


def _preserved_tags(source: tuple[RenderTagDTO, ...], output: tuple[RenderTagDTO, ...]) -> bool:
    present = {item.key: item.value for item in output}
    return all(item.key in _MUX_TAGS or present.get(item.key) == item.value for item in source)


def validate_rendered_media(source: RenderMediaDTO, output: RenderMediaDTO, last_cue_end_ms: int) -> None:
    """Validate staged MP4 independently of an FFmpeg exit status."""
    video, rendered = source.video, output.video
    frame_us = Fraction(1_000_000 * video.fps_denominator, video.fps_numerator)
    if "mp4" not in output.format_name.split(","):
        raise MediaProbeError("rendered container is not MP4")
    if output.video_stream_count != 1 or output.subtitle_stream_count or output.data_stream_count:
        raise MediaProbeError("unexpected rendered stream mapping")
    if rendered.codec_name != "h264" or rendered.pixel_format != "yuv420p":
        raise MediaProbeError("rendered codec or pixel format differs from profile")
    for name in ("width", "height", "sar_numerator", "sar_denominator", "dar_numerator", "dar_denominator",
                 "rotation_degrees", "fps_numerator", "fps_denominator", "r_fps_numerator", "r_fps_denominator"):
        if getattr(video, name) != getattr(rendered, name):
            raise MediaProbeError(f"rendered {name} differs from input")
    if abs(video.duration_us - rendered.duration_us) > frame_us or abs(video.start_time_us - rendered.start_time_us) > frame_us:
        raise MediaProbeError("rendered video timing differs from input")
    if video.frame_count is not None and rendered.frame_count != video.frame_count:
        raise MediaProbeError("rendered frame count differs from input")
    if type(last_cue_end_ms) is not int or last_cue_end_ms < 0 or last_cue_end_ms * 1000 > rendered.duration_us:
        raise MediaProbeError("last cue exceeds rendered video")
    if len(source.audio_streams) != len(output.audio_streams):
        raise MediaProbeError("rendered audio count differs from input")
    for original, result in zip(source.audio_streams, output.audio_streams):
        for name in ("codec_name", "sample_rate", "channels", "channel_layout", "default"):
            if getattr(original, name) != getattr(result, name):
                raise MediaProbeError(f"rendered audio {name} differs from input")
        if original.start_time_us != result.start_time_us:
            raise MediaProbeError("rendered audio start differs from input")
        if original.duration_us is not None and result.duration_us != original.duration_us:
            raise MediaProbeError("rendered audio duration differs from input")
        if not _preserved_tags(original.tags, result.tags):
            raise MediaProbeError("rendered audio metadata differs from input")
    if (not _preserved_tags(source.tags, output.tags) or not _preserved_tags(video.tags, rendered.tags)
            or source.chapters != output.chapters):
        raise MediaProbeError("rendered metadata or chapters differ from input")
