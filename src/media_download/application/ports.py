"""Application ports for media download use cases."""

from __future__ import annotations

from typing import Protocol

from media_download.domain import (
    DownloadedArtifact,
    DownloaderResult,
    DownloadPlan,
    MediaSource,
)


class MediaUrlResolver(Protocol):
    """Resolve a source page into a playable media URL."""

    def resolve(self, source: MediaSource) -> str:
        """Return the URL that should be passed to the downloader."""


class MediaDownloader(Protocol):
    """Downloader adapter hidden behind application services."""

    def download(self, plan: DownloadPlan) -> DownloaderResult:
        """Download the planned media artifact."""


class ChecksumCalculator(Protocol):
    """Checksum adapter for downloaded media files."""

    def sha256(self, path: str) -> str:
        """Return the SHA256 checksum for a local file."""


class DownloadArtifactStore(Protocol):
    """Filesystem-like persistence needed by the application layer."""

    def exists(self, path: str) -> bool:
        """Return whether an artifact already exists."""

    def size(self, path: str) -> int:
        """Return artifact size in bytes."""

    def write_manifest(self, path: str, artifact: DownloadedArtifact) -> str:
        """Persist the download manifest and return its path."""

    def read_manifest(self, path: str) -> DownloadedArtifact:
        """Read a previously recorded download manifest."""
