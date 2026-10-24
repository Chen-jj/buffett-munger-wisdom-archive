"""Thin command boundary with stable, non-sensitive error messages."""

from dataclasses import dataclass

from subtitle_rendering.application.workflow import SubtitleRenderingWorkflow, SubtitleRenderingWorkflowError


_ERROR_MESSAGES = {
    "input_invalid": "Rendering inputs are missing or invalid.",
    "artifact_conflict": "Existing rendering artifacts cannot be reused; explicit overwrite is required.",
    "font_invalid": "The exact rendering font could not be validated.",
    "layout_failed": "The fixed subtitle layout could not be validated.",
    "ass_generation_failed": "ASS subtitles could not preserve the authoritative plan.",
    "tool_unavailable": "The required rendering toolchain is unavailable.",
    "render_failed": "Video rendering did not complete.",
    "render_validation_failed": "The rendered video could not be validated.",
    "publication_failed": "Rendering artifacts could not be published.",
    "subtitle_rendering_failed": "Subtitle rendering did not complete.",
}


@dataclass(frozen=True)
class SubtitleRenderingCommand:
    asset_id: str
    srt_processing_manifest_path: str
    dry_run: bool = False
    overwrite: bool = False


@dataclass(frozen=True)
class SubtitleRenderingOutcome:
    status: str
    action: str | None
    plan_path: str | None
    ass_path: str | None
    video_path: str | None
    report_path: str | None
    manifest_path: str | None
    cue_count: int
    warning_count: int
    command: tuple[str, ...] | None
    error_category: str | None = None
    error_message: str | None = None


class SubtitleRenderingCommandHandler:
    def __init__(self, workflow: SubtitleRenderingWorkflow) -> None:
        self.workflow = workflow

    def handle(self, command: SubtitleRenderingCommand) -> SubtitleRenderingOutcome:
        if not isinstance(command, SubtitleRenderingCommand):
            raise ValueError("command must be a SubtitleRenderingCommand")
        try:
            result = self.workflow.execute(asset_id=command.asset_id,
                                           srt_processing_manifest_path=command.srt_processing_manifest_path,
                                           dry_run=command.dry_run, overwrite=command.overwrite)
        except SubtitleRenderingWorkflowError as error:
            category = error.category if error.category in _ERROR_MESSAGES else "subtitle_rendering_failed"
            return SubtitleRenderingOutcome("failed", None, None, None, None, error.report_path, None,
                                             0, 0, None, category, _ERROR_MESSAGES[category])
        return SubtitleRenderingOutcome(**result.__dict__)
