from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from archive_core.application import build_asset_workspace
from archive_core.domain import AssetId
from archive_core.interfaces import StructuredTranscriptDTO

from acquisition.domain import (
    AcquisitionResult,
    Chapter,
    MediaReference,
    Provenance,
    SourceMetadata,
    Transcript,
    TranscriptParagraph,
)
from acquisition.infrastructure import LocalAcquisitionArtifactWriter


_DEFAULT_TRANSCRIPT = object()


def _sample_result(
    transcript: Transcript | None | object = _DEFAULT_TRANSCRIPT,
) -> AcquisitionResult:
    asset_id = AssetId("cnbc", "1994", "morning")
    normalized_transcript = (
        Transcript(
            chapters=(
                Chapter(
                    number=1,
                    title="Opening",
                    paragraphs=(
                        TranscriptParagraph(
                            text="Welcome to the meeting.",
                            speaker_label="WARREN BUFFETT",
                            stage_directions=("APPLAUSE",),
                        ),
                        TranscriptParagraph(
                            text="",
                            stage_directions=("BREAK",),
                        ),
                    ),
                ),
            )
        )
        if transcript is _DEFAULT_TRANSCRIPT
        else transcript
    )
    return AcquisitionResult(
        asset_id=asset_id,
        source_ref="https://buffett.cnbc.com/video/morning-session.html",
        media_ref=MediaReference(
            kind="page_url",
            value="https://buffett.cnbc.com/video/morning-session.html",
            extra={"video_id": "123"},
        ),
        transcript=normalized_transcript,
        metadata=SourceMetadata(
            schema_version="acquisition.source-metadata.v1",
            title="Sample",
            video_id="123",
            raw_metadata={"id": "123"},
        ),
        provenance=Provenance(
            crawler="cnbc",
            fetched_at="2026-01-01T00:00:00+00:00",
            transcript_available=True,
        ),
    )


def test_writer_uses_archive_core_flat_workspace_and_writes_contract_files(
    tmp_path: Path,
) -> None:
    result = _sample_result()
    writer = LocalAcquisitionArtifactWriter(root=tmp_path / "output")

    output_dir = Path(writer.save(result))

    assert output_dir == build_asset_workspace(result.asset_id, tmp_path / "output")
    assert output_dir.name == "cnbc_1994_morning"
    assert (output_dir / "transcript.txt").read_text(encoding="utf-8")
    chapters_data = json.loads(
        (output_dir / "chapters.json").read_text(encoding="utf-8")
    )
    assert chapters_data == {
        "schema_version": "acquisition.transcript.v2",
        "language": "en",
        "chapters": [
            {
                "number": 1,
                "title": "Opening",
                "paragraphs": [
                    {
                        "speaker_label": "WARREN BUFFETT",
                        "text": "Welcome to the meeting.",
                        "stage_directions": ["APPLAUSE"],
                    },
                    {
                        "speaker_label": None,
                        "text": "",
                        "stage_directions": ["BREAK"],
                    },
                ],
            }
        ],
    }
    assert StructuredTranscriptDTO.from_dict(chapters_data).to_dict() == chapters_data
    transcript_text = (output_dir / "transcript.txt").read_text(encoding="utf-8")
    assert "WARREN BUFFETT: [APPLAUSE] Welcome to the meeting." in transcript_text
    assert "[BREAK]" in transcript_text

    meta = json.loads((output_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["schema_version"] == "acquisition.source-metadata.v1"
    assert meta["provenance"]["crawler"] == "cnbc"
    assert meta["asset_id"] == {"source": "cnbc", "group": "1994", "item": "morning"}

    media_ref = json.loads((output_dir / "media_ref.json").read_text(encoding="utf-8"))
    assert media_ref == {
        "kind": "page_url",
        "value": "https://buffett.cnbc.com/video/morning-session.html",
        "extra": {"video_id": "123"},
    }


def test_unversioned_transcript_shape_is_not_accepted_as_current_schema() -> None:
    with pytest.raises(ValueError, match="unsupported structured transcript schema"):
        StructuredTranscriptDTO.from_dict(
            {
                "chapters": [
                    {
                        "number": 1,
                        "title": "Opening",
                        "paragraphs": ["legacy paragraph"],
                    }
                ]
            }
        )


def test_writer_skips_transcript_files_when_transcript_is_unavailable(
    tmp_path: Path,
) -> None:
    result = _sample_result(transcript=None)
    writer = LocalAcquisitionArtifactWriter(root=tmp_path / "output")

    output_dir = Path(writer.save(result))

    assert not (output_dir / "transcript.txt").exists()
    assert not (output_dir / "chapters.json").exists()
    assert (output_dir / "meta.json").exists()
    assert (output_dir / "media_ref.json").exists()


def test_writer_overwrite_regenerates_all_contract_files(tmp_path: Path) -> None:
    result = _sample_result()
    writer = LocalAcquisitionArtifactWriter(root=tmp_path / "output", overwrite=True)

    first_dir = Path(writer.save(result))
    (first_dir / "transcript.txt").write_text("stale", encoding="utf-8")
    second_dir = Path(writer.save(result))

    assert second_dir == first_dir
    assert "=== Chapter 1: Opening ===" in (
        (first_dir / "transcript.txt").read_text(encoding="utf-8")
    )
    assert json.loads((first_dir / "meta.json").read_text(encoding="utf-8"))[
        "schema_version"
    ] == "acquisition.source-metadata.v1"


def test_writer_cleans_up_temporary_files_when_replace_fails(tmp_path: Path) -> None:
    result = _sample_result()
    writer = LocalAcquisitionArtifactWriter(root=tmp_path / "output")

    def failing_replace(self, other):
        raise OSError("replace failed")

    with mock.patch.object(Path, "replace", failing_replace):
        with pytest.raises(OSError, match="replace failed"):
            writer.save(result)

    output_dir = build_asset_workspace(result.asset_id, tmp_path / "output")
    assert output_dir.exists()
    leftovers = [
        entry for entry in output_dir.iterdir() if entry.name.startswith(".")
    ]
    assert leftovers == []
    assert not (output_dir / "meta.json").exists()


def test_writer_prechecks_all_outputs_before_writing(tmp_path: Path) -> None:
    result = _sample_result()
    output_dir = build_asset_workspace(result.asset_id, tmp_path / "output")
    output_dir.mkdir(parents=True)
    existing_chapters = output_dir / "chapters.json"
    existing_chapters.write_text("existing", encoding="utf-8")

    writer = LocalAcquisitionArtifactWriter(root=tmp_path / "output")

    with pytest.raises(FileExistsError):
        writer.save(result)

    assert not (output_dir / "transcript.txt").exists()
    assert not (output_dir / "meta.json").exists()
    assert not (output_dir / "media_ref.json").exists()
    assert existing_chapters.read_text(encoding="utf-8") == "existing"
