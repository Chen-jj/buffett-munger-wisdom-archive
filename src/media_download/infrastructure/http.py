"""HTTP client adapter owned by media download infrastructure."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


DEFAULT_USER_AGENT = "buffett-munger-wisdom-archive/1.0"


def _decode_text(response) -> str:
    """Read the body as text, honoring the page's real character set.

    ``requests`` falls back to ISO-8859-1 when the ``Content-Type`` header has
    no charset, which mojibakes UTF-8 source pages. Trust encoding detection
    over that default, but keep any charset the server declared explicitly.
    """
    if response.encoding is None or response.encoding.lower() == "iso-8859-1":
        response.encoding = response.apparent_encoding
    return response.text


@dataclass
class RequestsHttpClient:
    """Small requests-backed client for fetching media source pages."""

    timeout: float = 30.0
    user_agent: str = DEFAULT_USER_AGENT
    _session: Any | None = None

    def get_text(self, url: str) -> str:
        response = self._get_session().get(
            url,
            headers={"User-Agent": self.user_agent},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return _decode_text(response)

    def _get_session(self) -> Any:
        if self._session is None:
            try:
                import requests
            except ImportError as exc:
                raise RuntimeError(
                    "requests is required for media download HTTP resolution"
                ) from exc
            self._session = requests.Session()
        return self._session
