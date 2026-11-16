"""Opt-in real render/reuse on current, already generated, same-source artifacts."""
import hashlib
import os
from pathlib import Path

import pytest

from archive_core.application import build_asset_workspace
from archive_core.domain import AssetId, ArtifactType, canonical_filename
from archive_core.interfaces import SubtitleRenderManifestDTO, SubtitleRenderPlanDTO, SubtitleRenderReportDTO
from subtitle_rendering.interfaces import SubtitleRenderingCommand, build_subtitle_rendering_handler, verify_subtitle_rendering
from subtitle_rendering.application.inputs import parse_json


def snapshot(paths):
    result = {}
    for path in paths:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1048576), b""):
                digest.update(block)
        status = path.stat()
        result[str(path)] = (digest.hexdigest(), status.st_size, status.st_mtime_ns)
    return result


def test_current_final_draft_renders_and_reuses_without_changing_upstream():
    if (os.environ.get("RUN_ORCHESTRATION_INTEGRATION") != "1"
            or "local_media" not in os.environ.get("ORCHESTRATION_INTEGRATION_SCENARIOS", "").split(",")):
        pytest.skip("explicit orchestration local_media gate disabled")
    root = os.environ.get("ORCHESTRATION_LOCAL_MEDIA_ROOT")
    asset = os.environ.get("ORCHESTRATION_LOCAL_MEDIA_ASSET")
    assert root and asset, "set ORCHESTRATION_LOCAL_MEDIA_ROOT and ORCHESTRATION_LOCAL_MEDIA_ASSET to current artifacts"
    workspace = build_asset_workspace(AssetId(*asset.split(":")), Path(root).resolve())
    upstream = workspace / canonical_filename(ArtifactType.SRT_PROCESSING_MANIFEST)
    assert upstream.is_file(), f"precondition_missing: {upstream}"
    from archive_core.interfaces.bilingual import StageManifestDTO
    srt = StageManifestDTO.from_dict(parse_json(upstream.read_bytes()))
    protected_paths = [upstream, *(Path(item.path) for item in (*srt.inputs.values(), *srt.outputs.values()))]
    before = snapshot(protected_paths)
    command = SubtitleRenderingCommand(asset, str(upstream))
    handler = build_subtitle_rendering_handler(output_root=str(Path(root).resolve()))
    first = handler.handle(command)
    assert first.status in {"succeeded", "reused"}, first
    paths = [Path(getattr(first, name + "_path")) for name in ("plan", "ass", "video", "report", "manifest")]
    rendered = snapshot(paths)
    manifest = SubtitleRenderManifestDTO.from_dict(parse_json(Path(first.manifest_path).read_bytes()))
    plan = SubtitleRenderPlanDTO.from_dict(parse_json(Path(first.plan_path).read_bytes()))
    report = SubtitleRenderReportDTO.from_dict(parse_json(Path(first.report_path).read_bytes()))
    manifest.validate_against_plan_and_report(plan, report)
    assert report.summary.pixel_preflight_passed and len(report.pixel_results) == len(plan.cues)
    assert handler.handle(command).status == "reused"
    assert verify_subtitle_rendering(command, output_root=str(Path(root).resolve())).status == "reused"
    assert snapshot(paths) == rendered
    assert snapshot(protected_paths) == before
