import json
from pathlib import Path
import pytest
from archive_core.interfaces.bilingual import StageManifestDTO
from srt_processing.infrastructure.codec import Pysubs2SrtCodec
from srt_processing.interfaces.workflow import verify_srt_export
from .acceptance_fakes import LocalCase


def test_real_local_adapters_bind_both_chains_and_three_srt_projections(tmp_path):
    case = LocalCase(tmp_path)
    original = case.snapshot()
    first = case.handler.handle(case.command)
    assert first.status == "succeeded", first
    codec = Pysubs2SrtCodec()
    for language in ("english","chinese","bilingual"):
        output = codec.decode((case.workspace / (language + ".srt")).read_bytes())
        assert len(output) == len(case.draft.cues)
        for projection,cue in zip(output,case.draft.cues):
            assert (projection.start_ms,projection.end_ms) == (cue.start_ms,cue.end_ms)
            expected = cue.english_text if language == "english" else cue.chinese_text if language == "chinese" else cue.chinese_text + "\n" + cue.english_text
            assert projection.text == expected
    before = case.snapshot()
    assert all(before[name] == value for name,value in original.items())
    assert case.handler.handle(case.command).status == "reused"
    assert verify_srt_export(case.command, output_root=str(case.root)).status == "reused"
    assert case.snapshot() == before


def test_independent_local_generations_have_identical_content_artifacts(tmp_path):
    cases = [LocalCase(tmp_path / name) for name in ("first","second")]
    assert all(case.handler.handle(case.command).status == "succeeded" for case in cases)
    for name in ("english.srt","chinese.srt","bilingual.srt","srt_processing_report.json"):
        assert (cases[0].workspace / name).read_bytes() == (cases[1].workspace / name).read_bytes()


@pytest.mark.parametrize("name", ["english.srt","chinese.srt","bilingual.srt","srt_processing_report.json","srt_processing_manifest.json"])
def test_corrupted_real_artifacts_cannot_be_reused(tmp_path,name):
    case = LocalCase(tmp_path)
    assert case.handler.handle(case.command).status == "succeeded"
    (case.workspace / name).write_bytes(b"invalid")
    before = case.snapshot()
    assert case.handler.handle(case.command).status == "failed"
    assert case.snapshot() == before
