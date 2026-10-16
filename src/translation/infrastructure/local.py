"""Local filesystem adapters for the provider-neutral translation workflow."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
import time
from typing import Any, Callable, Mapping

from translation.application import GlossaryResource, PromptResource
from translation.domain import PROMPT_VERSION, TranslationGlossary


def _json_bytes(data: Mapping[str, Any]) -> bytes:
    return (json.dumps(dict(data), ensure_ascii=False, indent=2) + "\n").encode("utf-8")


class LocalChecksumService:
    def sha256(self, path: str) -> str:
        digest = hashlib.sha256()
        with Path(path).open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()


class LocalPromptLoader:
    def __init__(self, path: str | None = None) -> None:
        self.path = Path(path) if path is not None else (
            Path(__file__).parents[1] / "application" / "prompts" / "translation_zh_hans_v1.txt"
        )

    def load(self) -> PromptResource:
        data = self.path.read_bytes()
        return PromptResource(
            version=PROMPT_VERSION,
            text=data.decode("utf-8"),
            sha256=hashlib.sha256(data).hexdigest(),
        )


class LocalGlossaryLoader:
    def load(self, path: str) -> GlossaryResource:
        data = Path(path).read_bytes()
        parsed = json.loads(data.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError("glossary JSON root must be an object")
        return GlossaryResource(
            glossary=TranslationGlossary.from_dict(parsed),
            sha256=hashlib.sha256(data).hexdigest(),
        )


class LocalCheckpointStore:
    def __init__(self, directory: str) -> None:
        self.directory = Path(directory)

    def _path(self, cache_key: str) -> Path:
        if len(cache_key) != 64 or any(
            character not in "0123456789abcdef" for character in cache_key
        ):
            raise ValueError("checkpoint cache key must be a lowercase SHA-256 digest")
        return self.directory / f"{cache_key}.json"

    def exists(self, cache_key: str) -> bool:
        return self._path(cache_key).exists()

    def read(self, cache_key: str) -> Mapping[str, Any]:
        data = json.loads(self._path(cache_key).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("checkpoint JSON root must be an object")
        return data

    def write(
        self, cache_key: str, data: Mapping[str, Any], *, overwrite: bool
    ) -> None:
        target = self._path(cache_key)
        if target.exists() and not overwrite:
            raise FileExistsError(f"Refusing to overwrite checkpoint: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(target, _json_bytes(data), overwrite=overwrite)


class LocalTranslationArtifactStore:
    def exists(self, path: str) -> bool:
        return Path(path).exists()

    def size(self, path: str) -> int:
        return Path(path).stat().st_size

    def read_json(self, path: str) -> Mapping[str, Any]:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("artifact JSON root must be an object")
        return data

    def publish_json_pair(
        self,
        result_path: str,
        result_data: Mapping[str, Any],
        manifest_path: str,
        manifest_factory: Callable[[int, str], Mapping[str, Any]],
        *,
        overwrite: bool,
    ) -> tuple[int, str]:
        result = Path(result_path)
        manifest = Path(manifest_path)
        if result.parent != manifest.parent:
            raise ValueError("translation result and manifest must share a directory")
        if not overwrite and (result.exists() or manifest.exists()):
            raise FileExistsError("Refusing to overwrite translation artifact pair")
        result.parent.mkdir(parents=True, exist_ok=True)

        result_bytes = _json_bytes(result_data)
        result_sha256 = hashlib.sha256(result_bytes).hexdigest()
        manifest_bytes = _json_bytes(manifest_factory(len(result_bytes), result_sha256))
        staged: dict[Path, Path] = {}
        backups: dict[Path, Path] = {}
        installed: list[Path] = []
        try:
            staged[result] = _stage(result, result_bytes)
            staged[manifest] = _stage(manifest, manifest_bytes)
            for target in (result, manifest):
                if target.exists():
                    backups[target] = _stage(target, target.read_bytes())
            for target in (result, manifest):
                staged[target].replace(target)
                installed.append(target)
            return len(result_bytes), result_sha256
        except Exception:
            for target in reversed(installed):
                backup = backups.get(target)
                if backup is not None and backup.exists():
                    backup.replace(target)
                elif target.exists():
                    target.unlink()
            raise
        finally:
            for temporary in (*staged.values(), *backups.values()):
                if temporary.exists():
                    temporary.unlink()


class SystemSleeper:
    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


class SystemClock:
    def now_utc(self) -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class NullMetadataLogger:
    def log(self, event: str, metadata: Mapping[str, object]) -> None:
        return None


def _stage(target: Path, data: bytes) -> Path:
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(
            "wb",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            stream.write(data)
            temporary = Path(stream.name)
        return temporary
    except Exception:
        if temporary is not None and temporary.exists():
            temporary.unlink()
        raise


def _atomic_write(target: Path, data: bytes, *, overwrite: bool) -> None:
    if target.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite file: {target}")
    temporary = _stage(target, data)
    try:
        temporary.replace(target)
    finally:
        if temporary.exists():
            temporary.unlink()
