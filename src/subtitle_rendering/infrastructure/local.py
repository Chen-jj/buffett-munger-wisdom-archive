"""Streaming evidence and exclusive same-filesystem staging; no automatic deletion."""

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re
import uuid

from archive_core.domain import ArtifactType, canonical_filename


_OUTPUT_NAMES = {canonical_filename(kind) for kind in (
    ArtifactType.SUBTITLE_RENDER_PLAN, ArtifactType.BILINGUAL_ASS, ArtifactType.RENDERED_VIDEO,
    ArtifactType.SUBTITLE_RENDER_REPORT, ArtifactType.SUBTITLE_RENDER_MANIFEST,
)}


class LocalRenderingArtifactStore:
    def exists(self, path: str) -> bool:
        return os.path.lexists(path)

    def read_bytes(self, path: str) -> bytes:
        return Path(path).read_bytes()

    def size(self, path: str) -> int:
        return Path(path).stat().st_size

    def sha256(self, path: str) -> str:
        digest = hashlib.sha256()
        with Path(path).open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def plan_staging(self, workspace: str) -> str:
        return str(Path(workspace) / (".subtitle-rendering." + uuid.uuid4().hex))

    def create_staging(self, path: str) -> None:
        staging = Path(path)
        if re.fullmatch(r"\.subtitle-rendering\.[0-9a-f]{32}", staging.name) is None:
            raise ValueError("invalid rendering staging directory")
        # The upstream workspace already exists. Never create an alternative workspace tree.
        staging.mkdir()
        if staging.stat().st_dev != staging.parent.stat().st_dev:
            raise ValueError("render staging must share the workspace filesystem")

    def stage_bytes(self, path: str, data: bytes) -> None:
        staged = Path(path)
        if (staged.name not in _OUTPUT_NAMES | {"failure-report.json"} or staged.parent.is_symlink()
                or re.fullmatch(r"\.subtitle-rendering\.[0-9a-f]{32}", staged.parent.name) is None):
            raise ValueError("bytes may only be staged inside a rendering staging directory")
        with staged.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())

    def publish(self, staged: str, target: str, *, overwrite: bool) -> None:
        source, destination = Path(staged), Path(target)
        if source.is_symlink() or not source.is_file() or source.stat().st_size <= 0:
            raise ValueError("publication requires a nonempty staged regular file")
        if (destination.name not in _OUTPUT_NAMES or source.parent.is_symlink()
                or source.parent.parent != destination.parent or source.name != destination.name
                or re.fullmatch(r"\.subtitle-rendering\.[0-9a-f]{32}", source.parent.name) is None):
            raise ValueError("publication must use canonical same-workspace staging")
        if source.stat().st_dev != destination.parent.stat().st_dev:
            raise ValueError("publication must stay on the same filesystem")
        if self.exists(str(destination)) and not overwrite:
            raise FileExistsError("publication target already exists")
        os.replace(source, destination)


class SystemClock:
    def now_utc(self) -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
