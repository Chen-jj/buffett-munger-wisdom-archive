"""Explicit local-only acceptance; never downloads or generates upstream inputs.

Run from the repository with PYTHONPATH=src and the Python 3.11 virtualenv:
    python -m tests.srt_processing.sample_runner --run

No --run means no work. Missing canonical inputs are reported before constructing
the workflow. This runner has no overwrite option and never claims visual QA.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import time
from typing import Any

from archive_core.application import build_asset_workspace
from archive_core.domain import ArtifactType, AssetId, canonical_filename
from archive_core.interfaces import (
    SourceAlignmentDTO, SrtProcessingManifestDTO, SubtitlePlanDTO, TranslationResultDTO,
)
from srt_processing.infrastructure import LocalSubtitleArtifactStore, build_srt_processing_handler
from srt_processing.interfaces import SrtProcessingCommand


DEFAULT_ASSET = "cnbc:2000:morning"
DEFAULT_OUTPUT_ROOT = "output/transcription-integration"
INPUT_TYPES = {
    "transcription_manifest": ArtifactType.TRANSCRIPTION_MANIFEST,
    "source_alignment": ArtifactType.SOURCE_ALIGNMENT,
    "translation_manifest": ArtifactType.TRANSLATION_MANIFEST,
    "translation_result": ArtifactType.TRANSLATION_RESULT,
    "video": ArtifactType.SOURCE_VIDEO,
}
OUTPUT_TYPES = {
    "subtitle_plan": ArtifactType.SUBTITLE_PLAN, "english_srt": ArtifactType.ENGLISH_SRT,
    "chinese_srt": ArtifactType.CHINESE_SRT, "bilingual_srt": ArtifactType.BILINGUAL_SRT,
    "report": ArtifactType.SRT_PROCESSING_REPORT, "manifest": ArtifactType.SRT_PROCESSING_MANIFEST,
}


class ObservedLocalStore(LocalSubtitleArtifactStore):
    def __init__(self) -> None:
        self.writes: list[tuple[str, str]] = []

    def stage_bytes(self, target_path: str, data: bytes) -> str:
        self.writes.append(("stage", target_path))
        return super().stage_bytes(target_path, data)

    def publish(self, staged_path: str, target_path: str, *, overwrite: bool) -> None:
        self.writes.append(("publish", target_path))
        super().publish(staged_path, target_path, overwrite=overwrite)


def _snapshot(paths: dict[str, Path], store: LocalSubtitleArtifactStore) -> dict[str, Any]:
    return {
        key: {"path": str(path), "size_bytes": store.size(str(path)),
              "sha256": store.sha256(str(path)), "mtime_ns": path.stat().st_mtime_ns}
        for key, path in paths.items()
    }


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes().decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("sample artifact JSON must be an object")
    return value


def _cue_samples(plan: SubtitlePlanDTO) -> dict[str, Any]:
    cues = plan.cues
    selected = {
        "longest": max(cues, key=lambda cue: cue.end_ms - cue.start_ms),
        "shortest": min(cues, key=lambda cue: cue.end_ms - cue.start_ms),
        "unknown_speaker": next((cue for cue in cues if any(part.speaker_label is None for part in cue.fragments)), None),
        "merged": next((cue for cue in cues if len(cue.fragments) > 1), None),
        "proportional_split": next((cue for cue in cues if "english_emergency" in cue.break_methods
                                     or "chinese_emergency" in cue.break_methods), None),
    }
    return {key: cue.to_dict() if cue is not None else None for key, cue in selected.items()}


def run_local_sample(
    *, asset_id: str = DEFAULT_ASSET, output_root: str = DEFAULT_OUTPUT_ROOT,
    ffprobe_executable: str = "ffprobe", probe=None, clock=None, segmenter=None,
) -> dict[str, Any]:
    """Consume existing canonical inputs; port injection is only for offline tests."""
    try:
        if len(asset_id.split(":")) != 3:
            raise ValueError("asset_id must use source:group:item")
        asset = AssetId(*asset_id.split(":"))
    except (AttributeError, TypeError, ValueError):
        return {"status": "precondition_invalid", "message": "Invalid asset identity."}
    output_root = str(Path(output_root).resolve())
    workspace = build_asset_workspace(asset, output_root)
    inputs = {key: workspace / canonical_filename(kind) for key, kind in INPUT_TYPES.items()}
    missing = [str(path) for path in inputs.values() if not path.is_file()]
    if missing:
        return {"status": "precondition_missing", "asset_id": asset_id,
                "workspace": str(workspace), "missing_inputs": missing,
                "message": "Existing formal transcription, translation and video are required; no upstream stage was run."}

    store = ObservedLocalStore()
    outputs = {key: workspace / canonical_filename(kind) for key, kind in OUTPUT_TYPES.items()}
    output_names = {path.name for path in outputs.values()}
    upstream = {path.name: path for path in workspace.iterdir() if path.is_file() and path.name not in output_names}
    before = _snapshot(upstream, store)
    command = SrtProcessingCommand(asset_id, str(inputs["transcription_manifest"]), str(inputs["translation_manifest"]))
    options = dict(output_root=output_root, ffprobe_executable=ffprobe_executable,
                   artifacts=store, probe=probe, clock=clock, segmenter=segmenter)
    started = time.perf_counter()
    first = build_srt_processing_handler(**options).handle(command)
    if first.status not in ("succeeded", "reused"):
        return {"status": "failed", "first_outcome": asdict(first),
                "upstream_unchanged": before == _snapshot(upstream, store)}
    first_elapsed = time.perf_counter() - started
    first_bytes = {key: path.read_bytes() for key, path in outputs.items()}
    first_evidence = _snapshot(outputs, store)
    writes_before_reuse = list(store.writes)
    started = time.perf_counter()
    second = build_srt_processing_handler(**options).handle(command)
    second_elapsed = time.perf_counter() - started
    if second.status != "reused" or store.writes != writes_before_reuse:
        raise ValueError("second invocation must reuse without staging or publishing")
    if first_bytes != {key: path.read_bytes() for key, path in outputs.items()} or first_evidence != _snapshot(outputs, store):
        raise ValueError("reuse changed formal output bytes or file metadata")
    if before != _snapshot(upstream, store):
        raise ValueError("subtitle acceptance changed upstream files")

    plan = SubtitlePlanDTO.from_dict(_read_json(outputs["subtitle_plan"]))
    manifest = SrtProcessingManifestDTO.from_dict(_read_json(outputs["manifest"]))
    alignment = SourceAlignmentDTO.from_dict(_read_json(inputs["source_alignment"]))
    translation = TranslationResultDTO.from_dict(_read_json(inputs["translation_result"]))
    plan.validate_against_inputs(alignment, translation)
    manifest.validate_against_plan(plan)
    for key, evidence in manifest.inputs.items():
        if (evidence.path != inputs[key].name or evidence.size_bytes != store.size(str(inputs[key]))
                or evidence.sha256 != store.sha256(str(inputs[key]))):
            raise ValueError("manifest input evidence changed during acceptance")
    for key, evidence in manifest.outputs.items():
        if (evidence.path != outputs[key].name or evidence.size_bytes != store.size(str(outputs[key]))
                or evidence.sha256 != store.sha256(str(outputs[key]))):
            raise ValueError("manifest output evidence does not match formal files")
    return {
        "status": "passed", "asset_id": asset_id, "workspace": str(workspace),
        "first_status": first.status, "second_status": second.status,
        "generated_now": first.status == "succeeded", "byte_identical_reuse": True,
        "reuse_write_count": len(store.writes) - len(writes_before_reuse),
        "upstream_unchanged": True, "upstream": before, "outputs": first_evidence,
        "elapsed_seconds": {"first": first_elapsed, "reuse": second_elapsed},
        "source_counts": {"words": len(alignment.words), "sentences": len(alignment.sentences),
                          "sections": len(alignment.sections)},
        "summary": manifest.summary.to_dict(), "warning_count": second.warning_count,
        "profile": manifest.profile.to_dict(), "rules": manifest.rules.to_dict(),
        "media": manifest.media.to_dict(), "probe": manifest.probe.to_dict(),
        "codec": manifest.codec.to_dict(), "input_evidence": {key: evidence.to_dict() for key, evidence in manifest.inputs.items()},
        "cue_samples": _cue_samples(plan),
        "human_review_required": "Read source/Chinese proportional fragments; no semantic, pixel, ASS or rendered-video approval is implied.",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Explicitly run local subtitle acceptance.")
    parser.add_argument("--asset-id", default=DEFAULT_ASSET)
    parser.add_argument("--output-root", default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--ffprobe-executable", default="ffprobe")
    args = parser.parse_args(argv)
    if not args.run:
        result = {"status": "opt_in_required", "message": "Pass --run to consume existing local formal inputs."}
    else:
        try:
            result = run_local_sample(asset_id=args.asset_id, output_root=args.output_root,
                                      ffprobe_executable=args.ffprobe_executable)
        except Exception:
            result = {"status": "acceptance_failed", "message": "Local acceptance did not pass; existing files were not automatically cleaned or overwritten."}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
