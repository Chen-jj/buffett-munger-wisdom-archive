"""Pure word-level forced-alignment models and interpolation policy."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
import re
from typing import Any, Mapping, Sequence

from .audio_asr import ProviderIdentity, RawAsrArtifact, SourceTimeSpan


ALIGNED_ASR_SCHEMA_VERSION = "transcription.aligned-asr.v1"

_OPENING_PUNCTUATION = frozenset("([{“‘$")
_LEXICAL_OR_PUNCTUATION_RE = re.compile(
    r"[$£€]?\d{1,3}(?:,\d{3})+(?:\.\d+)?%?"
    r"|[$£€]?\d+(?:\.\d+)?%?"
    r"|[\w]+(?:['’-][\w]+)*"
    r"|[^\w\s]+",
    re.UNICODE,
)


def _require_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _require_int(value: object, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _require_sequence(value: object, name: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{name} must be an array")
    return value


def tokenize_surface_text(text: str) -> tuple[str, ...]:
    """Split lexical words while attaching punctuation to neighboring words."""

    _require_text(text, "text")
    pieces = _LEXICAL_OR_PUNCTUATION_RE.findall(text)
    words: list[str] = []
    prefix = ""
    for piece in pieces:
        if any(character.isalnum() or character == "_" for character in piece):
            words.append(prefix + piece)
            prefix = ""
        elif piece and all(character in _OPENING_PUNCTUATION for character in piece):
            prefix += piece
        elif words:
            words[-1] += piece
        else:
            prefix += piece
    if prefix and words:
        words[-1] += prefix
    return tuple(word for word in words if any(character.isalnum() for character in word))


@dataclass(frozen=True)
class RawAsrToken:
    id: str
    segment_id: str
    text: str

    def __post_init__(self) -> None:
        _require_text(self.id, "id")
        if not self.id.startswith("rw"):
            raise ValueError("raw word id must use rw<one-based position>")
        suffix = self.id.removeprefix("rw")
        if not suffix.isdigit() or suffix.startswith("0"):
            raise ValueError("raw word id must use rw<one-based position>")
        _require_text(self.segment_id, "segment_id")
        _require_text(self.text, "text")
        if not any(character.isalnum() for character in self.text):
            raise ValueError("raw word text must contain lexical content")


def build_raw_asr_tokens(raw_asr: RawAsrArtifact) -> tuple[RawAsrToken, ...]:
    tokens: list[RawAsrToken] = []
    for segment in raw_asr.segments:
        segment_tokens = tokenize_surface_text(segment.text)
        if not segment_tokens:
            raise ValueError(f"raw ASR segment has no lexical words: {segment.id}")
        for text in segment_tokens:
            tokens.append(
                RawAsrToken(
                    id=f"rw{len(tokens) + 1}",
                    segment_id=segment.id,
                    text=text,
                )
            )
    return tuple(tokens)


@dataclass(frozen=True)
class AlignmentCandidate:
    raw_word_id: str
    segment_id: str
    text: str
    start_ms: int | None
    end_ms: int | None
    alignment_score: float | None
    unaligned_reason: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.raw_word_id, "raw_word_id")
        _require_text(self.segment_id, "segment_id")
        _require_text(self.text, "text")
        if (self.start_ms is None) != (self.end_ms is None):
            raise ValueError("candidate start_ms and end_ms must be provided together")
        if self.start_ms is None:
            if self.alignment_score is not None:
                raise ValueError("unaligned candidate must not have alignment_score")
            _require_text(self.unaligned_reason, "unaligned_reason")
            return
        SourceTimeSpan(self.start_ms, self.end_ms)
        if self.alignment_score is None or isinstance(self.alignment_score, bool):
            raise ValueError("acoustically aligned candidate requires alignment_score")
        if not isinstance(self.alignment_score, (int, float)) or not math.isfinite(
            float(self.alignment_score)
        ):
            raise ValueError("alignment_score must be a finite number")
        if not 0 <= float(self.alignment_score) <= 1:
            raise ValueError("alignment_score must be between 0 and 1")
        if self.unaligned_reason is not None:
            raise ValueError("aligned candidate must not have unaligned_reason")


@dataclass(frozen=True)
class InterpolationPolicy:
    version: str
    max_consecutive_words: int = 1
    max_window_ms: int = 1_500
    min_word_duration_ms: int = 80
    min_anchor_alignment_score: float = 0.5
    allowed_reasons: tuple[str, ...] = field(
        default_factory=lambda: (
            "alignment_model_no_timing",
            "numeric_or_symbol",
            "out_of_vocabulary",
        )
    )

    def __post_init__(self) -> None:
        _require_text(self.version, "version")
        _require_int(self.max_consecutive_words, "max_consecutive_words", minimum=1)
        _require_int(self.max_window_ms, "max_window_ms", minimum=1)
        _require_int(self.min_word_duration_ms, "min_word_duration_ms", minimum=1)
        if (
            isinstance(self.min_anchor_alignment_score, bool)
            or not isinstance(self.min_anchor_alignment_score, (int, float))
            or not math.isfinite(float(self.min_anchor_alignment_score))
            or not 0 <= float(self.min_anchor_alignment_score) <= 1
        ):
            raise ValueError("min_anchor_alignment_score must be between 0 and 1")
        object.__setattr__(self, "allowed_reasons", tuple(self.allowed_reasons))
        if not self.allowed_reasons or not all(
            isinstance(reason, str) and reason.strip()
            for reason in self.allowed_reasons
        ):
            raise ValueError("allowed_reasons must contain non-empty strings")

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "max_consecutive_words": self.max_consecutive_words,
            "max_window_ms": self.max_window_ms,
            "min_word_duration_ms": self.min_word_duration_ms,
            "min_anchor_alignment_score": self.min_anchor_alignment_score,
            "allowed_reasons": list(self.allowed_reasons),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "InterpolationPolicy":
        reasons = _require_sequence(data.get("allowed_reasons", []), "allowed_reasons")
        return cls(
            version=data.get("version"),
            max_consecutive_words=data.get("max_consecutive_words"),
            max_window_ms=data.get("max_window_ms"),
            min_word_duration_ms=data.get("min_word_duration_ms"),
            min_anchor_alignment_score=data.get("min_anchor_alignment_score"),
            allowed_reasons=tuple(reasons),
        )


@dataclass(frozen=True)
class ForcedAlignmentConfig:
    model: str
    model_version: str
    device: str
    interpolation: InterpolationPolicy
    language: str = "en"

    def __post_init__(self) -> None:
        _require_text(self.model, "model")
        _require_text(self.model_version, "model_version")
        _require_text(self.device, "device")
        if not isinstance(self.interpolation, InterpolationPolicy):
            raise ValueError("interpolation must be an InterpolationPolicy")
        if self.language != "en":
            raise ValueError("language must be en")

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "model_version": self.model_version,
            "device": self.device,
            "language": self.language,
            "interpolation": self.interpolation.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ForcedAlignmentConfig":
        interpolation = data.get("interpolation")
        if not isinstance(interpolation, Mapping):
            raise ValueError("interpolation must be an object")
        return cls(
            model=data.get("model"),
            model_version=data.get("model_version"),
            device=data.get("device"),
            language=data.get("language"),
            interpolation=InterpolationPolicy.from_dict(interpolation),
        )


class AlignmentTimingSource(str, Enum):
    ACOUSTIC_ALIGNMENT = "acoustic_alignment"
    INTERPOLATED = "interpolated"


@dataclass(frozen=True)
class AlignedAsrWord:
    id: str
    raw_word_id: str
    segment_id: str
    text: str
    start_ms: int
    end_ms: int
    alignment_score: float | None
    timing_source: AlignmentTimingSource
    left_anchor_id: str | None = None
    right_anchor_id: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.id, "id")
        if not self.id.startswith("aw"):
            raise ValueError("aligned word id must use aw<one-based position>")
        suffix = self.id.removeprefix("aw")
        if not suffix.isdigit() or suffix.startswith("0"):
            raise ValueError("aligned word id must use aw<one-based position>")
        _require_text(self.raw_word_id, "raw_word_id")
        _require_text(self.segment_id, "segment_id")
        _require_text(self.text, "text")
        if not any(character.isalnum() for character in self.text):
            raise ValueError("aligned word text must contain lexical content")
        SourceTimeSpan(self.start_ms, self.end_ms)
        if not isinstance(self.timing_source, AlignmentTimingSource):
            raise ValueError("timing_source must be an AlignmentTimingSource")
        if self.timing_source is AlignmentTimingSource.ACOUSTIC_ALIGNMENT:
            if self.alignment_score is None or isinstance(self.alignment_score, bool):
                raise ValueError("acoustic word requires alignment_score")
            if not isinstance(self.alignment_score, (int, float)) or not math.isfinite(
                float(self.alignment_score)
            ):
                raise ValueError("alignment_score must be a finite number")
            if not 0 <= float(self.alignment_score) <= 1:
                raise ValueError("alignment_score must be between 0 and 1")
            if self.left_anchor_id is not None or self.right_anchor_id is not None:
                raise ValueError("acoustic word must not contain interpolation anchors")
        else:
            if self.alignment_score is not None:
                raise ValueError("interpolated word alignment_score must be null")
            _require_text(self.left_anchor_id, "left_anchor_id")
            _require_text(self.right_anchor_id, "right_anchor_id")

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "raw_word_id": self.raw_word_id,
            "segment_id": self.segment_id,
            "text": self.text,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "alignment_score": self.alignment_score,
            "timing_source": self.timing_source.value,
        }
        if self.left_anchor_id is not None:
            data["left_anchor_id"] = self.left_anchor_id
            data["right_anchor_id"] = self.right_anchor_id
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AlignedAsrWord":
        return cls(
            id=data.get("id"),
            raw_word_id=data.get("raw_word_id"),
            segment_id=data.get("segment_id"),
            text=data.get("text"),
            start_ms=data.get("start_ms"),
            end_ms=data.get("end_ms"),
            alignment_score=data.get("alignment_score"),
            timing_source=AlignmentTimingSource(data.get("timing_source")),
            left_anchor_id=data.get("left_anchor_id"),
            right_anchor_id=data.get("right_anchor_id"),
        )


@dataclass(frozen=True)
class AlignedAsrArtifact:
    audio_sha256: str
    raw_asr_sha256: str
    audio_duration_ms: int
    provider: ProviderIdentity
    config: ForcedAlignmentConfig
    words: tuple[AlignedAsrWord, ...]
    cache_key: str
    language: str = "en"
    schema_version: str = ALIGNED_ASR_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != ALIGNED_ASR_SCHEMA_VERSION:
            raise ValueError(f"unsupported aligned ASR schema: {self.schema_version}")
        if self.language != "en":
            raise ValueError("language must be en")
        _require_text(self.audio_sha256, "audio_sha256")
        _require_text(self.raw_asr_sha256, "raw_asr_sha256")
        _require_int(self.audio_duration_ms, "audio_duration_ms", minimum=1)
        _require_text(self.cache_key, "cache_key")
        if not isinstance(self.provider, ProviderIdentity):
            raise ValueError("provider must be a ProviderIdentity")
        if not isinstance(self.config, ForcedAlignmentConfig):
            raise ValueError("config must be a ForcedAlignmentConfig")
        object.__setattr__(self, "words", tuple(self.words))
        previous_end = 0
        for position, word in enumerate(self.words, start=1):
            if not isinstance(word, AlignedAsrWord):
                raise ValueError("words must contain AlignedAsrWord values")
            if word.id != f"aw{position}" or word.raw_word_id != f"rw{position}":
                raise ValueError("aligned/raw word IDs must be stable and ordered")
            if word.start_ms < previous_end:
                raise ValueError("aligned words must not overlap or move backward")
            if word.end_ms > self.audio_duration_ms:
                raise ValueError("aligned word exceeds audio duration")
            previous_end = word.end_ms

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "language": self.language,
            "audio_sha256": self.audio_sha256,
            "raw_asr_sha256": self.raw_asr_sha256,
            "audio_duration_ms": self.audio_duration_ms,
            "provider": self.provider.to_dict(),
            "config": self.config.to_dict(),
            "words": [word.to_dict() for word in self.words],
            "cache_key": self.cache_key,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AlignedAsrArtifact":
        if data.get("schema_version") != ALIGNED_ASR_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported aligned ASR schema: {data.get('schema_version')}"
            )
        provider = data.get("provider")
        config = data.get("config")
        words = _require_sequence(data.get("words", []), "words")
        if not isinstance(provider, Mapping) or not isinstance(config, Mapping):
            raise ValueError("provider and config must be objects")
        return cls(
            schema_version=data.get("schema_version"),
            language=data.get("language"),
            audio_sha256=data.get("audio_sha256"),
            raw_asr_sha256=data.get("raw_asr_sha256"),
            audio_duration_ms=data.get("audio_duration_ms"),
            provider=ProviderIdentity.from_dict(provider),
            config=ForcedAlignmentConfig.from_dict(config),
            words=tuple(AlignedAsrWord.from_dict(item) for item in words),
            cache_key=data.get("cache_key"),
        )
