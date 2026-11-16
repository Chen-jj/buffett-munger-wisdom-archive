"""Pure, finite single-asset pipeline plans and explicit execution authorization."""

from dataclasses import dataclass, field
import hashlib
import json
from typing import Mapping

from archive_core.domain import AssetId


STAGES = ("acquisition", "media_download", "media_derivation", "transcription", "source_chunking",
          "translation", "bilingual_postprocessing", "srt_export", "subtitle_rendering")


@dataclass(frozen=True)
class MediaSelection:
    start_ms: int
    end_ms: int
    chapter_numbers: tuple[int, ...]

    def __post_init__(self):
        if any(isinstance(value, bool) or not isinstance(value, int) for value in (self.start_ms, self.end_ms)) or not 0 <= self.start_ms < self.end_ms:
            raise ValueError("selection must have an explicit positive media range")
        if not self.chapter_numbers or tuple(sorted(set(self.chapter_numbers))) != self.chapter_numbers:
            raise ValueError("selection requires ordered complete chapter numbers")


@dataclass(frozen=True)
class PipelineCommand:
    asset_id: AssetId
    source_asset_id: AssetId
    locator: str
    output_root: str
    selection: MediaSelection | None = None
    target_stage: str = "subtitle_rendering"
    allowed_actions: tuple[str, ...] = ()
    max_stage_executions: int = 0
    resume_run_id: str | None = None
    model_bundle_path: str | None = None
    download_height: int | None = None

    def __post_init__(self):
        if not isinstance(self.asset_id, AssetId) or not isinstance(self.source_asset_id, AssetId):
            raise ValueError("pipeline requires explicit source and output assets")
        if self.selection is None:
            if self.asset_id != self.source_asset_id or self.target_stage == "media_derivation":
                raise ValueError("direct media must keep its original asset identity")
        elif not isinstance(self.selection, MediaSelection) or self.asset_id == self.source_asset_id or self.asset_id.source != self.source_asset_id.source:
            raise ValueError("derived asset must differ while preserving source and a production selection")
        if self.download_height is not None and (type(self.download_height) is not int or self.download_height <= 0):
            raise ValueError("download height must be an explicit positive integer")
        if self.target_stage not in STAGES or not set(self.allowed_actions) <= set(STAGES):
            raise ValueError("unknown pipeline stage or action")
        if isinstance(self.max_stage_executions, bool) or not isinstance(self.max_stage_executions, int) or self.max_stage_executions < 0:
            raise ValueError("stage execution budget must be a nonnegative integer")
        if not self.locator.strip() or not self.output_root.strip():
            raise ValueError("pipeline requires source locator and output root")

    def to_dict(self):
        return {"asset_id": self.asset_id.value, "source_asset_id": self.source_asset_id.value,
                "locator": self.locator, "output_root": self.output_root, "selection": {
                    "start_ms": self.selection.start_ms, "end_ms": self.selection.end_ms,
                    "chapter_numbers": list(self.selection.chapter_numbers)} if self.selection else None, "target_stage": self.target_stage,
                "allowed_actions": list(self.allowed_actions), "max_stage_executions": self.max_stage_executions,
                "resume_run_id": self.resume_run_id, "model_bundle_path": self.model_bundle_path, "download_height": self.download_height}

    def input_identity(self):
        fields = self.to_dict()
        return {key: fields[key] for key in ("asset_id", "source_asset_id", "locator", "output_root", "selection", "model_bundle_path", "download_height")}


@dataclass(frozen=True)
class StageInspection:
    status: str  # absent / verified / conflict
    evidence: Mapping[str, str] = field(default_factory=dict)
    reason: str = ""

    def __post_init__(self):
        if self.status not in ("absent", "verified", "conflict"):
            raise ValueError("unknown stage inspection status")
        if self.status == "verified" and not self.evidence:
            raise ValueError("verified stage must bind evidence")


@dataclass(frozen=True)
class StagePlan:
    stage: str
    action: str  # execute / verify_reuse / blocked
    reason: str
    evidence: Mapping[str, str]

    def __post_init__(self):
        if self.stage not in STAGES or self.action not in ("execute", "verify_reuse", "blocked"):
            raise ValueError("unknown plan action or stage")

    def to_dict(self):
        return {"stage": self.stage, "action": self.action, "reason": self.reason, "evidence": dict(self.evidence)}


@dataclass(frozen=True)
class PipelinePlan:
    command: PipelineCommand
    stages: tuple[StagePlan, ...]

    def to_dict(self):
        return {"schema_version": "pipeline.plan.v1", "command": self.command.to_dict(),
                "stages": [stage.to_dict() for stage in self.stages]}

    @property
    def sha256(self):
        return hashlib.sha256(json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    @property
    def executable(self):
        return all(stage.action != "blocked" for stage in self.stages)
