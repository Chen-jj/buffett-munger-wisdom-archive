"""Explicitly preserve then regenerate only the real CNBC downstream stages.

Requires both editorial_refresh and full_fresh integration scenarios: the latter
authorizes the existing independent-process reuse audit, not a fresh generation.
Preserved manifests retain their original absolute paths as forensic evidence.
"""

from argparse import ArgumentParser
from dataclasses import asdict, replace
from pathlib import Path
import json
import shutil

from archive_core.application import build_asset_workspace
from infrastructure.infrastructure.artifacts import write_json
from orchestration.interfaces import build_pipeline_handler
from srt_processing.interfaces import SrtProcessingCommand, build_srt_processing_handler
from srt_processing.interfaces.workflow import verify_srt_export
from subtitle_rendering.interfaces import SubtitleRenderingCommand, build_subtitle_rendering_handler, verify_subtitle_rendering
from translation.interfaces import (
    BilingualPostprocessingCommand, TranslationCommand,
    build_bilingual_postprocessing_handler, build_translation_handler,
)
from tests.orchestration.integration.gates import enabled
from .full_fresh import (
    DEFAULT_MODEL_BUNDLE, PARENT, SAMPLE, assert_reused, command, snapshot, verify_generated_sample,
)


_STAGE_OUTPUTS = {
    "translation": ("translation_result.json", "translation_manifest.json"),
    "bilingual_postprocessing": ("final_bilingual_draft.json", "bilingual_postprocessing_report.json", "bilingual_postprocessing_manifest.json"),
    "srt_export": ("english.srt", "chinese.srt", "bilingual.srt", "srt_processing_report.json", "srt_processing_manifest.json"),
    "subtitle_rendering": ("bilingual.ass", "subtitle_rendering_plan.json", "subtitle_rendering_report.json", "subtitle_rendering_manifest.json", "video_中文字幕.mp4"),
}
_OUTPUTS = {name for names in _STAGE_OUTPUTS.values() for name in names}


def _allowed_change(relative, workspace_name, *, allow_audit=False):
    parts = Path(relative).parts
    if allow_audit and (
        (len(parts) == 1 and parts[0].startswith("integration_evidence") and parts[0].endswith(".json"))
        or (len(parts) == 2 and parts[0] in {workspace_name, build_asset_workspace(PARENT, ".").name}
            and parts[1] == ".pipeline.lock")
        or (len(parts) > 2 and parts[0] == workspace_name and parts[1] == "pipeline_runs")
    ):
        return True
    if parts[0] == "translation_checkpoints":
        return True
    if len(parts) < 2 or parts[0] != workspace_name:
        return False
    return (len(parts) == 2 and (parts[1] in _OUTPUTS
            or any(parts[1].startswith(f".{name}.") and parts[1].endswith(".tmp") for name in _OUTPUTS))
            or parts[1].startswith(".subtitle-rendering."))


def _unexpected_changes(before, after, workspace_name, *, allow_audit=False):
    return sorted(path for path in before.keys() | after.keys()
                  if before.get(path) != after.get(path)
                  and not _allowed_change(path, workspace_name, allow_audit=allow_audit))


def execute_editorial_refresh(output_root, preservation_root, model_bundle=DEFAULT_MODEL_BUNDLE):
    if not enabled("editorial_refresh") or not enabled("full_fresh"):
        raise RuntimeError("enable editorial_refresh,full_fresh orchestration integration scenarios")
    preservation_path = Path(preservation_root)
    if preservation_path.exists() or preservation_path.is_symlink():
        raise ValueError("preservation root must be absent")
    root, preserved, model = (Path(path).resolve() for path in (output_root, preservation_root, model_bundle))
    if not root.is_dir() or not model.is_dir():
        raise ValueError("existing canonical output root and prepared model bundle are required")
    if preserved.exists() or preserved.is_relative_to(root) or root.is_relative_to(preserved):
        raise ValueError("preservation root must be absent and disjoint from the output root")
    workspace = build_asset_workspace(SAMPLE, root)
    pipeline = build_pipeline_handler()
    reuse = command(root, model, reuse=True)
    before = snapshot(root, all_files=True)
    upstream = pipeline.verify_run(replace(reuse, target_stage="source_chunking"))
    if not upstream.executable or any(stage.action != "verify_reuse" for stage in upstream.stages):
        raise ValueError("current upstream evidence must verify before preservation or overwrite")
    assert snapshot(root, all_files=True) == before, "upstream verification wrote files"
    shutil.copytree(root, preserved / "workspace", symlinks=True, copy_function=shutil.copy2)
    assert snapshot(preserved / "workspace", all_files=True) == before, "preservation copy differs"
    assert snapshot(root, all_files=True) == before, "source changed during preservation"
    report = preserved / "refresh_evidence.json"
    audit = {"schema_version": "pipeline.editorial-refresh-evidence.v1", "kind": "downstream_refresh",
             "fresh_generation": False, "status": "running", "output_root": str(root),
             "preserved_workspace": str(preserved / "workspace"),
             "preservation_note": "Forensic copy; absolute manifest paths are not relocated or re-signed.",
             "recovery_note": "Verified current stages are reused. Exact-input checkpoint reuse under an occupied stale translation output pair depends on the production overwrite/checkpoint policy; this runner never deletes it to force recovery.",
             "before": before, "upstream_stages": [stage.stage for stage in upstream.stages],
             "stages": [], "semantic_review": "not_run"}
    write_json(report, audit)
    stages = (
        ("translation", build_translation_handler, None, TranslationCommand(
            SAMPLE.value, str(workspace / "transcription_manifest.json"),
            str(workspace / "source_chunking_manifest.json"))),
        ("bilingual_postprocessing", build_bilingual_postprocessing_handler, None, BilingualPostprocessingCommand(
            SAMPLE.value, str(workspace / "transcription_manifest.json"),
            str(workspace / "source_chunking_manifest.json"), str(workspace / "translation_manifest.json"))),
        ("srt_export", build_srt_processing_handler, verify_srt_export, SrtProcessingCommand(
            SAMPLE.value, str(workspace / "bilingual_postprocessing_manifest.json"))),
        ("subtitle_rendering", build_subtitle_rendering_handler, verify_subtitle_rendering, SubtitleRenderingCommand(
            SAMPLE.value, str(workspace / "srt_processing_manifest.json"))),
    )
    try:
        for name, factory, verifier, stage_command in stages:
            entry = {"stage": name, "status": "running"}
            audit["stages"].append(entry)
            write_json(report, audit)
            handler = factory(output_root=str(root))
            before_verify = snapshot(root, all_files=True)
            checked = (verifier(stage_command, output_root=str(root)) if verifier is not None
                       else handler.verify(stage_command))
            assert snapshot(root, all_files=True) == before_verify, "downstream verification wrote files"
            current = checked.status in {"reused", "succeeded"}
            overwrite = not current and any((workspace / filename).exists() or (workspace / filename).is_symlink()
                                            for filename in _STAGE_OUTPUTS[name])
            stage_command = replace(stage_command, overwrite=overwrite)
            entry.update(verified_status=checked.status, overwrite=overwrite)
            result = handler.handle(stage_command)
            entry.update(asdict(result))
            changed = snapshot(root, all_files=True)
            unexpected = _unexpected_changes(before, changed, workspace.name)
            audit["unexpected_changes"] = unexpected
            write_json(report, audit)
            if unexpected:
                raise AssertionError(f"downstream refresh changed protected upstream paths: {unexpected}")
            if result.status not in {"succeeded", "reused"}:
                raise RuntimeError(f"{name} failed; retained evidence: {report}")
        completed = pipeline.run_asset(reuse)
        assert_reused(completed)
        verified = verify_generated_sample(pipeline, root, model, completed)
        unexpected = _unexpected_changes(before, snapshot(root, all_files=True), workspace.name, allow_audit=True)
        assert not unexpected, f"reuse audit changed protected upstream paths: {unexpected}"
        audit.update(status="succeeded", upstream_unchanged=True,
                     reuse_integration_evidence=verified["evidence_path"],
                     completed_reuse_run_id=completed["run_id"])
    except BaseException as error:
        if audit["stages"] and audit["stages"][-1]["status"] == "running":
            audit["stages"][-1]["status"] = "failed"
        changed = snapshot(root, all_files=True)
        unexpected = sorted(set(audit.get("unexpected_changes", ())) | set(
            _unexpected_changes(before, changed, workspace.name, allow_audit=True)))
        audit.update(status="failed", error_type=type(error).__name__, error_message=str(error),
                     unexpected_changes=unexpected, upstream_unchanged=not unexpected)
        write_json(report, audit)
        raise
    write_json(report, audit)
    return {"status": audit["status"], "kind": audit["kind"], "evidence_path": str(report),
            "reuse_integration_evidence": audit["reuse_integration_evidence"]}


def main(argv=None):
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--preservation-root", type=Path, required=True)
    parser.add_argument("--model-bundle", type=Path, default=DEFAULT_MODEL_BUNDLE)
    args = parser.parse_args(argv)
    print(json.dumps(execute_editorial_refresh(args.output_root, args.preservation_root, args.model_bundle),
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
