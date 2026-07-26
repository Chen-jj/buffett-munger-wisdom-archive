"""Asset identity value objects for archive workspaces."""

from __future__ import annotations

from dataclasses import dataclass
import re


_SESSION_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def _validate_identity_part(
    value: str, field_name: str, *, allow_empty: bool = False
) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    if not allow_empty and value == "":
        raise ValueError(f"{field_name} must not be empty")
    if "/" in value or "\\" in value:
        raise ValueError(f"{field_name} must not contain path separators")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(f"{field_name} must not contain control characters")
    return value


def _validate_session_slug(value: str) -> str:
    if not isinstance(value, str) or not _SESSION_SLUG_RE.fullmatch(value):
        raise ValueError("session must be a lowercase slug")
    return value


@dataclass(frozen=True)
class SessionId:
    """Identity for one `output/<year>/<session>/` workspace."""

    year: int
    session: str

    def __post_init__(self) -> None:
        if not isinstance(self.year, int) or self.year < 1000 or self.year > 9999:
            raise ValueError("year must be a four-digit integer")
        _validate_session_slug(self.session)

    @property
    def value(self) -> str:
        return f"{self.year}:{self.session}"

    @property
    def workspace_path(self) -> str:
        return f"output/cnbc_{self.year}_{self.session}"


@dataclass(frozen=True)
class AssetId:
    """Source-neutral identity for one archive asset."""

    source: str
    group: str
    item: str

    def __post_init__(self) -> None:
        _validate_identity_part(self.source, "source")
        _validate_identity_part(self.group, "group", allow_empty=True)
        _validate_identity_part(self.item, "item")

    @property
    def value(self) -> str:
        return f"{self.source}:{self.group}:{self.item}"
