from io import StringIO
import json

import pytest

from transcription.application import (
    EventCode,
    EventSeverity,
    QaResult,
    ReportStatus,
    TranscriptionEvent,
    TranscriptionObservability,
    TranscriptionReport,
    TranscriptionReportAggregator,
    flush_observability_on_failure,
)
from transcription.infrastructure import JsonLinesEventSink, JsonReportWriter
from transcription.interfaces import DefaultTranscriptionPresenter


ASSET_ID = "cnbc:1994:morning"
STAGE = "alignment"


def _event(
    severity: EventSeverity,
    code: EventCode,
    *,
    action: str = "record",
    reason: str = "test fixture",
) -> TranscriptionEvent:
    return TranscriptionEvent(
        asset_id=ASSET_ID,
        stage=STAGE,
        code=code,
        severity=severity,
        action=action,
        reason=reason,
        related_ids={"word_id": "aw1"},
        source_text="recognized",
        result_text="Recognized",
        start_ms=100,
        end_ms=250,
        details={"match_type": "normalized_exact"},
    )


class MemoryEventSink:
    def __init__(self) -> None:
        self.events: list[TranscriptionEvent] = []
        self.flushed = False

    def emit(self, event: TranscriptionEvent) -> None:
        self.events.append(event)

    def flush(self) -> None:
        self.flushed = True


class MemoryReportWriter:
    def __init__(self) -> None:
        self.reports: list[TranscriptionReport] = []

    def write(self, report: TranscriptionReport) -> None:
        self.reports.append(report)
















def test_json_lines_sink_writes_every_severity_without_filtering() -> None:
    stream = StringIO()
    sink = JsonLinesEventSink(stream)
    events = (
        _event(EventSeverity.DEBUG, EventCode.ALIGNMENT_WORD_ALIGNED),
        _event(EventSeverity.INFO, EventCode.FUSION_SURFACE_ADJUSTED),
        _event(EventSeverity.WARNING, EventCode.ALIGNMENT_WORD_INTERPOLATED),
        _event(EventSeverity.ERROR, EventCode.ALIGNMENT_WORD_UNRECOVERABLE),
    )

    for event in events:
        sink.emit(event)
    sink.flush()

    records = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert [record["severity"] for record in records] == [
        "DEBUG",
        "INFO",
        "WARNING",
        "ERROR",
    ]
    assert [record["code"] for record in records] == [
        event.code.value for event in events
    ]












def test_json_report_writer_replaces_previous_document() -> None:
    stream = StringIO("not valid json")
    writer = JsonReportWriter(stream)
    report = TranscriptionReportAggregator(ASSET_ID)
    report.mark_succeeded()

    writer.write(report.snapshot())

    data = json.loads(stream.getvalue())
    assert data["status"] == "succeeded"
    assert data["counts"] == {
        "aligned": 0,
        "interpolated": 0,
        "conflict": 0,
        "warning": 0,
        "error": 0,
    }
