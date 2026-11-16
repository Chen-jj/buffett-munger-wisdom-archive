"""Opt-in real production acquisition-to-rendering acceptance."""

import os
from pathlib import Path

import pytest

from tests.orchestration.integration.gates import enabled
from tests.orchestration.integration.runners.full_fresh import (
    DEFAULT_MODEL_BUNDLE, DEFAULT_OUTPUT_ROOT, execute_full_fresh,
)


@pytest.mark.live
def test_cnbc_full_fresh_production_pipeline_and_independent_reuse():
    if not enabled("full_fresh"):
        pytest.skip("enable the explicit full_fresh orchestration integration scenario")
    root = Path(os.environ.get("ORCHESTRATION_INTEGRATION_OUTPUT_ROOT", DEFAULT_OUTPUT_ROOT))
    model = Path(os.environ.get("ORCHESTRATION_STANZA_MODEL_BUNDLE", DEFAULT_MODEL_BUNDLE))
    evidence = execute_full_fresh(root, model)
    assert evidence["verify_unchanged"]
    assert Path(evidence["sample"]["path"]).name == "video_中文字幕.mp4"
