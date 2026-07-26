"""Application ports for source-neutral acquisition."""

from __future__ import annotations

from typing import Protocol

from acquisition.domain import AcquisitionRequest, AcquisitionResult, AcquisitionTarget


class SourceCrawler(Protocol):
    """Crawler contract implemented once per source site."""

    source_name: str

    def accepts(self, req: AcquisitionRequest) -> bool:
        """Return whether this crawler can handle the request."""

    def discover(self, req: AcquisitionRequest) -> list[AcquisitionTarget]:
        """Expand a request into concrete fetch targets."""

    def fetch(self, target: AcquisitionTarget) -> AcquisitionResult:
        """Fetch and normalize one target."""


class AcquisitionArtifactWriter(Protocol):
    """Persistence port for normalized acquisition artifacts."""

    def save(self, result: AcquisitionResult) -> str:
        """Persist one result and return the output directory path."""


class CrawlerRegistry(Protocol):
    """Crawler selection contract used by the acquisition use case."""

    def register(self, crawler: SourceCrawler) -> None:
        """Register a source crawler."""

    def select(self, req: AcquisitionRequest) -> SourceCrawler:
        """Select the first crawler accepting the request."""
