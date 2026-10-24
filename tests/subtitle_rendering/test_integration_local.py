"""Explicit local real-tool integration, not a network live test."""

import json
import os
from pathlib import Path
import uuid

import pytest

from tests.subtitle_rendering.sample_runner import DEFAULT_OUTPUT_ROOT, run_local_sample


def test_real_cnbc_rendering_persists_full_sample_and_reuses_without_writes():
    if os.environ.get("RUN_SUBTITLE_RENDERING_INTEGRATION") != "1":
        pytest.skip("set RUN_SUBTITLE_RENDERING_INTEGRATION=1 for real local rendering")
    # Missing prerequisites after explicit opt-in are an assertion failure, never a skip.
    result = run_local_sample()
    evidence_root = Path(DEFAULT_OUTPUT_ROOT).parents[2] / "subtitle-rendering-integration"
    evidence_root.mkdir(exist_ok=True)
    evidence_path = evidence_root / ("pytest-" + uuid.uuid4().hex + ".json")
    with evidence_path.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")
    assert result["status"] == "passed", result
    assert result["source_counts"] == {"sections": 2, "sentences": 97, "words": 1564, "cues": 163, "duration_ms": 623000}
    assert result["second_status"] == result["independent_process_reuse"]["first_status"] == "reused"
    assert result["qa"]["summary"]["cue_count"] == 163
    assert result["qa"]["output_media"]["video"]["duration_us"] == 623000000
    assert result["upstream_unchanged"] and result["byte_identical_reuse"]
    assert Path(result["outputs"]["video"]["path"]).is_file()
    assert not result["human_playback_confirmed"]
