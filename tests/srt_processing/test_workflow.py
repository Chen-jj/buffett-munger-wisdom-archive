from __future__ import annotations

from dataclasses import replace
import hashlib
import json

import pytest

from archive_core.interfaces import (
    SrtProcessingManifestDTO, SubtitleCodecDTO, SubtitlePlanDTO, SubtitleProfileDTO,
    normalize_chinese_text,
)
from srt_processing.application import (
    SrtProcessingArtifactConflict,
    SrtProcessingPlanningFailure,
    SrtProcessingProjectionFailure,
    SrtProcessingPublicationFailure,
    SubtitleInputError,
)
from srt_processing.domain import analyze_plan
from srt_processing.domain.rules import wrap_english_text

from tests.srt_processing.workflow_fakes import WorkflowCase


@pytest.fixture
def case():
    return WorkflowCase()


def _assert_upstream(case, before):
    assert {path: case.store.files[path] for path in case.paths.values()} == before


def _rebind_output(case, name):
    manifest = case.read_output("manifest")
    raw = case.store.files[case.output_paths[name]]
    manifest["outputs"][name]["size_bytes"] = len(raw)
    manifest["outputs"][name]["sha256"] = hashlib.sha256(raw).hexdigest()
    case.write_output("manifest", manifest)


def test_generation_prepares_and_qa_checks_all_outputs_before_manifest_last(case) -> None:
    before = dict(case.store.files)
    result = case.run()
    assert result.status == "succeeded" and result.cue_count == 1 and result.warning_count >= 2
    assert result.plan_path == case.output_paths["subtitle_plan"]
    assert result.english_srt_path == case.output_paths["english_srt"]
    assert result.chinese_srt_path == case.output_paths["chinese_srt"]
    assert result.bilingual_srt_path == case.output_paths["bilingual_srt"]
    assert result.report_path == case.output_paths["report"]
    assert result.manifest_path == case.output_paths["manifest"]
    assert case.store.operations == (
        [("stage", case.output_paths[key]) for key in tuple(case.output_paths)[:5]]
        + [("publish", case.output_paths[key]) for key in tuple(case.output_paths)[:5]]
        + [("stage", result.manifest_path), ("publish", result.manifest_path)]
    )
    assert set(case.formal_outputs()) == set(case.output_paths)
    assert case.planner.calls == 1 and case.clock.calls == 1
    manifest = SrtProcessingManifestDTO.from_dict(case.read_output("manifest"))
    plan = SubtitlePlanDTO.from_dict(case.read_output("subtitle_plan"))
    manifest.validate_against_plan(plan)
    assert manifest.completed_at == "2026-10-21T12:00:00Z"
    assert "completed_at" not in case.read_output("subtitle_plan")
    for key, evidence in manifest.outputs.items():
        raw = case.store.files[case.output_paths[key]]
        assert (evidence.size_bytes, evidence.sha256) == (len(raw), hashlib.sha256(raw).hexdigest())
    _assert_upstream(case, before)


def test_reuse_verifies_complete_evidence_without_planner_clock_or_writes(case) -> None:
    initial = case.run()
    before = dict(case.store.files)
    operations = list(case.store.operations)
    result = case.run()
    assert result.status == "reused"
    assert replace(result, status="succeeded") == initial
    assert case.planner.calls == 1 and case.clock.calls == 1
    assert len(case.probe.calls) == 2
    assert len(case.codec.decode_calls) >= 9
    assert case.store.files == before and case.store.operations == operations


def test_independent_generations_have_identical_plan_srt_and_report_bytes(case) -> None:
    other = WorkflowCase()
    case.run()
    other.run()
    assert case.formal_outputs() == other.formal_outputs()


@pytest.mark.parametrize("missing", ["subtitle_plan", "english_srt", "chinese_srt", "bilingual_srt", "report", "manifest"])
def test_partial_formal_set_is_a_read_only_conflict(case, missing) -> None:
    case.run()
    case.store.files.pop(case.output_paths[missing])
    before = dict(case.store.files)
    writes = list(case.store.operations)
    with pytest.raises(SrtProcessingArtifactConflict):
        case.run()
    assert case.store.files == before and case.store.operations == writes
    assert case.planner.calls == 1


@pytest.mark.parametrize("damaged", ["subtitle_plan", "english_srt", "chinese_srt", "bilingual_srt", "report", "manifest"])
def test_corrupt_formal_file_is_not_overwritten_without_permission(case, damaged) -> None:
    case.run()
    case.store.files[case.output_paths[damaged]] = b"corrupt"
    before = dict(case.store.files)
    with pytest.raises(SrtProcessingArtifactConflict):
        case.run()
    assert case.store.files == before and case.planner.calls == 1


@pytest.mark.parametrize("name", ["transcription_manifest", "source_alignment", "translation_manifest", "translation_result", "video"])
@pytest.mark.parametrize("field,value", [("size_bytes", 12345), ("sha256", "f" * 64)])
def test_every_input_evidence_dimension_binds_reuse(case, name, field, value) -> None:
    case.run()
    manifest = case.read_output("manifest")
    manifest["inputs"][name][field] = value
    case.write_output("manifest", manifest)
    before = dict(case.store.files)
    with pytest.raises(SrtProcessingArtifactConflict):
        case.run()
    assert case.store.files == before


@pytest.mark.parametrize("rule,parameter", [
    ("profile_name", "name"), ("profile_version", "version"),
    ("algorithm_version", "algorithm_version"),
    ("text_normalization_version", "text_normalization_version"),
    ("character_count_version", "character_count_version"),
    ("boundary_rules_version", "boundary_rules_version"), ("cost_rules_version", "cost_rules_version"),
])
def test_every_rule_version_binds_reuse(case, rule, parameter) -> None:
    case.run()
    manifest = case.read_output("manifest")
    manifest["profile"][parameter] += ".changed"
    manifest["rules"][rule] = manifest["profile"][parameter]
    manifest["rules"]["profile_sha256"] = hashlib.sha256(json.dumps(
        manifest["profile"], sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode()).hexdigest()
    case.write_output("manifest", manifest)
    with pytest.raises(SrtProcessingArtifactConflict):
        case.run()


def test_full_profile_parameters_bind_reuse_not_only_name(case) -> None:
    case.run()
    manifest = case.read_output("manifest")
    manifest["profile"]["english_capacity"] = 43
    manifest["rules"]["profile_sha256"] = SubtitleProfileDTO(manifest["profile"]).sha256
    case.write_output("manifest", manifest)
    with pytest.raises(SrtProcessingArtifactConflict):
        case.run()


@pytest.mark.parametrize("path,value", [
    (("schema_version",), "legacy"), (("asset_id",), "cnbc:2000:afternoon"),
    (("status",), "failed"), (("probe", "ffprobe_version"), "ffprobe version changed"),
    (("probe", "stream_selector"), "v:1"), (("probe", "show_entries"), "stream=r_frame_rate"),
    (("media", "video_duration_ms"), 1001), (("codec", "library_version"), "1.9.0"),
    (("codec", "newline"), "\r\n"), (("codec", "bilingual_order"), ["en", "zh-Hans"]),
])
def test_manifest_and_tool_identity_changes_conflict(case, path, value) -> None:
    case.run()
    manifest = case.read_output("manifest")
    target = manifest
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    case.write_output("manifest", manifest)
    with pytest.raises(SrtProcessingArtifactConflict):
        case.run()


@pytest.mark.parametrize("name", ["subtitle_plan", "english_srt", "chinese_srt", "bilingual_srt", "report"])
@pytest.mark.parametrize("field,value", [("size_bytes", 1), ("sha256", "f" * 64), ("path", "video.mp4")])
def test_every_output_evidence_dimension_is_verified(case, name, field, value) -> None:
    case.run()
    manifest = case.read_output("manifest")
    manifest["outputs"][name][field] = value
    case.write_output("manifest", manifest)
    with pytest.raises(SrtProcessingArtifactConflict):
        case.run()


@pytest.mark.parametrize("change", ["transcription_manifest", "translation_manifest", "alignment", "translation", "video"])
def test_actual_valid_input_changes_conflict_with_old_outputs(case, change) -> None:
    case.run()
    if change == "transcription_manifest":
        case.edit(change, ("workflow", "cache_hits"), ["source_alignment"])
    elif change == "translation_manifest":
        case.edit(change, ("completed_at",), "2026-10-21T01:00:00Z")
    elif change == "alignment":
        case.edit("source_alignment", ("sentences", 0, "speaker_label"), "BUFFETT")
        case.rebind_alignment()
    elif change == "translation":
        case.edit("translation_result", ("sentence_translations", 0, "translated_text"), "您好。")
        case.rebind_translation()
    else:
        case.store.files[case.paths["video"]] = b"new canonical video"
        case.edit("transcription_manifest", ("records", "audio", "provenance", "video_sha256"),
                  hashlib.sha256(b"new canonical video").hexdigest())
    before = case.formal_outputs()
    with pytest.raises(SrtProcessingArtifactConflict):
        case.run()
    assert case.formal_outputs() == before


def test_current_probe_identity_and_media_result_are_checked(case) -> None:
    case.run()
    original = case.probe.probe
    case.probe.probe = lambda path: replace(original(path), tool_version="ffprobe version newer")
    with pytest.raises(SrtProcessingArtifactConflict):
        case.run()
    case.probe.probe = lambda path: replace(original(path), video_duration_ms=999)
    with pytest.raises(SrtProcessingArtifactConflict):
        case.run()


def test_updated_hash_cannot_hide_invalid_plan_methods_or_coverage(case) -> None:
    case.run()
    plan = case.read_output("subtitle_plan")
    plan["cues"][0]["english_text"] = "Wrong."
    case.write_output("subtitle_plan", plan)
    _rebind_output(case, "subtitle_plan")
    with pytest.raises(SrtProcessingArtifactConflict):
        case.run()


@pytest.mark.parametrize("change", ["text", "time", "index", "count"])
def test_updated_hash_cannot_hide_srt_projection_loss(case, change) -> None:
    case.run()
    raw = json.loads(case.store.files[case.output_paths["bilingual_srt"]])
    if change == "text":
        raw[0][3] = "wrong"
    elif change == "time":
        raw[0][1] += 1
    elif change == "index":
        raw[0][0] += 1
    else:
        raw = []
    case.store.files[case.output_paths["bilingual_srt"]] = json.dumps(raw).encode()
    _rebind_output(case, "bilingual_srt")
    with pytest.raises(SrtProcessingArtifactConflict):
        case.run()


def test_report_is_recomputed_even_if_its_new_hash_is_recorded(case) -> None:
    case.run()
    report = case.read_output("report")
    report["findings"][0]["message"] = "Misleading unvalidated message"
    case.write_output("report", report)
    _rebind_output(case, "report")
    with pytest.raises(SrtProcessingArtifactConflict):
        case.run()


def test_recorded_summary_cannot_substitute_for_recomputed_qa(case) -> None:
    case.run()
    manifest = case.read_output("manifest")
    manifest["summary"]["extended_cue_count"] = 0
    case.write_output("manifest", manifest)
    with pytest.raises(SrtProcessingArtifactConflict):
        case.run()


def test_resigned_plan_timing_still_must_use_the_single_time_function(case) -> None:
    case.run()
    plan = case.read_output("subtitle_plan")
    plan["cues"][0]["end_ms"] += 1
    plan["cues"][0]["timing_adjustment"]["extension_ms"] += 1
    case.write_output("subtitle_plan", plan)
    _rebind_output(case, "subtitle_plan")
    with pytest.raises(SrtProcessingArtifactConflict):
        case.run()


def test_explicit_overwrite_regenerates_all_six_outputs_but_not_upstream(case) -> None:
    case.run()
    before = {path: case.store.files[path] for path in case.paths.values()}
    case.store.files[case.output_paths["english_srt"]] = b"damaged"
    old_operations = len(case.store.operations)
    assert case.run(overwrite=True).status == "succeeded"
    assert len(case.store.operations) - old_operations == 12
    assert case.planner.calls == 2
    assert case.run().status == "reused"
    _assert_upstream(case, before)


@pytest.mark.parametrize("fail_at", range(1, 7))
def test_each_stage_failure_never_publishes_a_success_manifest(case, fail_at) -> None:
    before = dict(case.store.files)
    case.store.fail_stage_at = fail_at
    with pytest.raises(SrtProcessingPublicationFailure):
        case.run()
    assert case.output_paths["manifest"] not in case.store.files
    _assert_upstream(case, before)


@pytest.mark.parametrize("fail_at", range(1, 7))
def test_each_publish_failure_never_publishes_a_success_manifest(case, fail_at) -> None:
    before = dict(case.store.files)
    case.store.fail_publish_at = fail_at
    with pytest.raises(SrtProcessingPublicationFailure):
        case.run()
    assert case.output_paths["manifest"] not in case.store.files
    _assert_upstream(case, before)


@pytest.mark.parametrize("fail_at", range(1, 7))
def test_each_staged_read_failure_never_publishes_a_success_manifest(case, fail_at) -> None:
    case.store.fail_staged_read_at = fail_at
    with pytest.raises(SrtProcessingPublicationFailure):
        case.run()
    assert case.output_paths["manifest"] not in case.store.files


@pytest.mark.parametrize("fail_at", range(1, 6))
def test_staged_byte_corruption_is_detected_before_any_formal_success_output(case, fail_at) -> None:
    case.store.corrupt_stage_at = fail_at
    with pytest.raises(SrtProcessingPublicationFailure, match="staging changed"):
        case.run()
    assert not any(path in case.store.files for key, path in case.output_paths.items() if key != "report")
    assert case.read_output("report")["status"] == "failed"


def test_staged_manifest_corruption_is_detected_before_success_marker(case) -> None:
    case.store.corrupt_stage_at = 6
    with pytest.raises(SrtProcessingPublicationFailure):
        case.run()
    assert case.output_paths["manifest"] not in case.store.files


def test_planner_failure_can_write_only_failed_report(case) -> None:
    case.planner.failure = ValueError("cannot plan /secret/path")
    with pytest.raises(SrtProcessingPlanningFailure):
        case.run()
    assert set(case.formal_outputs()) == {"report"}
    report = case.read_output("report")
    assert report["status"] == "failed" and report["error_code"] == "planning_failed"
    assert "/secret/path" not in str(report)


def test_failure_report_failure_does_not_mask_original_planning_error(case) -> None:
    case.planner.failure = ValueError("original planning error")
    case.store.fail_failed_report = True
    with pytest.raises(SrtProcessingPlanningFailure, match="original planning error"):
        case.run()
    assert case.formal_outputs() == {}


def test_failure_report_publish_error_does_not_mask_original_planning_error(case) -> None:
    case.planner.failure = ValueError("original planning error")
    case.store.fail_publish_at = 1
    with pytest.raises(SrtProcessingPlanningFailure, match="original planning error"):
        case.run()
    assert case.formal_outputs() == {}


def test_clock_failure_cannot_create_a_success_marker(case) -> None:
    case.clock.now_utc = lambda: "not a UTC timestamp"
    with pytest.raises(SrtProcessingPublicationFailure):
        case.run()
    assert case.output_paths["manifest"] not in case.store.files


def test_input_failure_writes_only_safe_failed_report_when_no_outputs_exist(case) -> None:
    case.store.files.pop(case.paths["translation_manifest"])
    with pytest.raises(SubtitleInputError):
        case.run()
    assert set(case.formal_outputs()) == {"report"}
    assert case.read_output("report")["error_code"] == "input_invalid"
    assert case.probe.calls == [] and case.planner.calls == 0


def test_stale_temporary_files_do_not_claim_formal_completion(case) -> None:
    case.store.files[str(case.workspace / ".subtitle_plan.json.old.tmp")] = b"orphan"
    assert case.run().status == "succeeded"
    assert case.store.files[str(case.workspace / ".subtitle_plan.json.old.tmp")] == b"orphan"


def test_codec_failure_cannot_publish_plan_or_success_marker(case) -> None:
    case.codec.failure = ValueError("codec /secret/path")
    with pytest.raises(SrtProcessingProjectionFailure):
        case.run()
    assert set(case.formal_outputs()) == {"report"}


@pytest.mark.parametrize("change", ["count", "time", "text", "index"])
def test_codec_roundtrip_mismatch_prevents_all_success_publication(case, change) -> None:
    def bad_decode(events):
        if change == "count":
            return ()
        key, value = {"time": ("start_ms", events[0].start_ms + 1),
                      "text": ("text", "changed"), "index": ("index", 2)}[change]
        return (replace(events[0], **{key: value}),)

    case.codec.bad_decode = bad_decode
    with pytest.raises(SrtProcessingProjectionFailure):
        case.run()
    assert set(case.formal_outputs()) == {"report"}


def test_default_input_failure_preserves_entire_existing_success_set(case) -> None:
    case.run()
    before = case.formal_outputs()
    operations = list(case.store.operations)
    case.edit("transcription_manifest", ("workflow", "status"), "failed")
    with pytest.raises(SubtitleInputError):
        case.run()
    assert case.formal_outputs() == before and case.store.operations == operations


def test_failed_explicit_overwrite_leaves_old_manifest_but_mixed_set_is_rejected(case) -> None:
    case.run()
    old_manifest = case.store.files[case.output_paths["manifest"]]
    case.edit("translation_result", ("sentence_translations", 0, "translated_text"), "您好。")
    case.rebind_translation()
    case.store.fail_publish_at = case.store.publish_count + 3
    with pytest.raises(SrtProcessingPublicationFailure):
        case.run(overwrite=True)
    assert case.store.files[case.output_paths["manifest"]] == old_manifest
    assert case.read_output("report")["status"] == "failed"
    with pytest.raises(SrtProcessingArtifactConflict):
        case.run()


@pytest.mark.parametrize("value", [0, 1, "false", None])
def test_overwrite_requires_an_actual_boolean_before_work(case, value) -> None:
    with pytest.raises(SubtitleInputError):
        case.run(overwrite=value)
    assert case.planner.calls == 0 and case.probe.calls == [] and case.store.operations == []


def test_success_report_matches_fresh_domain_qa(case) -> None:
    case.run()
    inputs = case.load()
    plan = SubtitlePlanDTO.from_dict(case.read_output("subtitle_plan"))
    findings, summary = analyze_plan(
        plan, inputs.alignment, inputs.translation,
        chinese_word_spans={sentence.sentence_id: case.segmenter.spans(normalize_chinese_text(sentence.translated_text))
                            for sentence in inputs.translation.sentence_translations},
    )
    report = case.read_output("report")
    assert report["summary"] == summary.to_dict()
    assert report["findings"] == [finding.to_dict() for finding in findings]


def _multiline_case():
    from tests.srt_processing.test_planner import inputs

    case = WorkflowCase()
    source, translated, media = inputs(
        [("Berkshire", "Hathaway's", "shareholders", "value", "long-term", "capital", "growth.")],
        ["长期资本增长。"], duration=400,
    )
    case.write("source_alignment", source.to_dict())
    case.write("translation_result", translated.to_dict())
    case.rebind_alignment()
    case.probe.duration = media.video_duration_ms
    return case


def test_workflow_generates_and_reuses_two_line_english_with_one_line_chinese() -> None:
    case = _multiline_case()
    assert case.run().status == "succeeded"
    plan = SubtitlePlanDTO.from_dict(case.read_output("subtitle_plan"))
    assert len(plan.cues) == 1
    cue = plan.cues[0]
    english = case.codec.decode(case.store.files[case.output_paths["english_srt"]])[0].text
    chinese = case.codec.decode(case.store.files[case.output_paths["chinese_srt"]])[0].text
    bilingual = case.codec.decode(case.store.files[case.output_paths["bilingual_srt"]])[0].text
    assert english == wrap_english_text(cue.english_text) and len(english.split("\n")) == 2
    assert chinese == cue.chinese_text and "\n" not in chinese
    assert bilingual == chinese + "\n" + english
    assert "\n" not in cue.english_text
    before, operations = dict(case.store.files), list(case.store.operations)
    assert case.run().status == "reused"
    assert case.store.files == before and case.store.operations == operations


@pytest.mark.parametrize("name", ["english_srt", "bilingual_srt"])
def test_reuse_rejects_resigned_wrong_line_break_even_with_self_consistent_encoder(name) -> None:
    case = _multiline_case()
    case.run()
    plan = SubtitlePlanDTO.from_dict(case.read_output("subtitle_plan"))
    cue = plan.cues[0]
    wrapped = wrap_english_text(cue.english_text)
    assert "\n" in wrapped
    raw = json.loads(case.store.files[case.output_paths[name]])
    raw[0][3] = raw[0][3].replace(wrapped, cue.english_text)
    case.store.files[case.output_paths[name]] = json.dumps(raw, ensure_ascii=False).encode()
    _rebind_output(case, name)
    original_encode = case.codec.encode

    def wrong_encode(plan, language):
        if language != name.removesuffix("_srt"):
            return original_encode(plan, language)
        data = json.loads(original_encode(plan, language))
        for event in data:
            event[3] = event[3].replace(wrapped, cue.english_text)
        return json.dumps(data, ensure_ascii=False).encode()

    case.codec.encode = wrong_encode
    before, operations = dict(case.store.files), list(case.store.operations)
    with pytest.raises(SrtProcessingArtifactConflict, match="preserve plan"):
        case.run()
    assert case.store.files == before and case.store.operations == operations


def test_workflow_rejects_unwrapped_encoder_before_any_success_publication() -> None:
    case = _multiline_case()
    original_encode = case.codec.encode

    def wrong_encode(plan, language):
        data = json.loads(original_encode(plan, language))
        for event, cue in zip(data, plan.cues, strict=True):
            event[3] = event[3].replace(wrap_english_text(cue.english_text), cue.english_text)
        return json.dumps(data, ensure_ascii=False).encode()

    case.codec.encode = wrong_encode
    with pytest.raises(SrtProcessingProjectionFailure, match="preserve plan"):
        case.run()
    assert set(case.formal_outputs()) == {"report"}


@pytest.mark.parametrize("key", ["chinese_segmentation_engine", "chinese_dictionary_sha256", "chinese_segmentation_mode"])
@pytest.mark.parametrize("existing", [False, True])
def test_segmenter_identity_mismatch_never_falls_back_or_overwrites(case, key, existing) -> None:
    if existing:
        case.run()
    case.segmenter.identity[key] += ".changed"
    before, operations = dict(case.store.files), list(case.store.operations)
    error = SrtProcessingArtifactConflict if existing else SrtProcessingPlanningFailure
    with pytest.raises(error, match="segmenter identity"):
        case.run()
    if existing:
        assert case.store.files == before and case.store.operations == operations
    else:
        assert set(case.formal_outputs()) == {"report"} and case.planner.calls == 0


def test_segmenter_missing_identity_fails_without_planning_fallback(case) -> None:
    del case.segmenter.identity
    with pytest.raises(SrtProcessingPlanningFailure):
        case.run()
    assert case.planner.calls == 0 and set(case.formal_outputs()) == {"report"}


@pytest.mark.parametrize("spans", [(), ((0, 1),), ((0, 2), (1, 3)), ((0, 4),)])
def test_invalid_segmenter_partition_cannot_publish_a_success_plan(case, spans) -> None:
    case.segmenter.spans = lambda text: spans
    with pytest.raises(SrtProcessingPlanningFailure):
        case.run()
    assert set(case.formal_outputs()) == {"report"}


def test_invalid_segmenter_partition_cannot_reuse_or_rewrite_existing_bundle(case) -> None:
    case.run()
    case.segmenter.spans = lambda text: ()
    before, operations = dict(case.store.files), list(case.store.operations)
    with pytest.raises(SrtProcessingArtifactConflict):
        case.run()
    assert case.store.files == before and case.store.operations == operations


@pytest.mark.parametrize("existing", [False, True])
def test_legacy_runtime_codec_identity_cannot_publish_or_reuse_current_profile(case, existing) -> None:
    if existing:
        case.run()
    case.codec.identity = SubtitleCodecDTO()
    before, operations = dict(case.store.files), list(case.store.operations)
    error = SrtProcessingArtifactConflict if existing else SrtProcessingProjectionFailure
    with pytest.raises(error, match="current serialization"):
        case.run()
    if existing:
        assert case.store.files == before and case.store.operations == operations
    else:
        assert set(case.formal_outputs()) == {"report"} and case.planner.calls == 0


@pytest.mark.parametrize("legacy", ["profile_v1", "profile_v2", "codec"])
def test_parseable_legacy_manifest_identity_is_a_read_only_conflict(case, legacy) -> None:
    case.run()
    manifest = case.read_output("manifest")
    if legacy == "codec":
        manifest["codec"].pop("serialization_version")
    else:
        from tests.archive_core.test_subtitle_contracts import candidate_profile, profile

        old = profile() if legacy == "profile_v1" else candidate_profile()
        manifest["profile"] = old.to_dict()
        manifest["rules"].update(profile_name=old.parameters["name"], profile_version=old.parameters["version"],
                                 profile_sha256=old.sha256)
        for name in ("algorithm_version", "text_normalization_version", "character_count_version",
                     "boundary_rules_version", "cost_rules_version"):
            manifest["rules"][name] = old.parameters[name]
    SrtProcessingManifestDTO.from_dict(manifest)
    case.write_output("manifest", manifest)
    before, operations = dict(case.store.files), list(case.store.operations)
    with pytest.raises(SrtProcessingArtifactConflict, match="identity"):
        case.run()
    assert case.store.files == before and case.store.operations == operations
