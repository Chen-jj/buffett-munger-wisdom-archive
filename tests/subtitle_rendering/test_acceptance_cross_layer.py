"""Independent SR-06: real local store/domain/ASS with explicit fake expensive ports."""

from dataclasses import replace
from pathlib import Path

import pytest

from archive_core.interfaces import (
    RenderBoundsDTO, SubtitlePlanDTO,
)
from subtitle_rendering.domain.models import LayoutError
from subtitle_rendering.domain.validation import validate_render_plan
from tests.subtitle_rendering.acceptance_support import (
    LocalCase, OUTPUT_NAMES, encoded, offline_guard, snapshot,
)


def assert_failure(outcome, category):
    assert outcome.status == "failed" and outcome.error_category == category
    assert "/secret" not in outcome.error_message and "private" not in outcome.error_message


def test_real_store_contracts_ass_and_media_validator_publish_then_read_only_reuse(tmp_path):
    case = LocalCase(tmp_path)
    initial = snapshot(tmp_path)
    upstream = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in case.input_paths}
    first = case.run()
    assert (first.status, first.action, first.cue_count) == ("succeeded", "render", 2)
    assert first.command == case.renderer.calls[0][0]
    render_plan, report, manifest = case.parsed_rendering()
    source = SubtitlePlanDTO.from_dict(case.read("subtitle_plan.json"))
    render_plan.validate_against_subtitle_plan(source)
    report.validate_against_plan(render_plan)
    manifest.validate_against_plan_and_report(render_plan, report)
    validate_render_plan(render_plan, source, case.font, case.segmenter)
    case.codec.validate(case.outputs["ass"].read_bytes(), render_plan, source)
    for key, evidence in manifest.outputs.items():
        assert case.evidence(OUTPUT_NAMES[key]) == evidence.to_dict()
    assert render_plan.cues[0].end_ms == 1216 and render_plan.cues[0].ass_end_ms == 1220
    assert [Path(path).name for operation, path in case.store.writes if operation == "publish"] == list(OUTPUT_NAMES.values())
    assert case.clock.calls == len(case.pixel_calls) == len(case.renderer.calls) == 1
    before, writes = snapshot(tmp_path), case.store.writes
    for dry_run, expected in ((False, "reused"), (True, "planned"), (False, "reused")):
        result = case.run(dry_run=dry_run)
        assert (result.status, result.action, result.command) == (expected, "reuse", None)
        assert snapshot(tmp_path) == before and case.store.writes == writes
    assert case.clock.calls == len(case.pixel_calls) == len(case.renderer.calls) == 1
    assert upstream == {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in case.input_paths}
    assert len(snapshot(tmp_path)) > len(initial)


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("overwrite", [False, True])
def test_dry_run_is_strictly_zero_write_for_fresh_reuse_and_overwrite(tmp_path, existing, overwrite):
    case = LocalCase(tmp_path)
    if existing:
        assert case.run().status == "succeeded"
    before, writes = snapshot(tmp_path), case.store.writes
    counters = case.clock.calls, len(case.pixel_calls), len(case.renderer.calls)
    result = case.run(dry_run=True, overwrite=overwrite)
    assert result.status == "planned"
    assert result.action == ("reuse" if existing and not overwrite else "render")
    assert (result.command is None) == (result.action == "reuse")
    assert snapshot(tmp_path) == before and case.store.writes == writes
    assert counters == (case.clock.calls, len(case.pixel_calls), len(case.renderer.calls))


@pytest.mark.parametrize("name", OUTPUT_NAMES)
@pytest.mark.parametrize("damage", ["missing", "empty", "corrupt", "dangling_link"])
@pytest.mark.parametrize("dry_run", [False, True])
def test_every_partial_corrupt_and_dangling_output_is_read_only_conflict(tmp_path, name, damage, dry_run):
    case = LocalCase(tmp_path)
    assert case.run().status == "succeeded"
    path = case.outputs[name]
    if damage in ("missing", "dangling_link"):
        path.replace(case.workspace / ("retained-" + path.name))
        if damage == "dangling_link":
            path.symlink_to(case.workspace / "nonexistent-retained-target")
    else:
        path.write_bytes(b"" if damage == "empty" else b"corrupt generation")
    before, writes = snapshot(tmp_path), case.store.writes
    assert_failure(case.run(dry_run=dry_run), "artifact_conflict")
    assert snapshot(tmp_path) == before and case.store.writes == writes
    assert case.clock.calls == len(case.pixel_calls) == len(case.renderer.calls) == 1


@pytest.mark.parametrize("identity", ["profile", "impossible_profile", "font", "tool", "valid_input"])
@pytest.mark.parametrize("dry_run", [False, True])
def test_valid_new_identity_is_conflict_before_new_layout_even_when_impossible(tmp_path, identity, dry_run):
    case = LocalCase(tmp_path)
    assert case.run().status == "succeeded"
    if identity in ("profile", "impossible_profile"):
        profile = case.workflow.profile
        case.workflow.profile = replace(profile, chinese=replace(profile.chinese, font_size=31 if identity == "profile" else 10000))
    elif identity == "font":
        case.font.identity = replace(case.font.identity, measurement_adapter_version=case.font.identity.measurement_adapter_version + ";changed")
    elif identity == "tool":
        case.renderer.tools = replace(case.renderer.tools, libx264_version="changed-libx264")
    else:
        data = case.read("srt_processing_manifest.json")
        data["completed_at"] = "2026-10-24T03:00:00Z"
        case.put("srt_processing_manifest.json", data)
    before, writes, measurements = snapshot(tmp_path), case.store.writes, len(case.font.measurements)
    assert_failure(case.run(dry_run=dry_run), "artifact_conflict")
    assert snapshot(tmp_path) == before and case.store.writes == writes
    assert len(case.font.measurements) == measurements


@pytest.mark.parametrize("damage", ["offset", "speaker", "section", "time", "text"])
def test_resigned_source_plan_must_still_match_public_alignment_and_translation(tmp_path, damage):
    case = LocalCase(tmp_path)
    source = case.read("subtitle_plan.json")
    cue = source["cues"][0]
    if damage == "offset": cue["fragments"][0]["chinese_start_offset"] = 1
    if damage == "speaker": cue["fragments"][0]["speaker_label"] = "MUNGER"
    if damage == "section": cue["section_id"] = "sec2"
    if damage == "time": cue["start_ms"] = 99
    if damage == "text": cue["chinese_text"] = "同意 我们。"
    case.put("subtitle_plan.json", source)
    case.resign_srt()
    assert case.read("srt_processing_manifest.json")["outputs"]["subtitle_plan"] == case.evidence("subtitle_plan.json")
    before = snapshot(tmp_path)
    assert_failure(case.run(), "input_invalid")
    assert snapshot(tmp_path) == before and not case.store.writes
    assert not case.font.calls and not case.renderer.calls and case.clock.calls == 0


@pytest.mark.parametrize("cache,field", [("vad", "audio_sha256"), ("raw_asr", "vad_cache_key"),
    ("aligned_asr", "raw_asr_sha256"), ("transcript_fusion", "aligned_asr_sha256")])
def test_outer_resigning_cannot_hide_deep_cache_generation_mix(tmp_path, cache, field):
    case = LocalCase(tmp_path)
    data = case.read(cache + ".json")
    data[field] = "f" * 64
    case.put(cache + ".json", data)
    case.resign_transcription(cache)
    record = case.read("transcription_manifest.json")["records"][cache]
    assert record["sha256"] == case.evidence(cache + ".json")["sha256"]
    before = snapshot(tmp_path)
    assert_failure(case.run(), "input_invalid")
    assert snapshot(tmp_path) == before and not case.store.writes and not case.font.calls


@pytest.mark.parametrize("name", ["video.mp4", "audio.wav", "vad.json", "raw_asr.json", "aligned_asr.json",
    "transcript_fusion.json", "source_alignment.json", "transcription_report.json", "transcription.log",
    "transcription_manifest.json", "translation_manifest.json", "translation_result.json", "subtitle_plan.json",
    "english.srt", "chinese.srt", "bilingual.srt", "srt_processing_report.json", "srt_processing_manifest.json"])
@pytest.mark.parametrize("damage", ["missing", "corrupt", "dangling_link"])
def test_every_real_upstream_file_is_required_before_font_or_any_write(tmp_path, name, damage):
    case = LocalCase(tmp_path)
    path = case.workspace / name
    if damage == "corrupt":
        path.write_bytes(b"untrusted corrupt bytes")
    else:
        path.replace(case.workspace / ("retained-" + name))
        if damage == "dangling_link":
            path.symlink_to(case.workspace / "missing-link-target")
    before = snapshot(tmp_path)
    assert_failure(case.run(), "input_invalid")
    assert snapshot(tmp_path) == before and not case.store.writes
    assert not case.font.calls and not case.renderer.calls and not case.pixel_calls and case.clock.calls == 0


def _summary_for(plan, previous):
    return replace(previous,
        chinese_line_counts=tuple(sum(len(c.chinese_lines) == n for c in plan.cues) for n in (1, 2)),
        english_line_counts=tuple(sum(len(c.english_lines) == n for c in plan.cues) for n in (1, 2)),
        four_line_cue_count=sum(len(c.chinese_lines) + len(c.english_lines) == 4 for c in plan.cues),
        maximum_width=max(line.width for c in plan.cues for line in (*c.chinese_lines, *c.english_lines)),
        maximum_height=max(c.expected_bounds.bottom - c.expected_bounds.top for c in plan.cues))


@pytest.mark.parametrize("damage", ["valid_losing_break", "safe_false_metrics", "safe_false_bounds"])
def test_resigned_plan_ass_report_manifest_still_need_deterministic_domain_recomputation(tmp_path, damage):
    case = LocalCase(tmp_path)
    assert case.run().status == "succeeded"
    saved, report, manifest = case.parsed_rendering()
    source = SubtitlePlanDTO.from_dict(case.read("subtitle_plan.json"))
    cue = saved.cues[0]
    if damage == "valid_losing_break":
        text = source.cues[0].english_text
        english = tuple(case.font.measure(line, 20, 2, 1) for line in (text[:3], text[3:]))
        width = max(line.width for line in (*cue.chinese_lines, *english))
        height = sum(line.height for line in (*cue.chinese_lines, *english))
        cue = replace(cue, english_break_offsets=(3,), english_lines=english,
                      expected_bounds=RenderBoundsDTO((640 - width) / 2, 318 - height, (640 + width) / 2, 318))
    elif damage == "safe_false_metrics":
        cue = replace(cue, english_lines=(replace(cue.english_lines[0], width=cue.english_lines[0].width + 1),))
    else:
        bounds = cue.expected_bounds
        cue = replace(cue, expected_bounds=RenderBoundsDTO(bounds.left + 1, bounds.top, bounds.right + 1, bounds.bottom))
    forged = replace(saved, cues=(cue, *saved.cues[1:]))
    pixels = tuple(replace(pixel, line_count=len(c.chinese_lines) + len(c.english_lines), bounds=c.expected_bounds)
                   for pixel, c in zip(report.pixel_results, forged.cues))
    forged_report = replace(report, summary=_summary_for(forged, report.summary), pixel_results=pixels)
    forged.validate_against_subtitle_plan(source)
    forged_report.validate_against_plan(forged)
    # All public contracts and the actual ASS round-trip succeed; only frozen layout differs.
    ass = case.codec.encode(forged, source)
    case.codec.validate(ass, forged, source)
    with pytest.raises(LayoutError):
        validate_render_plan(forged, source, case.font, case.segmenter)
    case.outputs["plan"].write_bytes(encoded(forged))
    case.outputs["ass"].write_bytes(ass)
    case.outputs["report"].write_bytes(encoded(forged_report))
    case.outputs["manifest"].write_bytes(encoded(replace(manifest, summary=forged_report.summary)))
    case.resign_render_outputs()
    reparsed_plan, reparsed_report, reparsed_manifest = case.parsed_rendering()
    reparsed_manifest.validate_against_plan_and_report(reparsed_plan, reparsed_report)
    before, writes = snapshot(tmp_path), case.store.writes
    assert_failure(case.run(), "artifact_conflict")
    assert snapshot(tmp_path) == before and case.store.writes == writes
    assert case.clock.calls == len(case.pixel_calls) == len(case.renderer.calls) == 1


@pytest.mark.parametrize("damage", ["time", "line_count", "bounds", "font", "styles", "order", "missing", "summary", "invented_warning"])
def test_report_and_manifest_resigning_cannot_hide_invalid_pixel_or_summary_crosslinks(tmp_path, damage):
    case = LocalCase(tmp_path)
    assert case.run().status == "succeeded"
    report = case.read(OUTPUT_NAMES["report"])
    pixel = report["pixel_results"][0]
    if damage == "time": pixel["time_ms"] += 1
    if damage == "line_count": pixel["line_count"] = 4
    if damage == "bounds": pixel["bounds"]["left"] = 0
    if damage == "font": pixel["font_identity_matches"] = False
    if damage == "styles": pixel["styles_match"] = False
    if damage == "order": report["pixel_results"].reverse()
    if damage == "missing": report["pixel_results"].pop()
    if damage == "summary": report["summary"]["maximum_width"] += 1
    if damage == "invented_warning":
        report["findings"].append({**report["findings"][0], "code": "invented.warning"})
        report["summary"]["warning_count"] += 1
    case.put(OUTPUT_NAMES["report"], report)
    manifest = case.read(OUTPUT_NAMES["manifest"])
    manifest["summary"] = report["summary"]
    case.put(OUTPUT_NAMES["manifest"], manifest)
    case.resign_render_outputs()
    assert case.read(OUTPUT_NAMES["manifest"])["outputs"]["report"] == case.evidence(OUTPUT_NAMES["report"])
    before, writes = snapshot(tmp_path), case.store.writes
    assert_failure(case.run(), "artifact_conflict")
    assert snapshot(tmp_path) == before and case.store.writes == writes


@pytest.mark.parametrize("change", [lambda raw: raw.replace(b"WrapStyle: 2", b"WrapStyle: 0"),
    lambda raw: raw.replace(b"\\fs20", b"\\fs19"), lambda raw: raw.replace(b"c1,", b"speaker,"),
    lambda raw: raw.replace(b"We agree.", br"{\pos(1,2)}We agree."), lambda raw: raw + b"; extra\n"])
def test_resigned_ass_must_still_be_canonical_and_source_preserving(tmp_path, change):
    case = LocalCase(tmp_path)
    assert case.run().status == "succeeded"
    original = case.outputs["ass"].read_bytes()
    altered = change(original)
    assert altered != original
    case.outputs["ass"].write_bytes(altered)
    case.resign_render_outputs()
    before, writes = snapshot(tmp_path), case.store.writes
    assert_failure(case.run(), "artifact_conflict")
    assert snapshot(tmp_path) == before and case.store.writes == writes


@pytest.mark.parametrize("text", [r"字面\N文本", r"字面{\pos}文本", "字面<b>x</b>", "反斜线\\"])
def test_real_ass_codec_preserves_literal_controls_through_local_workflow(tmp_path, text):
    case = LocalCase(tmp_path)
    translated = case.read("translation_result.json")
    translated["sentence_translations"][0]["translated_text"] = text
    case.put("translation_result.json", translated)
    translated_manifest = case.read("translation_manifest.json")
    translated_manifest["output"] = case.evidence("translation_result.json")
    case.put("translation_manifest.json", translated_manifest)
    source = case.read("subtitle_plan.json")
    source["translation_result_sha256"] = case.evidence("translation_result.json")["sha256"]
    source["cues"][0]["chinese_text"] = text
    source["cues"][0]["fragments"][0]["chinese_end_offset"] = len(text)
    case.put("subtitle_plan.json", source)
    case.resign_srt()
    case.assert_explicit_chain()
    assert case.run().status == "succeeded"
    render_plan, _, _ = case.parsed_rendering()
    original = SubtitlePlanDTO.from_dict(source)
    assert "".join(render_plan.cues[0].visual_lines(original.cues[0])[0]) == text
    case.codec.validate(case.outputs["ass"].read_bytes(), render_plan, original)
    assert case.run().status == "reused"


def test_explicit_overwrite_replaces_output_symlink_not_its_upstream_target(tmp_path):
    case = LocalCase(tmp_path)
    linked_target = tmp_path / "retained-input.ass"
    linked_target.write_bytes(b"never overwrite this target")
    before_target = linked_target.read_bytes(), linked_target.stat().st_mtime_ns
    case.outputs["ass"].symlink_to(linked_target)
    assert_failure(case.run(), "artifact_conflict")
    assert case.run(overwrite=True).status == "succeeded"
    assert not case.outputs["ass"].is_symlink()
    assert (linked_target.read_bytes(), linked_target.stat().st_mtime_ns) == before_target
    assert case.run().status == "reused"


def test_invalid_upstream_is_not_reclassified_as_conflict_and_preserves_old_success(tmp_path):
    case = LocalCase(tmp_path)
    assert case.run().status == "succeeded"
    case.put("source_alignment.json", b"corrupt source")
    before, writes = snapshot(tmp_path), case.store.writes
    assert_failure(case.run(), "input_invalid")
    assert snapshot(tmp_path) == before and case.store.writes == writes
