"""CNBC Buffett Archive crawler."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
import time
from urllib.parse import urljoin

from archive_core.domain import AssetId

from acquisition.domain import (
    AcquisitionRequest,
    AcquisitionResult,
    AcquisitionTarget,
    MediaReference,
    Provenance,
)

from .http import RequestsHttpClient
from .parsing import HtmlParseKit, MetadataExtractor, TranscriptNormalizer


CNBC_BASE_URL = "https://buffett.cnbc.com"


@dataclass
class CnbcCrawler:
    """SourceCrawler implementation for CNBC annual meeting archive pages."""

    http_client: RequestsHttpClient | None = None
    html: HtmlParseKit = HtmlParseKit()
    transcript_normalizer: TranscriptNormalizer = TranscriptNormalizer()
    metadata_extractor: MetadataExtractor = MetadataExtractor()
    delay_seconds: float = 1.0
    source_name: str = "cnbc"
    base_url: str = CNBC_BASE_URL

    def accepts(self, req: AcquisitionRequest) -> bool:
        locator = req.locator.lower()
        if locator.startswith("cnbc:"):
            return True
        if "buffett.cnbc.com" in locator:
            return True
        return "year" in req.hints

    def discover(self, req: AcquisitionRequest) -> list[AcquisitionTarget]:
        year = self._year_from_request(req)
        year_url = self._year_url(year)
        html = self._http_client().get_text(year_url)
        soup = self.html.soup(html)
        targets_by_session: dict[str, AcquisitionTarget] = {}

        for link in soup.find_all("a", href=True):
            href = str(link["href"])
            if "/video/" not in href:
                continue
            full_url = urljoin(self.base_url, href)
            session = _session_name_from_text(
                href.lower(),
                link.get_text(" ", strip=True).lower(),
            )
            if session is None or session in targets_by_session:
                continue
            targets_by_session[session] = AcquisitionTarget(
                asset_id=AssetId("cnbc", str(year), session),
                fetch_url=full_url,
                hints={
                    "year": year,
                    "session": session,
                    "year_url": year_url,
                },
            )

        self._sleep()
        return _select_full_sessions(targets_by_session)

    def fetch(self, target: AcquisitionTarget) -> AcquisitionResult:
        html = self._http_client().get_text(target.fetch_url)
        soup = self.html.soup(html)
        metadata = self.metadata_extractor.cnbc(soup)
        transcript = self.transcript_normalizer.from_cnbc_soup(soup)
        video_id = metadata.video_id or target.hints.get("video_id")
        self._sleep()
        return AcquisitionResult(
            asset_id=target.asset_id,
            source_ref=target.fetch_url,
            media_ref=MediaReference(
                kind="page_url",
                value=target.fetch_url,
                extra={"video_id": video_id} if video_id else {},
            ),
            transcript=transcript,
            metadata=metadata,
            provenance=Provenance(
                crawler=self.source_name,
                fetched_at=_utc_now(),
                transcript_available=transcript.length > 0,
            ),
        )

    def _http_client(self) -> RequestsHttpClient:
        if self.http_client is None:
            self.http_client = RequestsHttpClient()
        return self.http_client

    def _year_url(self, year: int) -> str:
        return f"{self.base_url}/{year}-berkshire-hathaway-annual-meeting/"

    def _year_from_request(self, req: AcquisitionRequest) -> int:
        if "year" in req.hints:
            return _validate_year(req.hints["year"])

        locator = req.locator.lower()
        if locator.startswith("cnbc:"):
            return _validate_year(locator.split(":", 1)[1])

        match = re.search(r"/([0-9]{4})-berkshire-hathaway-annual-meeting/?", locator)
        if match:
            return _validate_year(match.group(1))
        raise ValueError("CNBC request must include a year")

    def _sleep(self) -> None:
        if self.delay_seconds > 0:
            time.sleep(self.delay_seconds)


CnbcArchiveCrawler = CnbcCrawler


def _select_full_sessions(
    targets_by_session: dict[str, AcquisitionTarget]
) -> list[AcquisitionTarget]:
    has_full_session = (
        "morning" in targets_by_session or "afternoon" in targets_by_session
    )
    selected: list[AcquisitionTarget] = []
    for session, target in targets_by_session.items():
        if session == "highlight" and has_full_session:
            continue
        selected.append(target)
    return selected


def _session_name_from_text(href_lower: str, link_text: str) -> str | None:
    if "morning" in href_lower or "morning" in link_text:
        return "morning"
    if "afternoon" in href_lower or "afternoon" in link_text:
        return "afternoon"
    if "highlight" in href_lower or "highlight" in link_text:
        return "highlight"
    return None


def _validate_year(value: object) -> int:
    try:
        year = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("year must be a four-digit integer") from exc
    if year < 1000 or year > 9999:
        raise ValueError("year must be a four-digit integer")
    return year


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
