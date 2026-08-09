"""Media URL resolution adapters."""

from __future__ import annotations

from dataclasses import dataclass
import re

from media_download.application import ResolverRegistry
from media_download.domain import DownloadInput

from .http import RequestsHttpClient


_PLAYBACK_URL_RE = re.compile(r'playbackURL":"(.*?)"')


@dataclass(frozen=True)
class DirectUrlResolver:
    """Resolve direct media references."""

    def accepts(self, input: DownloadInput) -> bool:
        return input.media_ref.kind == "direct_url"

    def resolve(self, input: DownloadInput) -> str:
        return input.media_ref.value


@dataclass(frozen=True)
class EmbedIdResolver:
    """Resolve platform embed identifiers to downloader URLs."""

    def accepts(self, input: DownloadInput) -> bool:
        return input.media_ref.kind == "embed_id"

    def resolve(self, input: DownloadInput) -> str:
        return f"https://www.youtube.com/watch?v={input.media_ref.value}"


@dataclass
class CnbcPlaybackUrlResolver:
    """Resolve CNBC video pages to the playback URL consumed by yt-dlp."""

    http_client: RequestsHttpClient | None = None

    def accepts(self, input: DownloadInput) -> bool:
        return input.media_ref.kind == "page_url"

    def resolve(self, input: DownloadInput) -> str:
        html = self._http_client().get_text(input.media_ref.value)
        return extract_cnbc_playback_url(html, fallback_url=input.media_ref.value)

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


def build_default_resolver_registry() -> ResolverRegistry:
    registry = ResolverRegistry()
    # The registry uses the first matching resolver, so specific resolvers stay first.
    registry.register(DirectUrlResolver())
    registry.register(EmbedIdResolver())
    registry.register(CnbcPlaybackUrlResolver())
    return registry
