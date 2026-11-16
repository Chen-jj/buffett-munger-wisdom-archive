"""Public source grouping entry point, independent of final SRT export."""

from dataclasses import dataclass
from archive_core.interfaces.bilingual import ProtectedSpanDTO


@dataclass(frozen=True)
class SourceChunkingCommand:
    asset_id: str
    transcription_manifest_path: str
    media_boundary_path: str
    confirmed_protections: tuple[ProtectedSpanDTO, ...] = ()
    overwrite: bool = False


@dataclass(frozen=True)
class SourceChunkingOutcome:
    status: str
    source_chunks_path: str | None = None
    manifest_path: str | None = None
    report_path: str | None = None
    chunk_count: int = 0
    warning_count: int = 0
    analyzer_calls: int = 0
    writes: int = 0
    error_category: str | None = None
    error_message: str | None = None


class SourceChunkingCommandHandler:
    def __init__(self, workflow):
        self.workflow = workflow

    def handle(self, command: SourceChunkingCommand) -> SourceChunkingOutcome:
        try:
            status, paths, plan, calls = self.workflow.run(command)
            return SourceChunkingOutcome(status, paths["source_chunks"], paths["manifest"], paths["report"],
                                         len(plan.chunks), sum(len(chunk.issues) for chunk in plan.chunks),
                                         calls, 0 if status == "reused" else 3)
        except Exception as error:
            return SourceChunkingOutcome("failed", error_category="artifact_conflict" if isinstance(error, FileExistsError) else "input_invalid",
                                         error_message=str(error))


def build_source_chunking_handler(*, output_root="output", model_bundle_path=None,
                                  artifacts=None, analyzer=None, clock=None):
    from srt_processing.application.source_chunking import SourceChunkingWorkflow
    from srt_processing.infrastructure.local import LocalSubtitleArtifactStore, SystemClock
    if analyzer is None:
        from srt_processing.infrastructure.stanza_chunking import StanzaConstituencyAnalyzer
        if model_bundle_path is None:
            raise ValueError("explicit prepared Stanza model bundle is required")
        analyzer = StanzaConstituencyAnalyzer(model_bundle_path)
    return SourceChunkingCommandHandler(SourceChunkingWorkflow(
        artifacts=artifacts if artifacts is not None else LocalSubtitleArtifactStore(),
        analyzer=analyzer, clock=clock if clock is not None else SystemClock(), output_root=output_root))


def verify_source_chunking(command: SourceChunkingCommand, *, output_root="output", model_bundle_path=None):
    """Read-only current-format verification; never invokes an analyzer or publisher."""
    import hashlib
    import json
    from pathlib import Path
    from archive_core.application import build_asset_workspace
    from archive_core.domain import AssetId
    from archive_core.interfaces.bilingual import SourceChunkPlanDTO, StageManifestDTO
    from archive_core.interfaces.transcription import SourceAlignmentDTO
    from srt_processing.application.source_chunking import chunking_report, metadata_bytes
    from srt_processing.domain.chunking_policy import chunking_policy
    try:
        workspace = build_asset_workspace(AssetId(*command.asset_id.split(":")), output_root).resolve()
        manifest_path = workspace / "source_chunking_manifest.json"
        manifest = StageManifestDTO.from_dict(json.loads(manifest_path.read_bytes()))
        if manifest.stage != "source_chunking" or manifest.asset_id != command.asset_id:
            raise ValueError("source chunking manifest identity differs")
        if set(manifest.inputs) != {"transcription_manifest", "source_alignment", "video", "media_boundary"} or set(manifest.outputs) != {"source_chunks", "report"}:
            raise ValueError("source chunking evidence set differs")
        for evidence in (*manifest.inputs.values(), *manifest.outputs.values()):
            path = Path(evidence.path)
            if path.parent != workspace or path.stat().st_size != evidence.size_bytes:
                raise ValueError("source chunking evidence path/size differs")
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1048576), b""):
                    digest.update(block)
            if digest.hexdigest() != evidence.sha256:
                raise ValueError("source chunking evidence checksum differs")
        if (command.transcription_manifest_path != manifest.inputs["transcription_manifest"].path
                or command.media_boundary_path != manifest.inputs["media_boundary"].path):
            raise ValueError("source chunking input binding differs")
        plan = SourceChunkPlanDTO.from_dict(json.loads(Path(manifest.outputs["source_chunks"].path).read_bytes()))
        alignment = SourceAlignmentDTO.from_dict(json.loads(Path(manifest.inputs["source_alignment"].path).read_bytes()))
        plan.validate_against_alignment(alignment)
        if plan.source_alignment_sha256 != manifest.inputs["source_alignment"].sha256:
            raise ValueError("source chunking alignment binding differs")
        plan_payload = plan.to_dict()
        identity = {"policy": chunking_policy(), "analyzer": plan_payload["analyzer"],
                    "confirmed_protections": [span.to_dict() for span in command.confirmed_protections]}
        if metadata_bytes(plan_payload["policy"]) != metadata_bytes(identity["policy"]):
            raise ValueError("source chunking policy differs")
        if metadata_bytes(manifest.to_dict()["identity"]) != metadata_bytes(identity):
            raise ValueError("source chunking manifest policy, analyzer or protection differs")
        if model_bundle_path is not None:
            from srt_processing.infrastructure.stanza_chunking import StanzaConstituencyAnalyzer
            # This object validates files/identity only. analyze() is never called.
            if metadata_bytes(plan_payload["analyzer"]) != metadata_bytes(StanzaConstituencyAnalyzer(model_bundle_path).identity):
                raise ValueError("source chunking local model identity differs")
        if json.loads(Path(manifest.outputs["report"].path).read_bytes()) != chunking_report(plan):
            raise ValueError("source chunking report differs")
        return SourceChunkingOutcome("reused", manifest.outputs["source_chunks"].path, str(manifest_path), manifest.outputs["report"].path,
                                     len(plan.chunks), sum(len(chunk.issues) for chunk in plan.chunks))
    except Exception as error:
        return SourceChunkingOutcome("failed", error_category="input_invalid", error_message=str(error))
