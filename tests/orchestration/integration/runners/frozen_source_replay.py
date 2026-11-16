"""Explicit frozen-input adoption and five-stage replay; never rerun upstream.

The transcription manifest is a new, audited path-binding projection, not a new
ASR result or an assertion that nine production stages ran/reused in this root.
Original workflow/commands/cost/provenance remain byte-equivalent JSON values.
"""

from argparse import ArgumentParser
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4
import json
import os
import shutil
import subprocess
import sys

from archive_core.application import build_asset_workspace
from infrastructure.infrastructure.process import run_process
from srt_processing.interfaces.source_chunking import SourceChunkingCommand, build_source_chunking_handler, verify_source_chunking
from srt_processing.interfaces import SrtProcessingCommand, build_srt_processing_handler
from srt_processing.interfaces.workflow import verify_srt_export
from subtitle_rendering.interfaces import SubtitleRenderingCommand, build_subtitle_rendering_handler, verify_subtitle_rendering
from transcription.interfaces import TranscriptionCommand, verify_transcription
from translation.interfaces import (TranslationCommand, BilingualPostprocessingCommand,
                                    build_translation_handler, build_bilingual_postprocessing_handler)
from tests.orchestration.integration.gates import enabled
from .chunking_evaluation import fingerprint, write_exclusive
from .full_fresh import ROOT, SAMPLE, DEFAULT_MODEL_BUNDLE, snapshot


STAGES = ("source_chunking", "translation", "bilingual_postprocessing", "srt_export", "subtitle_rendering")
MODULE = "tests.orchestration.integration.runners.frozen_source_replay"
ADOPTION = "source_adoption.json"


def _require_gate():
    if not enabled("frozen_source_replay"):
        raise RuntimeError("enable the explicit frozen_source_replay integration scenario")


def _regular_tree(root):
    root = Path(root)
    if (any(path.is_symlink() for path in (root, *root.parents))
            or any(path.is_symlink() for path in root.rglob("*"))):
        raise ValueError("frozen-source replay does not accept symlink trees")


def _disjoint(left, right):
    if left == right or left.is_relative_to(right) or right.is_relative_to(left):
        raise ValueError("source and replay roots must be disjoint")


def _transcription_command(workspace, data):
    inputs = data["workflow"]["inputs"]
    return TranscriptionCommand(SAMPLE, inputs["download_manifest_path"], inputs["chapters_sha256"])


def adopt_source(source_root, output_root):
    """Copy verified inputs and publish a clearly identified materialisation view."""
    _require_gate()
    source_root, output_root = Path(source_root).absolute(), Path(output_root).absolute()
    if output_root.exists() or output_root.is_symlink():
        raise ValueError("replay root must be previously absent")
    _regular_tree(source_root)
    _regular_tree(output_root)
    source_root, output_root = source_root.resolve(), output_root.resolve()
    _disjoint(source_root, output_root)
    if not source_root.is_dir():
        raise ValueError("existing frozen-source root required")
    source_workspace = build_asset_workspace(SAMPLE, source_root).resolve()
    manifest_path = source_workspace / "transcription_manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    before = snapshot(source_root, all_files=True)
    verify_transcription(_transcription_command(source_workspace, manifest), output_root=str(source_root))
    if snapshot(source_root, all_files=True) != before:
        raise AssertionError("source verification changed protected files")
    workspace = build_asset_workspace(SAMPLE, output_root).resolve()
    files = {Path(record["path"]) for record in manifest["records"].values()}
    files.update(source_workspace / name for name in ("video.mp4", "media_boundary.json"))
    if manifest["workflow"]["inputs"]["chapters_sha256"] is not None:
        files.add(source_workspace / "chapters.json")
    if any(path.parent != source_workspace or path.resolve() != path for path in files):
        raise ValueError("adopted transcription inputs must be canonical local files")
    # Verify PTS/video correspondence without loading the syntax model.
    from archive_core.interfaces.bilingual import MediaBoundaryDTO
    media = MediaBoundaryDTO.from_dict(json.loads((source_workspace / "media_boundary.json").read_bytes()))
    if media.video_sha256 != fingerprint(source_workspace / "video.mp4")["sha256"]:
        raise ValueError("source frame evidence belongs to another video")
    workspace.mkdir(parents=True, exist_ok=False)
    copied = []
    for source in sorted(files):
        expected = fingerprint(source)
        destination = workspace / source.name
        shutil.copy2(source, destination)
        if fingerprint(destination) != expected:
            raise AssertionError("adopted file differs from source")
        copied.append({"source": str(source), "destination": str(destination), "fingerprint": expected})
    original = output_root / "source_transcription_manifest.original.json"
    shutil.copy2(manifest_path, original)
    projection = deepcopy(manifest)
    for record in projection["records"].values():
        record["path"] = str(workspace / Path(record["path"]).name)
    view_path = workspace / "transcription_manifest.json"
    write_exclusive(view_path, projection)
    # This is an actual production verifier, not a runner mock or a paper claim.
    verify_transcription(_transcription_command(workspace, projection), output_root=str(output_root))
    if snapshot(source_root, all_files=True) != before:
        raise AssertionError("materialisation changed the source root")
    adoption = {"schema_version": "pipeline.frozen-source-adoption.v1", "kind": "verified-input-materialisation",
                "asset_id": SAMPLE.value, "source_root": str(source_root), "output_root": str(output_root),
                "source_snapshot": before,
                "original_transcription_manifest": {"path": str(manifest_path), "fingerprint": fingerprint(manifest_path)},
                "original_copy": {"path": str(original), "fingerprint": fingerprint(original)},
                "projection": {"path": str(view_path), "fingerprint": fingerprint(view_path)},
                "copied_files": copied, "allowed_projection_change": "records[*].path only",
                "historical_workflow_and_provenance_unchanged": True,
                "public_transcription_verification": "passed", "upstream_stages_executed": [],
                "asr_calls": 0, "forced_alignment_calls": 0,
                "note": "Original successful upstream evidence is adopted, not newly generated or claimed as nine-stage reuse."}
    write_exclusive(output_root / ADOPTION, adoption)
    verify_adoption(output_root)
    return {"status": "prepared", "output_root": str(output_root), "adoption": str(output_root / ADOPTION),
            "adoption_sha256": fingerprint(output_root / ADOPTION)["sha256"], "asr_calls": 0}


def verify_adoption(output_root):
    _regular_tree(Path(output_root).absolute())
    output_root = Path(output_root).resolve()
    _regular_tree(output_root)
    adoption = json.loads((output_root / ADOPTION).read_bytes())
    if (adoption["schema_version"] != "pipeline.frozen-source-adoption.v1"
            or adoption["output_root"] != str(output_root) or adoption["asset_id"] != SAMPLE.value):
        raise ValueError("adoption identity differs")
    source_root = Path(adoption["source_root"])
    if not source_root.is_absolute() or source_root.resolve() != source_root:
        raise ValueError("adoption source root is not canonical")
    _disjoint(source_root, output_root)
    _regular_tree(source_root)
    source_workspace = build_asset_workspace(SAMPLE, source_root).resolve()
    if (adoption["original_copy"]["path"] != str(output_root / "source_transcription_manifest.original.json")
            or adoption["projection"]["path"] != str(build_asset_workspace(SAMPLE, output_root) / "transcription_manifest.json")
            or adoption["original_transcription_manifest"]["path"] != str(source_workspace / "transcription_manifest.json")):
        raise ValueError("adoption manifest paths differ")
    if snapshot(source_root, all_files=True) != adoption["source_snapshot"]:
        raise ValueError("protected original source evidence changed")
    for item in (adoption["original_transcription_manifest"], adoption["original_copy"], adoption["projection"]):
        if fingerprint(item["path"]) != item["fingerprint"]:
            raise ValueError("adoption manifest evidence differs")
    original = json.loads(Path(adoption["original_copy"]["path"]).read_bytes())
    if Path(adoption["original_copy"]["path"]).read_bytes() != Path(adoption["original_transcription_manifest"]["path"]).read_bytes():
        raise ValueError("original manifest forensic copy differs")
    expected = deepcopy(original)
    workspace = build_asset_workspace(SAMPLE, output_root).resolve()
    for record in expected["records"].values():
        record["path"] = str(workspace / Path(record["path"]).name)
    projection = json.loads((workspace / "transcription_manifest.json").read_bytes())
    if projection != expected:
        raise ValueError("materialisation changed more than record paths")
    required = {record["path"] for record in projection["records"].values()}
    required.update(str(workspace / name) for name in ("video.mp4", "media_boundary.json"))
    if original["workflow"]["inputs"]["chapters_sha256"] is not None:
        required.add(str(workspace / "chapters.json"))
    if {item["destination"] for item in adoption["copied_files"]} != required:
        raise ValueError("adoption copied-input set differs")
    for item in adoption["copied_files"]:
        if (Path(item["destination"]).parent != workspace
                or Path(item["source"]) != source_workspace / Path(item["destination"]).name
                or fingerprint(item["source"]) != item["fingerprint"]
                or fingerprint(item["destination"]) != item["fingerprint"]):
            raise ValueError("adopted input changed")
    verify_transcription(_transcription_command(workspace, projection), output_root=str(output_root))
    protected = {item["destination"]: item["fingerprint"] for item in adoption["copied_files"]}
    for path in (output_root / ADOPTION, Path(adoption["original_copy"]["path"]), workspace / "transcription_manifest.json"):
        protected[str(path)] = fingerprint(path)
    return protected


def _assert_protected(protected):
    if any(fingerprint(path) != value for path, value in protected.items()):
        raise AssertionError("replay changed adopted upstream evidence")


def _verify_stage(name, root, model_bundle):
    """No execution handler/model/provider/media process is constructed here."""
    workspace = build_asset_workspace(SAMPLE, root).resolve()
    transcription = str(workspace / "transcription_manifest.json")
    chunks = str(workspace / "source_chunking_manifest.json")
    if name == "source_chunking":
        return verify_source_chunking(SourceChunkingCommand(SAMPLE.value, transcription,
            str(workspace / "media_boundary.json")), output_root=str(root), model_bundle_path=str(model_bundle))
    if name == "translation":
        return build_translation_handler(output_root=str(root)).verify(TranslationCommand(SAMPLE.value, transcription, chunks))
    if name == "bilingual_postprocessing":
        return build_bilingual_postprocessing_handler(output_root=str(root)).verify(BilingualPostprocessingCommand(
            SAMPLE.value, transcription, chunks, str(workspace / "translation_manifest.json")))
    if name == "srt_export":
        return verify_srt_export(SrtProcessingCommand(SAMPLE.value, str(workspace / "bilingual_postprocessing_manifest.json")),
                                 output_root=str(root))
    return verify_subtitle_rendering(SubtitleRenderingCommand(SAMPLE.value, str(workspace / "srt_processing_manifest.json")),
                                     output_root=str(root))


def _preflight_reuse(root, model, stages):
    before = snapshot(root, all_files=True)
    for name in stages:
        checked = _verify_stage(name, root, model)
        if snapshot(root, all_files=True) != before:
            raise AssertionError("read-only replay verification wrote files")
        if checked.status != "reused":
            raise ValueError(f"reuse preflight rejected {name}: {getattr(checked, 'error_message', '')}")
    return before


def _only_new_audit_files(before, after):
    for name in before.keys() | after.keys():
        if before.get(name) == after.get(name):
            continue
        path = Path(name)
        if (name in before or name not in after or len(path.parts) != 1 or not path.name.endswith(".json")
                or not path.name.startswith(("replay_run-", "replay_reuse_evidence-"))):
            raise AssertionError(f"reuse changed a protected root path: {name}")


def _stage(name, root, model_bundle, render_counts):
    workspace = build_asset_workspace(SAMPLE, root).resolve()
    if name == "source_chunking":
        return build_source_chunking_handler(output_root=str(root), model_bundle_path=str(model_bundle)), SourceChunkingCommand(
            SAMPLE.value, str(workspace / "transcription_manifest.json"), str(workspace / "media_boundary.json"))
    if name == "translation":
        return build_translation_handler(output_root=str(root)), TranslationCommand(
            SAMPLE.value, str(workspace / "transcription_manifest.json"), str(workspace / "source_chunking_manifest.json"))
    if name == "bilingual_postprocessing":
        return build_bilingual_postprocessing_handler(output_root=str(root)), BilingualPostprocessingCommand(
            SAMPLE.value, str(workspace / "transcription_manifest.json"), str(workspace / "source_chunking_manifest.json"),
            str(workspace / "translation_manifest.json"))
    if name == "srt_export":
        return build_srt_processing_handler(output_root=str(root)), SrtProcessingCommand(
            SAMPLE.value, str(workspace / "bilingual_postprocessing_manifest.json"))

    def observed(argv, **options):
        if "-c:v" in argv and "-n" in argv:
            render_counts["render_encoding_calls"] += 1
        return run_process(argv, **options)

    return build_subtitle_rendering_handler(output_root=str(root), process_runner=observed), SubtitleRenderingCommand(
        SAMPLE.value, str(workspace / "srt_processing_manifest.json"))


def _zero_counts(counts):
    return bool(counts) and all(type(value) is int and value == 0 for value in counts.values())


def assert_reused(result, stages=STAGES):
    if result["status"] != "reused" or tuple(item["stage"] for item in result["stages"]) != tuple(stages):
        raise AssertionError("five-stage reuse status/order differs")
    for item in result["stages"]:
        if item["status"] != "reused" or not _zero_counts(item["counts"]) or item["observed_artifacts_changed"]:
            raise AssertionError("reuse executed content work or changed stage artifacts")


def run_replay(output_root, model_bundle=DEFAULT_MODEL_BUNDLE, *, reuse=False, allow_expensive=False,
               target_stage="subtitle_rendering"):
    _require_gate()
    if target_stage not in STAGES:
        raise ValueError("unsupported replay target")
    stages = STAGES[:STAGES.index(target_stage) + 1]
    if not reuse and len(stages) > 1 and not allow_expensive:
        raise ValueError("real provider/render execution requires explicit --allow-expensive")
    _regular_tree(Path(output_root).absolute())
    root, model = Path(output_root).resolve(), Path(model_bundle).resolve()
    protected = verify_adoption(root)
    reuse_snapshot = _preflight_reuse(root, model, stages) if reuse else None
    workspace = build_asset_workspace(SAMPLE, root)
    receipt = {"schema_version": "pipeline.frozen-source-replay.v1", "kind": "five-stage-frozen-source-replay",
               "status": "running", "upstream": "adopted-not-executed", "asr_calls": 0, "forced_alignment_calls": 0,
               "adoption_sha256": fingerprint(root / ADOPTION)["sha256"], "stages": []}
    receipt_path = root / f"replay_run-{uuid4().hex}.json"
    try:
        for name in stages:
            before = snapshot(root, all_files=True)
            if reuse and before != reuse_snapshot:
                raise AssertionError("replay inputs changed after reuse preflight")
            render_counts = {"render_encoding_calls": 0}
            handler, command = _stage(name, root, model, render_counts)
            if reuse and snapshot(root, all_files=True) != reuse_snapshot:
                raise AssertionError("handler construction changed verified reuse inputs")
            outcome = handler.handle(command)
            data = asdict(outcome)
            after = snapshot(root, all_files=True)
            changes = sorted(path for path in before.keys() | after.keys() if before.get(path) != after.get(path))
            counts = {"analyzer_calls": data.get("analyzer_calls", 0),
                      "provider_content_calls": data.get("attempt_count", data.get("provider_calls", 0)),
                      "render_encoding_calls": render_counts["render_encoding_calls"],
                      "reported_writes": data.get("writes", 0), "artifact_files_changed": len(changes)}
            entry = {"stage": name, **data, "counts": counts, "observed_artifacts_changed": changes}
            if name in {"translation", "bilingual_postprocessing"} and data["status"] not in {"succeeded", "reused"}:
                # Public failure outcomes can default to zero after content work.
                entry["provider_content_call_evidence"] = {
                    "status": "unknown", "reported_count": counts["provider_content_calls"],
                    "reported_count_field": "attempt_count" if name == "translation" else "provider_calls",
                    "reason": "Public failure outcomes do not expose a complete count of provider calls before the exception.",
                    "checkpoint_root": str(root / "translation_checkpoints"),
                    "checkpoints_before": {path: value for path, value in before.items() if path.startswith("translation_checkpoints/")},
                    "checkpoints_after": {path: value for path, value in after.items() if path.startswith("translation_checkpoints/")},
                }
                counts["provider_content_calls"] = None
            receipt["stages"].append(entry)
            _assert_protected(protected)
            verify_adoption(root)
            if data["status"] not in {"succeeded", "reused"}:
                raise RuntimeError(f"{name} failed: {data.get('error_category')}: {data.get('error_message')}")
            if reuse and (data["status"] != "reused" or not _zero_counts(counts) or changes):
                raise AssertionError("reuse unexpectedly executed or wrote stage work")
        verify_adoption(root)
        receipt["status"] = "reused" if all(item["status"] == "reused" for item in receipt["stages"]) else "succeeded"
        if reuse:
            assert_reused(receipt, stages)
    except BaseException as error:
        receipt.update(status="failed", error_type=type(error).__name__, error_message=str(error))
        write_exclusive(receipt_path, receipt)
        raise
    write_exclusive(receipt_path, receipt)
    return {**receipt, "receipt_path": str(receipt_path)}


def audit_reuse(output_root, model_bundle=DEFAULT_MODEL_BUNDLE):
    _require_gate()
    _regular_tree(Path(output_root).absolute())
    root = Path(output_root).resolve()
    workspace = build_asset_workspace(SAMPLE, root)
    before = snapshot(root, all_files=True)
    same = run_replay(root, model_bundle, reuse=True)
    assert_reused(same)
    _only_new_audit_files(before, snapshot(root, all_files=True))
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(ROOT / "src")
    child = subprocess.run([sys.executable, "-m", MODULE, "--reuse", "--output-root", str(root),
                            "--model-bundle", str(Path(model_bundle).resolve())], cwd=ROOT, env=environment,
                           capture_output=True, text=True, timeout=1800, check=True)
    independent = json.loads(child.stdout.splitlines()[-1])
    assert_reused(independent)
    _only_new_audit_files(before, snapshot(root, all_files=True))
    verify_adoption(root)
    evidence = {"schema_version": "pipeline.frozen-source-reuse-evidence.v1", "status": "passed",
                "scope": list(STAGES), "upstream": "adopted-not-nine-stage-reuse",
                "same_process": same, "independent_process": independent, "stage_artifacts": before,
                "stage_files_unchanged": True, "source_and_adopted_inputs_unchanged": True}
    path = root / f"replay_reuse_evidence-{uuid4().hex}.json"
    write_exclusive(path, evidence)
    return {"status": "passed", "evidence_path": str(path), "evidence_sha256": fingerprint(path)["sha256"]}


def main(argv=None):
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--model-bundle", type=Path, default=DEFAULT_MODEL_BUNDLE)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--reuse", action="store_true")
    mode.add_argument("--audit-reuse", action="store_true")
    parser.add_argument("--target-stage", choices=STAGES, default=STAGES[-1])
    parser.add_argument("--allow-expensive", action="store_true")
    args = parser.parse_args(argv)
    if args.prepare:
        if args.source_root is None:
            parser.error("prepare requires --source-root")
        result = adopt_source(args.source_root, args.output_root)
    elif args.audit_reuse:
        result = audit_reuse(args.output_root, args.model_bundle)
    else:
        result = run_replay(args.output_root, args.model_bundle, reuse=args.reuse,
                            allow_expensive=args.allow_expensive, target_stage=args.target_stage)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
