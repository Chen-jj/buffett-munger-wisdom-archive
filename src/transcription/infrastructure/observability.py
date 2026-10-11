"""JSON stream adapters for transcription observability artifacts."""

from __future__ import annotations

import json
from typing import TextIO

from transcription.application import TranscriptionEvent, TranscriptionReport


class JsonLinesEventSink:
    """Write every event severity as one parseable JSON line."""

    def __init__(self, stream: TextIO) -> None:
        self._stream = stream

    def emit(self, event: TranscriptionEvent) -> None:
        self._stream.write(
            json.dumps(event.to_dict(), ensure_ascii=False, allow_nan=False) + "\n"
        )

    def flush(self) -> None:
        self._stream.flush()


class JsonReportWriter:
    """Replace a seekable text stream with one parseable report document."""

    def __init__(self, stream: TextIO) -> None:
        self._stream = stream

    def write(self, report: TranscriptionReport) -> None:
        self._stream.seek(0)
        self._stream.truncate(0)
        json.dump(
            report.to_dict(),
            self._stream,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
        )
        self._stream.write("\n")
        self._stream.flush()
