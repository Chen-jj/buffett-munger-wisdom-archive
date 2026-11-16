"""Small auditable local artifact operations, preserving failures and old assets."""

from hashlib import sha256
import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from archive_core.interfaces.bilingual import ArtifactEvidenceDTO, StageManifestDTO


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def evidence(path) -> ArtifactEvidenceDTO:
    path = Path(path).resolve()
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return ArtifactEvidenceDTO(str(path), path.stat().st_size, digest.hexdigest())


def verify_evidence(item: ArtifactEvidenceDTO, expected_path=None) -> None:
    if expected_path is not None and Path(item.path) != Path(expected_path).resolve():
        raise ValueError("artifact evidence path mismatch")
    if evidence(item.path) != item:
        raise ValueError("artifact evidence changed")


def write_json(path, data) -> None:
    """Same-filesystem staging/rename; never remove a failed temporary artifact."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as stream:
        stream.write(payload)
        temporary = Path(stream.name)
    temporary.replace(path)


def verify_stage_manifest(path, *, stage, asset_id, inputs=None, outputs=None) -> StageManifestDTO:
    manifest = StageManifestDTO.from_dict(read_json(path))
    if manifest.stage != stage or manifest.asset_id != asset_id:
        raise ValueError("stage manifest identity mismatch")
    for name, expected in (("inputs", inputs), ("outputs", outputs)):
        items = getattr(manifest, name)
        if expected is not None and set(items) != set(expected):
            raise ValueError(f"stage {name} keys mismatch")
        for key, item in items.items():
            verify_evidence(item, None if expected is None else expected[key])
    return manifest
