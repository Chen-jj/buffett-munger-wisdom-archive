"""Strict, versioned rendering evidence and source-preserving visual plans."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import json
import math
from pathlib import PurePosixPath
import re
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from archive_core.domain import ArtifactType, AssetId, canonical_filename

from .subtitles import SubtitleCueDTO, SubtitlePlanDTO


SUBTITLE_RENDER_PLAN_SCHEMA_VERSION = "subtitle-rendering.plan.v1"
SUBTITLE_RENDER_REPORT_SCHEMA_VERSION = "subtitle-rendering.report.v1"
SUBTITLE_RENDER_MANIFEST_SCHEMA_VERSION = "subtitle-rendering.manifest.v1"
ASS_TIMING_POLICY = "nearest-centisecond-half-up.v1"
ASS_SERIALIZATION_VERSION = "bilingual-ass.word-joiner.v1"
RENDER_ERROR_CATEGORIES = frozenset((
    "input_invalid", "artifact_conflict", "font_invalid", "layout_failed",
    "ass_generation_failed", "tool_unavailable", "render_failed",
    "render_validation_failed", "publication_failed", "subtitle_rendering_failed",
))
_INPUT_TYPES = {"srt_processing_manifest": ArtifactType.SRT_PROCESSING_MANIFEST,
                "subtitle_plan": ArtifactType.SUBTITLE_PLAN, "video": ArtifactType.SOURCE_VIDEO}
_OUTPUT_TYPES = {"plan": ArtifactType.SUBTITLE_RENDER_PLAN, "ass": ArtifactType.BILINGUAL_ASS,
                 "video": ArtifactType.RENDERED_VIDEO, "report": ArtifactType.SUBTITLE_RENDER_REPORT}


def _keys(data: object, expected: tuple[str, ...], name: str) -> Mapping[str, Any]:
    if not isinstance(data, Mapping) or set(data) != set(expected):
        raise ValueError(f"{name} must contain exactly: {', '.join(expected)}")
    return data


def _integer(value: object, name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _signed_integer(value: object, name: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{name} must be an integer")
    return value


def _number(value: object, name: str, *, positive: bool = False) -> float:
    if type(value) not in (int, float) or (type(value) is float and not math.isfinite(value)) or value < 0 or (positive and value == 0):
        raise ValueError(f"{name} must be a finite {'positive' if positive else 'non-negative'} number")
    return value


def _string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _boolean(value: object, name: str) -> None:
    if type(value) is not bool:
        raise ValueError(f"{name} must be a boolean")


def _hash(value: object, name: str) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _asset_id(value: object) -> None:
    _string(value, "asset_id")
    parts = value.split(":")
    if len(parts) != 3:
        raise ValueError("asset_id must use source:group:item")
    AssetId(*parts)


def _cue_id(value: object) -> None:
    if not isinstance(value, str) or re.fullmatch(r"c[1-9][0-9]*", value) is None:
        raise ValueError("cue ID must use c<one-based position>")


def _array(value: object, name: str) -> tuple:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{name} must be an array")
    return tuple(value)


def _typed(value: object, dtype: type, name: str) -> None:
    if not isinstance(value, dtype):
        raise ValueError(f"{name} must be a {dtype.__name__}")


def _typed_tuple(value: object, dtype: type, name: str) -> tuple:
    items = _array(value, name)
    for item in items:
        _typed(item, dtype, name)
    return items


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def project_ass_time_ms(source_ms: int) -> int:
    """Project authoritative milliseconds onto the approved ASS centisecond grid."""
    return ((_integer(source_ms, "source_ms") + 5) // 10) * 10


@dataclass(frozen=True)
class RenderArtifactEvidenceDTO:
    path: str
    size_bytes: int
    sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.path, str) or self.path not in {canonical_filename(kind) for kind in (*_INPUT_TYPES.values(), *_OUTPUT_TYPES.values())}:
            raise ValueError("evidence path must be a canonical rendering input/output filename")
        _integer(self.size_bytes, "size_bytes", 1)
        _hash(self.sha256, "sha256")

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "size_bytes": self.size_bytes, "sha256": self.sha256}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RenderArtifactEvidenceDTO":
        return cls(**_keys(data, ("path", "size_bytes", "sha256"), "evidence"))


@dataclass(frozen=True)
class RenderFontSpecDTO:
    path: str = "/System/Library/Fonts/Hiragino Sans GB.ttc"
    sha256: str = "f887295caf2881cab9554b14c5ab4c9ee624c3895599da152ec37416b5aefae0"
    family: str = "Hiragino Sans GB"
    style: str = "W3"
    face_index: int = 0

    def __post_init__(self) -> None:
        _string(self.path, "font path")
        if not PurePosixPath(self.path).is_absolute() or ".." in PurePosixPath(self.path).parts or any(ord(char) < 32 for char in self.path):
            raise ValueError("font path must be an absolute, traversal-free path")
        _hash(self.sha256, "font sha256")
        _string(self.family, "font family")
        _string(self.style, "font style")
        _integer(self.face_index, "face_index")

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "sha256": self.sha256, "family": self.family,
                "style": self.style, "face_index": self.face_index}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RenderFontSpecDTO":
        return cls(**_keys(data, ("path", "sha256", "family", "style", "face_index"), "font spec"))


@dataclass(frozen=True)
class RenderFontIdentityDTO:
    spec: RenderFontSpecDTO
    size_bytes: int
    measurement_adapter_version: str
    postscript_name: str

    def __post_init__(self) -> None:
        _typed(self.spec, RenderFontSpecDTO, "font spec")
        _integer(self.size_bytes, "font size_bytes", 1)
        _string(self.measurement_adapter_version, "measurement_adapter_version")
        _string(self.postscript_name, "postscript_name")

    def to_dict(self) -> dict[str, Any]:
        return {"spec": self.spec.to_dict(), "size_bytes": self.size_bytes,
                "measurement_adapter_version": self.measurement_adapter_version,
                "postscript_name": self.postscript_name}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RenderFontIdentityDTO":
        data = dict(_keys(data, ("spec", "size_bytes", "measurement_adapter_version", "postscript_name"), "font identity"))
        data["spec"] = RenderFontSpecDTO.from_dict(data["spec"])
        return cls(**data)


@dataclass(frozen=True)
class RenderTextStyleDTO:
    font_size: int
    primary_color: str

    def __post_init__(self) -> None:
        _integer(self.font_size, "font_size", 1)
        if not isinstance(self.primary_color, str) or re.fullmatch(r"&H[0-9A-F]{8}", self.primary_color) is None:
            raise ValueError("primary_color must be an uppercase ASS &HAABBGGRR color")

    def to_dict(self) -> dict[str, Any]:
        return {"font_size": self.font_size, "primary_color": self.primary_color}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RenderTextStyleDTO":
        return cls(**_keys(data, ("font_size", "primary_color"), "text style"))


@dataclass(frozen=True)
class RenderEncoderDTO:
    video_codec: str = "libx264"
    crf: int = 18
    preset: str = "medium"
    pixel_format: str = "yuv420p"
    audio_mode: str = "copy-all"
    movflags: str = "+faststart"

    def __post_init__(self) -> None:
        _integer(self.crf, "crf")
        if self.to_dict() != {"video_codec": "libx264", "crf": 18, "preset": "medium",
                              "pixel_format": "yuv420p", "audio_mode": "copy-all", "movflags": "+faststart"}:
            raise ValueError("unsupported v1 encoder parameters")

    def to_dict(self) -> dict[str, Any]:
        return {"video_codec": self.video_codec, "crf": self.crf, "preset": self.preset,
                "pixel_format": self.pixel_format, "audio_mode": self.audio_mode, "movflags": self.movflags}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RenderEncoderDTO":
        return cls(**_keys(data, ("video_codec", "crf", "preset", "pixel_format", "audio_mode", "movflags"), "encoder"))


@dataclass(frozen=True)
class RenderStreamMappingDTO:
    video_selector: str = "0:v:0"
    audio_selector: str = "0:a?"
    fps_mode: str = "passthrough"
    map_metadata: str = "0"
    map_chapters: str = "0"
    include_subtitles: bool = False
    include_data: bool = False

    def __post_init__(self) -> None:
        _boolean(self.include_subtitles, "include_subtitles")
        _boolean(self.include_data, "include_data")
        if self.to_dict() != {"video_selector": "0:v:0", "audio_selector": "0:a?", "fps_mode": "passthrough",
                              "map_metadata": "0", "map_chapters": "0", "include_subtitles": False, "include_data": False}:
            raise ValueError("unsupported v1 stream mapping parameters")

    def to_dict(self) -> dict[str, Any]:
        return {"video_selector": self.video_selector, "audio_selector": self.audio_selector, "fps_mode": self.fps_mode,
                "map_metadata": self.map_metadata, "map_chapters": self.map_chapters,
                "include_subtitles": self.include_subtitles, "include_data": self.include_data}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RenderStreamMappingDTO":
        return cls(**_keys(data, ("video_selector", "audio_selector", "fps_mode", "map_metadata", "map_chapters",
                                 "include_subtitles", "include_data"), "stream mapping"))


@dataclass(frozen=True)
class RenderProfileDTO:
    name: str = "bilingual-burnin.hiragino-640x360.v1"
    version: str = "v1"
    layout_version: str = "pixel-wrap.v1"
    output_mode: str = "bilingual"
    reference_width: int = 640
    reference_height: int = 360
    horizontal_margin: int = 32
    vertical_margin: int = 42
    maximum_subtitle_height: int = 160
    maximum_chinese_lines: int = 2
    maximum_english_lines: int = 2
    maximum_total_lines: int = 4
    alignment: int = 2
    font: RenderFontSpecDTO = field(default_factory=RenderFontSpecDTO)
    chinese: RenderTextStyleDTO = field(default_factory=lambda: RenderTextStyleDTO(30, "&H00FFFFFF"))
    english: RenderTextStyleDTO = field(default_factory=lambda: RenderTextStyleDTO(20, "&H0060E6FF"))
    outline_color: str = "&H00000000"
    outline_width: int = 2
    shadow: int = 1
    encoder: RenderEncoderDTO = field(default_factory=RenderEncoderDTO)

    def __post_init__(self) -> None:
        _string(self.name, "profile name")
        if self.version != "v1" or self.layout_version != "pixel-wrap.v1" or self.output_mode != "bilingual":
            raise ValueError("unsupported rendering profile identity")
        for name in ("reference_width", "reference_height", "maximum_subtitle_height",
                     "maximum_chinese_lines", "maximum_english_lines", "maximum_total_lines", "alignment"):
            _integer(getattr(self, name), name, 1)
        for name in ("horizontal_margin", "vertical_margin", "outline_width", "shadow"):
            _integer(getattr(self, name), name)
        if (self.reference_width, self.reference_height) != (640, 360):
            raise ValueError("v1 profile reference resolution must be 640x360")
        if (self.maximum_chinese_lines, self.maximum_english_lines, self.maximum_total_lines, self.alignment) != (2, 2, 4, 2):
            raise ValueError("v1 requires two lines per language, four total, bottom-center alignment")
        if self.horizontal_margin * 2 >= self.reference_width or self.vertical_margin + self.maximum_subtitle_height > self.reference_height:
            raise ValueError("profile safe area must fit the reference resolution")
        for name, dtype in (("font", RenderFontSpecDTO), ("chinese", RenderTextStyleDTO),
                            ("english", RenderTextStyleDTO), ("encoder", RenderEncoderDTO)):
            _typed(getattr(self, name), dtype, name)
        RenderTextStyleDTO(1, self.outline_color)

    @property
    def sha256(self) -> str:
        return _digest(json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")))

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "version": self.version, "layout_version": self.layout_version,
                "output_mode": self.output_mode, "reference_width": self.reference_width,
                "reference_height": self.reference_height, "horizontal_margin": self.horizontal_margin,
                "vertical_margin": self.vertical_margin, "maximum_subtitle_height": self.maximum_subtitle_height,
                "maximum_chinese_lines": self.maximum_chinese_lines, "maximum_english_lines": self.maximum_english_lines,
                "maximum_total_lines": self.maximum_total_lines, "alignment": self.alignment,
                "font": self.font.to_dict(), "chinese": self.chinese.to_dict(), "english": self.english.to_dict(),
                "outline_color": self.outline_color, "outline_width": self.outline_width,
                "shadow": self.shadow, "encoder": self.encoder.to_dict()}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RenderProfileDTO":
        data = dict(_keys(data, ("name", "version", "layout_version", "output_mode", "reference_width", "reference_height",
                                "horizontal_margin", "vertical_margin", "maximum_subtitle_height", "maximum_chinese_lines",
                                "maximum_english_lines", "maximum_total_lines", "alignment", "font", "chinese", "english",
                                "outline_color", "outline_width", "shadow", "encoder"), "profile"))
        for name, dtype in (("font", RenderFontSpecDTO), ("chinese", RenderTextStyleDTO),
                            ("english", RenderTextStyleDTO), ("encoder", RenderEncoderDTO)):
            data[name] = dtype.from_dict(data[name])
        return cls(**data)


@dataclass(frozen=True)
class RenderToolsDTO:
    pysubs2_version: str
    ffmpeg_version: str
    ffprobe_version: str
    libass_version: str
    libx264_version: str

    def __post_init__(self) -> None:
        for name, value in self.to_dict().items():
            _string(value, name)

    def to_dict(self) -> dict[str, str]:
        return {"pysubs2_version": self.pysubs2_version, "ffmpeg_version": self.ffmpeg_version,
                "ffprobe_version": self.ffprobe_version, "libass_version": self.libass_version,
                "libx264_version": self.libx264_version}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RenderToolsDTO":
        return cls(**_keys(data, ("pysubs2_version", "ffmpeg_version", "ffprobe_version", "libass_version", "libx264_version"), "tools"))


@dataclass(frozen=True)
class RenderTagDTO:
    key: str
    value: str

    def __post_init__(self) -> None:
        _string(self.key, "tag key")
        if not isinstance(self.value, str):
            raise ValueError("tag value must be a string")

    def to_dict(self) -> dict[str, str]:
        return {"key": self.key, "value": self.value}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RenderTagDTO":
        return cls(**_keys(data, ("key", "value"), "tag"))


def _tags(value: object) -> tuple[RenderTagDTO, ...]:
    tags = _typed_tuple(value, RenderTagDTO, "tags")
    if len({item.key for item in tags}) != len(tags):
        raise ValueError("tags must not contain duplicate keys")
    if tuple(item.key for item in tags) != tuple(sorted(item.key for item in tags)):
        raise ValueError("tags must use lexicographic key order")
    return tags


@dataclass(frozen=True)
class RenderChapterDTO:
    id: int
    start_us: int
    end_us: int
    tags: tuple[RenderTagDTO, ...] = ()

    def __post_init__(self) -> None:
        for name in ("id", "start_us", "end_us"):
            _integer(getattr(self, name), name)
        if self.end_us <= self.start_us:
            raise ValueError("chapter must have positive duration")
        object.__setattr__(self, "tags", _tags(self.tags))

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "start_us": self.start_us, "end_us": self.end_us,
                "tags": [tag.to_dict() for tag in self.tags]}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RenderChapterDTO":
        data = dict(_keys(data, ("id", "start_us", "end_us", "tags"), "chapter"))
        data["tags"] = tuple(RenderTagDTO.from_dict(item) for item in _array(data["tags"], "tags"))
        return cls(**data)


@dataclass(frozen=True)
class RenderVideoStreamDTO:
    index: int
    codec_name: str
    width: int
    height: int
    sar_numerator: int
    sar_denominator: int
    dar_numerator: int
    dar_denominator: int
    fps_numerator: int
    fps_denominator: int
    r_fps_numerator: int
    r_fps_denominator: int
    start_time_us: int
    duration_us: int
    frame_count: int | None
    pixel_format: str
    rotation_degrees: int
    tags: tuple[RenderTagDTO, ...] = ()

    def __post_init__(self) -> None:
        _integer(self.index, "video index")
        for name in ("width", "height", "sar_numerator", "sar_denominator", "dar_numerator", "dar_denominator",
                     "fps_numerator", "fps_denominator", "r_fps_numerator", "r_fps_denominator", "duration_us"):
            _integer(getattr(self, name), name, 1)
        _signed_integer(self.start_time_us, "video start_time_us")
        _signed_integer(self.rotation_degrees, "rotation_degrees")
        if self.frame_count is not None:
            _integer(self.frame_count, "frame_count", 1)
        _string(self.codec_name, "video codec_name")
        _string(self.pixel_format, "pixel_format")
        if self.width * self.sar_numerator * self.dar_denominator != self.height * self.sar_denominator * self.dar_numerator:
            raise ValueError("DAR must agree with encoded dimensions and SAR")
        object.__setattr__(self, "tags", _tags(self.tags))

    def to_dict(self) -> dict[str, Any]:
        return {"index": self.index, "codec_name": self.codec_name, "width": self.width, "height": self.height,
                "sar_numerator": self.sar_numerator, "sar_denominator": self.sar_denominator,
                "dar_numerator": self.dar_numerator, "dar_denominator": self.dar_denominator,
                "fps_numerator": self.fps_numerator, "fps_denominator": self.fps_denominator,
                "r_fps_numerator": self.r_fps_numerator, "r_fps_denominator": self.r_fps_denominator,
                "start_time_us": self.start_time_us, "duration_us": self.duration_us, "frame_count": self.frame_count,
                "pixel_format": self.pixel_format, "rotation_degrees": self.rotation_degrees,
                "tags": [tag.to_dict() for tag in self.tags]}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RenderVideoStreamDTO":
        data = dict(_keys(data, ("index", "codec_name", "width", "height", "sar_numerator", "sar_denominator",
                                "dar_numerator", "dar_denominator", "fps_numerator", "fps_denominator",
                                "r_fps_numerator", "r_fps_denominator", "start_time_us", "duration_us", "frame_count",
                                "pixel_format", "rotation_degrees", "tags"), "video stream"))
        data["tags"] = tuple(RenderTagDTO.from_dict(item) for item in _array(data["tags"], "tags"))
        return cls(**data)


@dataclass(frozen=True)
class RenderAudioStreamDTO:
    index: int
    codec_name: str
    sample_rate: int
    channels: int
    channel_layout: str
    start_time_us: int
    duration_us: int | None
    default: bool
    tags: tuple[RenderTagDTO, ...] = ()

    def __post_init__(self) -> None:
        _integer(self.index, "audio index")
        _string(self.codec_name, "audio codec_name")
        _integer(self.sample_rate, "sample_rate", 1)
        _integer(self.channels, "channels", 1)
        _string(self.channel_layout, "channel_layout")
        _signed_integer(self.start_time_us, "audio start_time_us")
        if self.duration_us is not None:
            _integer(self.duration_us, "audio duration_us", 1)
        _boolean(self.default, "audio default")
        object.__setattr__(self, "tags", _tags(self.tags))

    def to_dict(self) -> dict[str, Any]:
        return {"index": self.index, "codec_name": self.codec_name, "sample_rate": self.sample_rate,
                "channels": self.channels, "channel_layout": self.channel_layout, "start_time_us": self.start_time_us,
                "duration_us": self.duration_us, "default": self.default, "tags": [tag.to_dict() for tag in self.tags]}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RenderAudioStreamDTO":
        data = dict(_keys(data, ("index", "codec_name", "sample_rate", "channels", "channel_layout",
                                "start_time_us", "duration_us", "default", "tags"), "audio stream"))
        data["tags"] = tuple(RenderTagDTO.from_dict(item) for item in _array(data["tags"], "tags"))
        return cls(**data)


@dataclass(frozen=True)
class RenderMediaDTO:
    format_name: str
    duration_us: int
    start_time_us: int
    video: RenderVideoStreamDTO
    audio_streams: tuple[RenderAudioStreamDTO, ...]
    video_stream_count: int
    subtitle_stream_count: int
    data_stream_count: int
    tags: tuple[RenderTagDTO, ...] = ()
    chapters: tuple[RenderChapterDTO, ...] = ()

    def __post_init__(self) -> None:
        _string(self.format_name, "format_name")
        _integer(self.duration_us, "media duration_us", 1)
        _signed_integer(self.start_time_us, "media start_time_us")
        _typed(self.video, RenderVideoStreamDTO, "video")
        _integer(self.video_stream_count, "video_stream_count", 1)
        for name in ("subtitle_stream_count", "data_stream_count"):
            _integer(getattr(self, name), name)
        audio = _typed_tuple(self.audio_streams, RenderAudioStreamDTO, "audio_streams")
        if len({item.index for item in audio} | {self.video.index}) != len(audio) + 1:
            raise ValueError("media stream indexes must be unique")
        if tuple(item.index for item in audio) != tuple(sorted(item.index for item in audio)):
            raise ValueError("audio streams must preserve stream index order")
        object.__setattr__(self, "audio_streams", audio)
        object.__setattr__(self, "tags", _tags(self.tags))
        chapters = _typed_tuple(self.chapters, RenderChapterDTO, "chapters")
        if len({item.id for item in chapters}) != len(chapters):
            raise ValueError("chapter IDs must be unique")
        if any(item.end_us > self.duration_us for item in chapters) or any(left.end_us > right.start_us for left, right in zip(chapters, chapters[1:])):
            raise ValueError("chapters must be ordered, non-overlapping and within media duration")
        object.__setattr__(self, "chapters", chapters)

    def to_dict(self) -> dict[str, Any]:
        return {"format_name": self.format_name, "duration_us": self.duration_us, "start_time_us": self.start_time_us,
                "video": self.video.to_dict(), "audio_streams": [item.to_dict() for item in self.audio_streams],
                "video_stream_count": self.video_stream_count, "subtitle_stream_count": self.subtitle_stream_count,
                "data_stream_count": self.data_stream_count, "tags": [tag.to_dict() for tag in self.tags],
                "chapters": [chapter.to_dict() for chapter in self.chapters]}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RenderMediaDTO":
        data = dict(_keys(data, ("format_name", "duration_us", "start_time_us", "video", "audio_streams",
                                "video_stream_count", "subtitle_stream_count", "data_stream_count", "tags", "chapters"), "media"))
        data["video"] = RenderVideoStreamDTO.from_dict(data["video"])
        for name, dtype in (("audio_streams", RenderAudioStreamDTO), ("tags", RenderTagDTO), ("chapters", RenderChapterDTO)):
            data[name] = tuple(dtype.from_dict(item) for item in _array(data[name], name))
        return cls(**data)


@dataclass(frozen=True)
class RenderBoundsDTO:
    left: float
    top: float
    right: float
    bottom: float

    def __post_init__(self) -> None:
        for name in ("left", "top", "right", "bottom"):
            _number(getattr(self, name), name)
        if self.right <= self.left or self.bottom <= self.top:
            raise ValueError("bounds must be a non-empty rectangle")

    def contains(self, other: "RenderBoundsDTO") -> bool:
        _typed(other, RenderBoundsDTO, "bounds")
        return self.left <= other.left < other.right <= self.right and self.top <= other.top < other.bottom <= self.bottom

    def to_dict(self) -> dict[str, float]:
        return {"left": self.left, "top": self.top, "right": self.right, "bottom": self.bottom}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RenderBoundsDTO":
        return cls(**_keys(data, ("left", "top", "right", "bottom"), "bounds"))


@dataclass(frozen=True)
class RenderLineMetricsDTO:
    width: float
    height: float

    def __post_init__(self) -> None:
        _number(self.width, "line width", positive=True)
        _number(self.height, "line height", positive=True)

    def to_dict(self) -> dict[str, float]:
        return {"width": self.width, "height": self.height}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RenderLineMetricsDTO":
        return cls(**_keys(data, ("width", "height"), "line metrics"))


@dataclass(frozen=True)
class RenderScaledStyleDTO:
    play_res_x: int
    play_res_y: int
    horizontal_margin: int
    vertical_margin: int
    maximum_subtitle_height: int
    chinese_font_size: int
    english_font_size: int
    outline_width: int
    shadow: int
    maximum_chinese_lines: int = 2
    maximum_english_lines: int = 2
    maximum_total_lines: int = 4
    alignment: int = 2

    def __post_init__(self) -> None:
        for name in ("play_res_x", "play_res_y", "maximum_subtitle_height", "chinese_font_size", "english_font_size",
                     "maximum_chinese_lines", "maximum_english_lines", "maximum_total_lines", "alignment"):
            _integer(getattr(self, name), name, 1)
        for name in ("horizontal_margin", "vertical_margin", "outline_width", "shadow"):
            _integer(getattr(self, name), name)
        if (self.maximum_chinese_lines, self.maximum_english_lines, self.maximum_total_lines, self.alignment) != (2, 2, 4, 2):
            raise ValueError("unsupported scaled line limits/alignment")
        if self.horizontal_margin * 2 >= self.play_res_x or self.vertical_margin + self.maximum_subtitle_height > self.play_res_y:
            raise ValueError("scaled safe area must fit the video resolution")

    def to_dict(self) -> dict[str, int]:
        return {"play_res_x": self.play_res_x, "play_res_y": self.play_res_y,
                "horizontal_margin": self.horizontal_margin, "vertical_margin": self.vertical_margin,
                "maximum_subtitle_height": self.maximum_subtitle_height, "chinese_font_size": self.chinese_font_size,
                "english_font_size": self.english_font_size, "outline_width": self.outline_width, "shadow": self.shadow,
                "maximum_chinese_lines": self.maximum_chinese_lines, "maximum_english_lines": self.maximum_english_lines,
                "maximum_total_lines": self.maximum_total_lines, "alignment": self.alignment}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RenderScaledStyleDTO":
        return cls(**_keys(data, ("play_res_x", "play_res_y", "horizontal_margin", "vertical_margin", "maximum_subtitle_height",
                                 "chinese_font_size", "english_font_size", "outline_width", "shadow", "maximum_chinese_lines",
                                 "maximum_english_lines", "maximum_total_lines", "alignment"), "scaled style"))


def _offsets(value: object, name: str) -> tuple[int, ...]:
    result = _array(value, name)
    for item in result:
        _integer(item, name, 1)
    if len(result) > 1:
        raise ValueError("v1 permits at most one visual break per language")
    return result


@dataclass(frozen=True)
class RenderCueDTO:
    id: str
    start_ms: int
    end_ms: int
    ass_start_ms: int
    ass_end_ms: int
    start_delta_ms: int
    end_delta_ms: int
    chinese_text_sha256: str
    english_text_sha256: str
    chinese_break_offsets: tuple[int, ...]
    english_break_offsets: tuple[int, ...]
    chinese_lines: tuple[RenderLineMetricsDTO, ...]
    english_lines: tuple[RenderLineMetricsDTO, ...]
    expected_bounds: RenderBoundsDTO

    def __post_init__(self) -> None:
        _cue_id(self.id)
        for name in ("start_ms", "end_ms", "ass_start_ms", "ass_end_ms"):
            _integer(getattr(self, name), name)
        if self.start_ms >= self.end_ms or self.ass_start_ms >= self.ass_end_ms:
            raise ValueError("original and ASS cue intervals must have positive duration")
        for prefix in ("start", "end"):
            delta = _signed_integer(getattr(self, f"{prefix}_delta_ms"), f"{prefix}_delta_ms")
            original, projected = getattr(self, f"{prefix}_ms"), getattr(self, f"ass_{prefix}_ms")
            if projected != project_ass_time_ms(original) or delta != projected - original or abs(delta) > 5:
                raise ValueError("ASS times and deltas must match nearest-10ms half-up projection")
        for name in ("chinese_text_sha256", "english_text_sha256"):
            _hash(getattr(self, name), name)
        for language in ("chinese", "english"):
            offsets = _offsets(getattr(self, f"{language}_break_offsets"), f"{language}_break_offsets")
            lines = _typed_tuple(getattr(self, f"{language}_lines"), RenderLineMetricsDTO, f"{language}_lines")
            if len(lines) != len(offsets) + 1:
                raise ValueError("visual line metrics must match break offsets plus one")
            object.__setattr__(self, f"{language}_break_offsets", offsets)
            object.__setattr__(self, f"{language}_lines", lines)
        _typed(self.expected_bounds, RenderBoundsDTO, "expected_bounds")

    def visual_lines(self, source_cue: SubtitleCueDTO) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Return Chinese then English slices without deleting even boundary whitespace."""
        _typed(source_cue, SubtitleCueDTO, "source_cue")
        if (source_cue.id, source_cue.start_ms, source_cue.end_ms) != (self.id, self.start_ms, self.end_ms):
            raise ValueError("render cue must preserve authoritative ID and millisecond times")
        result = []
        for language in ("chinese", "english"):
            text = getattr(source_cue, f"{language}_text")
            if _digest(text) != getattr(self, f"{language}_text_sha256"):
                raise ValueError("render cue logical text fingerprint must match source cue")
            offsets = getattr(self, f"{language}_break_offsets")
            if any(offset >= len(text) for offset in offsets):
                raise ValueError("visual offsets must be internal to the source logical text")
            boundaries = (0, *offsets, len(text))
            lines = tuple(text[start:end] for start, end in zip(boundaries, boundaries[1:]))
            if any(not line.strip() for line in lines) or "".join(lines) != text:
                raise ValueError("visual lines must exactly reconstruct non-empty source logical text")
            result.append(lines)
        return result[0], result[1]

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "start_ms": self.start_ms, "end_ms": self.end_ms,
                "ass_start_ms": self.ass_start_ms, "ass_end_ms": self.ass_end_ms,
                "start_delta_ms": self.start_delta_ms, "end_delta_ms": self.end_delta_ms,
                "chinese_text_sha256": self.chinese_text_sha256, "english_text_sha256": self.english_text_sha256,
                "chinese_break_offsets": list(self.chinese_break_offsets), "english_break_offsets": list(self.english_break_offsets),
                "chinese_lines": [line.to_dict() for line in self.chinese_lines],
                "english_lines": [line.to_dict() for line in self.english_lines], "expected_bounds": self.expected_bounds.to_dict()}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RenderCueDTO":
        data = dict(_keys(data, ("id", "start_ms", "end_ms", "ass_start_ms", "ass_end_ms", "start_delta_ms", "end_delta_ms",
                                "chinese_text_sha256", "english_text_sha256", "chinese_break_offsets", "english_break_offsets",
                                "chinese_lines", "english_lines", "expected_bounds"), "render cue"))
        for name in ("chinese_lines", "english_lines"):
            data[name] = tuple(RenderLineMetricsDTO.from_dict(item) for item in _array(data[name], name))
        data["expected_bounds"] = RenderBoundsDTO.from_dict(data["expected_bounds"])
        return cls(**data)


def _evidence_map(value: object, kinds: Mapping[str, ArtifactType], name: str) -> Mapping[str, RenderArtifactEvidenceDTO]:
    items = _keys(value, tuple(kinds), name)
    for key, kind in kinds.items():
        _typed(items[key], RenderArtifactEvidenceDTO, f"{name}.{key}")
        if items[key].path != canonical_filename(kind):
            raise ValueError(f"{name}.{key} must use its canonical filename")
    return MappingProxyType({key: items[key] for key in kinds})


@dataclass(frozen=True)
class SubtitleRenderPlanDTO:
    asset_id: str
    inputs: Mapping[str, RenderArtifactEvidenceDTO]
    input_media: RenderMediaDTO
    profile: RenderProfileDTO
    profile_sha256: str
    font: RenderFontIdentityDTO
    tools: RenderToolsDTO
    scaled_style: RenderScaledStyleDTO
    safe_area: RenderBoundsDTO
    cues: tuple[RenderCueDTO, ...]
    stream_mapping: RenderStreamMappingDTO = field(default_factory=RenderStreamMappingDTO)
    ass_serialization_version: str = ASS_SERIALIZATION_VERSION
    ass_timing_policy: str = ASS_TIMING_POLICY
    schema_version: str = SUBTITLE_RENDER_PLAN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SUBTITLE_RENDER_PLAN_SCHEMA_VERSION:
            raise ValueError("unsupported rendering plan schema")
        _asset_id(self.asset_id)
        object.__setattr__(self, "inputs", _evidence_map(self.inputs, _INPUT_TYPES, "inputs"))
        for name, dtype in (("input_media", RenderMediaDTO), ("profile", RenderProfileDTO), ("font", RenderFontIdentityDTO),
                            ("tools", RenderToolsDTO), ("scaled_style", RenderScaledStyleDTO), ("safe_area", RenderBoundsDTO),
                            ("stream_mapping", RenderStreamMappingDTO)):
            _typed(getattr(self, name), dtype, name)
        _hash(self.profile_sha256, "profile_sha256")
        if self.profile_sha256 != self.profile.sha256 or self.font.spec != self.profile.font:
            raise ValueError("plan profile/font identities must match complete profile")
        if self.ass_serialization_version != ASS_SERIALIZATION_VERSION or self.ass_timing_policy != ASS_TIMING_POLICY:
            raise ValueError("unsupported ASS serialization or timing policy")
        style, video, profile = self.scaled_style, self.input_media.video, self.profile
        if (style.play_res_x, style.play_res_y) != (video.width, video.height):
            raise ValueError("ASS PlayRes must match actual video resolution")
        scaled = lambda base, pixels, reference: (2 * base * pixels + reference) // (2 * reference)
        expected = {"horizontal_margin": scaled(profile.horizontal_margin, video.width, profile.reference_width),
                    "vertical_margin": scaled(profile.vertical_margin, video.height, profile.reference_height),
                    "maximum_subtitle_height": scaled(profile.maximum_subtitle_height, video.height, profile.reference_height),
                    "chinese_font_size": scaled(profile.chinese.font_size, video.height, profile.reference_height),
                    "english_font_size": scaled(profile.english.font_size, video.height, profile.reference_height),
                    "outline_width": scaled(profile.outline_width, video.height, profile.reference_height),
                    "shadow": scaled(profile.shadow, video.height, profile.reference_height)}
        if any(getattr(style, name) != value for name, value in expected.items()):
            raise ValueError("scaled style must use profile round-half-up scaling")
        bottom = video.height - style.vertical_margin
        if self.safe_area != RenderBoundsDTO(style.horizontal_margin, bottom - style.maximum_subtitle_height,
                                             video.width - style.horizontal_margin, bottom):
            raise ValueError("plan safe area must match scaled profile")
        cues = _typed_tuple(self.cues, RenderCueDTO, "cues")
        if not cues:
            raise ValueError("render plan must contain cues")
        previous_end, previous_ass_end = 0, 0
        for position, cue in enumerate(cues, 1):
            if cue.id != f"c{position}" or cue.start_ms < previous_end or cue.ass_start_ms < previous_ass_end:
                raise ValueError("render cues must use c1..cN and non-overlapping original/ASS timelines")
            if max(cue.end_ms, cue.ass_end_ms) * 1000 > video.duration_us:
                raise ValueError("original and ASS cue intervals must fit usable video duration")
            if not self.safe_area.contains(cue.expected_bounds):
                raise ValueError("expected cue bounds must fit safe area")
            if any(line.width > self.safe_area.right - self.safe_area.left for line in (*cue.chinese_lines, *cue.english_lines)):
                raise ValueError("measured line width must fit safe area")
            previous_end, previous_ass_end = cue.end_ms, cue.ass_end_ms
        object.__setattr__(self, "cues", cues)

    def validate_against_subtitle_plan(self, source: SubtitlePlanDTO) -> None:
        _typed(source, SubtitlePlanDTO, "source subtitle plan")
        if self.inputs["video"].sha256 != source.video_sha256 or len(self.cues) != len(source.cues):
            raise ValueError("render plan must match source video fingerprint and cue count")
        for cue, source_cue in zip(self.cues, source.cues):
            cue.visual_lines(source_cue)
            if cue.ass_end_ms > source.media.usable_duration_ms:
                raise ValueError("ASS projection must fit authoritative usable media duration")

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "asset_id": self.asset_id,
                "inputs": {key: item.to_dict() for key, item in self.inputs.items()}, "input_media": self.input_media.to_dict(),
                "profile": self.profile.to_dict(), "profile_sha256": self.profile_sha256, "font": self.font.to_dict(),
                "tools": self.tools.to_dict(), "scaled_style": self.scaled_style.to_dict(), "safe_area": self.safe_area.to_dict(),
                "cues": [cue.to_dict() for cue in self.cues], "ass_serialization_version": self.ass_serialization_version,
                "ass_timing_policy": self.ass_timing_policy, "stream_mapping": self.stream_mapping.to_dict()}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SubtitleRenderPlanDTO":
        data = dict(_keys(data, ("schema_version", "asset_id", "inputs", "input_media", "profile", "profile_sha256", "font",
                                "tools", "scaled_style", "safe_area", "cues", "ass_serialization_version", "ass_timing_policy",
                                "stream_mapping"), "render plan"))
        data["inputs"] = {key: RenderArtifactEvidenceDTO.from_dict(item) for key, item in _keys(data["inputs"], tuple(_INPUT_TYPES), "inputs").items()}
        for name, dtype in (("input_media", RenderMediaDTO), ("profile", RenderProfileDTO), ("font", RenderFontIdentityDTO),
                            ("tools", RenderToolsDTO), ("scaled_style", RenderScaledStyleDTO), ("safe_area", RenderBoundsDTO),
                            ("stream_mapping", RenderStreamMappingDTO)):
            data[name] = dtype.from_dict(data[name])
        data["cues"] = tuple(RenderCueDTO.from_dict(item) for item in _array(data["cues"], "cues"))
        return cls(**data)


@dataclass(frozen=True)
class RenderFindingDTO:
    code: str
    severity: str
    cue_id: str | None = None
    start_ms: int | None = None
    end_ms: int | None = None
    observed_width: float | None = None
    observed_height: float | None = None
    bounds: RenderBoundsDTO | None = None
    diagnostic: str | None = None

    def __post_init__(self) -> None:
        _string(self.code, "finding code")
        if self.severity not in ("info", "warning", "error"):
            raise ValueError("finding severity must be info, warning or error")
        if self.cue_id is not None:
            _cue_id(self.cue_id)
        if (self.start_ms is None) != (self.end_ms is None):
            raise ValueError("finding time endpoints must both be present or null")
        if self.start_ms is not None:
            _integer(self.start_ms, "finding start_ms")
            _integer(self.end_ms, "finding end_ms")
            if self.end_ms < self.start_ms:
                raise ValueError("finding time interval must be ordered")
        for name in ("observed_width", "observed_height"):
            if getattr(self, name) is not None:
                _number(getattr(self, name), name)
        if self.bounds is not None:
            _typed(self.bounds, RenderBoundsDTO, "finding bounds")
        if self.diagnostic is not None and (not isinstance(self.diagnostic, str) or len(self.diagnostic) > 2048):
            raise ValueError("finding diagnostic must be a string of at most 2048 characters")

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "severity": self.severity, "cue_id": self.cue_id,
                "start_ms": self.start_ms, "end_ms": self.end_ms, "observed_width": self.observed_width,
                "observed_height": self.observed_height, "bounds": None if self.bounds is None else self.bounds.to_dict(),
                "diagnostic": self.diagnostic}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RenderFindingDTO":
        data = dict(_keys(data, ("code", "severity", "cue_id", "start_ms", "end_ms", "observed_width",
                                "observed_height", "bounds", "diagnostic"), "finding"))
        if data["bounds"] is not None:
            data["bounds"] = RenderBoundsDTO.from_dict(data["bounds"])
        return cls(**data)


@dataclass(frozen=True)
class RenderPixelResultDTO:
    cue_id: str
    time_ms: int
    bounds: RenderBoundsDTO
    line_count: int
    font_identity_matches: bool
    styles_match: bool

    def __post_init__(self) -> None:
        _cue_id(self.cue_id)
        _integer(self.time_ms, "pixel time_ms")
        _typed(self.bounds, RenderBoundsDTO, "pixel bounds")
        _integer(self.line_count, "pixel line_count", 1)
        if self.line_count > 4:
            raise ValueError("pixel result must not contain a fifth visual line")
        _boolean(self.font_identity_matches, "font_identity_matches")
        _boolean(self.styles_match, "styles_match")

    def to_dict(self) -> dict[str, Any]:
        return {"cue_id": self.cue_id, "time_ms": self.time_ms, "bounds": self.bounds.to_dict(),
                "line_count": self.line_count, "font_identity_matches": self.font_identity_matches,
                "styles_match": self.styles_match}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RenderPixelResultDTO":
        data = dict(_keys(data, ("cue_id", "time_ms", "bounds", "line_count", "font_identity_matches", "styles_match"), "pixel result"))
        data["bounds"] = RenderBoundsDTO.from_dict(data["bounds"])
        return cls(**data)


@dataclass(frozen=True)
class RenderSummaryDTO:
    cue_count: int
    chinese_line_counts: tuple[int, int]
    english_line_counts: tuple[int, int]
    four_line_cue_count: int
    maximum_width: float
    maximum_height: float
    warning_count: int
    error_count: int
    font_glyph_passed: bool
    ass_round_trip_passed: bool
    pixel_preflight_passed: bool
    output_media_passed: bool

    def __post_init__(self) -> None:
        for name in ("cue_count", "four_line_cue_count", "warning_count", "error_count"):
            _integer(getattr(self, name), name)
        if self.four_line_cue_count > self.cue_count:
            raise ValueError("four-line count must not exceed cue count")
        for name in ("chinese_line_counts", "english_line_counts"):
            counts = _array(getattr(self, name), name)
            if len(counts) != 2:
                raise ValueError("line distribution must contain exactly one-line and two-line counts")
            for count in counts:
                _integer(count, name)
            if sum(counts) != self.cue_count:
                raise ValueError("line distribution must sum to cue_count")
            object.__setattr__(self, name, counts)
        for name in ("maximum_width", "maximum_height"):
            _number(getattr(self, name), name)
        for name in ("font_glyph_passed", "ass_round_trip_passed", "pixel_preflight_passed", "output_media_passed"):
            _boolean(getattr(self, name), name)

    @property
    def all_qa_passed(self) -> bool:
        return self.font_glyph_passed and self.ass_round_trip_passed and self.pixel_preflight_passed and self.output_media_passed

    def to_dict(self) -> dict[str, Any]:
        return {"cue_count": self.cue_count, "chinese_line_counts": list(self.chinese_line_counts),
                "english_line_counts": list(self.english_line_counts), "four_line_cue_count": self.four_line_cue_count,
                "maximum_width": self.maximum_width, "maximum_height": self.maximum_height,
                "warning_count": self.warning_count, "error_count": self.error_count,
                "font_glyph_passed": self.font_glyph_passed, "ass_round_trip_passed": self.ass_round_trip_passed,
                "pixel_preflight_passed": self.pixel_preflight_passed, "output_media_passed": self.output_media_passed}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RenderSummaryDTO":
        return cls(**_keys(data, ("cue_count", "chinese_line_counts", "english_line_counts", "four_line_cue_count",
                                 "maximum_width", "maximum_height", "warning_count", "error_count", "font_glyph_passed",
                                 "ass_round_trip_passed", "pixel_preflight_passed", "output_media_passed"), "summary"))

    def validate_against_plan(self, plan: SubtitleRenderPlanDTO) -> None:
        _typed(plan, SubtitleRenderPlanDTO, "plan")
        for language in ("chinese", "english"):
            distribution = tuple(sum(len(getattr(cue, f"{language}_lines")) == count for cue in plan.cues) for count in (1, 2))
            if getattr(self, f"{language}_line_counts") != distribution:
                raise ValueError("summary line distribution must match plan")
        four_lines = sum(len(cue.chinese_lines) + len(cue.english_lines) == 4 for cue in plan.cues)
        maximum_width = max(line.width for cue in plan.cues for line in (*cue.chinese_lines, *cue.english_lines))
        maximum_height = max(cue.expected_bounds.bottom - cue.expected_bounds.top for cue in plan.cues)
        if (self.cue_count, self.four_line_cue_count, self.maximum_width, self.maximum_height) != (len(plan.cues), four_lines, maximum_width, maximum_height):
            raise ValueError("summary counts and measured maximum dimensions must match plan")


@dataclass(frozen=True)
class SubtitleRenderReportDTO:
    asset_id: str
    status: str
    summary: RenderSummaryDTO
    findings: tuple[RenderFindingDTO, ...]
    pixel_results: tuple[RenderPixelResultDTO, ...]
    error_category: str | None = None
    schema_version: str = SUBTITLE_RENDER_REPORT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SUBTITLE_RENDER_REPORT_SCHEMA_VERSION:
            raise ValueError("unsupported rendering report schema")
        _asset_id(self.asset_id)
        if self.status not in ("succeeded", "failed"):
            raise ValueError("report status must be succeeded or failed")
        _typed(self.summary, RenderSummaryDTO, "summary")
        findings = _typed_tuple(self.findings, RenderFindingDTO, "findings")
        pixels = _typed_tuple(self.pixel_results, RenderPixelResultDTO, "pixel_results")
        if len({item.cue_id for item in pixels}) != len(pixels):
            raise ValueError("pixel results must not repeat cues")
        object.__setattr__(self, "findings", findings)
        object.__setattr__(self, "pixel_results", pixels)
        if self.summary.warning_count != sum(item.severity == "warning" for item in findings) or self.summary.error_count != sum(item.severity == "error" for item in findings):
            raise ValueError("report warning/error counts must match findings")
        if self.status == "succeeded":
            if self.error_category is not None or self.summary.error_count or not self.summary.all_qa_passed or not self.summary.cue_count:
                raise ValueError("successful report requires all QA and no errors")
            if tuple(item.cue_id for item in pixels) != tuple(f"c{position}" for position in range(1, self.summary.cue_count + 1)):
                raise ValueError("successful report requires all c1..cN pixel results in order")
            if any(not item.font_identity_matches or not item.styles_match for item in pixels):
                raise ValueError("successful report requires exact font and styles for every cue")
        elif not isinstance(self.error_category, str) or self.error_category not in RENDER_ERROR_CATEGORIES:
            raise ValueError("failed report requires a stable rendering error category")

    def validate_against_plan(self, plan: SubtitleRenderPlanDTO) -> None:
        _typed(plan, SubtitleRenderPlanDTO, "plan")
        if self.asset_id != plan.asset_id:
            raise ValueError("report asset must match plan")
        self.summary.validate_against_plan(plan)
        by_id = {cue.id: cue for cue in plan.cues}
        for finding in self.findings:
            if finding.cue_id is not None:
                cue = by_id.get(finding.cue_id)
                if cue is None or (finding.start_ms is not None and (finding.start_ms, finding.end_ms) != (cue.start_ms, cue.end_ms)):
                    raise ValueError("finding must reference an existing cue and original times")
        for pixel in self.pixel_results:
            cue = by_id.get(pixel.cue_id)
            if cue is None or pixel.time_ms != (cue.ass_start_ms + cue.ass_end_ms) // 2:
                raise ValueError("pixel result must sample the ASS projected midpoint")
            if self.status == "succeeded" and (not plan.safe_area.contains(pixel.bounds) or pixel.line_count != len(cue.chinese_lines) + len(cue.english_lines)):
                raise ValueError("pixel bounds and line count must match a safe successful plan")

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "asset_id": self.asset_id, "status": self.status,
                "summary": self.summary.to_dict(), "findings": [finding.to_dict() for finding in self.findings],
                "pixel_results": [pixel.to_dict() for pixel in self.pixel_results], "error_category": self.error_category}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SubtitleRenderReportDTO":
        data = dict(_keys(data, ("schema_version", "asset_id", "status", "summary", "findings", "pixel_results", "error_category"), "render report"))
        data["summary"] = RenderSummaryDTO.from_dict(data["summary"])
        for name, dtype in (("findings", RenderFindingDTO), ("pixel_results", RenderPixelResultDTO)):
            data[name] = tuple(dtype.from_dict(item) for item in _array(data[name], name))
        return cls(**data)


@dataclass(frozen=True)
class SubtitleRenderManifestDTO:
    asset_id: str
    status: str
    completed_at: str
    inputs: Mapping[str, RenderArtifactEvidenceDTO]
    profile: RenderProfileDTO
    profile_sha256: str
    font: RenderFontIdentityDTO
    tools: RenderToolsDTO
    input_media: RenderMediaDTO
    output_media: RenderMediaDTO
    outputs: Mapping[str, RenderArtifactEvidenceDTO]
    summary: RenderSummaryDTO
    schema_version: str = SUBTITLE_RENDER_MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SUBTITLE_RENDER_MANIFEST_SCHEMA_VERSION:
            raise ValueError("unsupported rendering manifest schema")
        _asset_id(self.asset_id)
        if self.status != "succeeded":
            raise ValueError("render manifest status must be succeeded")
        if not isinstance(self.completed_at, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?Z", self.completed_at) is None:
            raise ValueError("completed_at must be an ISO 8601 UTC timestamp")
        try:
            datetime.fromisoformat(self.completed_at.removesuffix("Z") + "+00:00")
        except ValueError as error:
            raise ValueError("completed_at must be a valid ISO 8601 UTC timestamp") from error
        for name, dtype in (("profile", RenderProfileDTO), ("font", RenderFontIdentityDTO), ("tools", RenderToolsDTO),
                            ("input_media", RenderMediaDTO), ("output_media", RenderMediaDTO), ("summary", RenderSummaryDTO)):
            _typed(getattr(self, name), dtype, name)
        _hash(self.profile_sha256, "profile_sha256")
        if self.profile_sha256 != self.profile.sha256 or self.font.spec != self.profile.font:
            raise ValueError("manifest profile/font identities must match complete profile")
        if not self.summary.cue_count or self.summary.error_count or not self.summary.all_qa_passed:
            raise ValueError("successful manifest must describe non-empty, successful QA")
        object.__setattr__(self, "inputs", _evidence_map(self.inputs, _INPUT_TYPES, "inputs"))
        object.__setattr__(self, "outputs", _evidence_map(self.outputs, _OUTPUT_TYPES, "outputs"))
        if self.output_media.video_stream_count != 1 or self.output_media.video.codec_name != "h264" or self.output_media.video.pixel_format != self.profile.encoder.pixel_format or self.output_media.subtitle_stream_count or self.output_media.data_stream_count:
            raise ValueError("successful output must contain one H.264 video and no subtitle/data streams")

    def validate_against_plan_and_report(self, plan: SubtitleRenderPlanDTO, report: SubtitleRenderReportDTO) -> None:
        _typed(plan, SubtitleRenderPlanDTO, "plan")
        _typed(report, SubtitleRenderReportDTO, "report")
        if self.asset_id != plan.asset_id or self.asset_id != report.asset_id or report.status != "succeeded":
            raise ValueError("manifest, plan and successful report must describe the same asset")
        for name in ("inputs", "profile", "profile_sha256", "font", "tools", "input_media"):
            if getattr(self, name) != getattr(plan, name):
                raise ValueError("manifest inputs, profile, font, tools and media must match plan")
        if self.summary != report.summary:
            raise ValueError("manifest summary must match report")
        report.validate_against_plan(plan)

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "asset_id": self.asset_id, "status": self.status,
                "completed_at": self.completed_at, "inputs": {key: item.to_dict() for key, item in self.inputs.items()},
                "profile": self.profile.to_dict(), "profile_sha256": self.profile_sha256, "font": self.font.to_dict(),
                "tools": self.tools.to_dict(), "input_media": self.input_media.to_dict(), "output_media": self.output_media.to_dict(),
                "outputs": {key: item.to_dict() for key, item in self.outputs.items()}, "summary": self.summary.to_dict()}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SubtitleRenderManifestDTO":
        data = dict(_keys(data, ("schema_version", "asset_id", "status", "completed_at", "inputs", "profile", "profile_sha256",
                                "font", "tools", "input_media", "output_media", "outputs", "summary"), "render manifest"))
        for name, kinds in (("inputs", _INPUT_TYPES), ("outputs", _OUTPUT_TYPES)):
            data[name] = {key: RenderArtifactEvidenceDTO.from_dict(item) for key, item in _keys(data[name], tuple(kinds), name).items()}
        for name, dtype in (("profile", RenderProfileDTO), ("font", RenderFontIdentityDTO), ("tools", RenderToolsDTO),
                            ("input_media", RenderMediaDTO), ("output_media", RenderMediaDTO), ("summary", RenderSummaryDTO)):
            data[name] = dtype.from_dict(data[name])
        return cls(**data)
