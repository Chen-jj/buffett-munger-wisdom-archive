"""Offline guards for the live-only public-entrypoint downstream refresh runner."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from archive_core.application import build_asset_workspace
from tests.orchestration.integration.runners import editorial_refresh as runner


def _paths(tmp_path):
    root, archive, model = (tmp_path / name for name in ("current", "preserved", "model"))
    root.mkdir()
    model.mkdir()
    return root, archive, model


@pytest.mark.parametrize("fault", ("closed", "missing-root", "missing-model", "existing-archive", "dangling-archive", "nested", "ancestor"))
def test_refresh_rejects_unsafe_roots_or_closed_gate_before_pipeline(tmp_path, monkeypatch, fault):
    root, archive, model = _paths(tmp_path)
    monkeypatch.setattr(runner, "enabled", lambda _: fault != "closed")
    monkeypatch.setattr(runner, "build_pipeline_handler", lambda: pytest.fail("must not construct pipeline"))
    if fault == "missing-root":
        root = tmp_path / "absent-root"
    elif fault == "missing-model":
        model = tmp_path / "absent-model"
    elif fault == "existing-archive":
        archive.mkdir()
    elif fault == "dangling-archive":
        archive.symlink_to(tmp_path / "absent-target")
    elif fault == "nested":
        archive = root / "nested"
    elif fault == "ancestor":
        archive = tmp_path
    before = runner.snapshot(tmp_path, all_files=True)
    with pytest.raises((RuntimeError, ValueError)):
        runner.execute_editorial_refresh(root, archive, model)
    assert runner.snapshot(tmp_path, all_files=True) == before


def test_invalid_upstream_stops_before_archive_or_stage_construction(tmp_path, monkeypatch):
    root, archive, model = _paths(tmp_path)
    monkeypatch.setattr(runner, "enabled", lambda _: True)
    commands = []

    class Pipeline:
        def verify_run(self, cmd):
            commands.append(cmd)
            return SimpleNamespace(executable=False, stages=[])

    monkeypatch.setattr(runner, "build_pipeline_handler", Pipeline)
    monkeypatch.setattr(runner, "build_translation_handler", lambda **_: pytest.fail("must not construct stages"))
    with pytest.raises(ValueError, match="upstream evidence"):
        runner.execute_editorial_refresh(root, archive, model)
    assert commands[0].target_stage == "source_chunking"
    assert commands[0].allowed_actions == () and commands[0].max_stage_executions == 0
    assert not archive.exists()


@dataclass
class Outcome:
    status: str = "succeeded"
    provider_calls: int = 1


def _wire(tmp_path, monkeypatch, *, stage_failure=None, upstream_mutation=False, reuse_mutation=False,
          current_stages=(), verifier_mutation=False):
    root, archive, model = _paths(tmp_path)
    workspace = build_asset_workspace(runner.SAMPLE, root)
    workspace.mkdir()
    source = workspace / "source_alignment.json"
    source.write_bytes(b"same source")
    os.utime(source, ns=(1_000_000_000, 1_000_000_000))
    (workspace / "translation_result.json").write_bytes(b"old translated content")
    calls = []
    monkeypatch.setattr(runner, "enabled", lambda _: True)

    class Pipeline:
        def verify_run(self, cmd):
            calls.append(("verify", cmd))
            return SimpleNamespace(executable=True, stages=[SimpleNamespace(stage="source_chunking", action="verify_reuse")])

        def run_asset(self, cmd):
            calls.append(("reuse", cmd))
            return {"run_id": "current-reuse", "status": "reused", "stages": [
                {"stage": stage, "status": "reused", "counts": {"calls": 0}, "observed_artifacts_changed": []}
                for stage in runner.command(root, model).allowed_actions
            ]}

    monkeypatch.setattr(runner, "build_pipeline_handler", Pipeline)
    names = ("translation", "bilingual_postprocessing", "srt_export", "subtitle_rendering")
    factories = ("build_translation_handler", "build_bilingual_postprocessing_handler",
                 "build_srt_processing_handler", "build_subtitle_rendering_handler")
    outputs = ("translation_result.json", "final_bilingual_draft.json", "bilingual.srt", "video_中文字幕.mp4")
    checks = {}
    for name, factory_name, output in zip(names, factories, outputs, strict=True):
        if name in current_stages:
            (workspace / output).write_text(f"current {name}")

        def check(cmd, *, output_root=str(root), name=name):
            assert output_root == str(root)
            calls.append((f"{name}-verify", cmd))
            if verifier_mutation:
                source.write_bytes(b"verifier wrote")
            return Outcome(status="reused" if name in current_stages else "failed", provider_calls=0)

        def factory(*, output_root, name=name, output=output):
            assert output_root == str(root)

            def handle(cmd):
                calls.append((name, cmd))
                assert cmd.overwrite is (name not in current_stages and (workspace / output).exists())
                if name in current_stages:
                    return Outcome(status="reused", provider_calls=0)
                (workspace / output).write_text(name)
                if name == "translation" and upstream_mutation:
                    source.write_bytes(b"wrong source")
                return Outcome(status="failed" if stage_failure == name else "succeeded")

            return SimpleNamespace(handle=handle, verify=checks[name])

        checks[name] = check
        monkeypatch.setattr(runner, factory_name, factory)
    monkeypatch.setattr(runner, "verify_srt_export", checks["srt_export"])
    monkeypatch.setattr(runner, "verify_subtitle_rendering", checks["subtitle_rendering"])

    def verify(pipeline, output_root, bundle, completed):
        calls.append(("independent-audit", completed))
        assert output_root == root and bundle == model
        if reuse_mutation:
            source.write_bytes(b"wrong reuse")
        run_path = workspace / "pipeline_runs" / "current" / "run.json"
        run_path.parent.mkdir(parents=True)
        run_path.write_text("{}")
        return {"evidence_path": str(root / "integration_evidence-current-reuse.json")}

    monkeypatch.setattr(runner, "verify_generated_sample", verify)
    return root, archive, model, source, calls


def test_preserves_exact_old_workspace_then_overwrites_only_public_downstream(tmp_path, monkeypatch):
    root, archive, model, source, calls = _wire(tmp_path, monkeypatch)
    before = runner.snapshot(root, all_files=True)
    result = runner.execute_editorial_refresh(root, archive, model)
    assert runner.snapshot(archive / "workspace", all_files=True) == before
    assert (archive / "workspace" / source.relative_to(root)).read_bytes() == b"same source"
    stage_calls = [(name, cmd) for name, cmd in calls if name in runner._STAGE_OUTPUTS]
    assert [name for name, _ in calls] == ["verify", "translation-verify", "translation",
        "bilingual_postprocessing-verify", "bilingual_postprocessing", "srt_export-verify", "srt_export",
        "subtitle_rendering-verify", "subtitle_rendering", "reuse", "independent-audit"]
    assert [cmd.overwrite for _, cmd in stage_calls] == [True, False, False, False]
    for name, cmd in stage_calls:
        assert cmd.asset_id == runner.SAMPLE.value
        for field, value in cmd.__dict__.items():
            if field.endswith("_path") and value is not None:
                assert Path(value).parent == source.parent
    audit = json.loads(Path(result["evidence_path"]).read_text())
    assert audit["kind"] == "downstream_refresh" and audit["fresh_generation"] is False
    assert audit["upstream_unchanged"] is True and audit["semantic_review"] == "not_run"
    assert [x["stage"] for x in audit["stages"]] == [x[0] for x in stage_calls]
    assert source.stat().st_mtime_ns == 1_000_000_000


@pytest.mark.parametrize("fault", ("stage-failed", "source-mutated", "reuse-mutated"))
def test_failure_keeps_archive_and_audits_without_rolling_back_assets(tmp_path, monkeypatch, fault):
    root, archive, model, source, calls = _wire(
        tmp_path, monkeypatch, stage_failure="bilingual_postprocessing" if fault == "stage-failed" else None,
        upstream_mutation=fault == "source-mutated", reuse_mutation=fault == "reuse-mutated")
    with pytest.raises((RuntimeError, AssertionError)):
        runner.execute_editorial_refresh(root, archive, model)
    audit = json.loads((archive / "refresh_evidence.json").read_text())
    assert audit["status"] == "failed"
    assert audit["upstream_unchanged"] is (fault == "stage-failed")
    assert (archive / "workspace" / source.relative_to(root)).read_bytes() == b"same source"
    if fault in {"stage-failed", "source-mutated"}:
        assert not any(name in {"subtitle_rendering", "reuse", "independent-audit"} for name, _ in calls)


def test_downstream_staging_is_allowed_but_unrelated_paths_are_not():
    workspace = build_asset_workspace(runner.SAMPLE, ".").name
    for path in (f"{workspace}/.bilingual.srt.any.tmp", f"{workspace}/.subtitle-rendering.abc/failure-report.json",
                 "translation_checkpoints/attempt.json"):
        assert runner._allowed_change(path, workspace)
    for path in (f"{workspace}/source_alignment.json", f"{workspace}/video.mp4", "unrelated.json"):
        assert not runner._allowed_change(path, workspace)


@pytest.mark.parametrize("stage", tuple(runner._STAGE_OUTPUTS))
def test_public_verified_stage_is_reused_without_overwrite(tmp_path, monkeypatch, stage):
    root, archive, model, source, calls = _wire(tmp_path, monkeypatch, current_stages=(stage,))
    before = runner.snapshot(root, all_files=True)
    runner.execute_editorial_refresh(root, archive, model)
    cmd = next(cmd for name, cmd in calls if name == stage)
    assert cmd.overwrite is False
    audit = json.loads((archive / "refresh_evidence.json").read_text())
    entry = next(x for x in audit["stages"] if x["stage"] == stage)
    assert (entry["status"], entry["verified_status"], entry["provider_calls"]) == ("reused", "reused", 0)
    for name in runner._STAGE_OUTPUTS[stage]:
        relative = str(source.parent.relative_to(root) / name)
        if relative in before:
            assert runner.snapshot(root, all_files=True)[relative] == before[relative]


def test_mutating_public_verifier_fails_before_downstream_execution(tmp_path, monkeypatch):
    root, archive, model, source, calls = _wire(tmp_path, monkeypatch, verifier_mutation=True)
    with pytest.raises(AssertionError, match="verification wrote"):
        runner.execute_editorial_refresh(root, archive, model)
    assert not any(name in runner._STAGE_OUTPUTS for name, _ in calls)
    audit = json.loads((archive / "refresh_evidence.json").read_text())
    assert audit["status"] == "failed" and not audit["upstream_unchanged"]
