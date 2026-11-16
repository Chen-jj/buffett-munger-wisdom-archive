"""Run/reuse the real, same-source CNBC sample through the public pipeline handler."""

from argparse import ArgumentParser
from pathlib import Path
from hashlib import sha256
import json
import os
import subprocess
import sys

from archive_core.application import build_asset_workspace, build_pipeline_run_path
from archive_core.domain import AssetId
from infrastructure.infrastructure.artifacts import evidence, read_json, write_json
from orchestration.interfaces import MediaSelection, PipelineCommand, STAGES, build_pipeline_handler
from tests.orchestration.integration.gates import enabled


ROOT = Path(__file__).resolve().parents[4]
PARENT = AssetId("cnbc", "2000", "morning")
SAMPLE = AssetId("cnbc", "2000", "morning-ch6-7")
DEFAULT_OUTPUT_ROOT = ROOT / "output" / "orchestration-integration" / "NB08-20261106-fresh-v1"
DEFAULT_MODEL_BUNDLE = ROOT / "output" / "models" / "stanza-en-1.11.0"
MODULE = "tests.orchestration.integration.runners.full_fresh"


def command(output_root, model_bundle, *, reuse=False, resume_run_id=None, target_stage="subtitle_rendering"):
    return PipelineCommand(SAMPLE, PARENT, "cnbc:2000", str(Path(output_root).resolve()),
                           MediaSelection(2101000, 2724000, (6, 7)), target_stage=target_stage,
                           allowed_actions=() if reuse else STAGES,
                           max_stage_executions=0 if reuse else len(STAGES), resume_run_id=resume_run_id,
                           model_bundle_path=str(Path(model_bundle).resolve()), download_height=360)


def snapshot(root, *, all_files=False):
    root = Path(root)
    workspaces = tuple(build_asset_workspace(asset, root) for asset in (PARENT, SAMPLE))
    audit_paths = {root / "integration_evidence.json", *(workspace / ".pipeline.lock" for workspace in workspaces)}
    run_dirs = tuple(workspace / "pipeline_runs" for workspace in workspaces)
    result = {}
    for path in sorted(root.rglob("*")):
        if not all_files and (path in audit_paths or any(path.is_relative_to(run_dir) for run_dir in run_dirs)):
            continue
        relative = str(path.relative_to(root))
        if path.is_symlink():
            lexical = path.lstat()
            entry = {"link_target": os.readlink(path), "link_size_bytes": lexical.st_size,
                     "link_mtime_ns": lexical.st_mtime_ns, "target_exists": path.exists()}
            result[relative] = entry
        elif not path.is_file():
            continue
        else:
            entry = result[relative] = {}
        if path.is_file():
            status = path.stat()
            digest = sha256(b"").hexdigest() if status.st_size == 0 else evidence(path).sha256
            entry.update(sha256=digest, size_bytes=status.st_size, mtime_ns=status.st_mtime_ns)
    return result


def assert_reused(result):
    assert result["status"] == "reused", result
    assert len(result["stages"]) == len(STAGES)
    for stage in result["stages"]:
        assert stage["status"] == "reused", stage
        assert stage["counts"] and all(value == 0 for value in stage["counts"].values()), stage
        assert stage["observed_artifacts_changed"] == [], stage


def execute_full_fresh(output_root, model_bundle=DEFAULT_MODEL_BUNDLE):
    if not enabled("full_fresh"):
        raise RuntimeError("set RUN_ORCHESTRATION_INTEGRATION=1 and ORCHESTRATION_INTEGRATION_SCENARIOS=full_fresh")
    output_root = Path(output_root).resolve()
    if output_root.exists():
        raise ValueError("full-fresh requires a previously absent output root; use resume/reuse explicitly")
    if not Path(model_bundle).is_dir():
        raise ValueError(f"prepared Stanza model bundle is missing: {model_bundle}")
    cmd = command(output_root, model_bundle)
    pipeline = build_pipeline_handler()
    plan = pipeline.plan_asset(cmd)
    assert plan.executable and all(stage.action == "execute" for stage in plan.stages), plan.to_dict()
    assert not output_root.exists(), "planning must not create output root"
    generated = pipeline.run_asset(cmd, expected_plan_sha256=plan.sha256)
    assert generated["status"] == "succeeded", generated
    assert tuple(stage["stage"] for stage in generated["stages"]) == STAGES
    assert all(stage["status"] == "succeeded" for stage in generated["stages"]), generated
    return verify_generated_sample(pipeline, output_root, model_bundle, generated)


def verify_generated_sample(pipeline, output_root, model_bundle, generated):
    """Apply the same audit to a completed first run or an explicitly resumed run."""
    workspace = build_asset_workspace(SAMPLE, output_root)
    video = workspace / "video_中文字幕.mp4"
    assert video.is_file(), "rendered MP4 was not persisted"

    protected = snapshot(output_root)
    reuse_cmd = command(output_root, model_bundle, reuse=True)
    same_process = pipeline.run_asset(reuse_cmd)
    assert_reused(same_process)
    assert snapshot(output_root) == protected
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    child = subprocess.run([sys.executable, "-m", MODULE, "--reuse", "--output-root", str(output_root),
                            "--model-bundle", str(model_bundle)], cwd=ROOT, env=env,
                           capture_output=True, text=True, timeout=1800, check=True)
    new_process = json.loads(child.stdout.splitlines()[-1])
    assert_reused(new_process)
    assert snapshot(output_root) == protected

    before_verify = snapshot(output_root, all_files=True)
    verified = pipeline.verify_run(reuse_cmd)
    assert verified.executable and all(stage.action == "verify_reuse" for stage in verified.stages)
    assert snapshot(output_root, all_files=True) == before_verify
    deliverable = evidence(video)
    render_manifest_path = workspace / "subtitle_rendering_manifest.json"
    render_report_path = workspace / "subtitle_rendering_report.json"
    manifest = read_json(render_manifest_path)
    report = read_json(render_report_path)
    assert manifest["summary"] == report["summary"] and report["summary"]["output_media_passed"]
    lineage = []
    parent_id = generated.get("parent_run_id")
    while parent_id is not None:
        if parent_id in {run["run_id"] for run in lineage}:
            raise ValueError("pipeline parent receipt chain is cyclic")
        parent_path = build_pipeline_run_path(SAMPLE, output_root, parent_id) / "run.json"
        previous = read_json(parent_path)
        assert previous["run_id"] == parent_id and previous["input_identity"] == generated["input_identity"]
        lineage.append({"run_id": parent_id, "status": previous["status"], "receipt": evidence(parent_path).to_dict()})
        parent_id = previous.get("parent_run_id")
    evidence_path = output_root / "integration_evidence.json"
    if evidence_path.exists():
        evidence_path = output_root / f"integration_evidence-{generated['run_id']}.json"
    result = {"schema_version": "pipeline.integration-evidence.v1", "first_run_id": lineage[-1]["run_id"] if lineage else generated["run_id"],
              "completed_run_id": generated["run_id"], "prior_runs": list(reversed(lineage)),
              "same_process_run_id": same_process["run_id"], "new_process_run_id": new_process["run_id"],
              "verify_unchanged": True, "protected_artifacts": protected, "sample": {
                  **deliverable.to_dict(), "duration_us": manifest["output_media"]["duration_us"],
                  "cue_count": report["summary"]["cue_count"], "render_report": evidence(render_report_path).to_dict(),
                  "render_manifest": evidence(render_manifest_path).to_dict(),
              },
              "evidence_path": str(evidence_path), "runs": [generated, same_process, new_process]}
    write_json(evidence_path, result)
    return result


def main(argv=None):
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--model-bundle", type=Path, default=DEFAULT_MODEL_BUNDLE)
    parser.add_argument("--reuse", action="store_true")
    parser.add_argument("--resume-run-id")
    args = parser.parse_args(argv)
    if not enabled("full_fresh"):
        parser.error("explicit full_fresh integration gate is closed")
    if args.reuse and args.resume_run_id:
        parser.error("reuse and resume are separate operations")
    if args.reuse or args.resume_run_id:
        pipeline = build_pipeline_handler()
        cmd = command(args.output_root, args.model_bundle, reuse=args.reuse, resume_run_id=args.resume_run_id)
        result = pipeline.run_asset(cmd) if args.reuse else pipeline.resume_asset(cmd)
        if args.reuse:
            assert_reused(result)
        elif result["status"] not in {"succeeded", "reused"}:
            raise RuntimeError(result)
        else:
            result = verify_generated_sample(pipeline, args.output_root.resolve(), args.model_bundle.resolve(), result)
    else:
        result = execute_full_fresh(args.output_root, args.model_bundle)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
