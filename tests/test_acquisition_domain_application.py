from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from archive_core.domain import AssetId

from acquisition.application import AcquireUseCase, CrawlerRegistry
from acquisition.domain import (
    AcquisitionRequest,
    AcquisitionResult,
    AcquisitionTarget,
    Chapter,
    MediaReference,
    Provenance,
    SourceMetadata,
    Transcript,
)


def _result(asset_id: AssetId, source_ref: str) -> AcquisitionResult:
    return AcquisitionResult(
        asset_id=asset_id,
        source_ref=source_ref,
        media_ref=MediaReference(kind="page_url", value=source_ref),
        transcript=Transcript(
            chapters=(
                Chapter(number=1, title="Opening", paragraphs=("hello",)),
            )
        ),
        metadata=SourceMetadata(
            schema_version="acquisition.source-metadata.v1",
            title="Sample",
            video_id="vid1",
            raw_metadata={},
        ),
        provenance=Provenance(
            crawler="fake",
            fetched_at="2026-01-01T00:00:00+00:00",
            transcript_available=True,
        ),
    )


@dataclass
class FakeCrawler:
    source_name: str = "fake"
    accepted: bool = True
    discovered: list[AcquisitionTarget] = field(default_factory=list)
    fetched: list[AcquisitionTarget] = field(default_factory=list)

    def accepts(self, req: AcquisitionRequest) -> bool:
        return self.accepted

    def discover(self, req: AcquisitionRequest) -> list[AcquisitionTarget]:
        return self.discovered

    def fetch(self, target: AcquisitionTarget) -> AcquisitionResult:
        self.fetched.append(target)
        return _result(target.asset_id, target.fetch_url)


@dataclass
class FakeWriter:
    saved: list[AcquisitionResult] = field(default_factory=list)

    def save(self, result: AcquisitionResult) -> str:
        self.saved.append(result)
        return f"/tmp/{result.asset_id.item}"


def test_acquire_use_case_discovers_fetches_and_saves_multiple_targets() -> None:
    targets = [
        AcquisitionTarget(AssetId("fake", "g", "one"), "https://example.test/1"),
        AcquisitionTarget(AssetId("fake", "g", "two"), "https://example.test/2"),
    ]
    crawler = FakeCrawler(discovered=targets)
    writer = FakeWriter()
    registry = CrawlerRegistry([crawler])

    results = AcquireUseCase(registry=registry, writer=writer).execute(
        AcquisitionRequest("fake:any")
    )

    assert [result.asset_id.item for result in results] == ["one", "two"]
    assert crawler.fetched == targets
    assert writer.saved == results


def test_acquire_use_case_without_writer_only_fetches() -> None:
    target = AcquisitionTarget(AssetId("fake", "", "one"), "https://example.test/1")
    crawler = FakeCrawler(discovered=[target])

    results = AcquireUseCase(registry=CrawlerRegistry([crawler])).execute(
        AcquisitionRequest("fake:any")
    )

    assert len(results) == 1
    assert crawler.fetched == [target]


def test_crawler_registry_selects_first_accepting_crawler() -> None:
    first = FakeCrawler(accepted=False)
    second = FakeCrawler(accepted=True)
    registry = CrawlerRegistry([first, second])

    assert registry.select(AcquisitionRequest("anything")) is second


def test_crawler_registry_raises_when_no_crawler_matches() -> None:
    registry = CrawlerRegistry([FakeCrawler(accepted=False)])

    with pytest.raises(ValueError, match="No acquisition crawler accepts"):
        registry.select(AcquisitionRequest("anything"))


def test_domain_value_objects_validate_required_fields() -> None:
    with pytest.raises(ValueError, match="locator"):
        AcquisitionRequest("")
    with pytest.raises(ValueError, match="asset_id"):
        AcquisitionTarget("bad", "https://example.test")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="kind"):
        MediaReference(kind="bad", value="x")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="number"):
        Chapter(number=-1, title="bad")


def test_transcript_full_text_and_length_are_computed() -> None:
    transcript = Transcript(
        chapters=(Chapter(number=1, title="Opening", paragraphs=("hello", "world")),)
    )

    assert "=== Chapter 1: Opening ===" in transcript.full_text
    assert transcript.length == len(transcript.full_text)
