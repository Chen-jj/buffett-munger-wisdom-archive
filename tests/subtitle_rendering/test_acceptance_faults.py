"""SR-06 real local publication fault matrix, including the irreversible commit point."""

from dataclasses import replace
from pathlib import Path

import pytest

from archive_core.interfaces import RenderBoundsDTO
from subtitle_rendering.application import workflow as workflow_module
from tests.subtitle_rendering.acceptance_support import LocalCase, OUTPUT_NAMES, offline_guard, snapshot
from tests.subtitle_rendering.test_acceptance_cross_layer import assert_failure


STAGED_CASES = [
    (operation, key, occurrence)
    for key in ("ass", "plan", "report", "manifest")
    for operation, occurrence in (("stage", 1), ("read", 1), ("read", 2))
]
EVIDENCE_CASES = [(operation, key, 1) for key in ("plan", "ass", "report") for operation in ("size", "sha256")]
EVIDENCE_CASES += [(operation, "video", occurrence) for operation in ("size", "sha256") for occurrence in (1, 2)]
FAULT_CASES = [("mkdir", "stage_dir", 1), *STAGED_CASES, *EVIDENCE_CASES]
FAULT_CASES += [("publish", key, 1) for key in OUTPUT_NAMES]
FAULT_CASES += [(operation, "published_" + key, 1) for key in ("plan", "ass", "video", "report") for operation in ("size", "sha256")]


@pytest.mark.parametrize("operation,key,occurrence", FAULT_CASES)
@pytest.mark.parametrize("old_success", [False, True])
def test_every_real_stage_readback_evidence_and_publish_failure_respects_manifest_last(
        tmp_path, operation, key, occurrence, old_success):
    case = LocalCase(tmp_path)
    if old_success:
        assert case.run().status == "succeeded"
        # Force a genuinely new generation for overwrite, not indistinguishable bytes.
        case.workflow.profile = replace(case.workflow.profile, english=replace(case.workflow.profile.english, font_size=21))
    old_manifest = case.outputs["manifest"].read_bytes() if old_success else None
    old_report = case.outputs["report"].read_bytes() if old_success else None
    upstream = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in case.input_paths}
    before_clock, count, triggered = case.clock.calls, 0, []
    published_key = key.removeprefix("published_")

    def fail(op, path):
        nonlocal count
        if triggered or op != operation:
            return
        target = Path(path)
        if key == "stage_dir":
            matches = op == "mkdir"
        elif key.startswith("published_") or op == "publish":
            matches = target == case.outputs[published_key]
        else:
            matches = target.name == OUTPUT_NAMES[key] and target.parent.name.startswith(".subtitle-rendering.")
        if matches:
            count += 1
            if count == occurrence:
                triggered.append(path)
                raise OSError("private /secret injected failure before side effect")

    case.store.before = fail
    result = case.run(overwrite=old_success)
    assert triggered, (operation, key, occurrence)
    category = "publication_failed"
    if operation == "read" and key == "ass" and occurrence == 2:
        category = "ass_generation_failed"
    if key == "video" and occurrence == 1 and operation in ("size", "sha256"):
        category = "render_validation_failed"
    assert_failure(result, category)
    assert case.clock.calls - before_clock == (1 if key == "manifest" else 0)
    assert upstream == {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in case.input_paths}
    if old_success:
        assert case.outputs["manifest"].read_bytes() == old_manifest
        if case.outputs["report"].read_bytes() != old_report:
            # A new *successful* report may already have been atomically published.
            # A diagnostic failed report must never replace either generation.
            assert case.read(OUTPUT_NAMES["report"])["status"] == "succeeded"
    else:
        assert not case.outputs["manifest"].exists()
    successful_publishes = [Path(path).name for op, path in case.store.operations if op == "publish"]
    # The selected fault is before the operation, so it may appear in the trace but never complete.
    assert successful_publishes.count(OUTPUT_NAMES["manifest"]) <= (2 if old_success else 1)
    assert any(p.is_dir() and p.name.startswith(".subtitle-rendering.") for p in case.workspace.iterdir())
    # Retained state is inspectable; no deletion or rollback is required to make it disappear.
    before_retry, writes = snapshot(tmp_path), case.store.writes
    case.store.before = None
    if any(path.exists() or path.is_symlink() for path in case.outputs.values()):
        assert_failure(case.run(), "artifact_conflict")
        assert snapshot(tmp_path) == before_retry and case.store.writes == writes


@pytest.mark.parametrize("key", ["ass", "plan", "report", "manifest"])
def test_actual_staged_bytes_corruption_is_detected_and_retained_before_success(tmp_path, key):
    case = LocalCase(tmp_path)
    corrupted = []

    def corrupt(operation, path):
        if operation == "stage" and Path(path).name == OUTPUT_NAMES[key] and not corrupted:
            Path(path).write_bytes(Path(path).read_bytes() + b"corruption")
            corrupted.append(Path(path))

    case.store.after = corrupt
    assert_failure(case.run(), "publication_failed")
    assert corrupted and corrupted[0].read_bytes().endswith(b"corruption")
    assert not case.outputs["manifest"].exists()
    assert case.clock.calls == (1 if key == "manifest" else 0)


@pytest.mark.parametrize("key", ["plan", "ass", "video", "report"])
def test_post_rename_body_corruption_cannot_publish_a_success_manifest(tmp_path, key):
    case = LocalCase(tmp_path)
    changed = []

    def corrupt(operation, path):
        if operation == "publish" and Path(path) == case.outputs[key] and not changed:
            Path(path).write_bytes(Path(path).read_bytes() + b"post-rename corruption")
            changed.append(path)

    case.store.after = corrupt
    assert_failure(case.run(), "publication_failed")
    assert changed and not case.outputs["manifest"].exists() and case.clock.calls == 0
    before, writes = snapshot(tmp_path), case.store.writes
    case.store.after = None
    assert_failure(case.run(), "artifact_conflict")
    assert snapshot(tmp_path) == before and case.store.writes == writes


@pytest.mark.parametrize("point", ["clock", "manifest_construct"])
def test_late_clock_and_manifest_construction_failures_retain_four_successful_bodies(tmp_path, monkeypatch, point):
    case = LocalCase(tmp_path)
    attempts = []

    def bad(*args, **kwargs):
        assert all(case.outputs[key].is_file() for key in ("plan", "ass", "video", "report"))
        attempts.append(point)
        if point == "clock":
            case.clock.calls += 1
        raise RuntimeError("private /secret late manifest failure")

    if point == "clock":
        case.clock.now_utc = bad
    else:
        monkeypatch.setattr(workflow_module, "SubtitleRenderManifestDTO", bad)
    assert_failure(case.run(), "publication_failed")
    assert attempts and not case.outputs["manifest"].exists()
    assert case.clock.calls == 1
    assert case.read(OUTPUT_NAMES["report"])["status"] == "succeeded"


@pytest.mark.parametrize("failure", ["publish_receipt", "final_readback"])
def test_manifest_commit_success_then_client_error_is_ambiguous_and_reusable(tmp_path, failure):
    case = LocalCase(tmp_path)
    committed = []

    def after(operation, path):
        if operation == "publish" and Path(path) == case.outputs["manifest"]:
            committed.append(path)
            if failure == "publish_receipt":
                raise OSError("manifest rename completed but receipt failed")

    def before(operation, path):
        if failure == "final_readback" and committed and operation == "read" and Path(path) == case.outputs["manifest"]:
            raise OSError("manifest rename completed but readback failed")

    case.store.before, case.store.after = before, after
    assert_failure(case.run(), "publication_failed")
    assert committed and case.outputs["manifest"].is_file()
    case.store.before = case.store.after = None
    plan, report, manifest = case.parsed_rendering()
    manifest.validate_against_plan_and_report(plan, report)
    before_state, writes = snapshot(tmp_path), case.store.writes
    # No rollback/delete after commit. Next call determines truth from the complete evidence set.
    assert case.run().status == "reused"
    assert snapshot(tmp_path) == before_state and case.store.writes == writes
    assert case.clock.calls == len(case.pixel_calls) == len(case.renderer.calls) == 1


def test_manifest_post_commit_actual_corruption_is_not_reusable(tmp_path):
    case = LocalCase(tmp_path)

    def corrupt(operation, path):
        if operation == "publish" and Path(path) == case.outputs["manifest"]:
            Path(path).write_bytes(b"corrupt manifest after rename")

    case.store.after = corrupt
    assert_failure(case.run(), "publication_failed")
    assert case.outputs["manifest"].read_bytes() == b"corrupt manifest after rename"
    before, writes = snapshot(tmp_path), case.store.writes
    case.store.after = None
    assert_failure(case.run(), "artifact_conflict")
    assert snapshot(tmp_path) == before and case.store.writes == writes


@pytest.mark.parametrize("point,category", [("font", "font_invalid"), ("ass", "ass_generation_failed"),
    ("pixel", "layout_failed"), ("render", "render_failed"), ("probe", "render_validation_failed"),
    ("media_qa", "render_validation_failed")])
def test_expensive_stage_failures_cannot_overwrite_old_success_report_or_manifest(tmp_path, point, category, monkeypatch):
    case = LocalCase(tmp_path)
    assert case.run().status == "succeeded"
    before = {key: (path.read_bytes(), path.stat().st_mtime_ns) for key, path in case.outputs.items()}
    upstream = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in case.input_paths}

    def bad(*args, **kwargs):
        raise RuntimeError("private /secret " + "diagnostic" * 1000)

    if point == "font": case.workflow.font_factory = bad
    if point == "ass": monkeypatch.setattr(case.codec, "encode", bad)
    if point == "pixel": case.workflow.pixel_preflight = bad
    if point == "render": case.renderer.render = bad
    if point == "probe":
        original = case.probe.probe
        case.probe.probe = lambda path: original(path) if Path(path).name == "video.mp4" else bad()
    if point == "media_qa": case.workflow.media_validator = bad
    outcome = case.run(overwrite=True)
    assert_failure(outcome, category)
    assert before == {key: (path.read_bytes(), path.stat().st_mtime_ns) for key, path in case.outputs.items()}
    assert upstream == {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in case.input_paths}
    assert case.clock.calls == 1
    if outcome.report_path:
        assert len(case.read(str(Path(outcome.report_path).relative_to(case.workspace)))["findings"][0]["diagnostic"]) <= 2048


@pytest.mark.parametrize("changed", ["transcription.log", "subtitle_plan.json", "english.srt", "video.mp4"])
@pytest.mark.parametrize("old_success", [False, True])
def test_input_mutation_during_encoding_prevents_all_new_formal_publication(tmp_path, changed, old_success):
    case = LocalCase(tmp_path)
    if old_success:
        assert case.run().status == "succeeded"
    old_outputs = {key: (p.read_bytes(), p.stat().st_mtime_ns) for key, p in case.outputs.items() if p.exists()}
    writes = len(case.store.writes)

    def mutation():
        path = case.workspace / changed
        path.write_bytes(path.read_bytes() + b"deliberate fixture change during encoding")

    case.renderer.on_render = mutation
    assert_failure(case.run(overwrite=old_success), "input_invalid")
    assert not any(op == "publish" for op, path in case.store.writes[writes:])
    assert old_outputs == {key: (p.read_bytes(), p.stat().st_mtime_ns) for key, p in case.outputs.items() if p.exists()}
    assert case.clock.calls == (1 if old_success else 0)


@pytest.mark.parametrize("damage", ["time", "bounds", "line_count", "font", "styles", "empty"])
def test_bad_pixel_port_output_fails_before_full_encoder_even_with_real_ass(tmp_path, damage):
    case = LocalCase(tmp_path)
    original = case.workflow.pixel_preflight

    def pixels(*args):
        values = original(*args)
        if damage == "empty": return ()
        first = values[0]
        if damage == "time": first = replace(first, time_ms=first.time_ms + 1)
        if damage == "bounds": first = replace(first, bounds=RenderBoundsDTO(0, 0, 1, 1))
        if damage == "line_count": first = replace(first, line_count=4)
        if damage == "font": first = replace(first, font_identity_matches=False)
        if damage == "styles": first = replace(first, styles_match=False)
        return (first, *values[1:])

    case.workflow.pixel_preflight = pixels
    assert_failure(case.run(), "layout_failed")
    assert not case.renderer.calls and case.clock.calls == 0
    assert not case.outputs["manifest"].exists()


def test_fresh_pre_staging_failure_can_publish_failed_report_but_dry_run_cannot(tmp_path):
    for dry_run in (False, True):
        case = LocalCase(tmp_path / str(dry_run))
        def fail(*args):
            raise RuntimeError("exact font unavailable")
        case.workflow.font_factory = fail
        before = snapshot(case.root)
        assert_failure(case.run(dry_run=dry_run), "font_invalid")
        if dry_run:
            assert snapshot(case.root) == before and not case.store.writes
        else:
            assert case.read(OUTPUT_NAMES["report"])["status"] == "failed"
            before_retry, writes = snapshot(case.root), case.store.writes
            assert_failure(case.run(), "artifact_conflict")
            assert snapshot(case.root) == before_retry and case.store.writes == writes
        assert case.clock.calls == 0


def test_failed_diagnostic_write_preserves_original_category(tmp_path):
    case = LocalCase(tmp_path)
    def encoder_failure(*args, **kwargs):
        raise RuntimeError("private /secret original encoder error")
    def diagnostic_failure(operation, path):
        if operation == "stage" and Path(path).name == "failure-report.json":
            raise OSError("secondary diagnostic error")
    case.renderer.render = encoder_failure
    case.store.before = diagnostic_failure
    result = case.run()
    assert_failure(result, "render_failed")
    assert result.report_path is None and not case.outputs["manifest"].exists()
