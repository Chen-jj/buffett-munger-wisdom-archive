"""Explicit chain corruption and mixed-generation tests without upstream execution."""

import json

import pytest

from subtitle_rendering.application.inputs import RenderingInputError, load_render_inputs, parse_json
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
    "translation_result.json", "final_bilingual_draft.json", "english.srt", "chinese.srt", "bilingual.srt", "srt_processing_report.json", "srt_processing_manifest.json"])
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
    ("translation_manifest.json", lambda d: d["inputs"]["source_alignment"].update(sha256="f" * 64)),
    ("translation_result.json", lambda d: d.update(source_alignment_sha256="f" * 64)),
    ("final_bilingual_draft.json", lambda d: d["media"].update(video_sha256="f" * 64)),
    ("final_bilingual_draft.json", lambda d: d["cues"][0].update(english_text="rewritten authoritative text")),
    ("srt_processing_report.json", lambda d: d.update(status="failed", error_code="failure")),
    ("srt_processing_report.json", lambda d: d["summary"].update(cue_count=0)),
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


@pytest.mark.parametrize(("text", "over_capacity"), [
    ("a" * 43, False),
    ("a" * 39 + " " + "b" * 40, False),
    ("a" * 85, True),
    ("a" * 42 + " " + "b" * 42, True),
])
def test_upstream_english_capacity_is_warning_not_render_input_budget(text, over_capacity):
    from dataclasses import replace
    from tests.support.current_bilingual import source_plan
    from srt_processing.application.workflow import export_report
    source = source_plan()
    source = replace(source, cues=(replace(source.cues[0], english_text=text), source.cues[1]))
    report = export_report(source)
    assert any(item["code"] == "english.capacity" and item["severity"] == "warning"
               for item in report["findings"]) is over_capacity
    assert report["status"] == "succeeded"


def test_english_count_includes_spaces_and_punctuation_in_current_contract():
    from archive_core.interfaces.bilingual_timing import english_characters
    assert english_characters("A B.") == 4


def test_valid_asr_only_source_has_no_synthetic_official_fusion():
    from dataclasses import replace
    from archive_core.interfaces.transcription import MatchType, TextSource
    from tests.support.current_bilingual import alignment, populate_current_chain
    case = WorkflowCase()
    source = alignment(sections=False)
    source = replace(source, words=tuple(replace(word, official_token_ids=(), match_type=MatchType.ASR_ONLY, text_source=TextSource.ASR)
                                        for word in source.words),
                     sentences=tuple(replace(sentence, text_source=TextSource.ASR) for sentence in source.sentences))
    case.put("source_alignment.json", source.to_dict())
    manifest = case.read("transcription_manifest.json")
    manifest["records"].pop("transcript_fusion")
    manifest["records"]["source_alignment"].update(size_bytes=case.evidence("source_alignment.json")["size_bytes"],
                                                    sha256=case.evidence("source_alignment.json")["sha256"])
    manifest["records"]["source_alignment"]["provenance"]["sentence_input_sha256"] = manifest["records"]["aligned_asr"]["sha256"]
    case.put("transcription_manifest.json", manifest)
    populate_current_chain(case)
    assert load(case).alignment == source


def case_with_many_to_one_fusion(*, interpolated=False, count_overrides=None, maximum_ratio=0.25):
    from dataclasses import replace
    from archive_core.interfaces.transcription import MatchType, TimingSource
    from tests.support.current_bilingual import alignment, populate_current_chain

    case = WorkflowCase()
    manifest = case.read("transcription_manifest.json")
    records = manifest["records"]

    def replace_record(name, filename, data):
        case.put(filename, data)
        recorded = case.evidence(filename)
        records[name].update(size_bytes=recorded["size_bytes"], sha256=recorded["sha256"])

    acoustic = case.read("aligned_asr.json")
    words = acoustic["words"]
    if interpolated:
        words[1].update(timing_source="interpolated", alignment_score=None,
                        left_anchor_id="aw1", right_anchor_id="aw3")
    last = words[-1]
    words[-1:] = [
        {**last, "text": "In", "end_ms": 1450},
        {**last, "id": "aw4", "raw_word_id": "rw4", "text": "deed.", "start_ms": 1450},
    ]
    replace_record("aligned_asr", "aligned_asr.json", acoustic)

    source = alignment()
    canonical = (
        replace(source.words[0], asr_word_ids=("aw1",)),
        replace(source.words[1], asr_word_ids=("aw2",),
                timing_source=TimingSource.INTERPOLATED if interpolated else TimingSource.ACOUSTIC_ALIGNMENT),
        replace(source.words[2], asr_word_ids=("aw3", "aw4"), match_type=MatchType.MANY_TO_ONE,
                timing_source=TimingSource.MERGED_ACOUSTIC_ALIGNMENT),
    )
    fusion = case.read("transcript_fusion.json")
    fusion["aligned_asr_sha256"] = records["aligned_asr"]["sha256"]
    fusion["words"] = [word.to_dict() for word in canonical]
    records["transcript_fusion"]["provenance"]["aligned_asr_sha256"] = fusion["aligned_asr_sha256"]
    replace_record("transcript_fusion", "transcript_fusion.json", fusion)
    records["source_alignment"]["provenance"]["sentence_input_sha256"] = records["transcript_fusion"]["sha256"]
    replace_record("source_alignment", "source_alignment.json", replace(source, words=canonical).to_dict())

    report = case.read("transcription_report.json")
    report["counts"].update(aligned=4 - int(interpolated), interpolated=int(interpolated), many_to_one=1)
    report["counts"].update(count_overrides or {})
    replace_record("transcription_report", "transcription_report.json", report)
    manifest["workflow"]["summary"] = report["counts"]
    manifest["workflow"]["qa_policy"]["max_interpolated_word_ratio"] = maximum_ratio
    case.put("transcription_manifest.json", manifest)
    populate_current_chain(case)
    return case


@pytest.mark.parametrize("interpolated", [False, True])
def test_forced_alignment_counts_are_not_post_fusion_word_counts(interpolated):
    case = case_with_many_to_one_fusion(interpolated=interpolated)
    result = load(case)
    assert len(case.read("aligned_asr.json")["words"]) == 4
    assert len(result.alignment.words) == 3
    assert result.alignment.words[-1].asr_word_ids == ("aw3", "aw4")
    assert not case.store.writes


@pytest.mark.parametrize("overrides,maximum_ratio", [
    ({"aligned": 3}, 0.25),
    ({"interpolated": 0}, 0.25),
    ({}, 0.24),
])
def test_resigned_qa_counts_and_interpolation_limit_still_bind_acoustic_evidence(overrides, maximum_ratio):
    # Use non-interpolated evidence for the first case: three is the incorrect post-fusion count.
    case = case_with_many_to_one_fusion(interpolated="aligned" not in overrides,
                                       count_overrides=overrides, maximum_ratio=maximum_ratio)
    with pytest.raises(RenderingInputError, match="transcription QA summary differs"):
        load(case)
