"""Application ports for media download use cases."""

from __future__ import annotations

from typing import Protocol

from media_download.domain import (
    DownloadInput,
    DownloadedArtifact,
    DownloaderResult,
    DownloadPlan,
    MediaRef,
)


class MediaUrlResolver(Protocol):
    """Resolve a media reference into a downloader URL."""

    def accepts(self, input: DownloadInput) -> bool:
        """Return whether this resolver can handle the input."""

    def resolve(self, input: DownloadInput) -> str:
        """Return the URL that should be passed to the downloader."""


class ResolverRegistry:
    """Ordered resolver registry for media reference dispatch."""

    def __init__(self) -> None:
        self._resolvers: list[MediaUrlResolver] = []

    def register(self, resolver: MediaUrlResolver) -> None:
        self._resolvers.append(resolver)

    def select(self, input: DownloadInput) -> MediaUrlResolver:
        for resolver in self._resolvers:
            if resolver.accepts(input):
                return resolver
        raise ValueError("No media URL resolver accepts input")


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

    def read_media_ref(self, path: str) -> MediaRef:
        """Read an upstream media reference."""
