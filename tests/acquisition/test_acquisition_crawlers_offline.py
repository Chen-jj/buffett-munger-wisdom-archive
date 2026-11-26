from __future__ import annotations

import json
from pathlib import Path

import pytest

from archive_core.application import build_asset_workspace
from archive_core.domain import AssetId
from archive_core.interfaces import (
    StructuredTranscriptDTO,
    TranscriptChapterDTO,
    TranscriptParagraphDTO,
)

from acquisition.application import AcquireUseCase, CrawlerRegistry
from acquisition.domain import (
    AcquisitionRequest,
    AcquisitionResult,
    AcquisitionTarget,
    TranscriptParagraph,
)
from acquisition.infrastructure import (
    CnbcCrawler,
    LocalAcquisitionArtifactWriter,
    YoutubeCrawler,
)
import acquisition.infrastructure.cnbc as cnbc_module
import acquisition.infrastructure.youtube as youtube_module
from acquisition.interfaces import repair_cnbc_structured_transcript


FIXTURES = Path(__file__).parents[1] / "fixtures"


class StubHttpClient:
    """Inline fixture client returning canned HTML strings by URL."""

    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.urls: list[str] = []

    def get_text(self, url: str) -> str:
        self.urls.append(url)
        return self.pages[url]


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




def test_cnbc_transcript_repairs_misdecoded_punctuation_in_page() -> None:
    url = "https://buffett.cnbc.com/video/2000/morning.html"
    http = StubHttpClient(
        {
            url: (
                '<div class="Transcript-transcriptBody">'
                '<div class="Chapter-chapter">'
                '<div class="Chapter-chapterTitle">3. Investing</div>'
                '<div class="ChapterParagraph-chapterParagraph"><p>'
                "WARREN BUFFETT: I didn\u00e2\u0080\u0099t \u00e2\u0080\u0094 "
                "well\u00e2\u0080\u00a6 (Laughter)"
                "</p></div></div></div>"
            )
        }
    )
    crawler = CnbcCrawler(http_client=http, delay_seconds=0)

    result = crawler.fetch(
        AcquisitionTarget(
            asset_id=AssetId("cnbc", "2000", "morning"),
            fetch_url=url,
        )
    )

    assert result.transcript is not None
    assert result.transcript.chapters[0].paragraphs[0] == TranscriptParagraph(
        text="I didn’t — well…",
        speaker_label="WARREN BUFFETT",
        stage_directions=("Laughter",),
    )


def test_cnbc_structured_transcript_repair_preserves_nonspoken_metadata() -> None:
    damaged = "didn\u00e2\u0080\u0099t \u00e2\u0080\u0094 \u00e2\u0080\u0098maybe\u00e2\u0080\u00a6 1\u00e2\u0080\u00932"
    unchanged = "Café — already clean. I don't mind..."
    transcript = StructuredTranscriptDTO(
        language="en",
        chapters=(
            TranscriptChapterDTO(3, "Investing — Basics", (
                TranscriptParagraphDTO(damaged, "WARREN BUFFETT", ("Laughter",)),
                TranscriptParagraphDTO("", stage_directions=("Applause",)),
            )),
            TranscriptChapterDTO(4, "Questions", (TranscriptParagraphDTO(unchanged),)),
        ),
    )

    repaired = repair_cnbc_structured_transcript(transcript)

    assert repaired.chapters[0] == TranscriptChapterDTO(3, "Investing — Basics", (
        TranscriptParagraphDTO("didn’t — ‘maybe… 1–2", "WARREN BUFFETT", ("Laughter",)),
        transcript.chapters[0].paragraphs[1],
    ))
    assert repaired.chapters[1] == transcript.chapters[1]
    assert transcript.chapters[0].paragraphs[0].text == damaged
    assert repair_cnbc_structured_transcript(repaired) == repaired


def test_cnbc_crawler_accepts_supported_locators_and_hints() -> None:
    crawler = CnbcCrawler()

    assert crawler.accepts(AcquisitionRequest("cnbc:1994"))
    assert crawler.accepts(
        AcquisitionRequest(
            "https://buffett.cnbc.com/1994-berkshire-hathaway-annual-meeting/"
        )
    )
    assert crawler.accepts(
        AcquisitionRequest("https://example.com/x", hints={"year": 2000})
    )
    assert not crawler.accepts(AcquisitionRequest("https://example.com/x"))
    assert not crawler.accepts(AcquisitionRequest("https://youtube.com/watch?v=1"))


def test_cnbc_discover_filters_non_video_duplicate_and_unnamed_links(
    tmp_path: Path,
) -> None:
    year_url = "https://buffett.cnbc.com/1994-berkshire-hathaway-annual-meeting/"
    http = StubHttpClient(
        {
            year_url: (
                "<html><body>"
                '<a href="/about">About</a>'
                '<a href="/video/1994/05/02/morning-session.html">Morning Session</a>'
                '<a href="/video/1994/05/02/morning-session-replay.html">'
                "Morning Session Replay</a>"
                '<a href="/video/1994/05/02/extra.html">Extra Clip</a>'
                "</body></html>"
            )
        }
    )
    crawler = CnbcCrawler(http_client=http, delay_seconds=0.001)

    targets = crawler.discover(AcquisitionRequest("cnbc:1994"))

    assert http.urls == [year_url]
    assert len(targets) == 1
    assert targets[0].asset_id == AssetId("cnbc", "1994", "morning")
    assert (
        targets[0].fetch_url
        == "https://buffett.cnbc.com/video/1994/05/02/morning-session.html"
    )
    assert targets[0].hints == {"year": 1994, "session": "morning", "year_url": year_url}


def test_cnbc_discover_keeps_highlight_when_no_full_session_exists() -> None:
    http = StubHttpClient(
        {
            "https://buffett.cnbc.com/1995-berkshire-hathaway-annual-meeting/": (
                '<html><body><a href="/video/1995/highlight.html">Highlights</a></body></html>'
            )
        }
    )
    crawler = CnbcCrawler(http_client=http, delay_seconds=0)

    targets = crawler.discover(AcquisitionRequest("cnbc:1995"))

    assert [target.asset_id.item for target in targets] == ["highlight"]


def test_cnbc_year_comes_from_hints_and_locator_patterns() -> None:
    empty_page = "<html><body></body></html>"
    http = StubHttpClient(
        {
            "https://buffett.cnbc.com/1994-berkshire-hathaway-annual-meeting/": empty_page,
            "https://buffett.cnbc.com/1996-berkshire-hathaway-annual-meeting/": empty_page,
        }
    )
    crawler = CnbcCrawler(http_client=http, delay_seconds=0)

    from_hints = crawler.discover(
        AcquisitionRequest("https://buffett.cnbc.com/anything/", hints={"year": 1994})
    )
    from_locator = crawler.discover(
        AcquisitionRequest(
            "https://buffett.cnbc.com/1996-berkshire-hathaway-annual-meeting/"
        )
    )

    assert from_hints == []
    assert http.urls[0].startswith("https://buffett.cnbc.com/1994-")
    assert from_locator == []
    assert http.urls[1].startswith("https://buffett.cnbc.com/1996-")


def test_cnbc_discover_requires_a_usable_year() -> None:
    crawler = CnbcCrawler(delay_seconds=0)

    with pytest.raises(ValueError, match="must include a year"):
        crawler.discover(AcquisitionRequest("https://buffett.cnbc.com/other/"))
    with pytest.raises(ValueError, match="four-digit"):
        crawler.discover(
            AcquisitionRequest("https://example.com/x", hints={"year": "abc"})
        )
    with pytest.raises(ValueError, match="four-digit"):
        crawler.discover(AcquisitionRequest("cnbc:99"))
    with pytest.raises(ValueError, match="four-digit"):
        crawler.discover(AcquisitionRequest("cnbc:12345"))


def test_cnbc_crawler_creates_default_http_client_lazily(monkeypatch) -> None:
    stub = StubHttpClient(
        {
            "https://buffett.cnbc.com/1994-berkshire-hathaway-annual-meeting/": "<html></html>"
        }
    )
    monkeypatch.setattr(cnbc_module, "RequestsHttpClient", lambda: stub)
    crawler = CnbcCrawler(delay_seconds=0)

    crawler.discover(AcquisitionRequest("cnbc:1994"))

    assert crawler.http_client is stub


def test_youtube_discover_supports_common_url_shapes() -> None:
    crawler = YoutubeCrawler()
    cases = [
        ("https://youtu.be/shortID1", "shortID1"),
        ("https://www.youtube.com/watch?v=watchID", "watchID"),
        ("https://www.youtube.com/embed/embedID", "embedID"),
        ("https://www.youtube.com/shorts/shortsID", "shortsID"),
    ]

    for locator, expected in cases:
        targets = crawler.discover(AcquisitionRequest(locator))

        assert len(targets) == 1
        assert targets[0].asset_id == AssetId("youtube", "", expected)
        assert targets[0].fetch_url == locator
        assert targets[0].hints == {"video_id": expected}


def test_youtube_discover_requires_video_id() -> None:
    with pytest.raises(ValueError, match="video id"):
        YoutubeCrawler().discover(AcquisitionRequest("https://www.youtube.com/feed"))


def test_youtube_crawler_creates_default_http_client_lazily(monkeypatch) -> None:
    url = "https://www.youtube.com/watch?v=vid123"
    stub = StubHttpClient({url: "<html><body>no title</body></html>"})
    monkeypatch.setattr(youtube_module, "RequestsHttpClient", lambda: stub)
    crawler = YoutubeCrawler()

    result = crawler.fetch(crawler.discover(AcquisitionRequest(url))[0])

    assert crawler.http_client is stub
    assert result.metadata.title is None
    assert result.media_ref.value == "vid123"
