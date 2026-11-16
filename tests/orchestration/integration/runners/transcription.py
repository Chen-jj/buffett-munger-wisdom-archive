"""Real ASR-only stage scenario using production acquisition, download and derivation."""

from pathlib import Path

from orchestration.interfaces import build_pipeline_handler
from tests.orchestration.integration.gates import enabled
from tests.orchestration.integration.runners.full_fresh import command, DEFAULT_MODEL_BUNDLE, snapshot


def run_transcription_scenario(output_root):
    if not enabled("asr"):
        raise RuntimeError("explicit orchestration asr scenario is closed")
    if Path(output_root).exists():
        raise ValueError("ASR integration requires a fresh output root")
    pipeline = build_pipeline_handler()
    request = command(output_root, DEFAULT_MODEL_BUNDLE, target_stage="transcription")
    first = pipeline.run_asset(request)
    assert first["status"] == "succeeded", first
    before = snapshot(output_root)
    second = pipeline.run_asset(command(output_root, DEFAULT_MODEL_BUNDLE, reuse=True, target_stage="transcription"))
    assert second["status"] == "reused", second
    assert snapshot(output_root) == before
    return first, second
