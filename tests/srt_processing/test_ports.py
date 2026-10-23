from __future__ import annotations

from dataclasses import replace

import pytest

from srt_processing.application.ports import MediaProbeResult, SrtCue


def test_probe_result_preserves_unreduced_frame_rate() -> None:
    result = MediaProbeResult(1234, 48000, 2000, "probe version 1")
    assert (result.fps_numerator, result.fps_denominator) == (48000, 2000)


@pytest.mark.parametrize("field,value", [
    ("video_duration_ms", 0), ("video_duration_ms", True),
    ("fps_numerator", 0), ("fps_numerator", -1),
    ("fps_denominator", 0), ("fps_denominator", True),
    ("tool_version", ""), ("tool_version", None),
])
def test_probe_result_rejects_invalid_evidence(field, value) -> None:
    with pytest.raises(ValueError):
        replace(MediaProbeResult(1234, 24, 1, "probe version 1"), **{field: value})


def test_srt_cue_retains_bilingual_text_and_long_times() -> None:
    cue = SrtCue(1, 360000000, 360001000, "我们同意。\nWe agree.")
    assert cue.text == "我们同意。\nWe agree."
    assert cue.start_ms == 360000000


@pytest.mark.parametrize("field,value", [
    ("index", 0), ("index", True), ("start_ms", -1),
    ("start_ms", False), ("end_ms", 0), ("end_ms", True),
    ("text", " "), ("text", None),
])
def test_srt_cue_rejects_invalid_values(field, value) -> None:
    with pytest.raises(ValueError):
        replace(SrtCue(1, 0, 1000, "text"), **{field: value})
