"""Public composition and read-only verification for orchestration."""
from .workflow import SubtitleRenderingCommand, SubtitleRenderingOutcome

def build_subtitle_rendering_handler(**kwargs):
    from subtitle_rendering.infrastructure.composition import build_subtitle_rendering_handler as build
    return build(**kwargs)


def verify_subtitle_rendering(command: SubtitleRenderingCommand, *, output_root="output"):
    """Static content/evidence verification, without executing media tools or layout search."""
    from archive_core.application import build_asset_workspace
    from archive_core.domain import AssetId
    from archive_core.interfaces import SubtitleRenderManifestDTO, SubtitleRenderPlanDTO, SubtitleRenderReportDTO
    from subtitle_rendering.application.inputs import load_render_inputs, parse_json
    from subtitle_rendering.infrastructure.local import LocalRenderingArtifactStore
    from subtitle_rendering.infrastructure.ass import Pysubs2AssCodec
    try:
        workspace = build_asset_workspace(AssetId(*command.asset_id.split(":")), output_root).resolve()
        store = LocalRenderingArtifactStore()
        manifest_path = workspace / "subtitle_rendering_manifest.json"
        manifest = SubtitleRenderManifestDTO.from_dict(parse_json(manifest_path.read_bytes()))
        for evidence in (*manifest.inputs.values(), *manifest.outputs.values()):
            path = workspace / evidence.path
            if path.parent != workspace or store.size(str(path)) != evidence.size_bytes or store.sha256(str(path)) != evidence.sha256:
                raise ValueError("render evidence differs")
        plan = SubtitleRenderPlanDTO.from_dict(parse_json((workspace / "subtitle_rendering_plan.json").read_bytes()))
        report = SubtitleRenderReportDTO.from_dict(parse_json((workspace / "subtitle_rendering_report.json").read_bytes()))
        manifest.validate_against_plan_and_report(plan, report)
        # This mode validates the recorded media contract, not a fresh tool probe.
        class RecordedMedia:
            def probe(self, path):
                return manifest.input_media
        inputs = load_render_inputs(asset_id=command.asset_id, srt_processing_manifest_path=command.srt_processing_manifest_path,
                                    artifacts=store, probe=RecordedMedia(), output_root=output_root)
        if inputs.evidence != manifest.inputs:
            raise ValueError("render input evidence differs")
        plan.validate_against_subtitle_plan(inputs.source_plan)
        Pysubs2AssCodec().validate((workspace / "bilingual.ass").read_bytes(), plan, inputs.source_plan)
        return SubtitleRenderingOutcome("reused", "reuse", str(workspace / "subtitle_rendering_plan.json"),
                                         str(workspace / "bilingual.ass"), str(workspace / "video_中文字幕.mp4"),
                                         str(workspace / "subtitle_rendering_report.json"), str(manifest_path), len(plan.cues), report.summary.warning_count, None)
    except Exception as error:
        return SubtitleRenderingOutcome("failed", None, None, None, None, None, None, 0, 0, None, "input_invalid", str(error))
