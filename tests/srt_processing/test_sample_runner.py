import json
import subprocess

import pytest

from tests.srt_processing import sample_runner
from tests.srt_processing.acceptance_fakes import LocalCase


@pytest.fixture(autouse=True)
def no_real_process_or_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("offline acceptance tests must not start tools or networking")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr("socket.create_connection", forbidden)


def test_no_opt_in_does_not_construct_workflow_or_touch_output(tmp_path, monkeypatch, capsys):
    def forbidden(**kwargs):
        raise AssertionError("handler construction is forbidden without --run")

    monkeypatch.setattr(sample_runner, "build_srt_processing_handler", forbidden)
    root = tmp_path / "never-created"
    assert sample_runner.main(["--output-root", str(root)]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "opt_in_required"
    assert not root.exists()


@pytest.mark.parametrize("missing", tuple(sample_runner.INPUT_TYPES))
def test_missing_formal_input_is_reported_before_any_handler_probe_or_write(tmp_path, monkeypatch, missing):
    case = LocalCase(tmp_path)
    path = case.inputs[missing]
    path.rename(path.with_suffix(path.suffix + ".preserved"))
    before = {path.name: path.read_bytes() for path in case.workspace.iterdir()}

    def forbidden(**kwargs):
        raise AssertionError("no workflow is constructed when canonical inputs are missing")

    monkeypatch.setattr(sample_runner, "build_srt_processing_handler", forbidden)
    result = sample_runner.run_local_sample(asset_id=case.asset.value, output_root=case.root)
    assert result["status"] == "precondition_missing"
    assert result["missing_inputs"] == [str(path)]
    assert {path.name: path.read_bytes() for path in case.workspace.iterdir()} == before
    assert not any(path.exists() for path in case.outputs.values())


def test_empty_workdir_does_not_download_generate_or_create_anything(tmp_path):
    root = tmp_path / "empty"
    result = sample_runner.run_local_sample(output_root=str(root))
    assert result["status"] == "precondition_missing"
    assert len(result["missing_inputs"]) == 5
    assert not root.exists()


@pytest.mark.parametrize("asset", ["invalid", "cnbc:2000:morning:extra", None])
def test_invalid_asset_has_no_filesystem_or_tool_side_effects(tmp_path, asset):
    result = sample_runner.run_local_sample(asset_id=asset, output_root=str(tmp_path / "new"))
    assert result["status"] == "precondition_invalid"
    assert list(tmp_path.iterdir()) == []


def test_local_sample_generates_and_reuses_real_srt_without_processes(tmp_path):
    case = LocalCase(tmp_path)
    upstream = case.upstream_bytes()
    result = sample_runner.run_local_sample(asset_id=case.asset.value, output_root=case.root,
                                            probe=case.probe, clock=case.clock, segmenter=case.segmenter)
    assert result["status"] == "passed"
    assert result["first_status"] == "succeeded" and result["second_status"] == "reused"
    assert result["generated_now"] and result["byte_identical_reuse"]
    assert result["upstream_unchanged"] and result["reuse_write_count"] == 0
    assert result["source_counts"] == {"words": 7, "sentences": 3, "sections": 2}
    assert result["summary"]["cue_count"] >= 3
    assert result["warning_count"] >= 3
    assert result["codec"]["library_version"] == "1.8.1"
    assert result["media"]["gap_threshold_ms"] == 84
    assert result["probe"]["ffprobe_version"] == "ffprobe version fake"
    assert set(result["outputs"]) == set(sample_runner.OUTPUT_TYPES)
    assert set(result["input_evidence"]) == set(sample_runner.INPUT_TYPES)
    assert result["cue_samples"]["unknown_speaker"] is not None
    longest, shortest = result["cue_samples"]["longest"], result["cue_samples"]["shortest"]
    assert longest["end_ms"] - longest["start_ms"] >= shortest["end_ms"] - shortest["start_ms"]
    assert "no semantic, pixel" in result["human_review_required"]
    assert case.upstream_bytes() == upstream
    assert len(case.probe.calls) == 2 and case.clock.calls == 1


def test_existing_complete_outputs_are_honestly_reported_as_reuse(tmp_path):
    case = LocalCase(tmp_path)
    assert case.handler().handle(case.command).status == "succeeded"
    before = case.output_bytes()
    result = sample_runner.run_local_sample(asset_id=case.asset.value, output_root=case.root,
                                            probe=case.probe, clock=case.clock, segmenter=case.segmenter)
    assert result["status"] == "passed"
    assert result["first_status"] == "reused" and not result["generated_now"]
    assert result["second_status"] == "reused" and result["byte_identical_reuse"]
    assert case.output_bytes() == before


def test_relative_root_resolves_to_absolute_canonical_upstream_record_paths(tmp_path, monkeypatch):
    case = LocalCase(tmp_path)
    monkeypatch.chdir(tmp_path)
    transcription = case.read_input("transcription_manifest")
    assert transcription["records"]["source_alignment"]["path"].startswith("/")
    result = sample_runner.run_local_sample(asset_id=case.asset.value, output_root="output",
                                            probe=case.probe, clock=case.clock, segmenter=case.segmenter)
    assert result["status"] == "passed" and result["generated_now"]
    assert result["workspace"] == str(case.workspace)
    assert result["second_status"] == "reused" and result["upstream_unchanged"]


def test_partial_output_set_is_not_automatically_overwritten_or_cleaned(tmp_path):
    case = LocalCase(tmp_path)
    case.outputs["english_srt"].write_bytes(b"preexisting partial result")
    before = {path.name: path.read_bytes() for path in case.workspace.iterdir()}
    result = sample_runner.run_local_sample(asset_id=case.asset.value, output_root=case.root,
                                            probe=case.probe, clock=case.clock, segmenter=case.segmenter)
    assert result["status"] == "failed"
    assert result["first_outcome"]["error_category"] == "artifact_conflict"
    assert result["upstream_unchanged"]
    assert {path.name: path.read_bytes() for path in case.workspace.iterdir()} == before


def test_cli_explicit_run_reports_missing_inputs_without_starting_a_tool(tmp_path, monkeypatch, capsys):
    def forbidden(**kwargs):
        raise AssertionError("missing inputs must be handled before composition")

    monkeypatch.setattr(sample_runner, "build_srt_processing_handler", forbidden)
    root = tmp_path / "empty"
    assert sample_runner.main(["--run", "--output-root", str(root)]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "precondition_missing" and len(result["missing_inputs"]) == 5
    assert not root.exists()


@pytest.mark.parametrize("change", ["output_metadata", "upstream"])
def test_runner_independently_rejects_unexpected_side_effect_after_reuse(tmp_path, monkeypatch, change):
    import os

    case = LocalCase(tmp_path)
    real_factory = sample_runner.build_srt_processing_handler
    constructions = []

    def altered_factory(**kwargs):
        handler = real_factory(**kwargs)
        constructions.append(handler)
        if len(constructions) == 2:
            original_handle = handler.handle

            def handle(command):
                result = original_handle(command)
                if change == "upstream":
                    (case.workspace / "audio.wav").write_bytes(b"unexpected upstream mutation")
                else:
                    path = case.outputs["english_srt"]
                    stamp = path.stat()
                    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 1))
                return result

            handler.handle = handle
        return handler

    monkeypatch.setattr(sample_runner, "build_srt_processing_handler", altered_factory)
    with pytest.raises(ValueError, match="upstream files" if change == "upstream" else "file metadata"):
        sample_runner.run_local_sample(asset_id=case.asset.value, output_root=case.root,
                                       probe=case.probe, clock=case.clock, segmenter=case.segmenter)
