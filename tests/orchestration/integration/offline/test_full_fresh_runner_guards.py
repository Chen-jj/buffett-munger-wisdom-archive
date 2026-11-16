"""Runner-only adversarial checks; no real stage, provider or child process executes."""

import json
import os
import subprocess

import pytest

from archive_core.application import build_asset_workspace
from tests.orchestration.integration.runners import full_fresh as runner


def _reused():
    return {"run_id": "reuse", "status": "reused", "stages": [
        {"status": "reused", "counts": {"content_calls": 0, "writes": 0}, "observed_artifacts_changed": []}
        for _ in runner.STAGES
    ]}


def test_protects_lexical_symlink_even_when_repointed_to_identical_target_bytes(tmp_path):
    for name in ("first", "other"):
        path = tmp_path / name
        path.write_bytes(b"same")
        os.utime(path, ns=(1_000_000_000, 1_000_000_000))
    link = tmp_path / "alias"
    link.symlink_to("first")
    before = runner.snapshot(tmp_path)
    pending = tmp_path / "pending"
    pending.symlink_to("other")
    pending.replace(link)
    after = runner.snapshot(tmp_path)
    assert before["alias"]["link_target"] == "first"
    assert after["alias"]["link_target"] == "other"
    for key in ("sha256", "size_bytes", "mtime_ns"):
        assert before["alias"][key] == after["alias"][key]
    assert before != after


def test_protects_dangling_link_and_only_excludes_exact_audit_paths(tmp_path):
    workspace = build_asset_workspace(runner.SAMPLE, tmp_path)
    audit = workspace / "pipeline_runs"
    audit.mkdir(parents=True)
    (audit / "run.json").write_text("{}")
    (workspace / ".pipeline.lock").write_text("")
    retained = tmp_path / "historical" / "pipeline_runs"
    retained.mkdir(parents=True)
    (retained / "run.json").write_text("{}")
    (tmp_path / "dangling").symlink_to("not-there")
    stage_only = runner.snapshot(tmp_path)
    assert stage_only["dangling"]["link_target"] == "not-there"
    assert stage_only["dangling"]["target_exists"] is False
    assert not any(path.startswith(f"{workspace.name}/") for path in stage_only)
    assert "historical/pipeline_runs/run.json" in stage_only
    assert f"{workspace.name}/pipeline_runs/run.json" in runner.snapshot(tmp_path, all_files=True)


@pytest.mark.parametrize("fault", ("wrong_status", "writes", "provider", "changed_files"))
def test_reuse_rejects_unverified_or_mutating_receipt(fault):
    outcome = _reused()
    entry = outcome["stages"][-1]
    if fault == "wrong_status":
        entry["status"] = "succeeded"
    elif fault == "writes":
        entry["counts"]["writes"] = 1
    elif fault == "provider":
        entry["counts"]["content_calls"] = 1
    else:
        entry["observed_artifacts_changed"] = ["video"]
    with pytest.raises(AssertionError):
        runner.assert_reused(outcome)


@pytest.mark.parametrize("condition", ("closed", "existing_root", "missing_model"))
def test_full_fresh_preconditions_fail_before_pipeline_construction_or_writes(tmp_path, monkeypatch, condition):
    output_root = tmp_path / "fresh"
    model = tmp_path / "missing-model"
    monkeypatch.setattr(runner, "enabled", lambda _: condition != "closed")

    def forbidden():
        pytest.fail("precondition failure must not construct a pipeline")

    monkeypatch.setattr(runner, "build_pipeline_handler", forbidden)
    if condition == "existing_root":
        output_root.mkdir()
    with pytest.raises((RuntimeError, ValueError)):
        runner.execute_full_fresh(output_root, model)
    assert list(tmp_path.iterdir()) == ([output_root] if condition == "existing_root" else [])


@pytest.mark.parametrize(("fault", "exception"), (
    ("nonzero", subprocess.CalledProcessError), ("bad_json", json.JSONDecodeError),
    ("bad_status", AssertionError), ("bad_counts", AssertionError), ("changed_upstream", AssertionError),
    ("changed_output", AssertionError),
))
def test_independent_reuse_rejects_process_or_protection_failures(tmp_path, monkeypatch, fault, exception):
    workspace = build_asset_workspace(runner.SAMPLE, tmp_path)
    workspace.mkdir()
    video = workspace / "video_中文字幕.mp4"
    upstream = workspace / "source_alignment.json"
    for path in (video, upstream):
        path.write_bytes(b"protected")

    class Pipeline:
        def run_asset(self, command):
            return _reused()

    def child(argv, **options):
        assert options["check"] is True and "--reuse" in argv
        if fault == "nonzero":
            raise subprocess.CalledProcessError(1, argv)
        if fault == "bad_json":
            return subprocess.CompletedProcess(argv, 0, "not-json")
        outcome = _reused()
        if fault == "bad_status":
            outcome["status"] = "failed"
        elif fault == "bad_counts":
            outcome["stages"][0]["counts"]["writes"] = 1
        elif fault == "changed_upstream":
            upstream.write_bytes(b"mutated")
        elif fault == "changed_output":
            video.write_bytes(b"mutated")
        return subprocess.CompletedProcess(argv, 0, json.dumps(outcome))

    monkeypatch.setattr(runner.subprocess, "run", child)
    with pytest.raises(exception):
        runner.verify_generated_sample(Pipeline(), tmp_path, tmp_path, {})
    assert not (tmp_path / "integration_evidence.json").exists()


@pytest.mark.parametrize("changed_file", ("source_alignment.json", "video_中文字幕.mp4"))
def test_same_process_reuse_rejects_changed_protected_files(tmp_path, monkeypatch, changed_file):
    workspace = build_asset_workspace(runner.SAMPLE, tmp_path)
    workspace.mkdir()
    for name in ("source_alignment.json", "video_中文字幕.mp4"):
        (workspace / name).write_bytes(b"protected")

    class Pipeline:
        def run_asset(self, command):
            (workspace / changed_file).write_bytes(b"modified!")
            return _reused()

    def forbidden(*args, **kwargs):
        pytest.fail("same-process failure must stop before new-process reuse")

    monkeypatch.setattr(runner.subprocess, "run", forbidden)
    with pytest.raises(AssertionError):
        runner.verify_generated_sample(Pipeline(), tmp_path, tmp_path, {})
    assert not (tmp_path / "integration_evidence.json").exists()


def test_reuse_only_missing_suite_never_creates_workspace(tmp_path):
    root = tmp_path / "absent"
    command = runner.command(root, tmp_path, reuse=True)
    pipeline = runner.build_pipeline_handler()
    outcome = pipeline.run_asset(command)
    assert outcome["status"] == "blocked" and outcome["receipt_writes"] == 0
    assert not root.exists()


def test_protection_detects_metadata_only_change_and_new_file(tmp_path):
    path = tmp_path / "unchanged.json"
    path.write_bytes(b"same")
    before = runner.snapshot(tmp_path)
    os.utime(path, ns=(1_000_000_000, 1_000_000_000))
    touched = runner.snapshot(tmp_path)
    assert touched[path.name]["sha256"] == before[path.name]["sha256"]
    assert touched != before
    (tmp_path / "new.json").write_bytes(b"new")
    assert runner.snapshot(tmp_path) != touched
