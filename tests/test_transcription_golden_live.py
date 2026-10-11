from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts.run_transcription_golden import main


@pytest.mark.live
def test_real_whisperx_transcription_golden() -> None:
    if os.environ.get("RUN_TRANSCRIPTION_GOLDEN") != "1":
        pytest.skip("set RUN_TRANSCRIPTION_GOLDEN=1 for the real WhisperX golden run")
    plan = os.environ.get("TRANSCRIPTION_GOLDEN_PLAN")
    record_dir = os.environ.get("TRANSCRIPTION_GOLDEN_RECORD_DIR")
    if not plan or not record_dir:
        pytest.fail(
            "set TRANSCRIPTION_GOLDEN_PLAN and TRANSCRIPTION_GOLDEN_RECORD_DIR"
        )

    assert main(
        [
            "--plan",
            str(Path(plan).expanduser()),
            "--record-dir",
            str(Path(record_dir).expanduser()),
        ]
    ) == 0
