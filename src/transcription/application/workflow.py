"""Assembly and manifest lifecycle for the complete transcription stage."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import json
from pathlib import Path
from typing import Any, Mapping

from archive_core.application import build_asset_workspace
from archive_core.domain import AssetId, ArtifactType, canonical_filename
from archive_core.interfaces import StructuredTranscriptDTO
from transcription.domain import (
    AlignmentTimingSource,
    AsrConfig,
    ForcedAlignmentConfig,
    MatchingPolicy,
    NormalizationPolicy,
    OfficialAlignmentConfig,
    SentenceBoundaryPolicy,
    TranscriptionQaPolicy,
    VadConfig,
)

from .alignment import ForcedAlignmentPolicy, ForcedAlignmentResult, ForcedAlignmentService
from .audio_asr import (
    AudioVadAsrCacheManifest,
    AudioVadAsrPolicy,
    AudioVadAsrResult,
    AudioVadAsrService,
    CacheRecord,
    SourceVideoInput,
    _cache_key,
)
from .fusion import (
    OfficialTranscriptInput,
    TranscriptFusionPolicy,
    TranscriptFusionResult,
    TranscriptFusionService,
)
from .observability import (
    EventCode,
    EventSeverity,
    QaResult,
    TranscriptionEvent,
    TranscriptionReport,
    TranscriptionReportAggregator,
)
from .ports import ChecksumService, TranscriptionArtifactStore
from .sentences import (
    SentenceBoundaryPublicationPolicy,
    SentenceBoundaryResult,
    SentenceBoundaryService,
)


WORKFLOW_STAGE_NAME = "transcription_workflow"
DOWNLOAD_MANIFEST_SCHEMA = "media-download.manifest.1"


class WorkflowStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


WORKFLOW_STAGE_ORDER = (
    "audio_vad_asr",
    "forced_alignment",
    "official_transcript_fusion",
    "sentence_boundaries",
)


@dataclass(frozen=True)
class TranscriptionWorkflowConfig:
    vad: VadConfig
    asr: AsrConfig
    alignment: ForcedAlignmentConfig
    normalization: NormalizationPolicy = field(default_factory=NormalizationPolicy)
    matching: MatchingPolicy = field(default_factory=MatchingPolicy)
    official_alignment: OfficialAlignmentConfig | None = None
    sentence_boundary: SentenceBoundaryPolicy = field(
        default_factory=SentenceBoundaryPolicy
    )
    qa: TranscriptionQaPolicy = field(default_factory=TranscriptionQaPolicy)

    def __post_init__(self) -> None:
        expected = (
            (self.vad, VadConfig, "vad"),
            (self.asr, AsrConfig, "asr"),
            (self.alignment, ForcedAlignmentConfig, "alignment"),
            (self.normalization, NormalizationPolicy, "normalization"),
            (self.matching, MatchingPolicy, "matching"),
            (self.sentence_boundary, SentenceBoundaryPolicy, "sentence_boundary"),
            (self.qa, TranscriptionQaPolicy, "qa"),
        )
        for value, value_type, name in expected:
            if not isinstance(value, value_type):
                raise ValueError(f"{name} must be a {value_type.__name__}")
        if self.official_alignment is not None and not isinstance(
            self.official_alignment, OfficialAlignmentConfig
        ):
            raise ValueError(
                "official_alignment must be an OfficialAlignmentConfig or null"
            )


@dataclass(frozen=True)
class TranscriptionWorkflowInput:
    asset_id: AssetId
    download_manifest_path: str
    chapters_sha256: str | None = None
    overwrite: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.asset_id, AssetId):
            raise ValueError("asset_id must be an AssetId")
        if not isinstance(self.download_manifest_path, str) or not self.download_manifest_path.strip():
            raise ValueError("download_manifest_path must be a non-empty string")
        if self.chapters_sha256 is not None and (
            not isinstance(self.chapters_sha256, str)
            or not self.chapters_sha256.strip()
        ):
            raise ValueError("chapters_sha256 must be a non-empty string or null")
        if not isinstance(self.overwrite, bool):
            raise ValueError("overwrite must be a bool")


@dataclass(frozen=True)
class TranscriptionWorkflowOutcome:
    status: WorkflowStatus
    source_alignment_path: str
    manifest_path: str
    log_path: str
    report_path: str
    report: TranscriptionReport
    cache_hits: tuple[str, ...]


class TranscriptionWorkflowInputError(RuntimeError):
    pass


class TranscriptionWorkflowQaError(RuntimeError):
    pass


class TranscriptionWorkflowEventRecorder:
    """Record the full event stream while aggregating only actionable findings."""

    def __init__(self, asset_id: str) -> None:
        self._report = TranscriptionReportAggregator(asset_id)
        self._events: list[TranscriptionEvent] = []

    @property
    def events(self) -> tuple[TranscriptionEvent, ...]:
        return tuple(self._events)

    def emit(self, event: TranscriptionEvent) -> None:
        self._report.emit(event)
        self._events.append(event)

    def flush(self) -> None:
        self._report.flush()

    def record_qa(self, result: QaResult) -> None:
        self._report.record_qa(result)

    def finalize_success(self) -> TranscriptionReport:
        self._report.mark_succeeded()
        return self._report.snapshot()

    def finalize_failure(self, error: Exception) -> TranscriptionReport:
        reason = str(error).strip() or error.__class__.__name__
        self.emit(
            TranscriptionEvent(
                asset_id=self._report.snapshot().asset_id,
                stage=WORKFLOW_STAGE_NAME,
                code=EventCode.STAGE_FAILED,
                severity=EventSeverity.ERROR,
                action="abort_workflow",
                reason=reason,
                details={"error_type": error.__class__.__name__},
            )
        )
        self._report.mark_failed(reason)
        return self._report.snapshot()

    def reset(self) -> None:
        self._report = TranscriptionReportAggregator(self._report.snapshot().asset_id)
        self._events.clear()


class TranscriptionWorkflow:
    """Run the fixed Phase 1 stage order and own final manifest state."""

    def __init__(
        self,
        *,
        audio_vad_asr: AudioVadAsrService,
        forced_alignment: ForcedAlignmentService,
        transcript_fusion: TranscriptFusionService,
        sentence_boundaries: SentenceBoundaryService,
        checksum: ChecksumService,
        artifacts: TranscriptionArtifactStore,
        events: TranscriptionWorkflowEventRecorder,
        config: TranscriptionWorkflowConfig,
        output_root: str = "output",
    ) -> None:
        self.audio_vad_asr = audio_vad_asr
        self.forced_alignment = forced_alignment
        self.transcript_fusion = transcript_fusion
        self.sentence_boundaries = sentence_boundaries
        self.checksum = checksum
        self.artifacts = artifacts
        self.events = events
        self.config = config
        self.output_root = output_root

    def execute(
        self, request: TranscriptionWorkflowInput
    ) -> TranscriptionWorkflowOutcome:
        self.events.reset()
        paths = self._paths(request.asset_id)
        completed: list[str] = []
        cache_hits: list[str] = []
        self.events.emit(
            TranscriptionEvent(
                asset_id=request.asset_id.value,
                stage=WORKFLOW_STAGE_NAME,
                code=EventCode.STAGE_STARTED,
                severity=EventSeverity.INFO,
                action="run_transcription",
                reason="fixed Phase 1 transcription workflow requested",
                details={"stage_count": len(WORKFLOW_STAGE_ORDER)},
            )
        )
        try:
            source = self._load_download_input(request)
            official = self._load_official_input(request, paths["chapters"])

            audio = self.audio_vad_asr.execute(
                source,
                vad_config=self.config.vad,
                asr_config=self.config.asr,
                policy=AudioVadAsrPolicy(overwrite=request.overwrite),
            )
            completed.append(WORKFLOW_STAGE_ORDER[0])
            cache_hits.extend(audio.cache_hits)

            aligned = self.forced_alignment.execute(
                audio,
                config=self.config.alignment,
                policy=ForcedAlignmentPolicy(overwrite=request.overwrite),
            )
            completed.append(WORKFLOW_STAGE_ORDER[1])
            if aligned.cache_hit:
                cache_hits.append("aligned_asr")
            self._evaluate_alignment_qa(aligned)

            fusion = self.transcript_fusion.execute(
                aligned,
                official=official,
                normalization=self.config.normalization,
                matching=self.config.matching,
                official_alignment_config=(
                    self.config.official_alignment if official is not None else None
                ),
                policy=TranscriptFusionPolicy(overwrite=request.overwrite),
            )
            completed.append(WORKFLOW_STAGE_ORDER[2])
            if fusion.cache_hit:
                cache_hits.append("transcript_fusion")

            sentence = self.sentence_boundaries.execute(
                aligned,
                fusion,
                official=official,
                boundary_policy=self.config.sentence_boundary,
                publication_policy=SentenceBoundaryPublicationPolicy(
                    overwrite=request.overwrite,
                    publish=False,
                ),
            )
            completed.append(WORKFLOW_STAGE_ORDER[3])
            if sentence.cache_hit:
                cache_hits.append("source_alignment")
            self.events.record_qa(
                QaResult(
                    name="source_alignment_public_contract",
                    passed=True,
                    detail=(
                        f"{len(sentence.alignment.words)} words and "
                        f"{len(sentence.alignment.sentences)} sentences round-tripped"
                    ),
                )
            )
            self.events.emit(
                TranscriptionEvent(
                    asset_id=request.asset_id.value,
                    stage=WORKFLOW_STAGE_NAME,
                    code=EventCode.STAGE_COMPLETED,
                    severity=EventSeverity.INFO,
                    action="publish_transcription",
                    reason="all stages and workflow QA gates succeeded",
                    details={"cache_hits": len(cache_hits)},
                )
            )
            report = self.events.finalize_success()
            log_record, report_record = self._persist_observability(paths, report)
            manifest = self._load_transcription_manifest(
                paths["manifest"], request.asset_id
            )
            manifest.records["transcription_log"] = log_record
            manifest.records["transcription_report"] = report_record
            manifest.workflow = self._workflow_state(
                WorkflowStatus.SUCCEEDED,
                request,
                completed,
                cache_hits,
                report,
            )
            if sentence.cache_hit:
                self.artifacts.write_json(
                    paths["manifest"], manifest.to_dict(), overwrite=True
                )
            else:
                def build_final_manifest(size_bytes: int, sha256: str) -> Mapping[str, Any]:
                    manifest.records["source_alignment"] = CacheRecord(
                        path=sentence.path,
                        size_bytes=size_bytes,
                        sha256=sha256,
                        cache_key=sentence.cache_key,
                        provenance=dict(sentence.provenance),
                    )
                    return manifest.to_dict()

                self.artifacts.publish_json_pair(
                    sentence.path,
                    sentence.alignment.to_dict(),
                    paths["manifest"],
                    build_final_manifest,
                    overwrite=request.overwrite,
                )
            return TranscriptionWorkflowOutcome(
                status=WorkflowStatus.SUCCEEDED,
                source_alignment_path=sentence.path,
                manifest_path=paths["manifest"],
                log_path=paths["log"],
                report_path=paths["report"],
                report=report,
                cache_hits=tuple(cache_hits),
            )
        except Exception as error:
            report = self.events.finalize_failure(error)
            self._persist_failure(paths, request, completed, cache_hits, report)
            raise

    def _load_download_input(
        self, request: TranscriptionWorkflowInput
    ) -> SourceVideoInput:
        expected_manifest = self._paths(request.asset_id)["download_manifest"]
        if Path(request.download_manifest_path) != Path(expected_manifest):
            raise TranscriptionWorkflowInputError(
                "download manifest path is not canonical"
            )
        try:
            data = self.artifacts.read_json(request.download_manifest_path)
            if data.get("schema_version") != DOWNLOAD_MANIFEST_SCHEMA:
                raise ValueError("unsupported download manifest schema")
            asset_data = _mapping(data.get("asset"), "asset")
            artifact_data = _mapping(data.get("artifact"), "artifact")
            checksum_data = _mapping(artifact_data.get("checksum"), "checksum")
            download_data = _mapping(data.get("download"), "download")
            manifest_asset = AssetId(
                source=asset_data.get("source"),
                group=asset_data.get("group", ""),
                item=asset_data.get("item"),
            )
            source = SourceVideoInput(
                asset_id=request.asset_id,
                path=artifact_data.get("path"),
                manifest_asset_id=manifest_asset,
                manifest_status=download_data.get("status"),
                size_bytes=artifact_data.get("size_bytes"),
                checksum_algorithm=checksum_data.get("algorithm"),
                checksum_value=checksum_data.get("value"),
            )
        except Exception as error:
            raise TranscriptionWorkflowInputError(
                "download manifest is missing or invalid"
            ) from error
        return source

    def _load_official_input(
        self, request: TranscriptionWorkflowInput, chapters_path: str
    ) -> OfficialTranscriptInput | None:
        if not self.artifacts.exists(chapters_path):
            if request.chapters_sha256 is not None:
                raise TranscriptionWorkflowInputError(
                    "chapters checksum supplied but canonical chapters.json is missing"
                )
            return None
        if request.chapters_sha256 is None:
            raise TranscriptionWorkflowInputError(
                "canonical chapters.json requires checksum evidence"
            )
        if self.checksum.sha256(chapters_path) != request.chapters_sha256:
            raise TranscriptionWorkflowInputError("chapters checksum is invalid")
        try:
            transcript = StructuredTranscriptDTO.from_dict(
                self.artifacts.read_json(chapters_path)
            )
        except Exception as error:
            raise TranscriptionWorkflowInputError(
                "canonical chapters.json is invalid"
            ) from error
        return OfficialTranscriptInput(
            path=chapters_path,
            sha256=request.chapters_sha256,
            transcript=transcript,
        )

    def _evaluate_alignment_qa(self, aligned: ForcedAlignmentResult) -> None:
        words = aligned.artifact.words
        if self.config.qa.require_non_empty_alignment and not words:
            result = QaResult(
                name="non_empty_alignment",
                passed=False,
                detail="workflow QA policy requires at least one aligned word",
            )
            self.events.record_qa(result)
            raise TranscriptionWorkflowQaError(result.detail)
        interpolated = sum(
            word.timing_source is AlignmentTimingSource.INTERPOLATED for word in words
        )
        ratio = interpolated / len(words) if words else 0.0
        passed = ratio <= self.config.qa.max_interpolated_word_ratio
        result = QaResult(
            name="interpolated_word_ratio",
            passed=passed,
            detail=(
                f"{interpolated}/{len(words)}={ratio:.6f}; maximum "
                f"{self.config.qa.max_interpolated_word_ratio:.6f} under "
                f"{self.config.qa.version}"
            ),
        )
        self.events.record_qa(result)
        if not passed:
            raise TranscriptionWorkflowQaError(result.detail)

    def _persist_observability(
        self, paths: Mapping[str, str], report: TranscriptionReport
    ) -> tuple[CacheRecord, CacheRecord]:
        lines = "".join(
            json.dumps(event.to_dict(), ensure_ascii=False, allow_nan=False) + "\n"
            for event in self.events.events
        )
        self.artifacts.write_text(paths["log"], lines, overwrite=True)
        self.artifacts.write_json(paths["report"], report.to_dict(), overwrite=True)
        return (
            self._diagnostic_record(paths["log"], "transcription_log", report),
            self._diagnostic_record(paths["report"], "transcription_report", report),
        )

    def _diagnostic_record(
        self, path: str, name: str, report: TranscriptionReport
    ) -> CacheRecord:
        return CacheRecord(
            path=path,
            size_bytes=self.artifacts.size(path),
            sha256=self.checksum.sha256(path),
            cache_key=_cache_key(
                f"{name}.v1",
                {"status": report.status.value, "event_count": len(self.events.events)},
            ),
            provenance={"status": report.status.value},
        )

    def _persist_failure(
        self,
        paths: Mapping[str, str],
        request: TranscriptionWorkflowInput,
        completed: list[str],
        cache_hits: list[str],
        report: TranscriptionReport,
    ) -> None:
        records: tuple[CacheRecord, CacheRecord] | None = None
        try:
            records = self._persist_observability(paths, report)
        except Exception:
            pass
        try:
            manifest = self._load_transcription_manifest(
                paths["manifest"], request.asset_id
            )
            if records is not None:
                manifest.records["transcription_log"] = records[0]
                manifest.records["transcription_report"] = records[1]
            manifest.workflow = self._workflow_state(
                WorkflowStatus.FAILED,
                request,
                completed,
                cache_hits,
                report,
            )
            self.artifacts.write_json(paths["manifest"], manifest.to_dict(), overwrite=True)
        except Exception:
            pass

    def _workflow_state(
        self,
        status: WorkflowStatus,
        request: TranscriptionWorkflowInput,
        completed: list[str],
        cache_hits: list[str],
        report: TranscriptionReport,
    ) -> dict[str, Any]:
        state: dict[str, Any] = {
            "status": status.value,
            "stage_order": list(WORKFLOW_STAGE_ORDER),
            "completed_stages": list(completed),
            "cache_hits": list(cache_hits),
            "inputs": {
                "download_manifest_path": request.download_manifest_path,
                "chapters_sha256": request.chapters_sha256,
            },
            "qa_policy": self.config.qa.to_dict(),
            "summary": dict(report.counts),
        }
        if report.failure_reason is not None:
            state["failure_reason"] = report.failure_reason
        return state

    def _load_transcription_manifest(
        self, path: str, asset_id: AssetId
    ) -> AudioVadAsrCacheManifest:
        if not self.artifacts.exists(path):
            return AudioVadAsrCacheManifest(asset_id=asset_id)
        manifest = AudioVadAsrCacheManifest.from_dict(self.artifacts.read_json(path))
        if manifest.asset_id != asset_id:
            raise TranscriptionWorkflowInputError(
                "transcription manifest asset identity is invalid"
            )
        return manifest

    def _paths(self, asset_id: AssetId) -> dict[str, str]:
        workspace = build_asset_workspace(asset_id, self.output_root)
        return {
            "download_manifest": str(workspace / "download_manifest.json"),
            "chapters": str(workspace / canonical_filename(ArtifactType.CHAPTERS)),
            "source_alignment": str(
                workspace / canonical_filename(ArtifactType.SOURCE_ALIGNMENT)
            ),
            "manifest": str(
                workspace / canonical_filename(ArtifactType.TRANSCRIPTION_MANIFEST)
            ),
            "log": str(
                workspace / canonical_filename(ArtifactType.TRANSCRIPTION_LOG)
            ),
            "report": str(
                workspace / canonical_filename(ArtifactType.TRANSCRIPTION_REPORT)
            ),
        }


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value
