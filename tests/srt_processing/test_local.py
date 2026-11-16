from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pytest

from srt_processing.infrastructure.local import (
    LocalSubtitleArtifactStore, SystemClock, json_bytes,
)


def test_json_bytes_are_stable_utf8_lf_and_have_a_terminal_newline() -> None:
    value = {"z": "中文", "a": {"second": 2, "first": 1}, "escaped": "a\nb"}
    data = json_bytes(value)
    assert data == json_bytes(dict(reversed(list(value.items()))))
    assert data == (
        '{\n  "a": {\n    "first": 1,\n    "second": 2\n  },\n'
        '  "escaped": "a\\nb",\n  "z": "中文"\n}\n'
    ).encode("utf-8")
    assert b"\r" not in data and not data.startswith(b"\xef\xbb\xbf")
    assert json.loads(data.decode("utf-8")) == value


@pytest.mark.parametrize("value", [[], None, {"bad": float("nan")}, {"bad": float("inf")}, {"bad": object()}])
def test_json_bytes_reject_non_objects_non_finite_numbers_and_non_json_values(value) -> None:
    with pytest.raises((ValueError, TypeError)):
        json_bytes(value)




























def test_system_clock_returns_explicit_utc_iso_timestamp(monkeypatch) -> None:
    import srt_processing.infrastructure.local as module

    class FixedDatetime:
        @classmethod
        def now(cls, tz):
            assert tz is timezone.utc
            return datetime(2026, 10, 21, 3, 4, 5, 123456, tzinfo=tz)

    monkeypatch.setattr(module, "datetime", FixedDatetime)
    assert SystemClock().now_utc() == "2026-10-21T03:04:05.123456Z"
