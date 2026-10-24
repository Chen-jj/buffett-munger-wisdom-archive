"""Runner regression with real local/ASS/workflow and explicitly fake expensive ports."""

from dataclasses import replace
import json
from pathlib import Path

import pytest

from archive_core.domain import AssetId
from infrastructure.infrastructure.process import ProcessResult
from subtitle_rendering.infrastructure.composition import build_subtitle_rendering_handler
from tests.subtitle_rendering import sample_runner as runner
from tests.subtitle_rendering.acceptance_support import FakeRenderer, LocalCase, offline_guard


@pytest.fixture
def sample(tmp_path, monkeypatch):
    case = LocalCase(tmp_path / "workspaces")
    monkeypatch.setattr(runner, "ASSET", AssetId("cnbc", "2000", "sample"))
    monkeypatch.setattr(runner, "fixture_paths", lambda *args: (
        case.workspace, case.workspace, {"fixture": case.workspace}, case.outputs,
        case.workspace / "unused-receipt.json", list(case.input_paths),
    ))
    monkeypatch.setattr(runner, "inspect_sources", lambda *args: {"cues": 2, "sections": 1, "sentences": 1})

    class ObservedFakeRenderer(FakeRenderer):
        def __init__(self, **kwargs):
            super().__init__()
            self.encode_count = self.pixel_count = 0

        def render(self, command, *, cwd):
            self.encode_count += 1
            return super().render(command, cwd=cwd)

    monkeypatch.setattr(runner, "ObservedRenderer", ObservedFakeRenderer)
    def build(**options):
        def pixels(*args):
            result = case.pixels(*args)
            options["renderer"].pixel_count += len(result)
            return result
        return build_subtitle_rendering_handler(
            output_root=str(case.root), artifacts=options["artifacts"], renderer=options["renderer"],
            probe=case.probe, font_factory=case.font, segmenter=case.segmenter,
            pixel_preflight=pixels, clock=case.clock,
        )
    monkeypatch.setattr(runner, "build_subtitle_rendering_handler", build)
    def child(**options):
        value = runner.run_local_sample(**options, reuse_only=True)
        return {"status": value["status"], "first_status": value.get("first_status"),
                "counts": value.get("first_counts"), "outputs": value.get("outputs"),
                "upstream_unchanged": value.get("upstream_unchanged")}
    monkeypatch.setattr(runner, "independent_reuse", child)
    return case


def test_opt_in_is_required_without_inspection_or_output(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(runner, "fixture_paths", lambda *args: pytest.fail("must not inspect without --run"))
    assert runner.main(["--output-root", str(tmp_path / "never")]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "opt_in_required"
    assert not list(tmp_path.iterdir())


def test_missing_preconditions_list_all_paths_and_never_construct_handler(tmp_path, monkeypatch, capsys):
    roots = {"missing": tmp_path / "missing-root"}
    missing = [tmp_path / "one.json", tmp_path / "two.json"]
    monkeypatch.setattr(runner, "fixture_paths", lambda *args: (tmp_path, tmp_path, roots, {}, tmp_path / "receipt", missing))
    monkeypatch.setattr(runner, "build_subtitle_rendering_handler", lambda **kwargs: pytest.fail("no handler"))
    assert runner.main(["--run"]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "precondition_missing"
    assert set(result["missing_inputs"]) == {str(path) for path in [*missing, *roots.values()]}
    assert not list(tmp_path.iterdir())


def test_explicit_integration_missing_inputs_is_failure_not_skip(tmp_path, monkeypatch):
    from tests.subtitle_rendering import test_integration_local as integration
    monkeypatch.setenv("RUN_SUBTITLE_RENDERING_INTEGRATION", "1")
    output = tmp_path / "output"
    output.mkdir()
    monkeypatch.setattr(integration, "DEFAULT_OUTPUT_ROOT", output / "cue-evaluation/date/workspaces")
    monkeypatch.setattr(integration, "run_local_sample", lambda: {"status": "precondition_missing", "missing_inputs": ["/missing"]})
    with pytest.raises(AssertionError, match="precondition_missing"):
        integration.test_real_cnbc_rendering_persists_full_sample_and_reuses_without_writes()
    receipts = list((output / "subtitle-rendering-integration").glob("pytest-*.json"))
    assert len(receipts) == 1 and json.loads(receipts[0].read_text())["status"] == "precondition_missing"


def test_fresh_success_then_same_and_independent_reuse_with_unchanged_real_files(sample):
    result = runner.run_local_sample()
    assert result["status"] == "passed", result
    assert (result["first_status"], result["second_status"]) == ("succeeded", "reused")
    assert result["independent_process_reuse"]["first_status"] == "reused"
    assert result["initial_output_names"] == [] and result["generated_now"]
    assert result["first_counts"] == {"write_count": 10, "stage_count": 4, "publish_count": 5,
                                      "staging_directory_count": 1, "content_encode_count": 1, "pixel_frame_count": 2}
    assert not any(result["same_process_reuse_counts"].values())
    assert not any(result["independent_process_reuse"]["counts"].values())
    assert result["protected_before"] == result["protected_after"]
    assert result["upstream_unchanged"] and result["byte_identical_reuse"]
    assert not result["human_playback_confirmed"]
    assert result["qa"]["summary"]["pixel_preflight_passed"]
    assert all(Path(value["path"]).is_absolute() for value in result["outputs"].values())
    assert sample.clock.calls == 1


def test_existing_complete_set_reports_reuse_not_fabricated_first_generation(sample):
    assert runner.run_local_sample()["status"] == "passed"
    result = runner.run_local_sample()
    assert result["status"] == "passed" and result["first_status"] == "reused"
    assert not result["generated_now"] and len(result["initial_output_names"]) == 5
    assert not any(result["first_counts"].values()) and sample.clock.calls == 1


def test_reuse_only_refuses_to_generate_a_missing_suite(sample):
    result = runner.run_local_sample(reuse_only=True)
    assert result["status"] == "acceptance_failed"
    assert not any(result["counts"].values())
    assert not any(path.exists() for path in sample.outputs.values())


def test_first_production_failure_returns_category_report_and_preserves_residuals(sample, monkeypatch):
    original = runner.build_subtitle_rendering_handler
    def broken(**kwargs):
        handler = original(**kwargs)
        handler.workflow.pixel_preflight = lambda *args: (_ for _ in ()).throw(ValueError("pixel mismatch"))
        return handler
    monkeypatch.setattr(runner, "build_subtitle_rendering_handler", broken)
    result = runner.run_local_sample()
    assert result["status"] == "failed" and result["error_category"] == "layout_failed"
    assert Path(result["first_outcome"]["report_path"]).is_file()
    assert result["residual_paths"] and all(Path(path).is_dir() for path in result["residual_paths"])
    assert not sample.outputs["manifest"].exists() and not sample.outputs["video"].exists()
    assert any(Path(result["residual_paths"][0]).iterdir())


@pytest.mark.parametrize("damage", ["status", "write", "output", "upstream"])
def test_reuse_acceptance_rejects_second_status_writes_or_changed_protected_files(sample, monkeypatch, damage):
    original = runner.build_subtitle_rendering_handler
    def broken(**kwargs):
        handler = original(**kwargs)
        base = handler.handle
        calls = []
        def handle(command):
            calls.append(command)
            value = base(command)
            if len(calls) == 2:
                if damage == "status": value = replace(value, status="failed")
                if damage == "write": kwargs["artifacts"].writes.append(("stage", "forbidden"))
                if damage == "output": sample.outputs["ass"].touch()
                if damage == "upstream": (sample.workspace / "transcription.log").touch()
            return value
        handler.handle = handle
        return handler
    monkeypatch.setattr(runner, "build_subtitle_rendering_handler", broken)
    assert runner.run_local_sample()["status"] == "acceptance_failed"


@pytest.mark.parametrize("damage", ["upstream", "output", "exception"])
def test_independent_reuse_must_prove_unchanged_outputs_and_inputs(sample, monkeypatch, damage):
    original = runner.independent_reuse
    def child(**kwargs):
        if damage == "exception": raise ValueError("bad independent result")
        value = original(**kwargs)
        if damage == "upstream": value["upstream_unchanged"] = False
        if damage == "output": value["outputs"] = {}
        return value
    monkeypatch.setattr(runner, "independent_reuse", child)
    assert runner.run_local_sample()["status"] == "acceptance_failed"


def test_fixture_baseline_failure_does_not_construct_production_handler(sample, monkeypatch):
    monkeypatch.setattr(runner, "inspect_sources", lambda *args: (_ for _ in ()).throw(ValueError("wrong baseline")))
    monkeypatch.setattr(runner, "build_subtitle_rendering_handler", lambda **kwargs: pytest.fail("baseline must gate production"))
    result = runner.run_local_sample()
    assert result["status"] == "acceptance_failed" and not any(result["counts"].values())


def test_snapshot_preserves_lexical_symlink_and_same_byte_target_repoint(tmp_path):
    target = tmp_path / "a"; target.write_bytes(b"same")
    twin = tmp_path / "b"; twin.write_bytes(b"same")
    link = tmp_path / "link"; link.symlink_to(target)
    before = runner.file_state(link)
    retained = tmp_path / "retained-link"; link.rename(retained)
    link.symlink_to(twin)
    after = runner.file_state(link)
    assert before["target"]["sha256"] == after["target"]["sha256"]
    assert before["readlink"] != after["readlink"] and before != after
    target.touch()
    assert runner.file_state(retained)["target"]["mtime_ns"] != before["target"]["mtime_ns"]


def test_snapshot_excludes_exact_new_outputs_not_historical_same_basename(tmp_path):
    source = tmp_path / "source"; source.mkdir()
    output = tmp_path / "output"; output.mkdir()
    a = source / "bilingual.ass"; a.write_bytes(b"historical")
    b = output / "bilingual.ass"; b.write_bytes(b"new")
    result = runner.snapshot({"tree": tmp_path}, excluded=[b])
    assert set(result["tree"]["files"]) == {"source/bilingual.ass"}


@pytest.mark.parametrize("failure", ["nonzero", "bad_json", "bad_status", "bad_counts"])
def test_independent_process_rejects_failed_or_unverified_receipts(monkeypatch, failure):
    value = {"status": "passed", "first_status": "reused", "first_counts": {"write_count": 0},
             "outputs": {}, "upstream_unchanged": True}
    if failure == "bad_status": value["first_status"] = "succeeded"
    if failure == "bad_counts": value["first_counts"]["write_count"] = 1
    def process(command, **options):
        assert "--reuse-only" in command and command[:3] == (runner.sys.executable, "-m", "tests.subtitle_rendering.sample_runner")
        assert options["cwd"] == runner.REPOSITORY and options["env"]["PYTHONPATH"] == str(runner.REPOSITORY / "src")
        return ProcessResult(command, 2 if failure == "nonzero" else 0,
                             "not JSON" if failure == "bad_json" else json.dumps(value), "")
    monkeypatch.setattr(runner, "run_process", process)
    with pytest.raises((ValueError, json.JSONDecodeError)):
        runner.independent_reuse(output_root=Path("output"), source_root=Path("source"),
                                 ffmpeg_executable="ffmpeg", ffprobe_executable="ffprobe")
