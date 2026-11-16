"""Runner guards; synthetic files, no ASR/provider/media process/model execution."""

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
import json
import subprocess

import pytest

from archive_core.application import build_asset_workspace
from archive_core.interfaces.bilingual import MediaBoundaryDTO
from tests.orchestration.integration.runners import frozen_source_replay as runner
from tests.orchestration.integration.runners.chunking_evaluation import fingerprint, write_exclusive
from tests.support.current_bilingual import alignment
from translation.interfaces.workflow import TranslationOutcome, BilingualPostprocessingOutcome


@pytest.fixture(autouse=True)
def gate_and_no_process(monkeypatch):
    monkeypatch.setattr(runner, "enabled", lambda _: True)
    monkeypatch.setattr(runner, "run_process", lambda *args, **kwargs: pytest.fail("external process forbidden"))


def source_fixture(tmp_path):
    root = tmp_path / "original"
    workspace = build_asset_workspace(runner.SAMPLE, root)
    workspace.mkdir(parents=True)
    (workspace / "video.mp4").write_bytes(b"synthetic frozen media")
    video = fingerprint(workspace / "video.mp4")
    source = alignment(sections=False)
    write_exclusive(workspace / "source_alignment.json", source.to_dict())
    for name, data in (("audio.wav", b"synthetic PCM"), ("transcription.log", b"synthetic log")):
        (workspace / name).write_bytes(data)
    for name in ("vad.json", "raw_asr.json", "aligned_asr.json"):
        write_exclusive(workspace / name, {"synthetic": True})
    write_exclusive(workspace / "transcription_report.json", {
        "schema_version": "transcription.report.v1", "asset_id": runner.SAMPLE.value,
        "status": "succeeded", "counts": {"aligned": 3, "error": 0}, "findings": [],
        "qa": [{"name": "synthetic", "passed": True, "detail": "Synthetic guard fixture, not real ASR"}]})
    download = workspace / "download_manifest.json"
    write_exclusive(download, {"artifact": {"checksum": {"value": video["sha256"]}, "size_bytes": video["size_bytes"]}})
    names = {"audio": "audio.wav", "vad": "vad.json", "raw_asr": "raw_asr.json", "aligned_asr": "aligned_asr.json",
             "source_alignment": "source_alignment.json", "transcription_log": "transcription.log",
             "transcription_report": "transcription_report.json"}
    records = {}
    for key, name in names.items():
        value = fingerprint(workspace / name)
        records[key] = {"path": str(workspace / name), "size_bytes": value["size_bytes"], "sha256": value["sha256"],
                        "cache_key": "a" * 64, "status": "succeeded", "provenance": {"historical_command": ["do-not-rewrite", str(workspace)]}}
    records["audio"]["provenance"]["video_sha256"] = video["sha256"]
    manifest = {"schema_version": "transcription.audio-vad-asr-cache.v1",
                "asset": {"source": runner.SAMPLE.source, "group": runner.SAMPLE.group, "item": runner.SAMPLE.item},
                "records": records, "workflow": {"status": "succeeded", "summary": {"aligned": 3, "error": 0},
                "inputs": {"download_manifest_path": str(download), "chapters_sha256": None}}}
    write_exclusive(workspace / "transcription_manifest.json", manifest)
    write_exclusive(workspace / "media_boundary.json", MediaBoundaryDTO(video["sha256"], 3000, tuple(range(0, 3000000, 40000))).to_dict())
    return root, workspace, manifest


def test_actual_public_transcription_verifier_accepts_only_explicit_path_projection(tmp_path):
    source, source_workspace, original = source_fixture(tmp_path)
    before = runner.snapshot(source, all_files=True)
    output = tmp_path / "new"
    result = runner.adopt_source(source, output)
    assert result["status"] == "prepared" and result["asr_calls"] == 0
    projected = json.loads((build_asset_workspace(runner.SAMPLE, output) / "transcription_manifest.json").read_bytes())
    restored = deepcopy(projected)
    for key in restored["records"]:
        restored["records"][key]["path"] = original["records"][key]["path"]
    assert restored == original
    assert projected["workflow"] == original["workflow"]
    assert (output / "source_transcription_manifest.original.json").read_bytes() == (source_workspace / "transcription_manifest.json").read_bytes()
    assert runner.snapshot(source, all_files=True) == before
    assert runner.verify_adoption(output)


@pytest.mark.parametrize("condition", ("closed", "existing", "nested", "same", "source_symlink", "parent_symlink"))
def test_prepare_guards_fail_before_copy_or_verifier(tmp_path, monkeypatch, condition):
    source = tmp_path / "source"
    source.mkdir()
    output = tmp_path / "new"
    if condition == "closed":
        monkeypatch.setattr(runner, "enabled", lambda _: False)
    elif condition == "existing":
        output.mkdir()
    elif condition == "nested":
        output = source / "nested"
    elif condition == "same":
        output = source
    elif condition == "source_symlink":
        (source / "escape").symlink_to("not-there")
    elif condition == "parent_symlink":
        alias = tmp_path / "alias"
        alias.symlink_to(source, target_is_directory=True)
        output = alias / "new"
    monkeypatch.setattr(runner, "verify_transcription", lambda *args, **kwargs: pytest.fail("precondition must precede verification"))
    with pytest.raises((ValueError, RuntimeError)):
        runner.adopt_source(source, output)
    if condition not in {"existing", "same"}:
        assert not output.exists()


@pytest.mark.parametrize("fault", ("source_changed", "copy_changed", "projection_changed", "original_changed", "symlink_copy"))
def test_adoption_rejects_tampering_and_retains_all_files(tmp_path, fault):
    source, source_workspace, _ = source_fixture(tmp_path)
    output = tmp_path / "new"
    runner.adopt_source(source, output)
    workspace = build_asset_workspace(runner.SAMPLE, output)
    if fault == "source_changed":
        (source_workspace / "source_alignment.json").write_bytes(b"changed")
    elif fault == "copy_changed":
        (workspace / "audio.wav").write_bytes(b"changed")
    elif fault == "projection_changed":
        (workspace / "transcription_manifest.json").write_text("{}")
    elif fault == "original_changed":
        (output / "source_transcription_manifest.original.json").write_text("{}")
    else:
        # Retain the displaced synthetic file rather than deleting it.
        (workspace / "audio.wav").rename(workspace / "audio.retained.wav")
        (workspace / "audio.wav").symlink_to(source_workspace / "audio.wav")
    before = runner.snapshot(output, all_files=True)
    with pytest.raises(ValueError):
        runner.verify_adoption(output)
    assert runner.snapshot(output, all_files=True) == before


def test_wrong_video_pts_fail_before_creating_replay_root(tmp_path):
    source, workspace, _ = source_fixture(tmp_path)
    path = workspace / "media_boundary.json"
    data = json.loads(path.read_bytes())
    data["video_sha256"] = "f" * 64
    path.write_text(json.dumps(data))
    output = tmp_path / "new"
    with pytest.raises(ValueError, match="frame evidence"):
        runner.adopt_source(source, output)
    assert not output.exists()


@dataclass
class Outcome:
    status: str = "reused"
    analyzer_calls: int = 0
    writes: int = 0
    attempt_count: int = 0


def replay_case(tmp_path, monkeypatch):
    output = tmp_path / "new"
    workspace = build_asset_workspace(runner.SAMPLE, output)
    workspace.mkdir(parents=True)
    (output / runner.ADOPTION).write_text("synthetic adoption")
    monkeypatch.setattr(runner, "verify_adoption", lambda _: {})
    monkeypatch.setattr(runner, "_verify_stage", lambda *args: SimpleNamespace(status="reused"))
    return output, workspace


def test_expensive_execution_requires_explicit_permission_before_any_handler(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "verify_adoption", lambda _: pytest.fail("guard must precede input IO"))
    with pytest.raises(ValueError, match="allow-expensive"):
        runner.run_replay(tmp_path)


@pytest.mark.parametrize("failed_stage", runner.STAGES)
def test_reuse_preflights_all_stages_before_any_execution_handler(tmp_path, monkeypatch, failed_stage):
    root, _ = replay_case(tmp_path, monkeypatch)
    checked = []
    def verify(name, *args):
        checked.append(name)
        return SimpleNamespace(status="failed" if name == failed_stage else "reused", error_message="stale or absent")
    monkeypatch.setattr(runner, "_verify_stage", verify)
    monkeypatch.setattr(runner, "_stage", lambda *args: pytest.fail("stale reuse must not construct execution handlers/providers"))
    with pytest.raises(ValueError, match="preflight"):
        runner.run_replay(root, reuse=True)
    assert checked == list(runner.STAGES[:runner.STAGES.index(failed_stage) + 1])
    assert not list(root.glob("replay_run-*.json"))


def test_verify_write_is_rejected_before_any_execution_handler(tmp_path, monkeypatch):
    root, _ = replay_case(tmp_path, monkeypatch)
    def verify(*args):
        (root / "translation_checkpoints").mkdir()
        (root / "translation_checkpoints" / "unexpected.json").write_text("mutation")
        return SimpleNamespace(status="reused")
    monkeypatch.setattr(runner, "_verify_stage", verify)
    monkeypatch.setattr(runner, "_stage", lambda *args: pytest.fail("mutating verify must stop"))
    with pytest.raises(AssertionError, match="verification wrote"):
        runner.run_replay(root, reuse=True)


def test_reuse_stops_if_handler_construction_changes_root_before_content_call(tmp_path, monkeypatch):
    root, _ = replay_case(tmp_path, monkeypatch)
    def stage(*args):
        (root / "translation_checkpoints").mkdir()
        (root / "translation_checkpoints/changed.json").write_text("unexpected")
        return SimpleNamespace(handle=lambda _: pytest.fail("content must not run after preflight bindings changed")), None
    monkeypatch.setattr(runner, "_stage", stage)
    with pytest.raises(AssertionError, match="construction changed"):
        runner.run_replay(root, reuse=True)


def test_reuse_rejects_lexical_root_symlink_before_verification(tmp_path, monkeypatch):
    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    monkeypatch.setattr(runner, "verify_adoption", lambda _: pytest.fail("lexical root guard must precede verification"))
    with pytest.raises(ValueError, match="symlink"):
        runner.run_replay(alias, reuse=True)


@pytest.mark.parametrize("fault", ("content_call", "checkpoint_write", "old_receipt_write", "failed"))
def test_reuse_rejects_calls_and_root_level_writes_and_retains_failure(tmp_path, monkeypatch, fault):
    root, _ = replay_case(tmp_path, monkeypatch)
    existing = root / "replay_run-historical.json"
    existing.write_text("existing evidence")
    def stage(*args):
        def handle(command):
            if fault == "checkpoint_write":
                (root / "translation_checkpoints").mkdir(exist_ok=True)
                (root / "translation_checkpoints" / "new.json").write_text("unexpected")
            elif fault == "old_receipt_write":
                existing.write_text("changed")
            return Outcome(status="failed" if fault == "failed" else "reused", attempt_count=int(fault == "content_call"))
        return SimpleNamespace(handle=handle), None
    monkeypatch.setattr(runner, "_stage", stage)
    with pytest.raises((RuntimeError, AssertionError)):
        runner.run_replay(root, reuse=True)
    failed = [json.loads(path.read_bytes()) for path in root.glob("replay_run-*.json") if path != existing]
    assert len(failed) == 1 and failed[0]["status"] == "failed"
    assert existing.exists()


def test_five_stage_reuse_is_zero_work_and_does_not_claim_nine_stages(tmp_path, monkeypatch):
    root, _ = replay_case(tmp_path, monkeypatch)
    monkeypatch.setattr(runner, "_stage", lambda *args: (SimpleNamespace(handle=lambda _: Outcome()), None))
    result = runner.run_replay(root, reuse=True)
    runner.assert_reused(result)
    assert len(result["stages"]) == 5 and result["upstream"] == "adopted-not-executed"
    assert result["asr_calls"] == result["forced_alignment_calls"] == 0
    assert all(stage["counts"]["provider_content_calls"] == 0 for stage in result["stages"])


@pytest.mark.parametrize("failed_stage", ("translation", "bilingual_postprocessing"))
@pytest.mark.parametrize("reported_count", (0, 2))
def test_provider_failure_retains_reported_count_but_never_claims_observed_zero(tmp_path, monkeypatch, failed_stage, reported_count):
    root, _ = replay_case(tmp_path, monkeypatch)
    checkpoints = root / "translation_checkpoints"
    checkpoints.mkdir()
    existing = checkpoints / "earlier.json"
    existing.write_text("synthetic earlier checkpoint")
    before = fingerprint(existing)
    completed = checkpoints / "completed-before-failure.json"
    def stage(name, *args):
        def handle(command):
            if name != failed_stage:
                return Outcome(status="succeeded")
            completed.write_text("synthetic partial provider work")
            if name == "translation":
                return TranslationOutcome("failed", None, None, 0, 0, reported_count, None,
                                          error_category="synthetic_failure", error_message="after checkpoint")
            return BilingualPostprocessingOutcome("failed", provider_calls=reported_count,
                                                 error_category="synthetic_failure", error_message="after checkpoint")
        return SimpleNamespace(handle=handle), None
    monkeypatch.setattr(runner, "_stage", stage)
    with pytest.raises(RuntimeError, match="after checkpoint"):
        runner.run_replay(root, allow_expensive=True, target_stage=failed_stage)
    receipts = list(root.glob("replay_run-*.json"))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_bytes())
    failed = receipt["stages"][-1]
    assert receipt["status"] == failed["status"] == "failed"
    assert failed["stage"] == failed_stage
    assert failed["counts"]["provider_content_calls"] is None
    assert failed["counts"]["analyzer_calls"] == failed["counts"]["render_encoding_calls"] == 0
    assert receipt["asr_calls"] == receipt["forced_alignment_calls"] == 0
    evidence = failed["provider_content_call_evidence"]
    assert evidence["status"] == "unknown" and evidence["reported_count"] == reported_count
    assert evidence["reported_count_field"] == ("attempt_count" if failed_stage == "translation" else "provider_calls")
    assert evidence["reason"] and evidence["checkpoint_root"] == str(checkpoints)
    assert evidence["checkpoints_before"] == {"translation_checkpoints/earlier.json": before}
    assert evidence["checkpoints_after"] == {"translation_checkpoints/earlier.json": before,
                                           "translation_checkpoints/completed-before-failure.json": fingerprint(completed)}
    assert completed.exists() and fingerprint(existing) == before
    assert failed["counts"]["artifact_files_changed"] == 1


def test_successful_zero_provider_count_remains_known(tmp_path, monkeypatch):
    root, _ = replay_case(tmp_path, monkeypatch)
    monkeypatch.setattr(runner, "_stage", lambda *args: (SimpleNamespace(handle=lambda _: Outcome(status="succeeded")), None))
    result = runner.run_replay(root, allow_expensive=True, target_stage="translation")
    assert result["status"] == "succeeded"
    assert result["stages"][-1]["counts"]["provider_content_calls"] == 0
    assert "provider_content_call_evidence" not in result["stages"][-1]


@pytest.mark.parametrize("unknown", (None, False, "0", 0.0))
def test_reuse_never_accepts_unknown_or_noninteger_zero_counts(tmp_path, monkeypatch, unknown):
    root, _ = replay_case(tmp_path, monkeypatch)
    monkeypatch.setattr(runner, "_stage", lambda *args: (SimpleNamespace(handle=lambda _: Outcome(attempt_count=unknown)), None))
    with pytest.raises(AssertionError, match="unexpectedly executed"):
        runner.run_replay(root, reuse=True)
    synthetic = {"status": "reused", "stages": [{"stage": "translation", "status": "reused",
                 "counts": {"provider_content_calls": unknown}, "observed_artifacts_changed": []}]}
    with pytest.raises(AssertionError, match="content work"):
        runner.assert_reused(synthetic, ("translation",))


@pytest.mark.parametrize("fault", ("bad_json", "nonzero", "bad_counts", "checkpoint_write", "old_receipt_write"))
def test_independent_reuse_audit_protects_complete_root(tmp_path, monkeypatch, fault):
    root, _ = replay_case(tmp_path, monkeypatch)
    retained = root / "replay_run-retained.json"
    retained.write_text("retained")
    good = {"status": "reused", "stages": [{"stage": name, "status": "reused", "counts": {"calls": 0}, "observed_artifacts_changed": []} for name in runner.STAGES]}
    monkeypatch.setattr(runner, "run_replay", lambda *args, **kwargs: deepcopy(good))
    def child(argv, **kwargs):
        assert kwargs["check"] is True and "--reuse" in argv
        if fault == "nonzero":
            raise subprocess.CalledProcessError(1, argv)
        if fault == "bad_json":
            return SimpleNamespace(stdout="not JSON")
        result = deepcopy(good)
        if fault == "bad_counts":
            result["stages"][0]["counts"]["calls"] = 1
        elif fault == "checkpoint_write":
            (root / "translation_checkpoints").mkdir()
            (root / "translation_checkpoints/unexpected.json").write_text("write")
        else:
            retained.write_text("changed")
        return SimpleNamespace(stdout=json.dumps(result))
    monkeypatch.setattr(runner.subprocess, "run", child)
    with pytest.raises((AssertionError, json.JSONDecodeError, subprocess.CalledProcessError)):
        runner.audit_reuse(root)
    assert not list(root.glob("replay_reuse_evidence-*.json"))
