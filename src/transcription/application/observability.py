"""Structured transcription events, reporting, and failure-safe flushing."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
import math
import re
from typing import Any, Iterator, Mapping, Protocol


REPORT_SCHEMA_VERSION = "transcription.report.v1"

_COUNTER_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_SENSITIVE_KEY_PARTS = (
    "apikey",
    "authorization",
    "credential",
    "password",
    "secret",
    "token",
)
_BASE_COUNTS = ("aligned", "interpolated", "conflict", "warning", "error")


def _require_non_empty_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _require_millisecond(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def _contains_sensitive_key(key: str) -> bool:
    normalized = "".join(character for character in key.lower() if character.isalnum())
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


class EventSeverity(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class EventCode(str, Enum):
    STAGE_STARTED = "stage.started"
    STAGE_COMPLETED = "stage.completed"
    STAGE_FAILED = "stage.failed"
    INPUT_VIDEO_VALIDATED = "input.video_validated"
    INPUT_VIDEO_REJECTED = "input.video_rejected"
    AUDIO_EXTRACTED = "audio.extracted"
    AUDIO_CACHE_HIT = "audio.cache_hit"
    VAD_COMPLETED = "vad.completed"
    VAD_CACHE_HIT = "vad.cache_hit"
    ASR_COMPLETED = "asr.completed"
    ASR_CACHE_HIT = "asr.cache_hit"
    ALIGNMENT_COMPLETED = "alignment.completed"
    ALIGNMENT_CACHE_HIT = "alignment.cache_hit"
    ALIGNMENT_WORD_ALIGNED = "alignment.word_aligned"
    ALIGNMENT_WORD_UNALIGNED = "alignment.word_unaligned"
    ALIGNMENT_WORD_INTERPOLATED = "alignment.word_interpolated"
    ALIGNMENT_WORD_UNRECOVERABLE = "alignment.word_unrecoverable"
    ALIGNMENT_WORD_OVERLAP = "alignment.word_overlap"
    FUSION_SURFACE_ADJUSTED = "fusion.surface_adjusted"
    FUSION_EXACT_MATCHED = "fusion.exact_matched"
    FUSION_TEXT_REPLACED = "fusion.text_replaced"
    FUSION_ONE_TO_MANY_COLLAPSED = "fusion.one_to_many_collapsed"
    FUSION_MANY_TO_ONE_COLLAPSED = "fusion.many_to_one_collapsed"
    FUSION_ASR_ONLY_RETAINED = "fusion.asr_only_retained"
    FUSION_OFFICIAL_ONLY_RECOVERED = "fusion.official_only_recovered"
    FUSION_OFFICIAL_ONLY_EXCLUDED = "fusion.official_only_excluded"
    FUSION_REGION_UNMATCHED = "fusion.region_unmatched"
    FUSION_COMPLETED = "fusion.completed"
    FUSION_CACHE_HIT = "fusion.cache_hit"
    FUSION_NO_OFFICIAL = "fusion.no_official"
    BOUNDARY_OFFICIAL_APPLIED = "boundary.official_applied"
    BOUNDARY_SPEAKER_CHANGE = "boundary.speaker_change"
    BOUNDARY_ASR_APPLIED = "boundary.asr_applied"
    BOUNDARY_PAUSE_INFERRED = "boundary.pause_inferred"
    BOUNDARY_FALLBACK_USED = "boundary.fallback_used"
    BOUNDARY_COMPLETED = "boundary.completed"
    BOUNDARY_CACHE_HIT = "boundary.cache_hit"


class ReportStatus(str, Enum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class TranscriptionEvent:
    asset_id: str
    stage: str
    code: EventCode
    severity: EventSeverity
    action: str
    reason: str
    related_ids: Mapping[str, str] = field(default_factory=dict)
    source_text: str | None = None
    result_text: str | None = None
    start_ms: int | None = None
    end_ms: int | None = None
    details: Mapping[str, str | int | float | bool | None] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        _require_non_empty_string(self.asset_id, "asset_id")
        _require_non_empty_string(self.stage, "stage")
        if not isinstance(self.code, EventCode):
            raise ValueError("code must be a stable EventCode")
        if not isinstance(self.severity, EventSeverity):
            raise ValueError("severity must be an EventSeverity")
        _require_non_empty_string(self.action, "action")
        _require_non_empty_string(self.reason, "reason")
        self._validate_related_ids()
        self._validate_text_excerpt(self.source_text, "source_text")
        self._validate_text_excerpt(self.result_text, "result_text")
        self._validate_time_range()
        self._validate_details()
        object.__setattr__(self, "related_ids", dict(self.related_ids))
        object.__setattr__(self, "details", dict(self.details))

    def _validate_related_ids(self) -> None:
        if not isinstance(self.related_ids, Mapping):
            raise ValueError("related_ids must be a mapping")
        for key, value in self.related_ids.items():
            _require_non_empty_string(key, "related_ids key")
            _require_non_empty_string(value, "related_ids value")
            if _contains_sensitive_key(key):
                raise ValueError(f"sensitive related ID is not allowed: {key}")

    @staticmethod
    def _validate_text_excerpt(value: str | None, field_name: str) -> None:
        if value is None:
            return
        _require_non_empty_string(value, field_name)
        if len(value) > 500:
            raise ValueError(f"{field_name} must be an excerpt of at most 500 characters")

    def _validate_time_range(self) -> None:
        if (self.start_ms is None) != (self.end_ms is None):
            raise ValueError("start_ms and end_ms must be provided together")
        if self.start_ms is None or self.end_ms is None:
            return
        _require_millisecond(self.start_ms, "start_ms")
        _require_millisecond(self.end_ms, "end_ms")
        if self.end_ms <= self.start_ms:
            raise ValueError("event time range must satisfy start_ms < end_ms")

    def _validate_details(self) -> None:
        if not isinstance(self.details, Mapping):
            raise ValueError("details must be a mapping")
        for key, value in self.details.items():
            _require_non_empty_string(key, "details key")
            if _contains_sensitive_key(key):
                raise ValueError(f"sensitive detail is not allowed: {key}")
            if not isinstance(value, (str, int, float, bool)) and value is not None:
                raise ValueError("detail values must be JSON scalar values")
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("detail float values must be finite")

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "asset_id": self.asset_id,
            "stage": self.stage,
            "code": self.code.value,
            "severity": self.severity.value,
            "action": self.action,
            "reason": self.reason,
            "related_ids": dict(self.related_ids),
            "details": dict(self.details),
        }
        if self.source_text is not None:
            data["source_text"] = self.source_text
        if self.result_text is not None:
            data["result_text"] = self.result_text
        if self.start_ms is not None:
            data["start_ms"] = self.start_ms
            data["end_ms"] = self.end_ms
        return data


class TranscriptionEventSink(Protocol):
    def emit(self, event: TranscriptionEvent) -> None:
        """Consume one structured event without changing it."""

    def flush(self) -> None:
        """Persist buffered events."""


@dataclass(frozen=True)
class QaResult:
    name: str
    passed: bool
    detail: str

    def __post_init__(self) -> None:
        _require_non_empty_string(self.name, "name")
        if not isinstance(self.passed, bool):
            raise ValueError("passed must be a bool")
        _require_non_empty_string(self.detail, "detail")

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


@dataclass(frozen=True)
class TranscriptionReport:
    asset_id: str
    status: ReportStatus
    counts: Mapping[str, int]
    findings: tuple[TranscriptionEvent, ...]
    qa: tuple[QaResult, ...]
    failure_reason: str | None = None
    schema_version: str = REPORT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "schema_version": self.schema_version,
            "asset_id": self.asset_id,
            "status": self.status.value,
            "counts": dict(self.counts),
            "findings": [finding.to_dict() for finding in self.findings],
            "qa": [result.to_dict() for result in self.qa],
        }
        if self.failure_reason is not None:
            data["failure_reason"] = self.failure_reason
        return data


class TranscriptionReportAggregator:
    """Aggregate report counters and actionable findings from emitted events."""

    def __init__(self, asset_id: str) -> None:
        self._asset_id = _require_non_empty_string(asset_id, "asset_id")
        self._status = ReportStatus.RUNNING
        self._counts = {name: 0 for name in _BASE_COUNTS}
        self._findings: list[TranscriptionEvent] = []
        self._qa: list[QaResult] = []
        self._failure_reason: str | None = None

    def emit(self, event: TranscriptionEvent) -> None:
        if event.asset_id != self._asset_id:
            raise ValueError("event asset_id must match report asset_id")
        if event.severity is EventSeverity.WARNING:
            self._counts["warning"] += 1
            self._findings.append(event)
        elif event.severity is EventSeverity.ERROR:
            self._counts["error"] += 1
            self._findings.append(event)

        if event.code is EventCode.ALIGNMENT_WORD_ALIGNED:
            self._counts["aligned"] += 1
        elif event.code is EventCode.ALIGNMENT_WORD_INTERPOLATED:
            self._counts["interpolated"] += 1
        elif event.code in {
            EventCode.ALIGNMENT_WORD_UNRECOVERABLE,
            EventCode.ALIGNMENT_WORD_OVERLAP,
            EventCode.FUSION_REGION_UNMATCHED,
        }:
            self._counts["conflict"] += 1
        elif event.code is EventCode.ALIGNMENT_CACHE_HIT:
            for counter in ("aligned", "interpolated"):
                amount = event.details.get(f"{counter}_count", 0)
                if isinstance(amount, int) and not isinstance(amount, bool) and amount > 0:
                    self._counts[counter] += amount

        fusion_counter = {
            EventCode.FUSION_EXACT_MATCHED: "exact",
            EventCode.FUSION_SURFACE_ADJUSTED: "normalized_exact",
            EventCode.FUSION_TEXT_REPLACED: "substitution",
            EventCode.FUSION_ONE_TO_MANY_COLLAPSED: "one_to_many",
            EventCode.FUSION_MANY_TO_ONE_COLLAPSED: "many_to_one",
            EventCode.FUSION_ASR_ONLY_RETAINED: "asr_only",
            EventCode.FUSION_OFFICIAL_ONLY_RECOVERED: "official_only_recovered",
            EventCode.FUSION_OFFICIAL_ONLY_EXCLUDED: "official_only_excluded",
        }.get(event.code)
        if fusion_counter is not None:
            self._counts[fusion_counter] = self._counts.get(fusion_counter, 0) + 1

    def flush(self) -> None:
        """Satisfy the event sink port; aggregation is already in memory."""

    def increment(self, counter: str, amount: int = 1) -> None:
        if not isinstance(counter, str) or _COUNTER_NAME_RE.fullmatch(counter) is None:
            raise ValueError("counter must be a lowercase snake_case name")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < 1:
            raise ValueError("amount must be a positive integer")
        self._counts[counter] = self._counts.get(counter, 0) + amount

    def record_qa(self, result: QaResult) -> None:
        if not isinstance(result, QaResult):
            raise ValueError("result must be a QaResult")
        self._qa.append(result)

    def mark_succeeded(self) -> None:
        self._status = ReportStatus.SUCCEEDED
        self._failure_reason = None

    def mark_failed(self, reason: str) -> None:
        self._status = ReportStatus.FAILED
        self._failure_reason = _require_non_empty_string(reason, "reason")

    def snapshot(self) -> TranscriptionReport:
        return TranscriptionReport(
            asset_id=self._asset_id,
            status=self._status,
            counts=dict(self._counts),
            findings=tuple(self._findings),
            qa=tuple(self._qa),
            failure_reason=self._failure_reason,
        )


class TranscriptionReportWriter(Protocol):
    def write(self, report: TranscriptionReport) -> None:
        """Replace the persisted report with the supplied snapshot."""


class TranscriptionObservability:
    """Coordinate the detailed log and aggregate report without UI concerns."""

    def __init__(
        self,
        *,
        asset_id: str,
        stage: str,
        detailed_log: TranscriptionEventSink,
        report: TranscriptionReportAggregator,
        report_writer: TranscriptionReportWriter,
    ) -> None:
        self.asset_id = _require_non_empty_string(asset_id, "asset_id")
        self.stage = _require_non_empty_string(stage, "stage")
        self._detailed_log = detailed_log
        self._report = report
        self._report_writer = report_writer

    def emit(self, event: TranscriptionEvent) -> None:
        if event.asset_id != self.asset_id or event.stage != self.stage:
            raise ValueError("event asset_id and stage must match observability context")
        self._report.emit(event)
        self._detailed_log.emit(event)

    def flush(self) -> None:
        self._detailed_log.flush()
        self._report.flush()

    def finalize_success(self) -> TranscriptionReport:
        self._report.mark_succeeded()
        self._detailed_log.flush()
        snapshot = self._report.snapshot()
        self._report_writer.write(snapshot)
        return snapshot

    def flush_failure(self, error: Exception) -> None:
        """Best-effort failure persistence that is guaranteed not to raise."""

        reason = str(error).strip() or error.__class__.__name__
        failure_event = TranscriptionEvent(
            asset_id=self.asset_id,
            stage=self.stage,
            code=EventCode.STAGE_FAILED,
            severity=EventSeverity.ERROR,
            action="abort_stage",
            reason=reason,
            details={"error_type": error.__class__.__name__},
        )
        operations = (
            lambda: self._report.emit(failure_event),
            lambda: self._detailed_log.emit(failure_event),
            lambda: self._report.mark_failed(reason),
            self._detailed_log.flush,
            lambda: self._report_writer.write(self._report.snapshot()),
        )
        for operation in operations:
            try:
                operation()
            except Exception:
                continue


@contextmanager
def flush_observability_on_failure(
    observability: TranscriptionObservability,
) -> Iterator[None]:
    """Flush diagnostics and then re-raise the original business exception."""

    try:
        yield
    except Exception as error:
        observability.flush_failure(error)
        raise
