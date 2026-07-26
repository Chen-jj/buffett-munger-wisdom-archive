from __future__ import annotations

import json
from pathlib import Path

from archive_core.application import build_asset_workspace
from archive_core.domain import AssetId

from acquisition.application import AcquireUseCase, CrawlerRegistry
from acquisition.domain import AcquisitionRequest, AcquisitionResult
from acquisition.infrastructure import (
    CnbcCrawler,
    LocalAcquisitionArtifactWriter,
    YoutubeCrawler,
)


FIXTURES = Path(__file__).parent / "fixtures"


class FixtureHttpClient:
    def __init__(self, mapping: dict[str, str]) -> None:
        self.mapping = mapping

    def get_text(self, url: str) -> str:
        fixture_name = self.mapping[url]
        return (FIXTURES / fixture_name).read_text(encoding="utf-8")


def _assert_result_contract(result: AcquisitionResult) -> None:
    assert result.asset_id.source
    assert result.asset_id.item
    assert result.source_ref
    assert result.media_ref.kind in {"page_url", "direct_url", "embed_id"}
    assert result.metadata.schema_version == "acquisition.source-metadata.v1"
    assert result.provenance.crawler
    assert isinstance(result.provenance.transcript_available, bool)


def test_cnbc_crawler_discovers_full_sessions_and_parses_transcript_metadata(
    tmp_path: Path,
) -> None:
    http = FixtureHttpClient(
        {
            "https://buffett.cnbc.com/1994-berkshire-hathaway-annual-meeting/": "acquisition_cnbc_1994_year.html",
            "https://buffett.cnbc.com/video/1994/05/02/1994-berkshire-hathaway-annual-meeting-morning-session.html": "acquisition_cnbc_1994_morning.html",
            "https://buffett.cnbc.com/video/1994/05/02/1994-berkshire-hathaway-annual-meeting-afternoon-session.html": "acquisition_cnbc_1994_afternoon.html",
        }
    )
    registry = CrawlerRegistry([CnbcCrawler(http_client=http, delay_seconds=0)])
    writer = LocalAcquisitionArtifactWriter(root=tmp_path / "output")

    results = AcquireUseCase(registry=registry, writer=writer).execute(
        AcquisitionRequest("cnbc:1994")
    )

    assert [result.asset_id.item for result in results] == ["morning", "afternoon"]
    morning = results[0]
    _assert_result_contract(morning)
    assert morning.asset_id == AssetId("cnbc", "1994", "morning")
    assert morning.metadata.video_id == "morning-video-id"
    assert morning.metadata.title == "1994 Berkshire Hathaway Annual Meeting Morning Session"
    assert morning.transcript is not None
    assert len(morning.transcript.chapters) == 2
    assert "capital allocation" in morning.transcript.full_text
    assert morning.provenance.transcript_available is True

    output_dir = build_asset_workspace(morning.asset_id, tmp_path / "output")
    assert output_dir.name == "cnbc_1994_morning"
    assert json.loads((output_dir / "media_ref.json").read_text(encoding="utf-8"))[
        "kind"
    ] == "page_url"


def test_youtube_crawler_returns_media_reference_without_transcript(
    tmp_path: Path,
) -> None:
    url = "https://www.youtube.com/watch?v=abc123XYZ"
    http = FixtureHttpClient({url: "acquisition_youtube_video.html"})
    registry = CrawlerRegistry([YoutubeCrawler(http_client=http)])
    writer = LocalAcquisitionArtifactWriter(root=tmp_path / "output")

    results = AcquireUseCase(registry=registry, writer=writer).execute(
        AcquisitionRequest(url)
    )

    assert len(results) == 1
    result = results[0]
    _assert_result_contract(result)
    assert result.asset_id == AssetId("youtube", "", "abc123XYZ")
    assert result.media_ref.kind == "embed_id"
    assert result.media_ref.value == "abc123XYZ"
    assert result.transcript is None
    assert result.provenance.transcript_available is False

    output_dir = build_asset_workspace(result.asset_id, tmp_path / "output")
    assert output_dir.name == "youtube_abc123xyz"
    assert not (output_dir / "transcript.txt").exists()
    assert json.loads((output_dir / "media_ref.json").read_text(encoding="utf-8")) == {
        "kind": "embed_id",
        "value": "abc123XYZ",
        "extra": {},
    }
