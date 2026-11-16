"""Stable command boundary for the translation workflow."""

from __future__ import annotations

from dataclasses import dataclass

from translation.application import TranslationWorkflow, TranslationWorkflowError


@dataclass(frozen=True)
class TranslationCommand:
    asset_id: str
    transcription_manifest_path: str
    source_chunking_manifest_path: str
    glossary_path: str | None = None
    overwrite: bool = False
    max_attempts: int = 3


@dataclass(frozen=True)
class TranslationOutcome:
    status: str
    result_path: str | None
    manifest_path: str | None
    request_count: int
    checkpoint_reuse_count: int
    attempt_count: int
    result_sha256: str | None
    error_category: str | None = None
    error_message: str | None = None


class TranslationCommandHandler:
    def __init__(self, workflow: TranslationWorkflow) -> None:
        self.workflow = workflow

    def verify(self, command: TranslationCommand) -> TranslationOutcome:
        return self._handle(command, verify=True)

    def handle(self, command: TranslationCommand) -> TranslationOutcome:
        return self._handle(command, verify=False)

    def _handle(self, command: TranslationCommand, *, verify) -> TranslationOutcome:
        if not isinstance(command, TranslationCommand):
            raise ValueError("command must be a TranslationCommand")
        try:
            result = (self.workflow.verify if verify else self.workflow.execute)(
                asset_id=command.asset_id,
                transcription_manifest_path=command.transcription_manifest_path,
                source_chunking_manifest_path=command.source_chunking_manifest_path,
                glossary_path=command.glossary_path,
                overwrite=command.overwrite,
                max_attempts=command.max_attempts,
            )
        except TranslationWorkflowError as error:
            return TranslationOutcome(
                status="failed",
                result_path=None,
                manifest_path=None,
                request_count=0,
                checkpoint_reuse_count=0,
                attempt_count=0,
                result_sha256=None,
                error_category=error.category,
                error_message=str(error),
            )
        return TranslationOutcome(
            status=result.status,
            result_path=result.result_path,
            manifest_path=result.manifest_path,
            request_count=result.request_count,
            checkpoint_reuse_count=result.checkpoint_reuse_count,
            attempt_count=result.attempt_count,
            result_sha256=result.result_sha256,
        )


@dataclass(frozen=True)
class BilingualPostprocessingCommand:
    asset_id: str
    transcription_manifest_path: str
    source_chunking_manifest_path: str
    translation_manifest_path: str
    glossary_path: str | None = None
    overwrite: bool = False


@dataclass(frozen=True)
class BilingualPostprocessingOutcome:
    status: str
    draft_path: str | None = None
    report_path: str | None = None
    manifest_path: str | None = None
    cue_count: int = 0
    warning_count: int = 0
    provider_calls: int = 0
    checkpoint_reuse_count: int = 0
    error_category: str | None = None
    error_message: str | None = None


class BilingualPostprocessingCommandHandler:
    def __init__(self, workflow):
        self.workflow = workflow

    def verify(self, command):
        return self._handle(command, verify=True)

    def handle(self, command):
        return self._handle(command, verify=False)

    def _handle(self, command, *, verify):
        if not isinstance(command, BilingualPostprocessingCommand):
            raise ValueError("command must be BilingualPostprocessingCommand")
        try:
            result = (self.workflow.verify if verify else self.workflow.execute)(**command.__dict__)
            return BilingualPostprocessingOutcome(**result.__dict__)
        except TranslationWorkflowError as error:
            return BilingualPostprocessingOutcome("failed", error_category=error.category,
                error_message=str(error))
