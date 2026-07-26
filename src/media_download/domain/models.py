"""Domain objects for planning and recording media downloads."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from archive_core.domain import SessionId


DEFAULT_FORMAT_SELECTOR = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"


class DownloadAction(str, Enum):
    DOWNLOAD = "download"
    SKIP = "skip"


@dataclass(frozen=True)
class MediaSource:
    """Source page for one archive session video."""

    source: str
    session_id: SessionId
    page_url: str

    def __post_init__(self) -> None:
        if not self.source:
            raise ValueError("source must not be empty")
        if not self.page_url.startswith(("http://", "https://")):
            raise ValueError("page_url must be absolute")


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

    source: MediaSource
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

    source: MediaSource
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
            "schema_version": "media-download.manifest.v1",
            "source": {
                "source": self.source.source,
                "year": self.source.session_id.year,
                "session": self.source.session_id.session,
                "page_url": self.source.page_url,
                "media_url": self.media_url,
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
        source_data = dict(data["source"])
        artifact_data = dict(data["artifact"])
        download_data = dict(data["download"])
        checksum_data = dict(artifact_data["checksum"])
        downloader_data = dict(download_data["downloader"])
        return cls(
            source=MediaSource(
                source=str(source_data["source"]),
                session_id=SessionId(
                    year=int(source_data["year"]),
                    session=str(source_data["session"]),
                ),
                page_url=str(source_data["page_url"]),
            ),
            media_url=str(source_data["media_url"]),
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
