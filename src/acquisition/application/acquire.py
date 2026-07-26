"""Unified acquisition use case."""

from __future__ import annotations

from dataclasses import dataclass

from acquisition.domain import AcquisitionRequest, AcquisitionResult

from .ports import AcquisitionArtifactWriter, CrawlerRegistry


@dataclass(frozen=True)
class AcquireUseCase:
    """Select a crawler, fetch all discovered targets, and optionally persist them."""

    registry: CrawlerRegistry
    writer: AcquisitionArtifactWriter | None = None

    def execute(self, req: AcquisitionRequest) -> list[AcquisitionResult]:
        crawler = self.registry.select(req)
        results: list[AcquisitionResult] = []
        for target in crawler.discover(req):
            result = crawler.fetch(target)
            if self.writer is not None:
                self.writer.save(result)
            results.append(result)
        return results
