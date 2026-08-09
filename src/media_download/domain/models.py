"""Domain objects for planning and recording media downloads."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal, Mapping

from archive_core.domain import AssetId


DEFAULT_FORMAT_SELECTOR = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
MANIFEST_SCHEMA = "media-download.manifest.1"
MEDIA_REF_KINDS = {"page_url", "direct_url", "embed_id"}
MediaRefKind = Literal["page_url", "direct_url", "embed_id"]


class DownloadAction(str, Enum):
    DOWNLOAD = "download"
    SKIP = "skip"


@dataclass(frozen=True)
class MediaRef:
    """Media reference produced by upstream artifacts."""

    kind: MediaRefKind
    value: str
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in MEDIA_REF_KINDS:
            raise ValueError("kind must be one of page_url, direct_url, embed_id")
        if not isinstance(self.value, str) or not self.value:
            raise ValueError("value must be a non-empty string")
        if not isinstance(self.extra, dict):
            raise ValueError("extra must be a dict")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MediaRef":
        if "kind" not in data:
            raise ValueError("kind is required")
        if "value" not in data:
            raise ValueError("value is required")
        kind = data["kind"]
        if not isinstance(kind, str):
            raise ValueError("kind must be a string")
        value = data["value"]
        if not isinstance(value, str):
            raise ValueError("value must be a non-empty string")
        extra = data.get("extra", {})
        if not isinstance(extra, dict):
            raise ValueError("extra must be a dict")
        return cls(kind=kind, value=value, extra=dict(extra))

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "value": self.value,
            "extra": dict(self.extra),
        }


@dataclass(frozen=True)
class DownloadInput:
    """Input object for planning one asset media download."""

    asset_id: AssetId
    media_ref: MediaRef

    def __post_init__(self) -> None:
        if not isinstance(self.asset_id, AssetId):
            raise ValueError("asset_id must be an AssetId")
        if not isinstance(self.media_ref, MediaRef):
            raise ValueError("media_ref must be a MediaRef")


@dataclass(frozen=True)
class DownloadPolicy:
    """Business policy for idempotent video downloads."""

    format_selector: str = DEFAULT_FORMAT_SELECTOR
    fallback_format: str = "best"
    retries: int = 3
    rate_limit: str | None = None
    merge_output_format: str = "mp4"
    resume: bool = True
    dry_run: bool = False
    overwrite: bool = False

    def __post_init__(self) -> None:
        if not self.format_selector:
            raise ValueError("format_selector must not be empty")
        if self.retries < 0:
            raise ValueError("retries must be non-negative")
        if not self.merge_output_format:
            raise ValueError("merge_output_format must not be empty")


@dataclass(frozen=True)
class DownloadPlan:
    """Resolved download plan independent of any concrete downloader."""

    asset_id: AssetId
    media_ref: MediaRef
    media_url: str
    output_path: str
    manifest_path: str
    policy: DownloadPolicy
    action: DownloadAction
    reason: str

    @property
    def should_download(self) -> bool:
        return self.action == DownloadAction.DOWNLOAD and not self.policy.dry_run


@dataclass(frozen=True)
class DownloaderResult:
    """Concrete downloader execution metadata returned by infrastructure."""

    downloader_name: str
    downloader_version: str
    command: tuple[str, ...]
    format_selector: str


@dataclass(frozen=True)
class DownloadedArtifact:
    """Recorded output artifact and provenance for a download decision."""

    asset_id: AssetId
    media_kind: MediaRefKind
    media_ref_value: str
    media_url: str
    output_path: str
    format_selector: str
    size_bytes: int
    checksum_algorithm: str
    checksum_value: str
    downloader_name: str
    downloader_version: str
    downloaded_at: str
    status: str

    def to_manifest_dict(self) -> dict[str, Any]:
        return {
            "schema_version": MANIFEST_SCHEMA,
            "asset": {
                "source": self.asset_id.source,
                "group": self.asset_id.group,
                "item": self.asset_id.item,
            },
            "media": {
                "kind": self.media_kind,
                "ref_value": self.media_ref_value,
                "resolved_url": self.media_url,
            },
            "artifact": {
                "path": self.output_path,
                "size_bytes": self.size_bytes,
                "checksum": {
                    "algorithm": self.checksum_algorithm,
                    "value": self.checksum_value,
                },
            },
            "download": {
                "status": self.status,
                "format": self.format_selector,
                "downloader": {
                    "name": self.downloader_name,
                    "version": self.downloader_version,
                },
                "downloaded_at": self.downloaded_at,
            },
        }

    @classmethod
    def from_manifest_dict(cls, data: Mapping[str, Any]) -> "DownloadedArtifact":
        if data.get("schema_version") != MANIFEST_SCHEMA:
            raise ValueError("unrecognized manifest schema")
        asset_data = dict(data["asset"])
        media_data = dict(data["media"])
        artifact_data = dict(data["artifact"])
        download_data = dict(data["download"])
        checksum_data = dict(artifact_data["checksum"])
        downloader_data = dict(download_data["downloader"])
        return cls(
            asset_id=AssetId(
                source=str(asset_data["source"]),
                group=str(asset_data["group"]),
                item=str(asset_data["item"]),
            ),
            media_kind=MediaRef(str(media_data["kind"]), str(media_data["ref_value"])).kind,
            media_ref_value=str(media_data["ref_value"]),
            media_url=str(media_data["resolved_url"]),
            output_path=str(artifact_data["path"]),
            format_selector=str(download_data["format"]),
            size_bytes=int(artifact_data["size_bytes"]),
            checksum_algorithm=str(checksum_data["algorithm"]),
            checksum_value=str(checksum_data["value"]),
            downloader_name=str(downloader_data["name"]),
            downloader_version=str(downloader_data["version"]),
            downloaded_at=str(download_data["downloaded_at"]),
            status=str(download_data["status"]),
        )
