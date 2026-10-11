"""Stable orchestration/CLI boundary for the transcription workflow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from archive_core.domain import AssetId
from transcription.application import (
    EventSeverity,
    TranscriptionEvent,
    TranscriptionWorkflow,
    TranscriptionWorkflowInput,
)


@dataclass(frozen=True)
class TranscriptionCommand:
    asset_id: AssetId
    download_manifest_path: str
    chapters_sha256: str | None = None
    overwrite: bool = False


@dataclass(frozen=True)
class TranscriptionResult:
    source_alignment_path: str
    manifest_path: str
    log_path: str
    report_path: str
    cache_hits: tuple[str, ...]
    findings: tuple[TranscriptionEvent, ...]
    summary: Mapping[str, int]


class TranscriptionCommandHandler:
    """Translate a provider-neutral command into one application workflow run."""

    def __init__(self, workflow: TranscriptionWorkflow) -> None:
        self.workflow = workflow

    def execute(self, command: TranscriptionCommand) -> TranscriptionResult:
        outcome = self.workflow.execute(
            TranscriptionWorkflowInput(
                asset_id=command.asset_id,
                download_manifest_path=command.download_manifest_path,
                chapters_sha256=command.chapters_sha256,
                overwrite=command.overwrite,
            )
        )
        findings = tuple(
            event
            for event in outcome.report.findings
            if event.severity in {EventSeverity.WARNING, EventSeverity.ERROR}
        )
        return TranscriptionResult(
            source_alignment_path=outcome.source_alignment_path,
            manifest_path=outcome.manifest_path,
            log_path=outcome.log_path,
            report_path=outcome.report_path,
            cache_hits=outcome.cache_hits,
            findings=findings,
            summary=dict(outcome.report.counts),
        )
