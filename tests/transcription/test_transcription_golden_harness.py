from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from archive_core.application import build_asset_workspace
from archive_core.domain import AssetId

from scripts.run_transcription_golden import (
    GoldenConfigurationError,
    POLICY_SCHEMA,
    _percentile,
    _workflow_config,
    evaluate_sample,
    hugging_face_token,
    load_json,
    require_live_gate,
    validate_plan,
    validate_reference,
    validate_policy,
)


POLICY_PATH = (
    Path(__file__).parents[2]
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
    require_live_gate(
        {"RUN_TRANSCRIPTION_GOLDEN": "1"}, cached_token_present=True
    )


def test_hugging_face_token_prefers_explicit_environment(monkeypatch) -> None:
    monkeypatch.setattr("huggingface_hub.get_token", lambda: "cached")

    assert hugging_face_token({"HF_TOKEN": "explicit"}) == "explicit"
    assert hugging_face_token({}) == "cached"


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


def test_golden_reference_requires_policy_annotation_count() -> None:
    reference = {
        "schema_version": "transcription.golden-reference.v1",
        "sample_id": "cnbc-sample",
        "word_timings": [
            {"word_id": "w1", "start_ms": 0, "end_ms": 100},
        ],
        "sentence_end_word_ids": ["w1"],
    }

    with pytest.raises(GoldenConfigurationError, match="at least 20"):
        validate_reference(
            reference,
            "cnbc-sample",
            minimum_word_timings=20,
        )


def test_partial_plan_requires_explicit_incomplete_coverage_opt_in(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "output"
    output_root.mkdir()
    workspace = build_asset_workspace(
        AssetId("cnbc", "2000", "morning"), output_root
    )
    workspace.mkdir()
    (workspace / "video.mp4").write_bytes(b"video")
    (workspace / "download_manifest.json").write_text("{}", encoding="utf-8")
    (workspace / "chapters.json").write_text("{}", encoding="utf-8")
    reference_path = tmp_path / "reference.json"
    reference_path.write_text(
        json.dumps(
            {
                "schema_version": "transcription.golden-reference.v1",
                "sample_id": "cnbc-only",
                "word_timings": [
                    {
                        "word_id": f"w{index}",
                        "start_ms": index * 100,
                        "end_ms": index * 100 + 50,
                    }
                    for index in range(1, 21)
                ],
                "sentence_end_word_ids": ["w20"],
            }
        ),
        encoding="utf-8",
    )
    plan = {
        "schema_version": "transcription.golden-plan.v1",
        "run_id": "partial-cnbc",
        "output_root": str(output_root),
        "runtime": {
            "device": "cpu",
            "compute_type": "int8",
            "batch_size": 8,
            "beam_size": 5,
            "vad_model": "pyannote/voice-activity-detection",
            "vad_model_version": "revision-1",
            "vad_onset": 0.5,
            "vad_offset": 0.5,
            "vad_padding_ms": 250,
            "vad_merge_gap_ms": 500,
            "alignment_model": "example/alignment",
            "alignment_model_version": "revision-1",
            "interpolation": {
                "version": "interpolation.v1",
                "max_consecutive_words": 1,
                "max_window_ms": 1500,
                "min_word_duration_ms": 80,
                "min_anchor_alignment_score": 0.5,
                "allowed_reasons": ["alignment_model_no_timing"],
            },
            "matching_anchor_ngram_size": 3,
            "official_min_alignment_score": 0.5,
            "official_min_anchor_alignment_score": 0.5,
        },
        "samples": [
            {
                "id": "cnbc-only",
                "kind": "cnbc_multi_speaker",
                "asset": {"source": "cnbc", "group": "2000", "item": "morning"},
                "coverage_tags": ["number"],
                "chapters_sha256": "checksum",
                "reference_path": str(reference_path),
            }
        ],
    }
    policy = load_json(POLICY_PATH)

    with pytest.raises(GoldenConfigurationError, match="missing sample kinds"):
        validate_plan(plan, policy, tmp_path / "plan.json")

    assert validate_plan(
        plan,
        policy,
        tmp_path / "plan.json",
        require_complete=False,
    ) == tuple(plan["samples"])
    assert _workflow_config(plan["runtime"]).matching.anchor_ngram_size == 3

    (workspace / "audio.wav").write_bytes(b"calibration audio")
    plan["schema_version"] = "transcription.integration-plan.v1"
    plan["samples"][0]["reference_path"] = str(tmp_path / "missing.json")
    assert validate_plan(
        plan,
        policy,
        tmp_path / "plan.json",
        require_complete=False,
        require_reference=False,
        require_cold_workspace=False,
    ) == tuple(plan["samples"])


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
