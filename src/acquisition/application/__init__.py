from .acquire import AcquireUseCase
from .ports import AcquisitionArtifactWriter, CrawlerRegistry, SourceCrawler
from .registry import DefaultCrawlerRegistry

CrawlerRegistry = DefaultCrawlerRegistry

__all__ = [
    "AcquireUseCase",
    "AcquisitionArtifactWriter",
    "CrawlerRegistry",
    "DefaultCrawlerRegistry",
    "SourceCrawler",
]
