from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.run_transcription_golden import (
    GoldenConfigurationError,
    POLICY_SCHEMA,
    _percentile,
    evaluate_sample,
    load_json,
    require_live_gate,
    validate_policy,
)


POLICY_PATH = (
    Path(__file__).parents[1]
    / "docs"
    / "golden"
    / "transcription"
    / "qa-policy.v1.json"
)


def test_real_golden_requires_explicit_live_and_model_access_gates() -> None:
    with pytest.raises(GoldenConfigurationError, match="RUN_TRANSCRIPTION_GOLDEN=1"):
        require_live_gate({})
    with pytest.raises(GoldenConfigurationError, match="HF_TOKEN"):
        require_live_gate({"RUN_TRANSCRIPTION_GOLDEN": "1"})

    require_live_gate(
        {"RUN_TRANSCRIPTION_GOLDEN": "1", "HF_HUB_OFFLINE": "1"}
    )


def test_versioned_golden_policy_is_machine_readable() -> None:
    policy = load_json(POLICY_PATH)
    validate_policy(policy)

    assert policy["schema_version"] == POLICY_SCHEMA
    assert policy["policy_version"] == "transcription-golden-qa.v1-candidate"
    assert policy["runtime"]["whisperx"] == "3.8.5"
    assert policy["required_sample_kinds"] == [
        "cnbc_single_speaker",
        "cnbc_multi_speaker",
        "youtube_noisy_archive",
    ]


def test_word_timing_percentile_is_deterministic() -> None:
    assert _percentile([0, 100, 200, 300], 0.50) == 150
    assert _percentile([0, 100, 200, 300], 0.95) == pytest.approx(285)


def test_golden_metrics_include_timing_fusion_alignment_and_boundaries() -> None:
    policy = dict(load_json(POLICY_PATH))
    policy["thresholds"] = {
        **policy["thresholds"],
        "minimum_annotated_word_timings_per_sample": 2,
        "maximum_interpolated_word_ratio": 0.5,
    }
    alignment = SimpleNamespace(
        words=(
            SimpleNamespace(
                id="w1", start_ms=100, end_ms=200, official_token_ids=("ot1",)
            ),
            SimpleNamespace(
                id="w2", start_ms=300, end_ms=400, official_token_ids=("ot2",)
            ),
        ),
        sentences=(SimpleNamespace(last_word_id="w2"),),
    )
    aligned_asr = SimpleNamespace(
        words=(
            SimpleNamespace(timing_source=SimpleNamespace(value="acoustic_alignment")),
            SimpleNamespace(timing_source=SimpleNamespace(value="interpolated")),
        )
    )
    events = SimpleNamespace(
        events=(SimpleNamespace(code=SimpleNamespace(value="fusion.text_replaced")),)
    )
    reference = {
        "word_timings": [
            {"word_id": "w1", "start_ms": 90, "end_ms": 210},
            {"word_id": "w2", "start_ms": 310, "end_ms": 390},
        ],
        "sentence_end_word_ids": ["w2"],
    }

    result = evaluate_sample(
        alignment,
        aligned_asr,
        events,
        reference,
        "cnbc_single_speaker",
        policy,
    )

    assert result["passed"] is True
    assert result["metrics"]["word_boundary_error_p95_ms"] == 10
    assert result["metrics"]["interpolated_word_ratio"] == 0.5
    assert result["metrics"]["fusion_official_word_coverage_ratio"] == 1
    assert result["metrics"]["conflict_types"] == {"fusion.text_replaced": 1}
    assert result["metrics"]["sentence_boundary_precision"] == 1
    assert result["metrics"]["sentence_boundary_recall"] == 1


def test_run_record_template_is_json_without_claimed_results() -> None:
    path = POLICY_PATH.with_name("golden-run-record.template.json")
    record = json.loads(path.read_text(encoding="utf-8"))

    assert record["schema_version"] == "transcription.golden-run-record.v1"
    assert record["status"] is None
    assert record["evaluation"]["passed"] is None
