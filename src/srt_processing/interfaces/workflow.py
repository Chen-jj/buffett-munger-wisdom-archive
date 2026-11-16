"""Thin final-draft export boundary."""
from dataclasses import dataclass


@dataclass(frozen=True)
class SrtProcessingCommand:
    asset_id: str
    bilingual_postprocessing_manifest_path: str
    overwrite: bool = False


@dataclass(frozen=True)
class SrtProcessingOutcome:
    status: str
    plan_path: str | None = None
    manifest_path: str | None = None
    report_path: str | None = None
    english_srt_path: str | None = None
    chinese_srt_path: str | None = None
    bilingual_srt_path: str | None = None
    cue_count: int = 0
    warning_count: int = 0
    writes: int = 0
    error_category: str | None = None
    error_message: str | None = None


class SrtProcessingCommandHandler:
    def __init__(self, workflow):
        self.workflow = workflow

    def handle(self, command: SrtProcessingCommand) -> SrtProcessingOutcome:
        if not isinstance(command, SrtProcessingCommand):
            raise ValueError("command must be SrtProcessingCommand")
        try:
            result = self.workflow.execute(asset_id=command.asset_id,
                                           bilingual_postprocessing_manifest_path=command.bilingual_postprocessing_manifest_path,
                                           overwrite=command.overwrite)
            return SrtProcessingOutcome(**result.__dict__)
        except Exception as error:
            return SrtProcessingOutcome("failed", error_category="artifact_conflict" if isinstance(error, FileExistsError) else getattr(error, "category", "srt_processing_failed"), error_message=str(error))


def build_srt_processing_handler(*, output_root="output", artifacts=None, codec=None, clock=None):
    from srt_processing.infrastructure.composition import build_srt_processing_handler as build
    return build(output_root=output_root, artifacts=artifacts, codec=codec, clock=clock)


def verify_srt_export(command: SrtProcessingCommand, *, output_root="output"):
    """Static, strictly read-only source-chain and exact-projection verification."""
    import json
    import hashlib
    from archive_core.interfaces.bilingual import StageManifestDTO
    from srt_processing.application.inputs import load_subtitle_inputs
    from srt_processing.application.workflow import export_report
    from srt_processing.application.source_chunking import metadata_bytes
    from srt_processing.infrastructure.local import LocalSubtitleArtifactStore
    from srt_processing.infrastructure.codec import Pysubs2SrtCodec
    try:
        store, codec = LocalSubtitleArtifactStore(), Pysubs2SrtCodec()
        inputs = load_subtitle_inputs(asset_id=command.asset_id, bilingual_postprocessing_manifest_path=command.bilingual_postprocessing_manifest_path,
                                      artifacts=store, output_root=output_root)
        path = inputs.workspace / "srt_processing_manifest.json"
        manifest = StageManifestDTO.from_dict(json.loads(path.read_bytes()))
        if manifest.stage != "srt_export" or manifest.asset_id != command.asset_id or manifest.inputs != inputs.evidence:
            raise ValueError("SRT source identity differs")
        expected = {language + "_srt": codec.encode(inputs.draft, language) for language in ("english", "chinese", "bilingual")}
        report = export_report(inputs.draft)
        expected["report"] = metadata_bytes(report)
        if set(manifest.outputs) != set(expected):
            raise ValueError("SRT output set differs")
        for name, raw in expected.items():
            evidence = manifest.outputs[name]
            if (store.read_bytes(evidence.path) != raw or evidence.size_bytes != len(raw)
                    or evidence.sha256 != hashlib.sha256(raw).hexdigest()):
                raise ValueError("SRT output projection differs")
        return SrtProcessingOutcome("reused", inputs.evidence["final_bilingual_draft"].path, str(path), manifest.outputs["report"].path,
                                     manifest.outputs["english_srt"].path, manifest.outputs["chinese_srt"].path, manifest.outputs["bilingual_srt"].path,
                                     len(inputs.draft.cues), report["summary"]["warning_count"])
    except Exception as error:
        return SrtProcessingOutcome("failed", error_category="input_invalid", error_message=str(error))
