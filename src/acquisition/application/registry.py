"""Crawler registry implementation."""

from __future__ import annotations

from dataclasses import dataclass, field

from acquisition.domain import AcquisitionRequest

from .ports import SourceCrawler


@dataclass
class DefaultCrawlerRegistry:
    """Select crawlers by registration order."""

    _crawlers: list[SourceCrawler] = field(default_factory=list)

    def register(self, crawler: SourceCrawler) -> None:
        self._crawlers.append(crawler)

    def select(self, req: AcquisitionRequest) -> SourceCrawler:
        for crawler in self._crawlers:
            if crawler.accepts(req):
                return crawler
        raise ValueError(f"No acquisition crawler accepts locator: {req.locator}")
