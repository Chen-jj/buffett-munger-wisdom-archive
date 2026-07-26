"""HTTP infrastructure for acquisition adapters."""

from __future__ import annotations

from dataclasses import dataclass, field


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36"
)


@dataclass
class RequestsHttpClient:
    """Small requests wrapper so source adapters do not own session setup."""

    user_agent: str = DEFAULT_USER_AGENT
    timeout_seconds: float = 30.0
    _session: object | None = field(default=None, init=False, repr=False)

    def get_text(self, url: str) -> str:
        session = self._requests_session()
        response = session.get(url, timeout=self.timeout_seconds)
        response.raise_for_status()
        return response.text

    def _requests_session(self):
        if self._session is None:
            try:
                import requests
            except ImportError as exc:
                raise RuntimeError(
                    "requests is required for acquisition HTTP crawling"
                ) from exc
            session = requests.Session()
            session.headers.update({"User-Agent": self.user_agent})
            self._session = session
        return self._session
