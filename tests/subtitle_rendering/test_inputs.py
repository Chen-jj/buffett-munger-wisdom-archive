"""Explicit chain corruption and mixed-generation tests without upstream execution."""

import json

import pytest

from subtitle_rendering.application.inputs import RenderingInputError, load_render_inputs, parse_json, validate_english_budget
from tests.subtitle_rendering.workflow_fakes import WorkflowCase, encoded


def load(case, **kwargs):
    return load_render_inputs(asset_id=case.asset_id, srt_processing_manifest_path=case.path("srt_processing_manifest.json"),
                              artifacts=case.store, probe=case.probe, output_root=case.root, **kwargs)


@pytest.mark.parametrize("chapters,download", [(False, False), (True, False), (False, True), (True, True)])
def test_entire_explicit_chain_is_validated_and_snapshotted(chapters, download):
    case = WorkflowCase(chapters=chapters, download=download)
    inputs = load(case)
    assert inputs.asset.value == case.asset_id
    assert len(inputs.source_plan.cues) == 2
    assert set(inputs.evidence) == {"srt_processing_manifest", "subtitle_plan", "video"}
    expected = len(case.store.files)
    assert len(inputs.fingerprints) == expected
    assert not case.store.writes
    assert not case.fonts.calls and not case.renderer.calls and not case.pixel_calls


@pytest.mark.parametrize("name", ["video.mp4", "audio.wav", "vad.json", "raw_asr.json", "aligned_asr.json", "transcript_fusion.json",
    "source_alignment.json", "transcription_report.json", "transcription.log", "transcription_manifest.json", "translation_manifest.json",
    "translation_result.json", "subtitle_plan.json", "english.srt", "chinese.srt", "bilingual.srt", "srt_processing_report.json", "srt_processing_manifest.json"])
@pytest.mark.parametrize("change", ["missing", "corrupt", "empty"])
def test_every_explicit_file_is_required_and_hash_checked(name, change):
    case = WorkflowCase()
    if change == "missing":
        case.store.files.pop(case.path(name))
    else:
        case.put(name, b"corrupt bytes" if change == "corrupt" else b"")
    with pytest.raises(RenderingInputError):
        load(case)
    assert not case.fonts.calls and not case.renderer.calls and not case.pixel_calls
    assert not case.store.writes


@pytest.mark.parametrize("record", ["audio", "vad", "raw_asr", "aligned_asr", "transcript_fusion", "source_alignment", "transcription_log", "transcription_report"])
@pytest.mark.parametrize("change", ["missing", "path", "status", "cache_key", "size", "hash", "extra"])
def test_every_transcription_record_is_strict_even_when_outer_manifest_resigned(record, change):
    case = WorkflowCase()
    data = case.read("transcription_manifest.json")
    target = data["records"][record]
    if change == "missing":
        data["records"].pop(record)
    elif change == "path":
        target["path"] = "/another_generation/" + target["path"].split("/")[-1]
    elif change == "status":
        target["status"] = "failed"
    elif change == "cache_key":
        target["cache_key"] = "not-sha256"
    elif change == "size":
        target["size_bytes"] = True
    elif change == "hash":
        target["sha256"] = "a" * 64
    else:
        target["legacy"] = True
    case.put("transcription_manifest.json", data)
    case.resign_srt()
    with pytest.raises(RenderingInputError):
        load(case)


@pytest.mark.parametrize("name,field,value", [
    ("vad", "schema_version", "unknown"), ("vad", "audio_sha256", "e" * 64), ("vad", "audio_duration_ms", 2999), ("vad", "cache_key", "e" * 64),
    ("raw_asr", "audio_sha256", "e" * 64), ("raw_asr", "vad_cache_key", "e" * 64), ("raw_asr", "audio_duration_ms", True),
    ("aligned_asr", "raw_asr_sha256", "e" * 64), ("aligned_asr", "audio_sha256", "e" * 64),
    ("transcript_fusion", "aligned_asr_sha256", "e" * 64), ("transcript_fusion", "chapters_sha256", "e" * 64),
])
def test_signed_cache_envelope_cannot_mix_generations(name, field, value):
    case = WorkflowCase()
    data = case.read(name + ".json")
    data[field] = value
    case.put(name + ".json", data)
    case.resign_transcription(name)
    with pytest.raises(RenderingInputError):
        load(case)


@pytest.mark.parametrize("record,field,value", [
    ("audio", "video_sha256", "f" * 64), ("audio", "duration_ms", 3001),
    ("source_alignment", "sentence_input_sha256", "f" * 64), ("source_alignment", "chapter_input_sha256", "f" * 64),
    ("transcript_fusion", "aligned_asr_sha256", "f" * 64), ("transcript_fusion", "chapters_sha256", "f" * 64),
    ("vad", "provider", {"name": "different", "version": "1"}), ("raw_asr", "config", {"different": True}),
])
def test_signed_record_provenance_links_are_cross_checked(record, field, value):
    case = WorkflowCase()
    data = case.read("transcription_manifest.json")
    data["records"][record]["provenance"][field] = value
    case.put("transcription_manifest.json", data)
    case.resign_srt()
    with pytest.raises(RenderingInputError):
        load(case)


@pytest.mark.parametrize("name,change", [
    ("translation_manifest.json", lambda d: d.update(asset_id="other:asset:id")),
    ("translation_manifest.json", lambda d: d["input"].update(sha256="f" * 64)),
    ("translation_result.json", lambda d: d.update(source_alignment_sha256="f" * 64)),
    ("subtitle_plan.json", lambda d: d.update(video_sha256="f" * 64)),
    ("subtitle_plan.json", lambda d: d["cues"][0].update(english_text="rewritten authoritative text")),
    ("srt_processing_report.json", lambda d: d.update(status="failed", error_code="failure")),
    ("srt_processing_report.json", lambda d: d["summary"].update(extended_cue_count=0)),
    ("source_alignment.json", lambda d: d["words"][0].update(unrecognized=True)),
])
def test_public_dto_and_source_coverage_revalidated_after_outer_resigning(name, change):
    case = WorkflowCase()
    data = case.read(name)
    change(data)
    case.put(name, data)
    case.resign_srt()
    with pytest.raises(RenderingInputError):
        load(case)


@pytest.mark.parametrize("change", [
    lambda d: d["workflow"].update(status="failed"),
    lambda d: d["workflow"].update(completed_stages=[]),
    lambda d: d["workflow"]["summary"].update(error=1),
    lambda d: d["workflow"]["qa_policy"].update(version="unknown"),
    lambda d: d["records"]["source_alignment"]["provenance"].update(sentence_input_sha256="f" * 64),
])
def test_transcription_success_summary_is_not_trusted_by_status_alone(change):
    case = WorkflowCase()
    data = case.read("transcription_manifest.json")
    change(data)
    case.put("transcription_manifest.json", data)
    case.resign_srt()
    with pytest.raises(RenderingInputError):
        load(case)


@pytest.mark.parametrize("change", [lambda d: d.update(status="failed"), lambda d: d["qa"][0].update(passed=False), lambda d: d["counts"].update(aligned=100)])
def test_transcription_report_is_cross_checked(change):
    case = WorkflowCase()
    data = case.read("transcription_report.json")
    change(data)
    case.put("transcription_report.json", data)
    case.resign_transcription("transcription_report")
    with pytest.raises(RenderingInputError):
        load(case)


@pytest.mark.parametrize("kind", ["missing", "corrupt", "schema", "unknown_field"])
def test_explicit_chapter_reference_cannot_be_ignored(kind):
    case = WorkflowCase(chapters=True)
    if kind == "missing":
        case.store.files.pop(case.path("chapters.json"))
    elif kind == "corrupt":
        case.put("chapters.json", b"wrong")
    else:
        data = case.read("chapters.json")
        data["schema_version" if kind == "schema" else "unknown"] = "wrong"
        case.put("chapters.json", data)
    with pytest.raises(RenderingInputError):
        load(case)


@pytest.mark.parametrize("kind", ["missing", "corrupt_video", "asset", "path", "status", "hash"])
def test_original_download_source_is_verified_without_relocation(kind):
    case = WorkflowCase(download=True)
    download_path = "/original/cnbc_2000_sample/download_manifest.json"
    if kind == "missing":
        case.store.files.pop(download_path)
    elif kind == "corrupt_video":
        case.store.files["/original/cnbc_2000_sample/video.mp4"] += b"different"
    else:
        data = json.loads(case.store.files[download_path])
        if kind == "asset": data["asset"]["item"] = "other"
        if kind == "path": data["artifact"]["path"] = case.path("video.mp4")
        if kind == "status": data["download"]["status"] = "failed"
        if kind == "hash": data["artifact"]["checksum"]["value"] = "f" * 64
        case.store.files[download_path] = encoded(data)
    with pytest.raises(RenderingInputError):
        load(case)


@pytest.mark.parametrize("raw", [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1e999}', b'[]', b'null', b'\xff'])
def test_json_does_not_silently_repair_duplicates_or_nonfinite_values(raw):
    with pytest.raises((ValueError, UnicodeError)):
        parse_json(raw)


def test_snapshots_rechecked_after_initial_gate():
    case = WorkflowCase()
    inputs = load(case)
    case.put("transcription.log", b"changed during encoding")
    with pytest.raises(RenderingInputError):
        inputs.verify_unchanged(case.store)


@pytest.mark.parametrize("text", ["a" * 42 + " " + "b" * 42, "a\u0301" * 42 + "\t" + "b" * 42,
    "a" * 42 + "\u3000" * 20 + "b" * 42, "👩\u200d💻" * 21 + " " + "👍🏽" * 42])
def test_english_count_uses_frozen_visible_units_and_excludes_spacing(text):
    validate_english_budget(text, {"english_capacity": 84, "english_line_capacity": 42, "english_max_lines": 2})


@pytest.mark.parametrize("text", ["a" * 43, "a" * 30 + " " + "b" * 30 + " " + "c" * 24])
def test_english_rejects_single_long_word_and_capacity_with_no_two_line_packing(text):
    with pytest.raises(ValueError):
        validate_english_budget(text, {"english_capacity": 84, "english_line_capacity": 42, "english_max_lines": 2})


def test_historical_profile_keeps_own_single_line_budget():
    with pytest.raises(ValueError):
        validate_english_budget("a" * 30 + " " + "b" * 30, {"english_capacity": 42})


def test_real_cnbc_c4_is_94_codepoints_but_within_frozen_visible_word_line_budget():
    text = "In 1999, Berkshire Hathaway managed to produce a positive gain in net worth of one-half of 1%."
    assert len(text) == 94
    validate_english_budget(text, {"english_capacity": 84, "english_line_capacity": 42, "english_max_lines": 2})
