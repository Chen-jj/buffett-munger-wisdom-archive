from __future__ import annotations

import json
import os
from pathlib import Path
import wave

import pytest

from archive_core.application import build_asset_workspace
from archive_core.domain import AssetId, ArtifactType, canonical_filename
from archive_core.interfaces import SourceAlignmentDTO
from scripts.prepare_cnbc_transcription_integration import (
    DEFAULT_OUTPUT_ROOT,
    INTEGRATION_PLAN_FILENAME,
    INTEGRATION_SAMPLE_FILENAME,
    parse_args as parse_preparation_args,
    prepare,
)
from scripts.run_transcription_golden import load_json, main
from transcription.application import AudioVadAsrCacheManifest
from transcription.domain import (
    AlignedAsrArtifact,
    RawAsrArtifact,
    TranscriptFusionArtifact,
    VadArtifact,
)


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
    had_complete_cache = []
    for sample_value in plan["samples"]:
        asset = dict(sample_value["asset"])
        workspace = build_asset_workspace(
            AssetId(asset["source"], asset.get("group", ""), asset["item"]),
            output_root,
        )
        workspaces.append(workspace)
        manifest_path = workspace / "transcription_manifest.json"
        if manifest_path.is_file():
            manifest = AudioVadAsrCacheManifest.from_dict(load_json(manifest_path))
            had_complete_cache.append(expected_records <= set(manifest.records))
        else:
            had_complete_cache.append(False)

    assert main(
        [
            "--plan",
            str(plan_path),
            "--allow-partial-plan",
            "--integration-only",
        ]
    ) == 0
    captured_stdout = capsys.readouterr().out
    result_start = captured_stdout.rfind('{\n  "status": "integration_completed"')
    assert result_start >= 0
    result = json.loads(captured_stdout[result_start:])
    assert result["status"] == "integration_completed"
    assert len(result["samples"]) == len(workspaces)

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
        SourceAlignmentDTO.from_dict(load_json(workspace / "source_alignment.json"))
        manifest = AudioVadAsrCacheManifest.from_dict(
            load_json(workspace / "transcription_manifest.json")
        )
        assert expected_records <= set(manifest.records)
        cache_hits = set(result["samples"][index]["cache_hits"])
        if had_complete_cache[index]:
            assert cache_hits == expected_records
        else:
            assert not cache_hits
        report = load_json(workspace / "transcription_report.json")
        assert report["status"] == "succeeded"
        assert report["counts"]["error"] == 0
        for line in (workspace / "transcription.log").read_text(
            encoding="utf-8"
        ).splitlines():
            json.loads(line)
