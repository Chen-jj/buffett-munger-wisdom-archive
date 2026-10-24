"""Opt-in local CNBC rendering acceptance; never prepares or changes upstream inputs.

PYTHONPATH=src .venv/bin/python -m tests.subtitle_rendering.sample_runner --run
The JSON result must be saved to a new evidence file outside the protected trees.
There is deliberately no overwrite, download, ASR, translation or SRT planning option.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sys
import time

from archive_core.application import build_asset_workspace
from archive_core.domain import ArtifactType, AssetId, canonical_filename
from archive_core.interfaces import (
    SourceAlignmentDTO, SubtitlePlanDTO, SubtitleRenderManifestDTO, SubtitleRenderPlanDTO,
    SubtitleRenderReportDTO, TranslationResultDTO,
)
from infrastructure.infrastructure.process import run_process
from subtitle_rendering.infrastructure.composition import build_subtitle_rendering_handler
from subtitle_rendering.infrastructure.ffmpeg import FfmpegRenderer
from subtitle_rendering.infrastructure.local import LocalRenderingArtifactStore
from subtitle_rendering.interfaces import SubtitleRenderingCommand


REPOSITORY = Path(__file__).resolve().parents[2]
ASSET = AssetId("cnbc", "2000", "morning")
EXPERIMENT = REPOSITORY / "output/cue-evaluation/20261023-candidate-v3"
DEFAULT_OUTPUT_ROOT = EXPERIMENT / "workspaces"
DEFAULT_SOURCE_ROOT = REPOSITORY / "output/transcription-integration"
DEFAULT_FFMPEG = "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"
DEFAULT_FFPROBE = "/opt/homebrew/opt/ffmpeg-full/bin/ffprobe"
INPUT_NAMES = (
    "aligned_asr.json", "audio.wav", "bilingual.srt", "chapters.json", "chinese.srt",
    "download_manifest.json", "english.srt", "integration-plan.json", "integration_sample.json",
    "media_ref.json", "meta.json", "raw_asr.json", "source_alignment.json",
    "srt_processing_manifest.json", "srt_processing_report.json", "subtitle_plan.json",
    "transcript.txt", "transcript_fusion.json", "transcription.log", "transcription_manifest.json",
    "transcription_report.json", "translation_manifest.json", "translation_result.json", "vad.json", "video.mp4",
)
OUTPUT_TYPES = {
    "plan": ArtifactType.SUBTITLE_RENDER_PLAN, "ass": ArtifactType.BILINGUAL_ASS,
    "video": ArtifactType.RENDERED_VIDEO, "report": ArtifactType.SUBTITLE_RENDER_REPORT,
    "manifest": ArtifactType.SUBTITLE_RENDER_MANIFEST,
}
FROZEN_HASHES = {
    "source_alignment.json": "99f36287d28d0581ae039f64eeea55c14bef044dbb87fdca2f9c8d26ad7fbf91",
    "translation_result.json": "0862d8759a3bb0cec59bf2d3531fd2301a37b889d2499135c46ea24a608d1dfb",
    "video.mp4": "364d6cc6b2fd164d972344b42bbb9019b6d55a838257d0cc243c54ddca5b59e0",
}


class ObservedStore(LocalRenderingArtifactStore):
    """Count real operations, without replacing their filesystem behavior."""

    def __init__(self):
        self.writes = []

    def create_staging(self, path):
        self.writes.append(("mkdir", path))
        return super().create_staging(path)

    def stage_bytes(self, path, data):
        self.writes.append(("stage", path))
        return super().stage_bytes(path, data)

    def publish(self, staged, target, *, overwrite):
        self.writes.append(("publish", target))
        return super().publish(staged, target, overwrite=overwrite)


class ObservedRenderer(FfmpegRenderer):
    """Distinguish complete content encoding from read-only zero-frame tool queries."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.encode_count = self.pixel_count = 0

    def render(self, command, *, cwd):
        self.encode_count += 1
        return super().render(command, cwd=cwd)

    def render_transparent_frame(self, *args, **kwargs):
        self.pixel_count += 1
        return super().render_transparent_frame(*args, **kwargs)


def evidence(path):
    path = Path(path)
    stamp = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"path": str(path.absolute()), "size_bytes": stamp.st_size,
            "sha256": digest.hexdigest(), "mtime_ns": stamp.st_mtime_ns}


def file_state(path):
    """Preserve lexical links and their targets, not merely followed stat results."""
    path = Path(path).absolute()
    stamp = path.lstat()
    result = {"path": str(path), "lstat_mtime_ns": stamp.st_mtime_ns}
    if path.is_symlink():
        result.update(kind="symlink", readlink=str(path.readlink()), resolved_target=str(path.resolve()),
                      target=evidence(path.resolve()) if path.is_file() else None)
    else:
        result.update(kind="file", file=evidence(path))
    return result


def snapshot(roots, *, excluded=()):
    excluded = {str(Path(path).absolute()) for path in excluded}
    result = {}
    for name, root in roots.items():
        root = Path(root).absolute()
        files = {str(path.relative_to(root)): file_state(path) for path in sorted(root.rglob("*"))
                 if (path.is_file() or path.is_symlink()) and str(path.absolute()) not in excluded}
        result[name] = {"root": str(root), "files": files}
    return result


def fixture_paths(output_root, source_root):
    workspace = build_asset_workspace(ASSET, Path(output_root).absolute())
    source = build_asset_workspace(ASSET, Path(source_root).absolute())
    roots = {
        "formal": source,
        "sp09": REPOSITORY / "output/cue-evaluation/20261022-agent-vs-dp",
        "candidate_v2": REPOSITORY / "output/cue-evaluation/20261022-candidate-v2",
        "user_preferences": REPOSITORY / "output/cue-evaluation/20261023-user-preferences",
        "candidate_v3": workspace.parent.parent,
    }
    outputs = {key: workspace / canonical_filename(kind) for key, kind in OUTPUT_TYPES.items()}
    receipt = workspace.parent.parent / "preparation.v1.json"
    required = [workspace / name for name in INPUT_NAMES]
    required += [source / name for name in ("source_alignment.json", "translation_result.json",
                                           "translation_manifest.json", "transcription_manifest.json", "video.mp4", "audio.wav")]
    required.append(receipt)
    return workspace, source, roots, outputs, receipt, required


def read_json(path):
    value = json.loads(Path(path).read_bytes())
    if not isinstance(value, dict):
        raise ValueError("acceptance artifact must be a JSON object")
    return value


def inspect_sources(workspace, source, receipt):
    """Check the frozen fixture and the already-approved relocation; do not repair it."""
    alignment = SourceAlignmentDTO.from_dict(read_json(workspace / "source_alignment.json"))
    translation = TranslationResultDTO.from_dict(read_json(workspace / "translation_result.json"))
    plan = SubtitlePlanDTO.from_dict(read_json(workspace / "subtitle_plan.json"))
    translation.validate_against_alignment(alignment)
    plan.validate_against_inputs(alignment, translation)
    counts = {"sections": len(alignment.sections), "sentences": len(alignment.sentences),
              "words": len(alignment.words), "cues": len(plan.cues), "duration_ms": alignment.audio_duration_ms}
    if counts != {"sections": 2, "sentences": 97, "words": 1564, "cues": 163, "duration_ms": 623000}:
        raise ValueError("CNBC fixture no longer matches its accepted sample baseline")
    for name, expected in FROZEN_HASHES.items():
        if evidence(workspace / name)["sha256"] != expected or evidence(source / name)["sha256"] != expected:
            raise ValueError("source and v3 content must match the accepted real integration fixture")
    if (workspace / "translation_manifest.json").read_bytes() != (source / "translation_manifest.json").read_bytes():
        raise ValueError("v3 translation manifest differs from the accepted SP-08A source")
    prepared = read_json(receipt)
    if prepared["source_workspace"] != str(source) or prepared["candidate_workspace"] != str(workspace):
        raise ValueError("preparation receipt identifies a different source or workspace")
    original = read_json(source / "transcription_manifest.json")
    expected = json.loads(json.dumps(original))
    relocations = []
    for name, record in expected["records"].items():
        old = record["path"]
        record["path"] = str(workspace / Path(old).name)
        relocations.append({"record": name, "original": old, "candidate": record["path"]})
    if expected != read_json(workspace / "transcription_manifest.json"):
        raise ValueError("transcription manifest changes exceed the approved record-path relocation")
    if relocations != prepared["derived_transcription_manifest"]["path_rebases_only"]:
        raise ValueError("transcription relocation does not match its existing receipt")
    for name in ("audio.wav", "video.mp4"):
        path = workspace / name
        if not path.is_symlink() or str(path.readlink()) != prepared["media_links"][name] or path.resolve() != source / name:
            raise ValueError("v3 media symlink differs from the approved source")
    return counts


def counts(store, renderer):
    return {"write_count": len(store.writes), "stage_count": sum(op == "stage" for op, _ in store.writes),
            "publish_count": sum(op == "publish" for op, _ in store.writes),
            "staging_directory_count": sum(op == "mkdir" for op, _ in store.writes),
            "content_encode_count": renderer.encode_count, "pixel_frame_count": renderer.pixel_count}


def difference(after, before):
    return {key: after[key] - before[key] for key in after}


def require_zero(values):
    if any(values.values()):
        raise ValueError("reuse must not write, stage, publish, sample pixels or encode content")


def inspect_outputs(workspace, outputs):
    source = SubtitlePlanDTO.from_dict(read_json(workspace / "subtitle_plan.json"))
    plan = SubtitleRenderPlanDTO.from_dict(read_json(outputs["plan"]))
    report = SubtitleRenderReportDTO.from_dict(read_json(outputs["report"]))
    manifest = SubtitleRenderManifestDTO.from_dict(read_json(outputs["manifest"]))
    plan.validate_against_subtitle_plan(source)
    manifest.validate_against_plan_and_report(plan, report)
    for key, item in manifest.outputs.items():
        actual = evidence(outputs[key])
        if (item.path, item.size_bytes, item.sha256) != (outputs[key].name, actual["size_bytes"], actual["sha256"]):
            raise ValueError("formal output evidence differs from the successful manifest")
    return {"summary": report.summary.to_dict(), "input_media": manifest.input_media.to_dict(),
            "output_media": manifest.output_media.to_dict(), "tools": manifest.tools.to_dict(),
            "font": manifest.font.to_dict(), "profile": manifest.profile.to_dict(),
            "inputs": {key: item.to_dict() for key, item in manifest.inputs.items()},
            "pixel_results": [item.to_dict() for item in report.pixel_results]}


def independent_reuse(*, output_root, source_root, ffmpeg_executable, ffprobe_executable):
    command = (sys.executable, "-m", "tests.subtitle_rendering.sample_runner", "--run", "--reuse-only",
               "--output-root", str(output_root), "--source-root", str(source_root),
               "--ffmpeg-executable", ffmpeg_executable, "--ffprobe-executable", ffprobe_executable)
    result = run_process(command, cwd=REPOSITORY,
                         env={**os.environ, "PYTHONPATH": str(REPOSITORY / "src")}, timeout=3600)
    if not result.ok:
        raise ValueError("independent rendering reuse did not complete successfully")
    value = json.loads(result.stdout)
    if value.get("status") != "passed" or value.get("first_status") != "reused":
        raise ValueError("independent process did not return verified reused")
    require_zero(value["first_counts"])
    return {"status": value["status"], "first_status": value["first_status"],
            "counts": value["first_counts"], "outputs": value["outputs"],
            "upstream_unchanged": value["upstream_unchanged"], "command": list(command)}


def run_local_sample(*, output_root=DEFAULT_OUTPUT_ROOT, source_root=DEFAULT_SOURCE_ROOT,
                     ffmpeg_executable=DEFAULT_FFMPEG, ffprobe_executable=DEFAULT_FFPROBE,
                     reuse_only=False):
    workspace, source, roots, outputs, receipt, required = fixture_paths(output_root, source_root)
    missing = [str(path) for path in required if not path.is_file()]
    missing += [str(root) for root in roots.values() if not root.is_dir()]
    if missing:
        return {"status": "precondition_missing", "missing_inputs": sorted(set(missing)),
                "message": "Existing real upstream artifacts are required; no upstream stage was run."}
    before = snapshot(roots, excluded=outputs.values())
    base = {"asset_id": ASSET.value, "workspace": str(workspace), "source_workspace": str(source),
            "protected_before": before, "human_playback_confirmed": False,
            "quality_boundary": "Technical rendering only; no human playback or publication approval implied."}
    store = ObservedStore()
    renderer = ObservedRenderer(executable=ffmpeg_executable)
    try:
        source_counts = inspect_sources(workspace, source, receipt)
        existing = [key for key, path in outputs.items() if os.path.lexists(path)]
        if reuse_only and len(existing) != len(outputs):
            raise ValueError("reuse-only requires an existing complete formal output set")
        handler = build_subtitle_rendering_handler(
            output_root=str(Path(output_root).absolute()), config_path=REPOSITORY / "config.yaml",
            ffmpeg_executable=ffmpeg_executable, ffprobe_executable=ffprobe_executable,
            artifacts=store, renderer=renderer,
        )
        command = SubtitleRenderingCommand(ASSET.value, str(workspace / "srt_processing_manifest.json"))
        started = time.perf_counter()
        first = handler.handle(command)
        first_elapsed = time.perf_counter() - started
        first_counts = counts(store, renderer)
        base.update(first_outcome=asdict(first), first_status=first.status, first_counts=first_counts,
                    initial_output_names=existing, source_counts=source_counts)
        if first.status not in ("succeeded", "reused"):
            return {**base, "status": "failed", "error_category": first.error_category,
                    "residual_paths": [str(path) for path in sorted(workspace.glob(".subtitle-rendering.*"))],
                    "protected_after": snapshot(roots, excluded=outputs.values())}
        if (reuse_only or existing) and first.status != "reused":
            raise ValueError("existing outputs must be reused without regeneration")
        if not existing and first.status != "succeeded":
            raise ValueError("the first fresh rendering must genuinely succeed")
        if first.status == "reused":
            require_zero(first_counts)
        elif first_counts["content_encode_count"] != 1 or first_counts["pixel_frame_count"] != source_counts["cues"]:
            raise ValueError("fresh rendering must encode once and sample every cue")
        qa = inspect_outputs(workspace, outputs)
        output_before = {key: file_state(path) for key, path in outputs.items()}
        result = {**base, "status": "passed", "generated_now": first.status == "succeeded",
                  "outputs": output_before, "qa": qa, "elapsed_seconds": {"first": first_elapsed}}
        if not reuse_only:
            started = time.perf_counter()
            second = handler.handle(command)
            result["elapsed_seconds"]["reuse"] = time.perf_counter() - started
            result["second_status"] = second.status
            reuse_counts = difference(counts(store, renderer), first_counts)
            result["same_process_reuse_counts"] = reuse_counts
            if second.status != "reused":
                raise ValueError("same-process second rendering must be reused")
            require_zero(reuse_counts)
            if output_before != {key: file_state(path) for key, path in outputs.items()}:
                raise ValueError("same-process reuse changed formal output bytes or metadata")
            child = independent_reuse(output_root=output_root, source_root=source_root,
                                      ffmpeg_executable=ffmpeg_executable, ffprobe_executable=ffprobe_executable)
            if not child["upstream_unchanged"] or child["outputs"] != output_before:
                raise ValueError("independent reuse changed formal outputs or upstream inputs")
            result["independent_process_reuse"] = child
        after = snapshot(roots, excluded=outputs.values())
        if before != after or output_before != {key: file_state(path) for key, path in outputs.items()}:
            raise ValueError("rendering acceptance changed protected inputs or reused outputs")
        result.update(protected_after=after, upstream_unchanged=True, byte_identical_reuse=True)
        return result
    except Exception as error:
        return {**base, "status": "acceptance_failed", "diagnostic": str(error)[:2048],
                "counts": counts(store, renderer), "protected_after": snapshot(roots, excluded=outputs.values()),
                "residual_paths": [str(path) for path in sorted(workspace.glob(".subtitle-rendering.*"))]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--reuse-only", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--source-root", default=str(DEFAULT_SOURCE_ROOT))
    parser.add_argument("--ffmpeg-executable", default=DEFAULT_FFMPEG)
    parser.add_argument("--ffprobe-executable", default=DEFAULT_FFPROBE)
    args = parser.parse_args(argv)
    if not args.run:
        result = {"status": "opt_in_required", "message": "Pass --run to consume existing real local inputs."}
    else:
        result = run_local_sample(output_root=Path(args.output_root).absolute(), source_root=Path(args.source_root).absolute(),
                                  ffmpeg_executable=args.ffmpeg_executable, ffprobe_executable=args.ffprobe_executable,
                                  reuse_only=args.reuse_only)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False))
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
