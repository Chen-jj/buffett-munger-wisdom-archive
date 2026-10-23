"""Local subtitle bytes, evidence and single-file atomic publication adapters."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Mapping


def json_bytes(data: Mapping[str, Any]) -> bytes:
    """Encode local metadata deterministically, without a BOM or non-JSON numbers."""
    if not isinstance(data, Mapping):
        raise ValueError("artifact JSON root must be an object")
    text = json.dumps(
        dict(data), ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
    )
    return (text + "\n").encode("utf-8")


class LocalSubtitleArtifactStore:
    def exists(self, path: str) -> bool:
        target = Path(path)
        return target.exists() or target.is_symlink()

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

    def stage_bytes(self, target_path: str, data: bytes) -> str:
        if not isinstance(data, bytes):
            raise ValueError("artifact data must be bytes")
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        # delete=False deliberately preserves all failed/interrupted staging files.
        with NamedTemporaryFile(
            "wb", dir=target.parent, prefix=f".{target.name}.",
            suffix=".tmp", delete=False,
        ) as stream:
            stream.write(data)
            staged_path = stream.name
        return staged_path

    def publish(self, staged_path: str, target_path: str, *, overwrite: bool) -> None:
        staged, target = Path(staged_path), Path(target_path)
        if staged.parent.resolve() != target.parent.resolve():
            raise ValueError("staged artifact and target must share a directory")
        if not staged.name.startswith(f".{target.name}.") or not staged.name.endswith(".tmp"):
            raise ValueError("publish requires a staging file for this target")
        if self.exists(target_path) and not overwrite:
            raise FileExistsError(f"Refusing to overwrite subtitle artifact: {target}")
        # This commits exactly one file. Workflow owns all QA and manifest-last order.
        staged.replace(target)


class SystemClock:
    def now_utc(self) -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
