"""Whole-set identity, zero-write modes, stage faults and manifest-last safety."""

from dataclasses import replace
import json
from pathlib import Path

import pytest

from archive_core.interfaces import RenderPixelResultDTO, RenderProfileDTO
from subtitle_rendering.application.workflow import SubtitleRenderingWorkflowError
from subtitle_rendering.interfaces import SubtitleRenderingCommand
from tests.subtitle_rendering.workflow_fakes import WorkflowCase, encoded, sha


@pytest.fixture
def case():
    return WorkflowCase()


def outputs(case):
    return {key: case.store.files.get(path) for key, path in case.output_paths.items()}


def assert_error(case, category, **kwargs):
    with pytest.raises(SubtitleRenderingWorkflowError) as caught:
        case.run(**kwargs)
    assert caught.value.category == category
    return caught.value


def test_success_has_real_stage_order_and_manifest_last(case):
    upstream = dict(case.store.files)
    result = case.run()
    assert result.status == "succeeded" and result.action == "render"
    assert result.cue_count == 2 and result.warning_count == 1
    assert result.command == case.renderer.calls[0][0]
    assert case.clock.calls == 1 and len(case.pixel_calls) == 1
    assert [Path(path).name for op, path in case.store.writes if op == "stage"] == [
        "bilingual.ass", "subtitle_rendering_plan.json", "subtitle_rendering_report.json", "subtitle_rendering_manifest.json"]
    assert [Path(path).name for op, path in case.store.writes if op == "publish"] == [
        "subtitle_rendering_plan.json", "bilingual.ass", "video_中文字幕.mp4", "subtitle_rendering_report.json", "subtitle_rendering_manifest.json"]
    for path, data in upstream.items():
        assert case.store.files[path] == data
    assert all(outputs(case).values())
    manifest = json.loads(outputs(case)["manifest"])
    assert manifest["completed_at"] == "2026-10-24T01:02:03Z"
    assert manifest["summary"]["output_media_passed"] is True
    for key, evidence in manifest["outputs"].items():
        assert evidence["sha256"] == sha(outputs(case)[key])


@pytest.mark.parametrize("overwrite", [False, True])
def test_dry_run_plans_without_directory_stage_clock_pixels_or_encoding(case, overwrite):
    before = dict(case.store.files)
    result = case.run(dry_run=True, overwrite=overwrite)
    assert (result.status, result.action) == ("planned", "render")
    assert result.command and "-n" in result.command
    assert case.store.files == before and not case.store.writes and not case.store.directories
    assert case.clock.calls == 0 and not case.pixel_calls and not case.renderer.calls


@pytest.mark.parametrize("dry_run", [False, True])
def test_reuse_revalidates_without_stage_uuid_clock_pixels_or_encoding(case, dry_run):
    case.run()
    before, writes, count = dict(case.store.files), list(case.store.writes), case.store.serial
    result = case.run(dry_run=dry_run)
    assert (result.status, result.action) == ("planned" if dry_run else "reused", "reuse")
    assert result.command is None
    assert case.store.files == before and case.store.writes == writes and case.store.serial == count
    assert case.clock.calls == 1 and len(case.pixel_calls) == 1 and len(case.renderer.calls) == 1
    assert len(case.probe.calls) == 4  # Source/output for each attempt.
    assert len(case.fonts.calls) == 2


@pytest.mark.parametrize("name", ["plan", "ass", "video", "report", "manifest"])
@pytest.mark.parametrize("dry_run", [False, True])
def test_partial_output_set_is_read_only_conflict(case, name, dry_run):
    case.run()
    case.store.files.pop(case.output_paths[name])
    before, writes = dict(case.store.files), list(case.store.writes)
    assert_error(case, "artifact_conflict", dry_run=dry_run)
    assert case.store.files == before and case.store.writes == writes
    assert case.clock.calls == 1 and len(case.renderer.calls) == 1


@pytest.mark.parametrize("name", ["plan", "ass", "video", "report", "manifest"])
def test_corrupted_complete_output_set_is_read_only_conflict(case, name):
    case.run()
    case.store.files[case.output_paths[name]] += b"corruption"
    before, writes = dict(case.store.files), list(case.store.writes)
    assert_error(case, "artifact_conflict")
    assert case.store.files == before and case.store.writes == writes


@pytest.mark.parametrize("identity", ["tools", "font", "profile", "profile_no_layout", "source_inputs", "media"])
@pytest.mark.parametrize("dry_run", [False, True])
def test_valid_new_identity_conflicts_even_if_new_layout_would_be_impossible(case, identity, dry_run):
    case.run()
    if identity == "tools":
        case.renderer.tools = replace(case.renderer.tools, libass_version="new-libass")
    elif identity == "font":
        case.fonts.identity = replace(case.fonts.identity, measurement_adapter_version=case.fonts.identity.measurement_adapter_version + ";new-font")
    elif identity in ("profile", "profile_no_layout"):
        size = 31 if identity == "profile" else 10000
        case.workflow.profile = replace(RenderProfileDTO(), chinese=replace(RenderProfileDTO().chinese, font_size=size))
    elif identity == "source_inputs":
        data = case.read("srt_processing_manifest.json")
        data["completed_at"] = "2026-10-24T02:03:04Z"
        case.put("srt_processing_manifest.json", data)
    else:
        case.probe.source = replace(case.probe.source, video=replace(case.probe.source.video, pixel_format="yuv444p"))
    before, writes = dict(case.store.files), list(case.store.writes)
    assert_error(case, "artifact_conflict", dry_run=dry_run)
    assert case.store.files == before and case.store.writes == writes


def test_invalid_upstream_remains_input_invalid_not_old_set_conflict(case):
    case.run()
    case.put("source_alignment.json", b"corrupt")
    writes = list(case.store.writes)
    assert_error(case, "input_invalid")
    assert case.store.writes == writes


@pytest.mark.parametrize("partial", [False, True])
def test_explicit_overwrite_regenerates_only_this_stage(case, partial):
    upstream = dict(case.store.files)
    case.run()
    if partial:
        case.store.files.pop(case.output_paths["video"])
    result = case.run(overwrite=True)
    assert (result.status, result.action) == ("succeeded", "render")
    assert len(case.renderer.calls) == 2 and case.clock.calls == 2
    for path, data in upstream.items():
        assert case.store.files[path] == data
    assert case.run().status == "reused"


def test_overwrite_dry_run_does_not_touch_successful_set(case):
    case.run()
    before, writes = dict(case.store.files), list(case.store.writes)
    result = case.run(dry_run=True, overwrite=True)
    assert result.action == "render" and result.command
    assert case.store.files == before and case.store.writes == writes and case.clock.calls == 1


@pytest.mark.parametrize("field,value", [("time_ms", 999), ("line_count", 4), ("font_identity_matches", False), ("styles_match", False)])
def test_pixels_are_mechanically_checked_before_complete_video_encoding(case, field, value):
    base = case.workflow.pixel_preflight
    def invalid(*args):
        pixels = base(*args)
        return (replace(pixels[0], **{field: value}), *pixels[1:])
    case.workflow.pixel_preflight = invalid
    assert_error(case, "layout_failed")
    assert not case.renderer.calls and case.clock.calls == 0
    assert not case.store.exists(case.output_paths["manifest"])


@pytest.mark.parametrize("pixels", [(), [], (object(),)])
def test_incomplete_or_untyped_pixel_results_fail(case, pixels):
    case.workflow.pixel_preflight = lambda *args: pixels
    assert_error(case, "layout_failed")
    assert not case.renderer.calls


def test_success_report_is_never_constructed_or_staged_before_output_media_qa(case, monkeypatch):
    import subtitle_rendering.application.workflow as module
    checked = []
    original = module._successful_report
    def report_after_qa(*args):
        assert checked
        return original(*args)
    def validated(*args):
        checked.append(True)
    case.workflow.media_validator = validated
    monkeypatch.setattr(module, "_successful_report", report_after_qa)
    assert case.run().status == "succeeded"


def test_source_change_during_encoding_prevents_any_body_publication(case):
    case.renderer.on_render = lambda: case.put("transcription.log", b"changed input during render")
    assert_error(case, "input_invalid")
    assert not any(op == "publish" for op, _ in case.store.writes)
    assert case.clock.calls == 0
    assert not case.store.exists(case.output_paths["manifest"])


@pytest.mark.parametrize("operation,name", [
    ("mkdir", None), ("stage", "bilingual.ass"), ("read", "bilingual.ass"),
    ("stage", "subtitle_rendering_plan.json"), ("read", "subtitle_rendering_plan.json"),
    ("stage", "subtitle_rendering_report.json"), ("read", "subtitle_rendering_report.json"),
    ("publish", "subtitle_rendering_plan.json"), ("publish", "bilingual.ass"), ("publish", "video_中文字幕.mp4"), ("publish", "subtitle_rendering_report.json"),
    ("stage", "subtitle_rendering_manifest.json"), ("read", "subtitle_rendering_manifest.json"), ("publish", "subtitle_rendering_manifest.json"),
])
def test_each_stage_readback_and_publish_fault_never_publishes_new_success(case, operation, name):
    def fail(op, path):
        if op != operation:
            return False
        if name is None:
            return True
        return Path(path).name == name and (operation == "publish" or ".subtitle-rendering." in path)
    case.store.failure = fail
    assert_error(case, "publication_failed")
    assert not case.store.exists(case.output_paths["manifest"])
    assert case.clock.calls == (1 if name == "subtitle_rendering_manifest.json" else 0)
    assert not any(op in ("unlink", "rmtree") for op, _ in case.store.operations)
    # Every file left by a failed attempt remains available for inspection.
    if name != "bilingual.ass" or operation == "read":
        assert case.store.directories or operation == "mkdir"


def test_clock_fault_only_after_four_verified_bodies_published(case):
    def clock_failure():
        assert all(case.store.exists(case.output_paths[name]) for name in ("plan", "ass", "video", "report"))
        raise RuntimeError("private clock failure")
    case.clock.now_utc = clock_failure
    assert_error(case, "publication_failed")
    assert not case.store.exists(case.output_paths["manifest"])


@pytest.mark.parametrize("stage,category", [("font", "font_invalid"), ("tools", "tool_unavailable"), ("ass", "ass_generation_failed"),
    ("render", "render_failed"), ("output_probe", "render_validation_failed"), ("output_qa", "render_validation_failed")])
def test_stage_exception_categories_and_bounded_nonpublic_diagnostics(case, stage, category):
    def bad(*args, **kwargs):
        raise RuntimeError("private /secret/path " + "x" * 5000)
    if stage == "font": case.workflow.font_factory = bad
    if stage == "tools": case.renderer.tool_identity = bad
    if stage == "ass": case.codec.encode = bad
    if stage == "render": case.renderer.render = bad
    if stage == "output_qa": case.workflow.media_validator = bad
    if stage == "output_probe":
        base = case.probe.probe
        case.probe.probe = lambda path: base(path) if Path(path).name == "video.mp4" else bad()
    outcome = case.outcome()
    assert outcome.status == "failed" and outcome.error_category == category
    assert "/secret" not in outcome.error_message and "xxxxx" not in outcome.error_message
    assert case.clock.calls == 0
    if outcome.report_path:
        report = json.loads(case.store.files[outcome.report_path])
        assert len(report["findings"][0]["diagnostic"]) <= 2048


def test_failed_overwrite_does_not_replace_prior_success_report(case):
    case.run()
    before = outputs(case)
    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt()
    case.renderer.render = interrupted
    assert_error(case, "render_failed", overwrite=True)
    assert outputs(case) == before
    assert case.clock.calls == 1
    assert any(Path(path).name == "failure-report.json" for path in case.store.files)


def test_failed_best_effort_diagnostic_cannot_mask_original_error(case):
    case.store.failure = lambda op, path: op == "stage"
    result = case.outcome()
    assert result.status == "failed" and result.error_category == "publication_failed"
    assert result.report_path is None and case.clock.calls == 0


@pytest.mark.parametrize("field,value", [("time_ms", 0), ("font_identity_matches", False), ("styles_match", False), ("line_count", 4)])
def test_resigned_report_cannot_forge_saved_pixel_checks(case, field, value):
    case.run()
    report = json.loads(outputs(case)["report"])
    report["pixel_results"][0][field] = value
    raw = encoded(report)
    case.store.files[case.output_paths["report"]] = raw
    manifest = json.loads(outputs(case)["manifest"])
    manifest["outputs"]["report"].update(size_bytes=len(raw), sha256=sha(raw))
    case.store.files[case.output_paths["manifest"]] = encoded(manifest)
    writes = list(case.store.writes)
    assert_error(case, "artifact_conflict")
    assert case.store.writes == writes


def test_handler_rejects_wrong_command_without_running_workflow(case):
    with pytest.raises(ValueError):
        case.handler.handle({"asset_id": case.asset_id})


@pytest.mark.parametrize("flag,value", [("dry_run", 1), ("overwrite", "yes")])
def test_handler_validates_boolean_flags(case, flag, value):
    result = case.outcome(**{flag: value})
    assert result.error_category == "input_invalid" and not case.store.writes
