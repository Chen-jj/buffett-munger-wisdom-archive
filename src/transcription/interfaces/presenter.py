"""Human-facing filtering and formatting for transcription events."""

from __future__ import annotations

from transcription.application import (
    EventSeverity,
    TranscriptionEvent,
    TranscriptionReport,
)


class DefaultTranscriptionPresenter:
    """Show actionable events and a compact summary without business rules."""

    _VISIBLE_SEVERITIES = frozenset({EventSeverity.WARNING, EventSeverity.ERROR})

    def render_event(self, event: TranscriptionEvent) -> str | None:
        if event.severity not in self._VISIBLE_SEVERITIES:
            return None
        return (
            f"[{event.severity.value}] {event.stage} {event.code.value}: "
            f"{event.action} ({event.reason})"
        )

    def render_stage_summary(self, report: TranscriptionReport) -> str:
        counts = report.counts
        summary = [
            f"[{report.status.value}]",
            f"aligned={counts.get('aligned', 0)}",
            f"interpolated={counts.get('interpolated', 0)}",
            f"conflict={counts.get('conflict', 0)}",
        ]
        for counter in (
            "exact",
            "normalized_exact",
            "substitution",
            "one_to_many",
            "many_to_one",
            "asr_only",
            "official_only_recovered",
            "official_only_excluded",
        ):
            if counter in counts:
                summary.append(f"{counter}={counts[counter]}")
        summary.extend(
            (
                f"warning={counts.get('warning', 0)}",
                f"error={counts.get('error', 0)}",
            )
        )
        return " ".join(summary)
