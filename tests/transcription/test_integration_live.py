from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import wave

import pytest

from archive_core.application import build_asset_workspace
from archive_core.domain import AssetId, ArtifactType, canonical_filename
from archive_core.interfaces import (
    BoundarySource,
    BoundaryStatus,
    SourceAlignmentDTO,
)
from tests.transcription.live_fixture import (
    DEFAULT_OUTPUT_ROOT,
    INTEGRATION_PLAN_FILENAME,
    INTEGRATION_SAMPLE_FILENAME,
    parse_args as parse_preparation_args,
    prepare,
)
from tests.transcription.live_runner import load_json, main
from transcription.application import AudioVadAsrCacheManifest
from transcription.domain import (
    AlignedAsrArtifact,
    RawAsrArtifact,
    TranscriptFusionArtifact,
    VadArtifact,
)


EXPECTED_CHAPTER_TITLES = (
    '"There\'s nothing magic about a one-year period"',
    'We want a "mathematical edge in every transaction"',
)


def _captured_result(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    captured_stdout = capsys.readouterr().out
    result_start = captured_stdout.rfind('{\n  "status": "integration_completed"')
    assert result_start >= 0
    return json.loads(captured_stdout[result_start:])


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.live
def test_real_cnbc_transcription_pipeline_produces_every_artifact(
    capsys: pytest.CaptureFixture[str],
) -> None:
    if os.environ.get("RUN_TRANSCRIPTION_INTEGRATION") != "1":
        pytest.skip(
            "set RUN_TRANSCRIPTION_INTEGRATION=1 for the real transcription integration"
        )
    plan_value = os.environ.get("TRANSCRIPTION_INTEGRATION_PLAN")
    uses_default_preparation = not plan_value
    if plan_value:
        plan_path = Path(plan_value).expanduser().resolve()
    else:
        output_root = Path(
            os.environ.get("TRANSCRIPTION_INTEGRATION_OUTPUT_ROOT", DEFAULT_OUTPUT_ROOT)
        ).expanduser().resolve()
        workspace = build_asset_workspace(
            AssetId("cnbc", "2000", "morning"), output_root
        )
        plan_path = workspace / INTEGRATION_PLAN_FILENAME
        if not plan_path.is_file():
            prepare(
                parse_preparation_args(["--output-root", str(output_root)])
            )

    plan = load_json(plan_path)
    expected_records = {
        "audio",
        "vad",
        "raw_asr",
        "aligned_asr",
        "transcript_fusion",
        "source_alignment",
    }
    output_root = Path(plan["output_root"]).expanduser()
    if not output_root.is_absolute():
        output_root = (plan_path.parent / output_root).resolve()
    workspaces = []
    for sample_value in plan["samples"]:
        asset = dict(sample_value["asset"])
        workspace = build_asset_workspace(
            AssetId(asset["source"], asset.get("group", ""), asset["item"]),
            output_root,
        )
        workspaces.append(workspace)

    assert main(
        [
            "--plan",
            str(plan_path),
        ]
    ) == 0
    result = _captured_result(capsys)
    assert result["status"] == "integration_completed"
    assert len(result["samples"]) == len(workspaces)
    first_checksums = []

    for index, sample_value in enumerate(plan["samples"]):
        workspace = workspaces[index]
        upstream_names = [
            "meta.json",
            "media_ref.json",
            "transcript.txt",
            "chapters.json",
            "video.mp4",
            "download_manifest.json",
        ]
        if uses_default_preparation:
            upstream_names.extend(
                (INTEGRATION_SAMPLE_FILENAME, INTEGRATION_PLAN_FILENAME)
            )
        for upstream_name in upstream_names:
            upstream_path = workspace / upstream_name
            assert upstream_path.is_file() and upstream_path.stat().st_size > 0
        expected = tuple(
            workspace / canonical_filename(artifact_type)
            for artifact_type in (
                ArtifactType.SOURCE_AUDIO,
                ArtifactType.VAD,
                ArtifactType.RAW_ASR,
                ArtifactType.ALIGNED_ASR,
                ArtifactType.TRANSCRIPT_FUSION,
                ArtifactType.SOURCE_ALIGNMENT,
                ArtifactType.TRANSCRIPTION_LOG,
                ArtifactType.TRANSCRIPTION_REPORT,
                ArtifactType.TRANSCRIPTION_MANIFEST,
            )
        )
        assert all(path.is_file() and path.stat().st_size > 0 for path in expected)

        with wave.open(str(workspace / "audio.wav"), "rb") as audio:
            assert audio.getframerate() == 16_000
            assert audio.getnchannels() == 1
            assert audio.getsampwidth() == 2
        VadArtifact.from_dict(load_json(workspace / "vad.json"))
        RawAsrArtifact.from_dict(load_json(workspace / "raw_asr.json"))
        AlignedAsrArtifact.from_dict(load_json(workspace / "aligned_asr.json"))
        TranscriptFusionArtifact.from_dict(
            load_json(workspace / "transcript_fusion.json")
        )
        alignment = SourceAlignmentDTO.from_dict(
            load_json(workspace / "source_alignment.json")
        )
        assert [section.id for section in alignment.sections] == ["sec1", "sec2"]
        assert tuple(section.title for section in alignment.sections) == (
            EXPECTED_CHAPTER_TITLES
        )
        sentence_positions = {
            sentence.id: position
            for position, sentence in enumerate(alignment.sentences)
        }
        first_section, second_section = alignment.sections
        assert sentence_positions[first_section.first_sentence_id] == 0
        transition_position = sentence_positions[first_section.last_sentence_id]
        assert sentence_positions[second_section.first_sentence_id] == (
            transition_position + 1
        )
        assert sentence_positions[second_section.last_sentence_id] == (
            len(alignment.sentences) - 1
        )
        transition_sentence = alignment.sentences[transition_position]
        assert transition_sentence.boundary_status is BoundaryStatus.VERIFIED
        assert transition_sentence.boundary_source in {
            BoundarySource.OFFICIAL_PUNCTUATION,
            BoundarySource.SPEAKER_CHANGE,
            BoundarySource.DOCUMENT_SECTION_CHANGE,
        }
        manifest = AudioVadAsrCacheManifest.from_dict(
            load_json(workspace / "transcription_manifest.json")
        )
        assert expected_records <= set(manifest.records)
        cache_hits = set(result["samples"][index]["cache_hits"])
        assert not cache_hits
        report = load_json(workspace / "transcription_report.json")
        assert report["status"] == "succeeded"
        assert report["counts"]["error"] == 0
        first_checksums.append(_sha256(workspace / "source_alignment.json"))
        if uses_default_preparation:
            sample_metadata = load_json(workspace / INTEGRATION_SAMPLE_FILENAME)
            assert sample_metadata["selection"] == {
                "source_start_seconds": 2101,
                "source_end_seconds": 2724,
                "duration_seconds": 623,
                "chapter_numbers": [6, 7],
                "chapter_titles": list(EXPECTED_CHAPTER_TITLES),
            }
        for line in (workspace / "transcription.log").read_text(
            encoding="utf-8"
        ).splitlines():
            json.loads(line)

    assert main(["--plan", str(plan_path)]) == 0
    rerun_result = _captured_result(capsys)
    assert rerun_result["status"] == "integration_completed"
    assert len(rerun_result["samples"]) == len(workspaces)
    for index, workspace in enumerate(workspaces):
        assert set(rerun_result["samples"][index]["cache_hits"]) == expected_records
        assert _sha256(workspace / "source_alignment.json") == first_checksums[index]
