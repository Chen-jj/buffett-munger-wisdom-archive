"""Local artifact persistence for normalized acquisition results."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from archive_core.application import build_asset_workspace
from archive_core.interfaces import (
    StructuredTranscriptDTO,
    TranscriptChapterDTO,
    TranscriptParagraphDTO,
)

from acquisition.domain import AcquisitionResult, Transcript


@dataclass(frozen=True)
class LocalAcquisitionArtifactWriter:
    """Write canonical acquisition files under `output/<source>_<group>_<item>/`."""

    root: Path | str = Path("output")
    overwrite: bool = False

    def save(self, result: AcquisitionResult) -> str:
        output_dir = build_asset_workspace(result.asset_id, self.root)
        structured_transcript = (
            _structured_transcript(result.transcript)
            if result.transcript is not None
            else None
        )
        paths = _planned_paths(output_dir, result)
        _ensure_can_write_all(tuple(paths.values()), overwrite=self.overwrite)
        output_dir.mkdir(parents=True, exist_ok=True)

        if result.transcript is not None and structured_transcript is not None:
            _write_text(
                paths["transcript"],
                result.transcript.full_text,
                overwrite=self.overwrite,
            )
            _write_json(
                paths["chapters"],
                structured_transcript.to_dict(),
                overwrite=self.overwrite,
            )

        _write_json(
            paths["meta"],
            {
                **result.metadata.to_dict(),
                "source_ref": result.source_ref,
                "asset_id": {
                    "source": result.asset_id.source,
                    "group": result.asset_id.group,
                    "item": result.asset_id.item,
                },
                "provenance": result.provenance.to_dict(),
            },
            overwrite=self.overwrite,
        )
        _write_json(
            paths["media_ref"],
            result.media_ref.to_dict(),
            overwrite=self.overwrite,
        )
        return str(output_dir)


def _planned_paths(output_dir: Path, result: AcquisitionResult) -> dict[str, Path]:
    paths = {
        "meta": output_dir / "meta.json",
        "media_ref": output_dir / "media_ref.json",
    }
    if result.transcript is not None:
        paths["transcript"] = output_dir / "transcript.txt"
        paths["chapters"] = output_dir / "chapters.json"
    return paths


def _structured_transcript(transcript: Transcript) -> StructuredTranscriptDTO:
    return StructuredTranscriptDTO(
        language="en",
        chapters=tuple(
            TranscriptChapterDTO(
                number=chapter.number,
                title=chapter.title,
                paragraphs=tuple(
                    TranscriptParagraphDTO(
                        text=paragraph.text,
                        speaker_label=paragraph.speaker_label,
                        stage_directions=paragraph.stage_directions,
                    )
                    for paragraph in chapter.paragraphs
                ),
            )
            for chapter in transcript.chapters
        ),
    )


def _write_json(path: Path, data: Any, *, overwrite: bool) -> Path:
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    return _write_text(path, f"{payload}\n", overwrite=overwrite)


def _ensure_can_write_all(paths: tuple[Path, ...], *, overwrite: bool) -> None:
    if overwrite:
        return
    existing = [path for path in paths if path.exists()]
    if existing:
        existing_list = ", ".join(str(path) for path in existing)
        raise FileExistsError(f"Refusing to overwrite existing files: {existing_list}")


def _write_text(path: Path, text: str, *, overwrite: bool) -> Path:
    if path.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp.write(text)
            tmp_path = Path(tmp.name)
        tmp_path.replace(path)
    finally:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink()
    return path
