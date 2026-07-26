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
class Chapter:
    """Transcript chapter independent of any page structure."""

    number: int
    title: str
    paragraphs: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.number, int) or self.number < 0:
            raise ValueError("number must be a non-negative integer")
        _validate_text(self.title, "title", allow_empty=True)
        object.__setattr__(self, "paragraphs", tuple(self.paragraphs))
        if not all(isinstance(paragraph, str) for paragraph in self.paragraphs):
            raise ValueError("paragraphs must contain strings")

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "title": self.title,
            "paragraphs": list(self.paragraphs),
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
            lines.extend(chapter.paragraphs)
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
