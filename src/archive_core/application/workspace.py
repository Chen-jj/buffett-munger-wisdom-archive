"""Session workspace parsing for archive output directories."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from os import PathLike
from pathlib import Path, PurePath

from archive_core.domain import (
    AssetId,
    ArtifactType,
    SessionId,
    canonical_filename,
)


_WORKSPACE_NAME_MAX_LENGTH = 100
_WORKSPACE_HASH_LENGTH = 8
_UNSAFE_WORKSPACE_CHARS_RE = re.compile(r"[^a-z0-9_-]+")
_UNDERSCORES_RE = re.compile(r"_+")
_SESSION_WORKSPACE_RE = re.compile(r"^cnbc_(?P<year>[0-9]{4})_(?P<session>.+)$")


def _safe_workspace_part(value: str) -> str:
    normalized = _UNSAFE_WORKSPACE_CHARS_RE.sub("_", value.lower())
    normalized = _UNDERSCORES_RE.sub("_", normalized).strip("_")
    if normalized:
        return normalized
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:_WORKSPACE_HASH_LENGTH]


def _asset_workspace_name(asset_id: AssetId) -> str:
    parts = [
        _safe_workspace_part(asset_id.source),
        _safe_workspace_part(asset_id.group) if asset_id.group else "",
        _safe_workspace_part(asset_id.item),
    ]
    name = _UNDERSCORES_RE.sub("_", "_".join(part for part in parts if part))
    name = name.strip("_")
    if len(name) <= _WORKSPACE_NAME_MAX_LENGTH:
        return name

    locator = f"{asset_id.source}\0{asset_id.group}\0{asset_id.item}"
    digest = hashlib.sha256(locator.encode("utf-8")).hexdigest()[
        :_WORKSPACE_HASH_LENGTH
    ]
    prefix_length = _WORKSPACE_NAME_MAX_LENGTH - _WORKSPACE_HASH_LENGTH - 1
    return f"{name[:prefix_length].rstrip('_')}_{digest}"


@dataclass(frozen=True)
class SessionWorkspace:
    """Parsed `output/<year>/<session>/` workspace without filesystem access."""

    session_id: SessionId
    workspace_path: str

    def artifact_path(self, artifact_type: ArtifactType) -> str:
        return str(PurePath(self.workspace_path) / canonical_filename(artifact_type))


def parse_session_workspace(path: str | PathLike[str]) -> SessionWorkspace:
    """Parse a CNBC session workspace built by `build_session_workspace`."""

    workspace_path = str(PurePath(path))
    parts = PurePath(workspace_path).parts
    if len(parts) < 2:
        raise ValueError("workspace path must end with output/cnbc_<year>_<session>")

    output_dir, workspace_name = parts[-2:]
    if output_dir != "output":
        raise ValueError("workspace path must end with output/cnbc_<year>_<session>")
    match = _SESSION_WORKSPACE_RE.fullmatch(workspace_name)
    if match is None:
        raise ValueError("workspace path must end with output/cnbc_<year>_<session>")

    return SessionWorkspace(
        session_id=SessionId(
            year=int(match.group("year")),
            session=match.group("session"),
        ),
        workspace_path=workspace_path,
    )


def build_asset_workspace(asset_id: AssetId, root: str | Path) -> Path:
    """Build the flat source-neutral workspace path for an asset."""

    return Path(root) / _asset_workspace_name(asset_id)


def build_session_workspace(
    output_root: str | PathLike[str], session_id: SessionId
) -> SessionWorkspace:
    output_parts = PurePath(str(output_root)).parts
    if output_parts and output_parts[-1] == "output":
        workspace_root = Path(output_root)
    else:
        workspace_root = Path(output_root) / "output"
    asset_id = AssetId(
        source="cnbc",
        group=str(session_id.year),
        item=session_id.session,
    )
    workspace_path = build_asset_workspace(asset_id, workspace_root)
    return SessionWorkspace(
        session_id=session_id,
        workspace_path=str(workspace_path),
    )
