"""The only production cross-module composition; import public interfaces only."""

from dataclasses import asdict, is_dataclass
from pathlib import Path

from archive_core.application import build_asset_workspace
from archive_core.interfaces.bilingual import StageManifestDTO
from infrastructure.infrastructure.artifacts import evidence, read_json
from infrastructure.infrastructure.process import run_process
from orchestration.application.workflow import PipelineService
from orchestration.domain.models import StageInspection, STAGES
from .local import LocalAssetLock, LocalRunStore

from acquisition.interfaces import AcquisitionCommand, build_acquisition_handler
from media_download.interfaces import DownloadCommand, MediaDerivationCommand, build_download_handler, build_media_derivation_handler
from transcription.interfaces import TranscriptionCommand, build_transcription_handler, verify_transcription
from srt_processing.interfaces.source_chunking import SourceChunkingCommand, build_source_chunking_handler, verify_source_chunking
from srt_processing.interfaces.workflow import SrtProcessingCommand, build_srt_processing_handler, verify_srt_export
from translation.interfaces import (
    TranslationCommand, BilingualPostprocessingCommand, build_translation_handler,
    build_bilingual_postprocessing_handler,
)
from subtitle_rendering.interfaces import SubtitleRenderingCommand, build_subtitle_rendering_handler, verify_subtitle_rendering


_MARKERS = {"acquisition": "acquisition_receipt.json", "media_download": "download_manifest.json",
            "media_derivation": "media_derivation_manifest.json", "transcription": "transcription_manifest.json",
            "source_chunking": "source_chunking_manifest.json", "translation": "translation_manifest.json",
            "bilingual_postprocessing": "bilingual_postprocessing_manifest.json", "srt_export": "srt_processing_manifest.json",
            "subtitle_rendering": "subtitle_rendering_manifest.json"}
_PARTIAL_OUTPUTS = {"acquisition": ("meta.json", "media_ref.json"), "media_download": ("video.mp4",),
                    "media_derivation": ("video.mp4",), "source_chunking": ("source_chunks.json",),
                    "translation": ("translation_result.json",), "bilingual_postprocessing": ("final_bilingual_draft.json",),
                    "srt_export": ("english.srt", "chinese.srt", "bilingual.srt"), "subtitle_rendering": ("video_中文字幕.mp4",)}


class ProductionStage:
    def __init__(self, name, *, runtime=None):
        self.name, self.runtime = name, runtime

    def _workspace(self, command):
        asset = command.source_asset_id if self.name in {"acquisition", "media_download"} else command.asset_id
        return build_asset_workspace(asset, Path(command.output_root).resolve())

    def _command(self, command):
        workspace = self._workspace(command)
        if self.name == "acquisition":
            return AcquisitionCommand(command.source_asset_id, command.locator)
        if self.name == "media_download":
            return DownloadCommand(command.source_asset_id, prepare_boundary=command.selection is None, height=command.download_height)
        if self.name == "media_derivation":
            return MediaDerivationCommand(command.source_asset_id, command.asset_id, command.selection.start_ms,
                                         command.selection.end_ms, command.selection.chapter_numbers)
        if self.name == "transcription":
            chapters = workspace / "chapters.json"
            return TranscriptionCommand(command.asset_id, str(workspace / "download_manifest.json"), evidence(chapters).sha256 if chapters.exists() else None)
        if self.name == "source_chunking":
            return SourceChunkingCommand(command.asset_id.value, str(workspace / "transcription_manifest.json"), str(workspace / "media_boundary.json"))
        if self.name == "translation":
            return TranslationCommand(command.asset_id.value, str(workspace / "transcription_manifest.json"), str(workspace / "source_chunking_manifest.json"))
        if self.name == "bilingual_postprocessing":
            return BilingualPostprocessingCommand(command.asset_id.value, str(workspace / "transcription_manifest.json"),
                                                  str(workspace / "source_chunking_manifest.json"), str(workspace / "translation_manifest.json"))
        if self.name == "srt_export":
            return SrtProcessingCommand(command.asset_id.value, str(workspace / "bilingual_postprocessing_manifest.json"))
        return SubtitleRenderingCommand(command.asset_id.value, str(workspace / "srt_processing_manifest.json"))

    def _handler(self, command, process_runner=None):
        root = str(Path(command.output_root).resolve())
        if self.name == "acquisition":
            return build_acquisition_handler(output_root=root)
        if self.name == "media_download":
            return build_download_handler(output_root=root, process_runner=process_runner)
        if self.name == "media_derivation":
            return build_media_derivation_handler(output_root=root, process_runner=process_runner)
        if self.name == "transcription":
            return build_transcription_handler(output_root=root, runtime=self.runtime)
        if self.name == "source_chunking":
            return build_source_chunking_handler(output_root=root, model_bundle_path=command.model_bundle_path)
        if self.name == "translation":
            return build_translation_handler(output_root=root)
        if self.name == "bilingual_postprocessing":
            return build_bilingual_postprocessing_handler(output_root=root)
        if self.name == "srt_export":
            return build_srt_processing_handler(output_root=root)
        return build_subtitle_rendering_handler(output_root=root, process_runner=process_runner or run_process)

    def inspect(self, command):
        workspace = self._workspace(command)
        marker = workspace / _MARKERS[self.name]
        if not marker.exists():
            partial = any((workspace / filename).exists() for filename in _PARTIAL_OUTPUTS.get(self.name, ()))
            return StageInspection("conflict" if partial else "absent", reason="partial stage outputs without a successful manifest" if partial else "")
        try:
            if self.name == "media_download" and command.selection is None and not (workspace / "media_boundary.json").exists():
                build_download_handler(output_root=command.output_root).verify(DownloadCommand(command.source_asset_id, height=command.download_height))
                return StageInspection("absent", reason="download verified; local frame evidence pending")
            # Failed/interrupted transcription keeps its valid layered cache; execute may resume it.
            if self.name == "transcription" and read_json(marker).get("workflow", {}).get("status") != "succeeded":
                return StageInspection("absent", reason="transcription retains an unfinished layered checkpoint")
            stage_command = self._command(command)
            root = str(Path(command.output_root).resolve())
            if self.name == "transcription":
                verify_transcription(stage_command, output_root=root)
            elif self.name == "source_chunking":
                result = verify_source_chunking(stage_command, output_root=root, model_bundle_path=command.model_bundle_path)
                if result.status == "failed":
                    raise ValueError(result.error_message)
            elif self.name == "srt_export":
                result = verify_srt_export(stage_command, output_root=root)
                if result.status == "failed":
                    raise ValueError(result.error_message)
            elif self.name == "subtitle_rendering":
                result = verify_subtitle_rendering(stage_command, output_root=root)
                if result.status == "failed":
                    raise ValueError(result.error_message)
            else:
                result = self._handler(command).verify(stage_command)
                if getattr(result, "status", "reused") == "failed":
                    raise ValueError(result.error_message)
            # Bind all evidence, not just receipt status, for plan staleness/TOCTOU checks.
            data = read_json(marker)
            bindings = {str(marker): evidence(marker).sha256}
            if data.get("schema_version") == "pipeline.stage-manifest.v1":
                manifest = StageManifestDTO.from_dict(data)
                for item in (*manifest.inputs.values(), *manifest.outputs.values()):
                    bindings[item.path] = item.sha256
            elif self.name == "transcription":
                for record in data["records"].values():
                    bindings[record["path"]] = record["sha256"]
            elif self.name == "media_download":
                bindings[data["artifact"]["path"]] = data["artifact"]["checksum"]["value"]
                if command.selection is None:
                    boundary = evidence(workspace / "media_boundary.json")
                    bindings[boundary.path] = boundary.sha256
            elif self.name == "subtitle_rendering":
                for item in (*data["inputs"].values(), *data["outputs"].values()):
                    bindings[item["path"]] = item["sha256"]
            return StageInspection("verified", bindings)
        except Exception as error:
            return StageInspection("conflict", reason=f"{self.name}: {error}")

    def run(self, command):
        stage_command = self._command(command)
        counters = {name: 0 for name in ("download_calls", "media_derivation_encoding_calls", "render_encoding_calls")
                    if self.name == {"download_calls": "media_download", "media_derivation_encoding_calls": "media_derivation",
                                     "render_encoding_calls": "subtitle_rendering"}[name]}

        def observed_process(argv, **options):
            if self.name == "media_download" and "--retries" in argv and "-o" in argv:
                counters["download_calls"] += 1
            if self.name == "media_derivation" and "-c:v" in argv and "-n" in argv:
                counters["media_derivation_encoding_calls"] += 1
            if self.name == "subtitle_rendering" and "-c:v" in argv and "-n" in argv:
                counters["render_encoding_calls"] += 1
            return run_process(argv, **options)

        workspace = self._workspace(command)
        before = _stage_snapshot(workspace)
        handler = self._handler(command, process_runner=observed_process)
        if self.name == "transcription":
            result = handler.execute(stage_command)
            counts = dict(handler.last_counts)
            data = {"status": "reused" if not any(counts.values()) else "succeeded",
                    "manifest_path": result.manifest_path, "counts": counts, "cache_hits": list(result.cache_hits)}
        else:
            result = handler.handle(stage_command)
            if self.name == "media_download":
                data = {"status": "reused" if result.plan.action.value == "skip" else "succeeded", "manifest_path": result.manifest_path}
            else:
                data = asdict(result) if is_dataclass(result) else dict(result)
            if self.name == "translation":
                counters["provider_content_calls"] = data["attempt_count"]
            elif self.name == "bilingual_postprocessing":
                counters["provider_content_calls"] = data["provider_calls"]
            elif self.name == "source_chunking":
                counters["analyzer_calls"] = data["analyzer_calls"]
            elif self.name == "acquisition":
                counters["network_calls"] = data["network_calls"]
            data["counts"] = counters
        after = _stage_snapshot(workspace)
        changed = tuple(sorted(path for path in before.keys() | after.keys() if before.get(path) != after.get(path)))
        data["observed_artifacts_changed"] = list(changed)
        data["counts"]["artifact_files_changed"] = len(changed)
        if self.name == "media_download" and changed and data["status"] == "reused":
            data["status"] = "succeeded"  # Existing download + freshly published local frame evidence.
        return data


def _stage_snapshot(workspace):
    """Observe persisted file changes; exact full-run hashes are independently checked by the runner."""
    if not workspace.exists():
        return {}
    return {str(path): (path.stat().st_size, path.stat().st_mtime_ns)
            for path in workspace.rglob("*") if path.is_file() and "pipeline_runs" not in path.relative_to(workspace).parts
            and path.name != ".pipeline.lock"}


def build_pipeline_handler(*, runtime=None):
    return PipelineService(stages={name: ProductionStage(name, runtime=runtime) for name in STAGES},
                           store=LocalRunStore(), lock=LocalAssetLock())
