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


def test_event_serialization_contains_required_observability_fields() -> None:
    event = _event(EventSeverity.INFO, EventCode.FUSION_SURFACE_ADJUSTED)

    assert event.to_dict() == {
        "asset_id": ASSET_ID,
        "stage": STAGE,
        "code": "fusion.surface_adjusted",
        "severity": "INFO",
        "action": "record",
        "reason": "test fixture",
        "related_ids": {"word_id": "aw1"},
        "details": {"match_type": "normalized_exact"},
        "source_text": "recognized",
        "result_text": "Recognized",
        "start_ms": 100,
        "end_ms": 250,
    }


def test_document_section_event_codes_are_stable() -> None:
    assert {
        code.value
        for code in (
            EventCode.SECTION_DIRECT_ASSIGNED,
            EventCode.SECTION_ASR_ONLY_ASSIGNED_TO_FIRST,
            EventCode.SECTION_ASR_ONLY_ASSIGNED_TO_PREVIOUS,
            EventCode.SECTION_DOCUMENT_CHANGE_BOUNDARY,
            EventCode.SECTION_CHAPTER_UNMAPPED,
            EventCode.SECTION_NON_MONOTONIC,
            EventCode.SECTION_SENTENCE_CROSSES_SECTIONS,
            EventCode.SECTION_PUBLICATION_SKIPPED,
            EventCode.SECTION_PUBLISHED,
        )
    } == {
        "section.direct_assigned",
        "section.asr_only_assigned_to_first",
        "section.asr_only_assigned_to_previous",
        "section.document_change_boundary",
        "section.chapter_unmapped",
        "section.non_monotonic",
        "section.sentence_crosses_sections",
        "section.publication_skipped",
        "section.published",
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {"asset_id": ""},
        {"stage": ""},
        {"code": "alignment.word_aligned"},
        {"severity": "INFO"},
        {"action": ""},
        {"reason": ""},
    ],
)
def test_event_rejects_missing_or_untyped_required_fields(
    overrides: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "asset_id": ASSET_ID,
        "stage": STAGE,
        "code": EventCode.ALIGNMENT_WORD_ALIGNED,
        "severity": EventSeverity.INFO,
        "action": "keep_word",
        "reason": "alignment succeeded",
    }
    values.update(overrides)

    with pytest.raises(ValueError):
        TranscriptionEvent(**values)  # type: ignore[arg-type]


def test_event_constructor_requires_event_code_argument() -> None:
    with pytest.raises(TypeError):
        TranscriptionEvent(  # type: ignore[call-arg]
            asset_id=ASSET_ID,
            stage=STAGE,
            severity=EventSeverity.INFO,
            action="keep_word",
            reason="alignment succeeded",
        )


@pytest.mark.parametrize(
    "details",
    [
        {"api_key": "secret"},
        {"apiKey": "secret"},
        {"authorization-header": "Bearer secret"},
        {"access_token": "secret"},
        {"database_password": "secret"},
        {"client_secret": "secret"},
        {"provider_credentials": "secret"},
    ],
)
def test_event_rejects_sensitive_configuration(details: dict[str, str]) -> None:
    with pytest.raises(ValueError, match="sensitive detail"):
        TranscriptionEvent(
            asset_id=ASSET_ID,
            stage=STAGE,
            code=EventCode.STAGE_STARTED,
            severity=EventSeverity.INFO,
            action="start",
            reason="requested",
            details=details,
        )


def test_event_rejects_sensitive_values_disguised_as_related_ids() -> None:
    with pytest.raises(ValueError, match="sensitive related ID"):
        TranscriptionEvent(
            asset_id=ASSET_ID,
            stage=STAGE,
            code=EventCode.STAGE_STARTED,
            severity=EventSeverity.INFO,
            action="start",
            reason="requested",
            related_ids={"access-token": "secret"},
        )


@pytest.mark.parametrize(
    ("start_ms", "end_ms"),
    [(0, None), (None, 1), (-1, 1), (0, 0), (2, 1), (False, 1)],
)
def test_event_rejects_invalid_optional_original_timeline_range(
    start_ms: object, end_ms: object
) -> None:
    with pytest.raises(ValueError):
        TranscriptionEvent(
            asset_id=ASSET_ID,
            stage=STAGE,
            code=EventCode.ALIGNMENT_WORD_UNALIGNED,
            severity=EventSeverity.WARNING,
            action="inspect",
            reason="missing acoustic anchor",
            start_ms=start_ms,  # type: ignore[arg-type]
            end_ms=end_ms,  # type: ignore[arg-type]
        )


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


def test_report_aggregates_counts_findings_qa_and_success_status() -> None:
    report = TranscriptionReportAggregator(ASSET_ID)
    report.emit(_event(EventSeverity.DEBUG, EventCode.ALIGNMENT_WORD_ALIGNED))
    report.emit(_event(EventSeverity.INFO, EventCode.ALIGNMENT_WORD_ALIGNED))
    report.emit(
        _event(EventSeverity.WARNING, EventCode.ALIGNMENT_WORD_INTERPOLATED)
    )
    report.emit(_event(EventSeverity.ERROR, EventCode.FUSION_REGION_UNMATCHED))
    report.increment("asr_only", 2)
    report.record_qa(
        QaResult(name="timeline_monotonic", passed=True, detail="all words ordered")
    )
    report.mark_succeeded()

    snapshot = report.snapshot()
    data = snapshot.to_dict()

    assert snapshot.status is ReportStatus.SUCCEEDED
    assert data["schema_version"] == "transcription.report.v1"
    assert data["counts"] == {
        "aligned": 2,
        "interpolated": 1,
        "conflict": 1,
        "warning": 1,
        "error": 1,
        "asr_only": 2,
    }
    assert [finding["severity"] for finding in data["findings"]] == [
        "WARNING",
        "ERROR",
    ]
    assert data["qa"] == [
        {
            "name": "timeline_monotonic",
            "passed": True,
            "detail": "all words ordered",
        }
    ]


def test_default_presenter_hides_debug_info_but_shows_findings_and_summary() -> None:
    presenter = DefaultTranscriptionPresenter()
    report = TranscriptionReportAggregator(ASSET_ID)
    warning = _event(
        EventSeverity.WARNING,
        EventCode.ALIGNMENT_WORD_INTERPOLATED,
        action="interpolate",
        reason="two acoustic anchors",
    )
    error = _event(
        EventSeverity.ERROR,
        EventCode.ALIGNMENT_WORD_UNRECOVERABLE,
        action="abort",
        reason="missing right anchor",
    )
    for event in (
        _event(EventSeverity.DEBUG, EventCode.ALIGNMENT_WORD_ALIGNED),
        _event(EventSeverity.INFO, EventCode.FUSION_SURFACE_ADJUSTED),
        warning,
        error,
    ):
        report.emit(event)

    assert (
        presenter.render_event(
            _event(EventSeverity.DEBUG, EventCode.ALIGNMENT_WORD_ALIGNED)
        )
        is None
    )
    assert (
        presenter.render_event(
            _event(EventSeverity.INFO, EventCode.FUSION_SURFACE_ADJUSTED)
        )
        is None
    )
    assert presenter.render_event(warning) == (
        "[WARNING] alignment alignment.word_interpolated: "
        "interpolate (two acoustic anchors)"
    )
    assert presenter.render_event(error) == (
        "[ERROR] alignment alignment.word_unrecoverable: "
        "abort (missing right anchor)"
    )
    assert presenter.render_stage_summary(report.snapshot()) == (
        "[running] aligned=1 interpolated=1 conflict=1 normalized_exact=1 "
        "warning=1 error=1"
    )


def test_observability_success_flushes_log_and_replaces_parseable_report() -> None:
    log_sink = MemoryEventSink()
    report_writer = MemoryReportWriter()
    report = TranscriptionReportAggregator(ASSET_ID)
    observability = TranscriptionObservability(
        asset_id=ASSET_ID,
        stage=STAGE,
        detailed_log=log_sink,
        report=report,
        report_writer=report_writer,
    )

    observability.emit(
        _event(EventSeverity.WARNING, EventCode.ALIGNMENT_WORD_INTERPOLATED)
    )
    snapshot = observability.finalize_success()

    assert log_sink.flushed is True
    assert snapshot.status is ReportStatus.SUCCEEDED
    assert report_writer.reports == [snapshot]


def test_failure_path_flushes_log_and_writes_parseable_failed_report() -> None:
    log_stream = StringIO()
    report_stream = StringIO()
    report = TranscriptionReportAggregator(ASSET_ID)
    observability = TranscriptionObservability(
        asset_id=ASSET_ID,
        stage=STAGE,
        detailed_log=JsonLinesEventSink(log_stream),
        report=report,
        report_writer=JsonReportWriter(report_stream),
    )

    class BusinessFailure(RuntimeError):
        pass

    with pytest.raises(BusinessFailure, match="alignment provider failed"):
        with flush_observability_on_failure(observability):
            raise BusinessFailure("alignment provider failed")

    logged = [json.loads(line) for line in log_stream.getvalue().splitlines()]
    persisted_report = json.loads(report_stream.getvalue())
    assert logged[-1]["code"] == "stage.failed"
    assert logged[-1]["severity"] == "ERROR"
    assert persisted_report["status"] == "failed"
    assert persisted_report["failure_reason"] == "alignment provider failed"
    assert persisted_report["counts"]["error"] == 1
    assert persisted_report["findings"][-1]["code"] == "stage.failed"


def test_flush_failures_do_not_mask_original_business_exception() -> None:
    class BrokenSink:
        def emit(self, event: TranscriptionEvent) -> None:
            raise OSError("log unavailable")

        def flush(self) -> None:
            raise OSError("log flush unavailable")

    class BrokenWriter:
        def write(self, report: TranscriptionReport) -> None:
            raise OSError("report unavailable")

    report = TranscriptionReportAggregator(ASSET_ID)
    observability = TranscriptionObservability(
        asset_id=ASSET_ID,
        stage=STAGE,
        detailed_log=BrokenSink(),
        report=report,
        report_writer=BrokenWriter(),
    )

    original = RuntimeError("original business failure")
    with pytest.raises(RuntimeError) as caught:
        with flush_observability_on_failure(observability):
            raise original

    assert caught.value is original
    snapshot = report.snapshot()
    assert snapshot.status is ReportStatus.FAILED
    assert snapshot.counts["error"] == 1
    assert snapshot.findings[-1].code is EventCode.STAGE_FAILED


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
