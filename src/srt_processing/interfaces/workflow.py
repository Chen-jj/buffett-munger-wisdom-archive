"""Thin, safe command boundary for local subtitle processing."""

from __future__ import annotations

from dataclasses import dataclass

from srt_processing.application import (
    SrtProcessingWorkflow,
    SrtProcessingWorkflowError,
    SubtitleInputError,
)


_ERROR_MESSAGES = {
    "input_invalid": "Subtitle inputs are missing or invalid.",
    "media_invalid": "The canonical video could not be validated.",
    "artifact_conflict": "Existing subtitle artifacts cannot be reused; explicit overwrite is required.",
    "planning_failed": "No valid subtitle plan could be produced.",
    "projection_failed": "Subtitle projections could not preserve the plan.",
    "publication_failed": "Subtitle artifacts could not be published.",
    "srt_processing_failed": "Subtitle processing did not complete.",
}


@dataclass(frozen=True)
class SrtProcessingCommand:
    asset_id: str
    transcription_manifest_path: str
    translation_manifest_path: str
    overwrite: bool = False


@dataclass(frozen=True)
class SrtProcessingOutcome:
    status: str
    plan_path: str | None
    manifest_path: str | None
    report_path: str | None
    english_srt_path: str | None
    chinese_srt_path: str | None
    bilingual_srt_path: str | None
    cue_count: int
    warning_count: int
    error_category: str | None = None
    error_message: str | None = None


class SrtProcessingCommandHandler:
    def __init__(self, workflow: SrtProcessingWorkflow) -> None:
        self.workflow = workflow

    def handle(self, command: SrtProcessingCommand) -> SrtProcessingOutcome:
        if not isinstance(command, SrtProcessingCommand):
            raise ValueError("command must be a SrtProcessingCommand")
        try:
            result = self.workflow.execute(
                asset_id=command.asset_id,
                transcription_manifest_path=command.transcription_manifest_path,
                translation_manifest_path=command.translation_manifest_path,
                overwrite=command.overwrite,
            )
        except (SubtitleInputError, SrtProcessingWorkflowError) as error:
            category = error.category if error.category in _ERROR_MESSAGES else "srt_processing_failed"
            return SrtProcessingOutcome(
                "failed", None, None, None, None, None, None, 0, 0,
                category, _ERROR_MESSAGES[category],
            )
        return SrtProcessingOutcome(
            status=result.status, plan_path=result.plan_path, manifest_path=result.manifest_path,
            report_path=result.report_path, english_srt_path=result.english_srt_path,
            chinese_srt_path=result.chinese_srt_path, bilingual_srt_path=result.bilingual_srt_path,
            cue_count=result.cue_count, warning_count=result.warning_count,
        )
