"""Source-neutral acquisition domain objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from archive_core.domain import AssetId


def _validate_text(value: str, field_name: str, *, allow_empty: bool = False) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    if not allow_empty and value == "":
        raise ValueError(f"{field_name} must not be empty")


def _validate_mapping(value: dict[str, Any], field_name: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be a dict")


@dataclass(frozen=True)
class AcquisitionRequest:
    """Unified acquisition input selected by registered crawlers."""

    locator: str
    hints: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_text(self.locator, "locator")
        _validate_mapping(self.hints, "hints")


@dataclass(frozen=True)
class AcquisitionTarget:
    """One concrete fetch target discovered by a source crawler."""

    asset_id: AssetId
    fetch_url: str
    hints: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.asset_id, AssetId):
            raise ValueError("asset_id must be an AssetId")
        _validate_text(self.fetch_url, "fetch_url")
        _validate_mapping(self.hints, "hints")


@dataclass(frozen=True)
class MediaReference:
    """Stable reference to the media behind an acquired source page."""

    kind: Literal["page_url", "direct_url", "embed_id"]
    value: str
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in {"page_url", "direct_url", "embed_id"}:
            raise ValueError("kind must be page_url, direct_url, or embed_id")
        _validate_text(self.value, "value")
        _validate_mapping(self.extra, "extra")

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "value": self.value,
            "extra": self.extra,
        }


@dataclass(frozen=True)
class TranscriptParagraph:
    """One source-neutral transcript paragraph and its explicit metadata."""

    text: str
    speaker_label: str | None = None
    stage_directions: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or (self.text and not self.text.strip()):
            raise ValueError("text must contain spoken text or be empty")
        if self.speaker_label is not None:
            if (
                not isinstance(self.speaker_label, str)
                or not self.speaker_label.strip()
            ):
                raise ValueError("speaker_label must be a non-empty string or None")
        object.__setattr__(self, "stage_directions", tuple(self.stage_directions))
        if not all(
            isinstance(direction, str) and direction.strip()
            for direction in self.stage_directions
        ):
            raise ValueError("stage_directions must contain non-empty strings")
        if not self.text.strip() and not self.stage_directions:
            raise ValueError("text or stage_directions must not be empty")

    @property
    def human_text(self) -> str:
        parts = [f"[{direction}]" for direction in self.stage_directions]
        if self.text:
            parts.append(self.text)
        body = " ".join(parts)
        return f"{self.speaker_label}: {body}" if self.speaker_label else body

    def to_dict(self) -> dict[str, Any]:
        return {
            "speaker_label": self.speaker_label,
            "text": self.text,
            "stage_directions": list(self.stage_directions),
        }


@dataclass(frozen=True)
class Chapter:
    """Transcript chapter independent of any page structure."""

    number: int
    title: str
    paragraphs: tuple[TranscriptParagraph, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.number, int) or self.number < 0:
            raise ValueError("number must be a non-negative integer")
        _validate_text(self.title, "title", allow_empty=True)
        object.__setattr__(self, "paragraphs", tuple(self.paragraphs))
        if not all(
            isinstance(paragraph, TranscriptParagraph)
            for paragraph in self.paragraphs
        ):
            raise ValueError("paragraphs must contain TranscriptParagraph values")

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "title": self.title,
            "paragraphs": [paragraph.to_dict() for paragraph in self.paragraphs],
        }


@dataclass(frozen=True)
class Transcript:
    """Normalized transcript text grouped into chapters."""

    chapters: tuple[Chapter, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "chapters", tuple(self.chapters))
        if not all(isinstance(chapter, Chapter) for chapter in self.chapters):
            raise ValueError("chapters must contain Chapter values")

    @property
    def full_text(self) -> str:
        lines: list[str] = []
        for chapter in self.chapters:
            lines.append(f"=== Chapter {chapter.number}: {chapter.title} ===")
            lines.extend(paragraph.human_text for paragraph in chapter.paragraphs)
            lines.append("")
        return "\n".join(lines).strip()

    @property
    def length(self) -> int:
        return len(self.full_text)


@dataclass(frozen=True)
class SourceMetadata:
    """Normalized source metadata with raw provider metadata preserved."""

    schema_version: str
    title: str | None
    video_id: str | None
    raw_metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_text(self.schema_version, "schema_version")
        if self.title is not None:
            _validate_text(self.title, "title")
        if self.video_id is not None:
            _validate_text(self.video_id, "video_id")
        _validate_mapping(self.raw_metadata, "raw_metadata")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "title": self.title,
            "video_id": self.video_id,
            "raw_metadata": self.raw_metadata,
        }


@dataclass(frozen=True)
class Provenance:
    """How and when a crawler produced an acquisition result."""

    crawler: str
    fetched_at: str
    transcript_available: bool

    def __post_init__(self) -> None:
        _validate_text(self.crawler, "crawler")
        _validate_text(self.fetched_at, "fetched_at")
        if not isinstance(self.transcript_available, bool):
            raise ValueError("transcript_available must be a bool")

    def to_dict(self) -> dict[str, Any]:
        return {
            "crawler": self.crawler,
            "fetched_at": self.fetched_at,
            "transcript_available": self.transcript_available,
        }


@dataclass(frozen=True)
class AcquisitionResult:
    """Uniform acquisition output returned by every crawler."""

    asset_id: AssetId
    source_ref: str
    media_ref: MediaReference
    transcript: Transcript | None
    metadata: SourceMetadata
    provenance: Provenance

    def __post_init__(self) -> None:
        if not isinstance(self.asset_id, AssetId):
            raise ValueError("asset_id must be an AssetId")
        _validate_text(self.source_ref, "source_ref")
        if not isinstance(self.media_ref, MediaReference):
            raise ValueError("media_ref must be a MediaReference")
        if self.transcript is not None and not isinstance(self.transcript, Transcript):
            raise ValueError("transcript must be a Transcript or None")
        if not isinstance(self.metadata, SourceMetadata):
            raise ValueError("metadata must be SourceMetadata")
        if not isinstance(self.provenance, Provenance):
            raise ValueError("provenance must be Provenance")
