"""YouTube source crawler."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from urllib.parse import parse_qs, urlparse

from archive_core.domain import AssetId

from acquisition.domain import (
    AcquisitionRequest,
    AcquisitionResult,
    AcquisitionTarget,
    MediaReference,
    Provenance,
)

from .http import RequestsHttpClient
from .parsing import HtmlParseKit, MetadataExtractor


@dataclass
class YoutubeCrawler:
    """SourceCrawler implementation for YouTube links."""

    http_client: RequestsHttpClient | None = None
    html: HtmlParseKit = HtmlParseKit()
    metadata_extractor: MetadataExtractor = MetadataExtractor()
    source_name: str = "youtube"

    def accepts(self, req: AcquisitionRequest) -> bool:
        host = urlparse(req.locator).netloc.lower()
        return "youtube.com" in host or host == "youtu.be"

    def discover(self, req: AcquisitionRequest) -> list[AcquisitionTarget]:
        video_id = _video_id(req.locator)
        return [
            AcquisitionTarget(
                asset_id=AssetId("youtube", "", video_id),
                fetch_url=req.locator,
                hints={"video_id": video_id},
            )
        ]

    def fetch(self, target: AcquisitionTarget) -> AcquisitionResult:
        metadata = self.metadata_extractor.html_title(
            self.html.soup(self._http_client().get_text(target.fetch_url)),
            video_id=target.hints.get("video_id"),
        )
        video_id = metadata.video_id or target.hints["video_id"]
        return AcquisitionResult(
            asset_id=target.asset_id,
            source_ref=target.fetch_url,
            media_ref=MediaReference(kind="embed_id", value=video_id),
            transcript=None,
            metadata=metadata,
            provenance=Provenance(
                crawler=self.source_name,
                fetched_at=datetime.now(timezone.utc).isoformat(),
                transcript_available=False,
            ),
        )

    def _http_client(self) -> RequestsHttpClient:
        if self.http_client is None:
            self.http_client = RequestsHttpClient()
        return self.http_client


def _video_id(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host == "youtu.be":
        value = parsed.path.strip("/")
        if value:
            return value
    query_id = parse_qs(parsed.query).get("v", [""])[0]
    if query_id:
        return query_id
    match = re.search(r"/(?:embed|shorts)/([^/?#]+)", parsed.path)
    if match:
        return match.group(1)
    raise ValueError("YouTube URL must include a video id")
