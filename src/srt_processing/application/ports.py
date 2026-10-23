"""Library-neutral dependencies of the subtitle workflow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping, Protocol

from archive_core.interfaces import SubtitleCodecDTO, SubtitlePlanDTO


SubtitleLanguage = Literal["english", "chinese", "bilingual"]


class ChineseWordSegmenter(Protocol):
    @property
    def identity(self) -> Mapping[str, str]: ...

    def spans(self, text: str) -> tuple[tuple[int, int], ...]:
        """Return an exact ordered code-point partition without rewriting text."""
        ...


class SubtitleArtifactStore(Protocol):
    def exists(self, path: str) -> bool: ...

    def read_bytes(self, path: str) -> bytes: ...

    def size(self, path: str) -> int: ...

    def sha256(self, path: str) -> str: ...

    def stage_bytes(self, target_path: str, data: bytes) -> str:
        """Prepare a same-filesystem temporary file without replacing its target."""
        ...

    def publish(self, staged_path: str, target_path: str, *, overwrite: bool) -> None:
        """Atomically publish one prepared file, not a multi-file transaction."""
        ...


@dataclass(frozen=True)
class MediaProbeResult:
    video_duration_ms: int
    fps_numerator: int
    fps_denominator: int
    tool_version: str

    def __post_init__(self) -> None:
        for name in ("video_duration_ms", "fps_numerator", "fps_denominator"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if not isinstance(self.tool_version, str) or not self.tool_version.strip():
            raise ValueError("tool_version must be a non-empty string")


class MediaProbe(Protocol):
    def probe(self, video_path: str) -> MediaProbeResult: ...


@dataclass(frozen=True)
class SrtCue:
    index: int
    start_ms: int
    end_ms: int
    text: str

    def __post_init__(self) -> None:
        if type(self.index) is not int or self.index <= 0:
            raise ValueError("index must be a positive integer")
        if type(self.start_ms) is not int or self.start_ms < 0:
            raise ValueError("start_ms must be a non-negative integer")
        if type(self.end_ms) is not int or self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be an integer greater than start_ms")
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("text must be a non-empty string")


class SrtCodec(Protocol):
    @property
    def identity(self) -> SubtitleCodecDTO: ...

    def encode(self, plan: SubtitlePlanDTO, language: SubtitleLanguage) -> bytes: ...

    def decode(self, data: bytes) -> tuple[SrtCue, ...]: ...


class Clock(Protocol):
    def now_utc(self) -> str: ...
