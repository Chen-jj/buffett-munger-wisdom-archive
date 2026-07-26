"""Media URL resolution adapters."""

from __future__ import annotations

from dataclasses import dataclass
import re

from acquisition.infrastructure import RequestsHttpClient
from media_download.domain import MediaSource


_PLAYBACK_URL_RE = re.compile(r'playbackURL":"(.*?)"')


@dataclass
class CnbcPlaybackUrlResolver:
    """Resolve CNBC video pages to the playback URL consumed by yt-dlp."""

    http_client: RequestsHttpClient | None = None

    def resolve(self, source: MediaSource) -> str:
        html = self._http_client().get_text(source.page_url)
        return extract_cnbc_playback_url(html, fallback_url=source.page_url)

    def _http_client(self) -> RequestsHttpClient:
        if self.http_client is None:
            self.http_client = RequestsHttpClient()
        return self.http_client


def extract_cnbc_playback_url(html: str, *, fallback_url: str) -> str:
    """Extract CNBC `playbackURL` while preserving legacy fallback behavior."""

    match = _PLAYBACK_URL_RE.search(html)
    if not match:
        return fallback_url

    raw_url = match.group(1).replace("\\/", "/")
    media_url = raw_url.encode("utf-8").decode("unicode_escape")
    if media_url.startswith("//"):
        return f"https:{media_url}"
    return media_url
