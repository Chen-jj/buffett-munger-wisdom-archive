"""Generic fallback crawler for simple HTML sources."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import re
from urllib.parse import urlparse

from archive_core.domain import AssetId

from acquisition.domain import (
    AcquisitionRequest,
    AcquisitionResult,
    AcquisitionTarget,
    Chapter,
    MediaReference,
    Provenance,
    Transcript,
    TranscriptParagraph,
)

from .http import RequestsHttpClient
from .parsing import HtmlParseKit, MetadataExtractor


@dataclass
class GenericCrawler:
    """Fallback SourceCrawler for selector-driven HTML pages."""

    http_client: RequestsHttpClient | None = None
    html: HtmlParseKit = HtmlParseKit()
    metadata_extractor: MetadataExtractor = MetadataExtractor()
    source_name: str = "generic"

    def accepts(self, req: AcquisitionRequest) -> bool:
        return bool(req.hints.get("generic", True))

    def discover(self, req: AcquisitionRequest) -> list[AcquisitionTarget]:
        parsed = urlparse(req.locator)
        host_slug = _slug(parsed.netloc or req.hints.get("host", "unknown"))
        item = hashlib.sha256(req.locator.encode("utf-8")).hexdigest()[:8]
        return [
            AcquisitionTarget(
                asset_id=AssetId("generic", host_slug, item),
                fetch_url=req.locator,
                hints=dict(req.hints),
            )
        ]

    def fetch(self, target: AcquisitionTarget) -> AcquisitionResult:
        soup = self.html.soup(self._http_client().get_text(target.fetch_url))
        transcript = _extract_transcript(soup, target.hints)
        return AcquisitionResult(
            asset_id=target.asset_id,
            source_ref=target.fetch_url,
            media_ref=MediaReference(kind="page_url", value=target.fetch_url),
            transcript=transcript,
            metadata=self.metadata_extractor.html_title(soup),
            provenance=Provenance(
                crawler=self.source_name,
                fetched_at=datetime.now(timezone.utc).isoformat(),
                transcript_available=transcript is not None and transcript.length > 0,
            ),
        )

    def _http_client(self) -> RequestsHttpClient:
        if self.http_client is None:
            self.http_client = RequestsHttpClient()
        return self.http_client


def _extract_transcript(soup, hints: dict[str, object]) -> Transcript | None:
    selector = hints.get("transcript_selector")
    if not isinstance(selector, str) or not selector:
        return None
    nodes = soup.select(selector)
    paragraphs = tuple(
        TranscriptParagraph(text=text, speaker_label=None)
        for node in nodes
        if (text := node.get_text(" ", strip=True))
    )
    if not paragraphs:
        return None
    return Transcript(
        chapters=(Chapter(number=1, title="Transcript", paragraphs=paragraphs),)
    )


def _slug(value: object) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "_", str(value).lower()).strip("_")
    return slug or "unknown"
