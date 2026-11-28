"""Real WhisperX, all canonical artifacts and zero-write layered reuse."""

import json
import os
from pathlib import Path
import wave

import pytest

from archive_core.application import build_asset_workspace
from archive_core.interfaces import BoundarySource, BoundaryStatus, SourceAlignmentDTO
from transcription.application import AudioVadAsrCacheManifest
from transcription.domain import AlignedAsrArtifact, RawAsrArtifact, TranscriptFusionArtifact, VadArtifact
from tests.orchestration.integration.gates import enabled
from tests.orchestration.integration.runners.full_fresh import ROOT, SAMPLE
from tests.orchestration.integration.runners.transcription import run_transcription_scenario


EXPECTED_CHAPTER_TITLES = (
    '"There\'s nothing magic about a one-year period"',
    'We want a "mathematical edge in every transaction"',
)


@pytest.mark.live
def test_real_cnbc_transcription_pipeline_produces_every_artifact():
    if not enabled("asr"):
        pytest.skip("enable the explicit orchestration asr scenario")
    output_root = Path(os.environ.get("ORCHESTRATION_ASR_OUTPUT_ROOT", ROOT / "output" / "orchestration-integration" / "NB08-asr-only"))
    first, second = run_transcription_scenario(output_root)
    workspace = build_asset_workspace(SAMPLE, output_root)

    def payload(name):
        return json.loads((workspace / name).read_text(encoding="utf-8"))

    for name in ("meta.json", "media_ref.json", "transcript.txt", "chapters.json", "video.mp4", "download_manifest.json",
                 "media_derivation_manifest.json", "media_boundary.json", "audio.wav", "vad.json", "raw_asr.json", "aligned_asr.json",
                 "transcript_fusion.json", "source_alignment.json", "transcription.log", "transcription_report.json", "transcription_manifest.json"):
        assert (workspace / name).stat().st_size > 0
    with wave.open(str(workspace / "audio.wav"), "rb") as audio:
        assert (audio.getframerate(), audio.getnchannels(), audio.getsampwidth()) == (16000, 1, 2)
    VadArtifact.from_dict(payload("vad.json"))
    RawAsrArtifact.from_dict(payload("raw_asr.json"))
    AlignedAsrArtifact.from_dict(payload("aligned_asr.json"))
    TranscriptFusionArtifact.from_dict(payload("transcript_fusion.json"))
    alignment = SourceAlignmentDTO.from_dict(payload("source_alignment.json"))
    assert tuple(section.id for section in alignment.sections) == ("sec1", "sec2")
    assert tuple(section.title for section in alignment.sections) == EXPECTED_CHAPTER_TITLES
    positions = {sentence.id: position for position, sentence in enumerate(alignment.sentences)}
    left, right = alignment.sections
    assert positions[left.first_sentence_id] == 0
    transition = positions[left.last_sentence_id]
    assert positions[right.first_sentence_id] == transition + 1
    assert positions[right.last_sentence_id] == len(alignment.sentences) - 1
    boundary = alignment.sentences[transition]
    assert boundary.boundary_status is BoundaryStatus.VERIFIED
    assert boundary.boundary_source in {BoundarySource.FUSED_PUNCTUATION, BoundarySource.SPEAKER_CHANGE, BoundarySource.DOCUMENT_SECTION_CHANGE}
    records = {"audio", "vad", "raw_asr", "aligned_asr", "transcript_fusion", "source_alignment"}
    assert records <= set(AudioVadAsrCacheManifest.from_dict(payload("transcription_manifest.json")).records)
    assert first["stages"][-1]["cache_hits"] == []
    assert set(second["stages"][-1]["cache_hits"]) == records
    assert all(count == 0 for count in second["stages"][-1]["counts"].values())
    report = payload("transcription_report.json")
    assert report["status"] == "succeeded" and report["counts"]["error"] == 0
    derivation = payload("media_derivation_manifest.json")["identity"]["request"]
    assert derivation["chapter_numbers"] == [6, 7]
    assert derivation["time_mapping"] == {"source_start_ms": 2101000, "derived_start_ms": 0, "duration_ms": 623000}
    for line in (workspace / "transcription.log").read_text(encoding="utf-8").splitlines():
        json.loads(line)
