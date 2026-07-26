"""Local artifact store for media download outputs and manifests."""

from __future__ import annotations

import json
from pathlib import Path

from infrastructure.infrastructure.filesystem import write_json_file
from media_download.domain import DownloadedArtifact


class LocalDownloadArtifactStore:
    """Filesystem-backed artifact store for application services."""

    def exists(self, path: str) -> bool:
        return Path(path).exists()

    def size(self, path: str) -> int:
        return Path(path).stat().st_size

    def write_manifest(self, path: str, artifact: DownloadedArtifact) -> str:
        written = write_json_file(
            path,
            artifact.to_manifest_dict(),
            overwrite=True,
        )
        return str(written)

    def read_manifest(self, path: str) -> DownloadedArtifact:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return DownloadedArtifact.from_manifest_dict(data)
