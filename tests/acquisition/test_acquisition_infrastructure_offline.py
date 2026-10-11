from __future__ import annotations

import hashlib
import sys
import types

import pytest

from archive_core.domain import AssetId

import acquisition.infrastructure.generic as generic_module
from acquisition.domain import (
    AcquisitionRequest,
    MediaReference,
    TranscriptParagraph,
)
from acquisition.infrastructure import (
    GenericCrawler,
    HtmlParseKit,
    MetadataExtractor,
    RequestsHttpClient,
    TranscriptNormalizer,
)


class StubHttpClient:
    """Inline fixture client returning canned HTML strings by URL."""

    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages

    def get_text(self, url: str) -> str:
        return self.pages[url]


def _soup(html: str):
    return HtmlParseKit().soup(html)


# ---------------------------------------------------------------------------
# GenericCrawler


def test_generic_crawler_uses_host_hint_when_locator_has_no_netloc() -> None:
    from_hint = GenericCrawler().discover(
        AcquisitionRequest("plain-page", hints={"host": "custom.host"})
    )[0]
    from_default = GenericCrawler().discover(AcquisitionRequest("plain-page"))[0]

    assert from_hint.asset_id.group == "custom_host"
    assert from_default.asset_id.group == "unknown"


def test_generic_crawler_accepts_by_default_and_can_be_disabled() -> None:
    crawler = GenericCrawler()

    assert crawler.accepts(AcquisitionRequest("https://anything.test/x"))
    assert not crawler.accepts(
        AcquisitionRequest("https://anything.test/x", hints={"generic": False})
    )


def test_generic_crawler_discover_builds_host_and_hash_identity() -> None:
    locator = "https://www.example.com/page"

    targets = GenericCrawler().discover(AcquisitionRequest(locator))

    assert len(targets) == 1
    target = targets[0]
    assert target.asset_id == AssetId(
        source="generic",
        group="www_example_com",
        item=hashlib.sha256(locator.encode("utf-8")).hexdigest()[:8],
    )
    assert target.fetch_url == locator
    assert target.hints == {}


def test_generic_crawler_fetch_extracts_transcript_with_selector() -> None:
    locator = "https://www.example.com/page"
    html = (
        "<html><head><title>Example Page</title></head><body>"
        '<div class="t">First paragraph.</div>'
        '<p class="t">Second paragraph.</p>'
        "</body></html>"
    )
    crawler = GenericCrawler(http_client=StubHttpClient({locator: html}))
    target = crawler.discover(
        AcquisitionRequest(locator, hints={"transcript_selector": ".t"})
    )[0]

    result = crawler.fetch(target)

    assert result.metadata.title == "Example Page"
    assert result.media_ref == MediaReference(kind="page_url", value=locator)
    assert result.transcript is not None
    assert result.transcript.chapters[0].paragraphs == (
        TranscriptParagraph(text="First paragraph.", speaker_label=None),
        TranscriptParagraph(text="Second paragraph.", speaker_label=None),
    )
    assert result.provenance.transcript_available is True


def test_generic_crawler_fetch_without_selector_has_no_transcript() -> None:
    locator = "https://www.example.com/page"
    crawler = GenericCrawler(
        http_client=StubHttpClient({locator: "<html><title>T</title></html>"})
    )

    result = crawler.fetch(crawler.discover(AcquisitionRequest(locator))[0])

    assert result.transcript is None
    assert result.provenance.transcript_available is False


def test_generic_crawler_fetch_with_selector_without_matches_has_no_transcript() -> None:
    locator = "https://www.example.com/page"
    crawler = GenericCrawler(
        http_client=StubHttpClient({locator: "<html><title>T</title></html>"})
    )
    target = crawler.discover(
        AcquisitionRequest(locator, hints={"transcript_selector": ".missing"})
    )[0]

    result = crawler.fetch(target)

    assert result.transcript is None


def test_generic_crawler_creates_default_http_client_lazily(monkeypatch) -> None:
    locator = "https://www.example.com/page"
    stub = StubHttpClient({locator: "<html><title>T</title></html>"})
    monkeypatch.setattr(generic_module, "RequestsHttpClient", lambda: stub)
    crawler = GenericCrawler()

    result = crawler.fetch(crawler.discover(AcquisitionRequest(locator))[0])

    assert crawler.http_client is stub
    assert result.metadata.title == "T"


# ---------------------------------------------------------------------------
# TranscriptNormalizer / MetadataExtractor / HtmlParseKit


def test_transcript_normalizer_returns_empty_transcript_without_body() -> None:
    transcript = TranscriptNormalizer().from_cnbc_soup(
        _soup("<html><body><div>nothing here</div></body></html>")
    )

    assert transcript.chapters == ()
    assert transcript.length == 0


def test_transcript_normalizer_skips_paragraph_nodes_without_p_tags() -> None:
    html = (
        "<html><body><div class=\"Transcript-transcriptBody\">"
        '<div class="Chapter-chapter">'
        '<div class="Chapter-chapterTitle">1. Intro</div>'
        '<div class="ChapterParagraph-chapterParagraph">no p tag</div>'
        '<div class="ChapterParagraph-chapterParagraph"><p>real text</p></div>'
        "</div></div></body></html>"
    )

    transcript = TranscriptNormalizer().from_cnbc_soup(_soup(html))

    assert len(transcript.chapters) == 1
    chapter = transcript.chapters[0]
    assert (chapter.number, chapter.title) == (1, "Intro")
    assert chapter.paragraphs == (TranscriptParagraph(text="real text"),)


def test_transcript_normalizer_defaults_chapter_number_when_unnumbered() -> None:
    html = (
        "<html><body><div class=\"Transcript-transcriptBody\">"
        '<div class="Chapter-chapter">'
        '<div class="Chapter-chapterTitle">Opening Remarks</div>'
        '<div class="ChapterParagraph-chapterParagraph"><p>text</p></div>'
        "</div></div></body></html>"
    )

    transcript = TranscriptNormalizer().from_cnbc_soup(_soup(html))

    assert transcript.chapters[0].number == 0
    assert transcript.chapters[0].title == "Opening Remarks"


def test_transcript_normalizer_separates_speakers_colons_and_stage_directions() -> None:
    paragraph_texts = [
        "WARREN BUFFETT: Good morning.",
        "A paragraph without a speaker.",
        "UNKNOWN SPEAKER: Can you hear me?",
        "WARREN BUFFETT: Berkshire: then and now.",
        "WALTER E. SCOTT, JR.: Thank you.",
        "WARREN BUFFETT: We agree. [APPLAUSE] Thank you again. (LAUGHTER)",
        "[MUSIC]",
        "Question: What makes a durable moat?",
        "WARREN BUFFETT: We own (through subsidiaries) several businesses.",
    ]
    paragraphs_html = "".join(
        '<div class="ChapterParagraph-chapterParagraph">'
        f"<p>{text}</p></div>"
        for text in paragraph_texts
    )
    html = (
        '<div class="Transcript-transcriptBody">'
        '<div class="Chapter-chapter">'
        '<div class="Chapter-chapterTitle">1. Opening</div>'
        f"{paragraphs_html}</div></div>"
    )

    paragraphs = TranscriptNormalizer().from_cnbc_soup(_soup(html)).chapters[
        0
    ].paragraphs

    assert paragraphs == (
        TranscriptParagraph(text="Good morning.", speaker_label="WARREN BUFFETT"),
        TranscriptParagraph(text="A paragraph without a speaker."),
        TranscriptParagraph(
            text="Can you hear me?", speaker_label="UNKNOWN SPEAKER"
        ),
        TranscriptParagraph(
            text="Berkshire: then and now.", speaker_label="WARREN BUFFETT"
        ),
        TranscriptParagraph(text="Thank you.", speaker_label="WALTER E. SCOTT, JR."),
        TranscriptParagraph(
            text="We agree. Thank you again.",
            speaker_label="WARREN BUFFETT",
            stage_directions=("APPLAUSE", "LAUGHTER"),
        ),
        TranscriptParagraph(text="", stage_directions=("MUSIC",)),
        TranscriptParagraph(text="Question: What makes a durable moat?"),
        TranscriptParagraph(
            text="We own (through subsidiaries) several businesses.",
            speaker_label="WARREN BUFFETT",
        ),
    )


def test_metadata_extractor_cnbc_handles_absent_payload() -> None:
    metadata = MetadataExtractor().cnbc(
        _soup("<html><script>var unrelated = 1;</script></html>")
    )

    assert metadata.raw_metadata == {}
    assert metadata.title is None
    assert metadata.video_id is None


def test_metadata_extractor_cnbc_handles_marker_without_assignment() -> None:
    metadata = MetadataExtractor().cnbc(
        _soup("<html><script>var __CNBC_META_DATA</script></html>")
    )

    assert metadata.raw_metadata == {}


def test_metadata_extractor_cnbc_handles_broken_json() -> None:
    metadata = MetadataExtractor().cnbc(
        _soup("<html><script>__CNBC_META_DATA = {broken</script></html>")
    )

    assert metadata.raw_metadata == {}


def test_metadata_extractor_cnbc_ignores_non_object_payload() -> None:
    metadata = MetadataExtractor().cnbc(
        _soup("<html><script>__CNBC_META_DATA = [1, 2]</script></html>")
    )

    assert metadata.raw_metadata == {}


def test_metadata_extractor_cnbc_maps_null_and_numeric_video_ids() -> None:
    extractor = MetadataExtractor()
    null_id = extractor.cnbc(
        _soup('<html><script>__CNBC_META_DATA = {"id": null}</script></html>')
    )
    numeric_id = extractor.cnbc(
        _soup('<html><script>__CNBC_META_DATA = {"id": 700001}</script></html>')
    )

    assert null_id.video_id is None
    assert numeric_id.video_id == "700001"


def test_metadata_extractor_html_title_without_title_tag() -> None:
    metadata = MetadataExtractor().html_title(_soup("<html><body></body></html>"))

    assert metadata.title is None
    assert metadata.video_id is None


def test_html_parse_kit_requires_beautifulsoup(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "bs4", None)

    with pytest.raises(RuntimeError, match="beautifulsoup4"):
        HtmlParseKit().soup("<p>x</p>")


# ---------------------------------------------------------------------------
# RequestsHttpClient (fake requests module injected into sys.modules)


class _FakeResponse:
    """Simulates requests' decoding: ``text`` decodes ``content`` with the
    current ``encoding``, so reassigning ``encoding`` changes the result."""

    def __init__(
        self,
        content: bytes,
        *,
        encoding: str | None = "utf-8",
        apparent_encoding: str = "utf-8",
        fail: bool = False,
    ) -> None:
        self.content = content
        self.encoding = encoding
        self.apparent_encoding = apparent_encoding
        self._fail = fail

    @property
    def text(self) -> str:
        return self.content.decode(self.encoding or "utf-8")

    def raise_for_status(self) -> None:
        if self._fail:
            raise RuntimeError("500 Server Error")


class _FakeSession:
    def __init__(self, response: _FakeResponse) -> None:
        self.headers: dict[str, str] = {}
        self._response = response
        self.calls: list[tuple[str, float]] = []

    def get(self, url: str, timeout: float | None = None) -> _FakeResponse:
        self.calls.append((url, timeout))
        return self._response


def _install_fake_requests(monkeypatch, session: _FakeSession) -> None:
    module = types.ModuleType("requests")
    module.Session = lambda: session  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "requests", module)


def test_requests_http_client_sets_headers_and_reuses_session(monkeypatch) -> None:
    session = _FakeSession(_FakeResponse(b"page body"))
    _install_fake_requests(monkeypatch, session)
    client = RequestsHttpClient(user_agent="test-agent/1", timeout_seconds=5.0)

    assert client.get_text("https://example.test/page") == "page body"
    assert client.get_text("https://example.test/other") == "page body"

    assert session.headers == {"User-Agent": "test-agent/1"}
    assert session.calls == [
        ("https://example.test/page", 5.0),
        ("https://example.test/other", 5.0),
    ]


@pytest.mark.parametrize(
    ("encoding", "apparent_encoding", "expected"),
    [
        # requests' default fallback mojibakes UTF-8 pages; detection must win.
        ("ISO-8859-1", "utf-8", "Moody\u2019s moat \u2014 quoted\n"),
        # No declared charset at all: fall back to detection.
        (None, "utf-8", "Moody\u2019s moat \u2014 quoted\n"),
        # Server-declared charset is honored and never overridden.
        ("utf-8", "windows-1252", "Moody\u2019s moat \u2014 quoted\n"),
    ],
)
def test_requests_http_client_decodes_utf8_pages_correctly(
    monkeypatch, encoding, apparent_encoding, expected
) -> None:
    body = "Moody\u2019s moat \u2014 quoted\n".encode("utf-8")
    session = _FakeSession(
        _FakeResponse(
            body, encoding=encoding, apparent_encoding=apparent_encoding
        )
    )
    _install_fake_requests(monkeypatch, session)

    text = RequestsHttpClient().get_text("https://buffett.cnbc.com/video")

    assert text == expected


def test_requests_http_client_propagates_http_errors(monkeypatch) -> None:
    session = _FakeSession(_FakeResponse(b"", fail=True))
    _install_fake_requests(monkeypatch, session)

    with pytest.raises(RuntimeError, match="500"):
        RequestsHttpClient().get_text("https://example.test/missing")


def test_requests_http_client_requires_requests_package(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "requests", None)

    with pytest.raises(RuntimeError, match="requests is required"):
        RequestsHttpClient().get_text("https://example.test/page")
