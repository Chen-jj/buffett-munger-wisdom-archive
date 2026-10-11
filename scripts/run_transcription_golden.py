#!/usr/bin/env python3
"""Run the explicitly gated real WhisperX transcription golden evaluation."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
import json
import math
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
from time import perf_counter
from typing import Any, Mapping, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from archive_core.application import build_asset_workspace
from archive_core.domain import AssetId, ArtifactType, canonical_filename
from archive_core.interfaces import SourceAlignmentDTO
from transcription.application import (
    AudioVadAsrService,
    ForcedAlignmentService,
    SentenceBoundaryService,
    TranscriptFusionService,
    TranscriptionWorkflow,
    TranscriptionWorkflowConfig,
    TranscriptionWorkflowEventRecorder,
    TranscriptionWorkflowInput,
)
from transcription.domain import (
    AlignedAsrArtifact,
    AsrConfig,
    ForcedAlignmentConfig,
    MatchingPolicy,
    NormalizationPolicy,
    OfficialAlignmentConfig,
    SentenceBoundaryPolicy,
    TranscriptionQaPolicy,
    VadConfig,
)
from transcription.infrastructure import (
    FfmpegAudioExtractor,
    FfprobeMediaProbe,
    LocalTranscriptionArtifactStore,
    PyannoteVadDetector,
    RuleBasedSentenceBoundaryDetector,
    Sha256ChecksumService,
    WhisperXAsrEngine,
    WhisperXForcedAligner,
    WhisperXOfficialTranscriptAligner,
)


PLAN_SCHEMA = "transcription.golden-plan.v1"
REFERENCE_SCHEMA = "transcription.golden-reference.v1"
RECORD_SCHEMA = "transcription.golden-run-record.v1"
POLICY_SCHEMA = "transcription.golden-qa-policy.v1"
LIVE_GATE_ENV = "RUN_TRANSCRIPTION_GOLDEN"
PLAN_ENV = "TRANSCRIPTION_GOLDEN_PLAN"
TOKEN_ENV_NAMES = ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN")
REQUIRED_SAMPLE_KINDS = {
    "cnbc_single_speaker",
    "cnbc_multi_speaker",
    "youtube_noisy_archive",
}


class GoldenConfigurationError(RuntimeError):
    """Raised before any model is loaded when a golden input is unsafe or incomplete."""


def _object(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise GoldenConfigurationError(f"{name} must be a JSON object")
    return value


def _array(value: object, name: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise GoldenConfigurationError(f"{name} must be a JSON array")
    return value


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GoldenConfigurationError(f"{name} must be a non-empty string")
    if "<" in value or ">" in value:
        raise GoldenConfigurationError(f"{name} still contains a template placeholder")
    return value


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GoldenConfigurationError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise GoldenConfigurationError(f"{name} must be finite")
    return result


def load_json(path: Path) -> Mapping[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise GoldenConfigurationError(f"cannot read JSON file {path}: {error}") from error
    return _object(data, str(path))


def require_live_gate(environment: Mapping[str, str]) -> None:
    if environment.get(LIVE_GATE_ENV) != "1":
        raise GoldenConfigurationError(
            f"real golden execution requires explicit {LIVE_GATE_ENV}=1"
        )
    has_token = any(environment.get(name) for name in TOKEN_ENV_NAMES)
    offline_cache = environment.get("HF_HUB_OFFLINE") == "1"
    if not has_token and not offline_cache:
        raise GoldenConfigurationError(
            "set HF_TOKEN/HUGGING_FACE_HUB_TOKEN, or set HF_HUB_OFFLINE=1 only "
            "after populating the required local model cache"
        )


def validate_policy(policy: Mapping[str, Any]) -> None:
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise GoldenConfigurationError("unsupported golden QA policy schema")
    _text(policy.get("policy_version"), "policy.policy_version")
    runtime = _object(policy.get("runtime"), "policy.runtime")
    for name in (
        "whisperx",
        "pyannote.audio",
        "faster-whisper",
        "sentence_detector",
    ):
        _text(runtime.get(name), f"policy.runtime.{name}")
    thresholds = _object(policy.get("thresholds"), "policy.thresholds")
    for name in (
        "minimum_annotated_word_timings_per_sample",
        "maximum_word_boundary_error_p95_ms",
        "maximum_unaligned_word_ratio",
        "maximum_interpolated_word_ratio",
        "minimum_official_fusion_coverage_ratio",
        "minimum_sentence_boundary_precision",
        "minimum_sentence_boundary_recall",
    ):
        _number(thresholds.get(name), f"policy.thresholds.{name}")
    required_tags = _array(policy.get("required_coverage_tags"), "required_coverage_tags")
    if not required_tags or not all(isinstance(item, str) and item for item in required_tags):
        raise GoldenConfigurationError("required_coverage_tags must contain strings")


def validate_plan(
    plan: Mapping[str, Any], policy: Mapping[str, Any], plan_path: Path
) -> tuple[Mapping[str, Any], ...]:
    if plan.get("schema_version") != PLAN_SCHEMA:
        raise GoldenConfigurationError("unsupported golden plan schema")
    _text(plan.get("run_id"), "plan.run_id")
    runtime = _object(plan.get("runtime"), "plan.runtime")
    _text(runtime.get("device"), "plan.runtime.device")
    _text(runtime.get("compute_type"), "plan.runtime.compute_type")
    _text(runtime.get("vad_model"), "plan.runtime.vad_model")
    _immutable_revision(runtime.get("vad_model_version"), "vad_model_version")
    _text(runtime.get("alignment_model"), "plan.runtime.alignment_model")
    _immutable_revision(
        runtime.get("alignment_model_version"), "alignment_model_version"
    )
    _workflow_config(runtime)
    output_root = _resolve_path(
        plan_path, _text(plan.get("output_root"), "plan.output_root")
    )
    if not output_root.is_dir():
        raise GoldenConfigurationError(f"output_root does not exist: {output_root}")

    samples = tuple(
        _object(item, f"samples[{index}]")
        for index, item in enumerate(_array(plan.get("samples"), "plan.samples"))
    )
    if not samples:
        raise GoldenConfigurationError("plan.samples must not be empty")
    kinds: set[str] = set()
    tags: set[str] = set()
    sample_ids: set[str] = set()
    for index, sample in enumerate(samples):
        prefix = f"samples[{index}]"
        sample_id = _text(sample.get("id"), f"{prefix}.id")
        if sample_id in sample_ids:
            raise GoldenConfigurationError(f"duplicate sample id: {sample_id}")
        sample_ids.add(sample_id)
        kind = _text(sample.get("kind"), f"{prefix}.kind")
        kinds.add(kind)
        sample_tags = _array(sample.get("coverage_tags"), f"{prefix}.coverage_tags")
        if not all(isinstance(tag, str) and tag for tag in sample_tags):
            raise GoldenConfigurationError(f"{prefix}.coverage_tags must contain strings")
        tags.update(sample_tags)
        asset = _object(sample.get("asset"), f"{prefix}.asset")
        asset_id = AssetId(
            source=_text(asset.get("source"), f"{prefix}.asset.source"),
            group=asset.get("group", ""),
            item=_text(asset.get("item"), f"{prefix}.asset.item"),
        )
        workspace = build_asset_workspace(asset_id, output_root)
        _require_file(workspace / "download_manifest.json", "download manifest")
        _require_file(
            workspace / canonical_filename(ArtifactType.SOURCE_VIDEO), "source video"
        )
        reference_path = _resolve_path(
            plan_path,
            _text(sample.get("reference_path"), f"{prefix}.reference_path"),
        )
        reference = load_json(reference_path)
        validate_reference(reference, sample_id)
        chapters_sha256 = sample.get("chapters_sha256")
        chapters_path = workspace / canonical_filename(ArtifactType.CHAPTERS)
        if chapters_sha256 is None:
            if chapters_path.exists():
                raise GoldenConfigurationError(
                    f"{sample_id}: chapters.json exists but chapters_sha256 is null"
                )
        else:
            _text(chapters_sha256, f"{prefix}.chapters_sha256")
            _require_file(chapters_path, "chapters")
        for artifact_type in (
            ArtifactType.SOURCE_AUDIO,
            ArtifactType.VAD,
            ArtifactType.RAW_ASR,
            ArtifactType.ALIGNED_ASR,
            ArtifactType.TRANSCRIPT_FUSION,
            ArtifactType.SOURCE_ALIGNMENT,
            ArtifactType.TRANSCRIPTION_MANIFEST,
        ):
            path = workspace / canonical_filename(artifact_type)
            if path.exists():
                raise GoldenConfigurationError(
                    f"{sample_id}: golden runs require a cold workspace; found {path}"
                )
    missing_kinds = REQUIRED_SAMPLE_KINDS - kinds
    if missing_kinds:
        raise GoldenConfigurationError(
            f"golden plan is missing sample kinds: {sorted(missing_kinds)}"
        )
    required_tags = set(policy["required_coverage_tags"])
    missing_tags = required_tags - tags
    if missing_tags:
        raise GoldenConfigurationError(
            f"golden plan is missing coverage tags: {sorted(missing_tags)}"
        )
    return samples


def validate_reference(reference: Mapping[str, Any], sample_id: str) -> None:
    if reference.get("schema_version") != REFERENCE_SCHEMA:
        raise GoldenConfigurationError(f"{sample_id}: unsupported reference schema")
    if reference.get("sample_id") != sample_id:
        raise GoldenConfigurationError(f"{sample_id}: reference sample_id mismatch")
    timings = _array(reference.get("word_timings"), "reference.word_timings")
    for index, item in enumerate(timings):
        timing = _object(item, f"reference.word_timings[{index}]")
        _text(timing.get("word_id"), f"reference.word_timings[{index}].word_id")
        start = _number(timing.get("start_ms"), "reference start_ms")
        end = _number(timing.get("end_ms"), "reference end_ms")
        if start < 0 or end <= start:
            raise GoldenConfigurationError("reference word timing must satisfy 0 <= start < end")
    boundaries = _array(
        reference.get("sentence_end_word_ids"), "reference.sentence_end_word_ids"
    )
    if not boundaries or not all(isinstance(item, str) and item for item in boundaries):
        raise GoldenConfigurationError("sentence_end_word_ids must contain word IDs")


def _immutable_revision(value: object, name: str) -> str:
    revision = _text(value, f"plan.runtime.{name}")
    if revision.casefold() in {"default", "latest", "main", "master"}:
        raise GoldenConfigurationError(f"{name} must be an immutable tag or commit")
    return revision


def _require_file(path: Path, name: str) -> None:
    if not path.is_file() or path.stat().st_size <= 0:
        raise GoldenConfigurationError(f"{name} is missing or empty: {path}")


def _resolve_path(plan_path: Path, value: str) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = plan_path.parent / candidate
    return candidate.resolve()


def _package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError as error:
        raise GoldenConfigurationError(f"required package is not installed: {name}") from error


def runtime_inventory(ffmpeg_path: str) -> dict[str, Any]:
    package_versions = {
        name: _package_version(name)
        for name in (
            "whisperx",
            "pyannote.audio",
            "faster-whisper",
            "torch",
            "torchaudio",
            "transformers",
            "huggingface-hub",
        )
    }
    try:
        ffmpeg_line = subprocess.run(
            (ffmpeg_path, "-version"),
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()[0]
    except (OSError, subprocess.CalledProcessError, IndexError) as error:
        raise GoldenConfigurationError(f"ffmpeg is not executable: {ffmpeg_path}") from error
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or None,
        "packages": package_versions,
        "ffmpeg": ffmpeg_line,
        "sentence_detector": "local-rule-sentence-detector/1",
    }


def verify_runtime(policy: Mapping[str, Any], inventory: Mapping[str, Any]) -> None:
    expected = _object(policy["runtime"], "policy.runtime")
    packages = _object(inventory["packages"], "inventory.packages")
    for name in ("whisperx", "pyannote.audio", "faster-whisper"):
        if packages.get(name) != expected.get(name):
            raise GoldenConfigurationError(
                f"runtime mismatch for {name}: expected {expected.get(name)}, "
                f"found {packages.get(name)}"
            )
    if inventory.get("sentence_detector") != expected.get("sentence_detector"):
        raise GoldenConfigurationError("sentence detector version does not match policy")


def _workflow_config(runtime: Mapping[str, Any]) -> TranscriptionWorkflowConfig:
    device = _text(runtime.get("device"), "plan.runtime.device")
    alignment = ForcedAlignmentConfig.from_dict(
        {
            "model": runtime["alignment_model"],
            "model_version": runtime["alignment_model_version"],
            "device": device,
            "language": "en",
            "interpolation": _object(runtime.get("interpolation"), "interpolation"),
        }
    )
    return TranscriptionWorkflowConfig(
        vad=VadConfig(
            model=runtime["vad_model"],
            model_version=runtime["vad_model_version"],
            onset=runtime.get("vad_onset"),
            offset=runtime.get("vad_offset"),
            padding_ms=runtime.get("vad_padding_ms"),
            merge_gap_ms=runtime.get("vad_merge_gap_ms"),
        ),
        asr=AsrConfig.production(
            model="large-v3",
            device=device,
            compute_type=_text(runtime.get("compute_type"), "compute_type"),
            batch_size=runtime.get("batch_size"),
            beam_size=runtime.get("beam_size"),
        ),
        alignment=alignment,
        normalization=NormalizationPolicy(),
        matching=MatchingPolicy(),
        official_alignment=OfficialAlignmentConfig.from_dict(
            {
                "model": runtime["alignment_model"],
                "model_version": runtime["alignment_model_version"],
                "device": device,
                "language": "en",
                "min_alignment_score": runtime.get(
                    "official_min_alignment_score"
                ),
                "min_anchor_alignment_score": runtime.get(
                    "official_min_anchor_alignment_score"
                ),
            }
        ),
        sentence_boundary=SentenceBoundaryPolicy(),
        qa=TranscriptionQaPolicy(),
    )


def _workflow(
    asset_id: AssetId,
    output_root: Path,
    runtime: Mapping[str, Any],
    inventory: Mapping[str, Any],
) -> tuple[
    TranscriptionWorkflow,
    TranscriptionWorkflowEventRecorder,
    TranscriptionWorkflowConfig,
]:
    packages = _object(inventory["packages"], "inventory.packages")
    ffmpeg_path = _text(runtime.get("ffmpeg_path"), "plan.runtime.ffmpeg_path")
    ffprobe_path = _text(runtime.get("ffprobe_path"), "plan.runtime.ffprobe_path")
    events = TranscriptionWorkflowEventRecorder(asset_id.value)
    artifacts = LocalTranscriptionArtifactStore()
    checksum = Sha256ChecksumService()
    aligner = WhisperXForcedAligner(whisperx_version=packages["whisperx"])
    official_aligner = WhisperXOfficialTranscriptAligner(
        whisperx_version=packages["whisperx"]
    )
    config = _workflow_config(runtime)
    common = {
        "checksum": checksum,
        "artifacts": artifacts,
        "events": events,
        "output_root": str(output_root),
    }
    workflow = TranscriptionWorkflow(
        audio_vad_asr=AudioVadAsrService(
            audio_extractor=FfmpegAudioExtractor(
                ffmpeg_version=inventory["ffmpeg"], ffmpeg_path=ffmpeg_path
            ),
            vad_detector=PyannoteVadDetector(
                pyannote_version=packages["pyannote.audio"],
                auth_token=next(
                    (os.environ[name] for name in TOKEN_ENV_NAMES if os.environ.get(name)),
                    None,
                ),
            ),
            asr_engine=WhisperXAsrEngine(whisperx_version=packages["whisperx"]),
            media_probe=FfprobeMediaProbe(ffprobe_path=ffprobe_path),
            **common,
        ),
        forced_alignment=ForcedAlignmentService(aligner=aligner, **common),
        transcript_fusion=TranscriptFusionService(
            official_aligner=official_aligner, **common
        ),
        sentence_boundaries=SentenceBoundaryService(
            detector=RuleBasedSentenceBoundaryDetector(), **common
        ),
        checksum=checksum,
        artifacts=artifacts,
        events=events,
        config=config,
        output_root=str(output_root),
    )
    return workflow, events, config


def evaluate_sample(
    alignment: SourceAlignmentDTO,
    aligned_asr: AlignedAsrArtifact,
    events: TranscriptionWorkflowEventRecorder,
    reference: Mapping[str, Any],
    sample_kind: str,
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    by_id = {word.id: word for word in alignment.words}
    boundary_errors: list[float] = []
    for item in reference["word_timings"]:
        expected = _object(item, "reference word timing")
        word_id = _text(expected.get("word_id"), "reference word_id")
        if word_id not in by_id:
            raise GoldenConfigurationError(f"reference word is absent from output: {word_id}")
        actual = by_id[word_id]
        boundary_errors.extend(
            (
                abs(actual.start_ms - _number(expected["start_ms"], "start_ms")),
                abs(actual.end_ms - _number(expected["end_ms"], "end_ms")),
            )
        )
    predicted_boundaries = {sentence.last_word_id for sentence in alignment.sentences}
    expected_boundaries = set(reference["sentence_end_word_ids"])
    true_positive = len(predicted_boundaries & expected_boundaries)
    precision = true_positive / len(predicted_boundaries) if predicted_boundaries else 0.0
    recall = true_positive / len(expected_boundaries) if expected_boundaries else 0.0
    unaligned_count = sum(
        event.code.value == "alignment.word_unaligned" for event in events.events
    )
    interpolated_count = sum(
        word.timing_source.value == "interpolated" for word in aligned_asr.words
    )
    fusion_events = Counter(
        event.code.value
        for event in events.events
        if event.code.value.startswith("fusion.")
    )
    official_words = sum(bool(word.official_token_ids) for word in alignment.words)
    word_count = len(alignment.words)
    official_coverage = official_words / word_count if sample_kind.startswith("cnbc_") else None
    thresholds = policy["thresholds"]
    metrics = {
        "annotated_word_timing_count": len(reference["word_timings"]),
        "word_boundary_error_median_ms": _percentile(boundary_errors, 0.50),
        "word_boundary_error_p95_ms": _percentile(boundary_errors, 0.95),
        "word_boundary_error_max_ms": max(boundary_errors),
        "unaligned_word_count": unaligned_count,
        "unaligned_word_ratio": unaligned_count / word_count if word_count else 1.0,
        "interpolated_word_count": interpolated_count,
        "interpolated_word_ratio": interpolated_count / word_count if word_count else 1.0,
        "fusion_official_word_coverage_ratio": official_coverage,
        "fusion_event_counts": dict(sorted(fusion_events.items())),
        "conflict_types": dict(
            sorted(
                (name, count)
                for name, count in fusion_events.items()
                if name
                in {
                    "fusion.asr_only_retained",
                    "fusion.official_only_excluded",
                    "fusion.region_unmatched",
                    "fusion.text_replaced",
                }
            )
        ),
        "sentence_boundary_precision": precision,
        "sentence_boundary_recall": recall,
        "predicted_sentence_boundary_count": len(predicted_boundaries),
        "reference_sentence_boundary_count": len(expected_boundaries),
    }
    gates = {
        "minimum_annotated_word_timings": len(reference["word_timings"])
        >= thresholds["minimum_annotated_word_timings_per_sample"],
        "word_boundary_error_p95": metrics["word_boundary_error_p95_ms"]
        <= thresholds["maximum_word_boundary_error_p95_ms"],
        "unaligned_word_ratio": metrics["unaligned_word_ratio"]
        <= thresholds["maximum_unaligned_word_ratio"],
        "interpolated_word_ratio": metrics["interpolated_word_ratio"]
        <= thresholds["maximum_interpolated_word_ratio"],
        "sentence_boundary_precision": precision
        >= thresholds["minimum_sentence_boundary_precision"],
        "sentence_boundary_recall": recall
        >= thresholds["minimum_sentence_boundary_recall"],
    }
    if official_coverage is not None:
        gates["official_fusion_coverage"] = official_coverage >= thresholds[
            "minimum_official_fusion_coverage_ratio"
        ]
    return {"metrics": metrics, "gates": gates, "passed": all(gates.values())}


def _percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        raise GoldenConfigurationError("word timing reference must not be empty")
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _peak_rss_mb() -> float:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return value / (1024 * 1024)
    return value / 1024


def _git_revision() -> str | None:
    result = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _write_new_json(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")


def run_plan(
    plan: Mapping[str, Any],
    policy: Mapping[str, Any],
    plan_path: Path,
    record_dir: Path,
    inventory: Mapping[str, Any],
) -> int:
    output_root = _resolve_path(plan_path, plan["output_root"])
    runtime = _object(plan["runtime"], "plan.runtime")
    failures = 0
    for sample in plan["samples"]:
        sample = _object(sample, "sample")
        sample_id = sample["id"]
        asset_data = _object(sample["asset"], "sample.asset")
        asset_id = AssetId(
            source=asset_data["source"],
            group=asset_data.get("group", ""),
            item=asset_data["item"],
        )
        workspace = build_asset_workspace(asset_id, output_root)
        reference_path = _resolve_path(plan_path, sample["reference_path"])
        reference = load_json(reference_path)
        workflow, events, workflow_config = _workflow(
            asset_id, output_root, runtime, inventory
        )
        started = datetime.now(timezone.utc)
        started_clock = perf_counter()
        record: dict[str, Any] = {
            "schema_version": RECORD_SCHEMA,
            "policy_version": policy["policy_version"],
            "run_id": plan["run_id"],
            "sample_id": sample_id,
            "kind": sample["kind"],
            "coverage_tags": list(sample["coverage_tags"]),
            "asset": dict(asset_data),
            "repository_revision": _git_revision(),
            "started_at": started.isoformat(),
            "runtime": dict(inventory),
            "parameters": {
                "vad": workflow_config.vad.to_dict(),
                "asr": workflow_config.asr.to_dict(),
                "alignment": workflow_config.alignment.to_dict(),
                "normalization": workflow_config.normalization.to_dict(),
                "matching": workflow_config.matching.to_dict(),
                "official_alignment": workflow_config.official_alignment.to_dict(),
                "sentence_boundary": workflow_config.sentence_boundary.to_dict(),
                "workflow_qa": workflow_config.qa.to_dict(),
            },
            "auth": {
                "hugging_face_token_present": any(os.environ.get(name) for name in TOKEN_ENV_NAMES),
                "hugging_face_offline": os.environ.get("HF_HUB_OFFLINE") == "1",
            },
        }
        try:
            outcome = workflow.execute(
                TranscriptionWorkflowInput(
                    asset_id=asset_id,
                    download_manifest_path=str(workspace / "download_manifest.json"),
                    chapters_sha256=sample.get("chapters_sha256"),
                    overwrite=False,
                )
            )
            if outcome.cache_hits:
                raise GoldenConfigurationError(
                    f"golden evaluation must be cold; cache hits: {outcome.cache_hits}"
                )
            alignment = SourceAlignmentDTO.from_dict(
                load_json(Path(outcome.source_alignment_path))
            )
            aligned_asr = AlignedAsrArtifact.from_dict(
                load_json(workspace / canonical_filename(ArtifactType.ALIGNED_ASR))
            )
            evaluation = evaluate_sample(
                alignment,
                aligned_asr,
                events,
                reference,
                sample["kind"],
                policy,
            )
            record.update(
                {
                    "status": "passed" if evaluation["passed"] else "failed_qa",
                    "artifacts": {
                        "source_alignment": outcome.source_alignment_path,
                        "manifest": outcome.manifest_path,
                        "log": outcome.log_path,
                        "report": outcome.report_path,
                    },
                    "evaluation": evaluation,
                }
            )
            if not evaluation["passed"]:
                failures += 1
        except Exception as error:
            failures += 1
            record.update(
                {
                    "status": "failed_execution",
                    "error_type": error.__class__.__name__,
                    "error": str(error),
                }
            )
        finally:
            record["elapsed_seconds"] = perf_counter() - started_clock
            record["resources"] = {
                "process_peak_rss_mb_at_sample_end": _peak_rss_mb(),
                "gpu_peak_memory_mb": None,
                "gpu_peak_memory_note": (
                    "not measured by the v1 harness; capture externally when device is not CPU"
                ),
            }
            record["finished_at"] = datetime.now(timezone.utc).isoformat()
            _write_new_json(
                record_dir / f"{plan['run_id']}--{sample_id}.json", record
            )
    return 1 if failures else 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plan",
        type=Path,
        default=Path(os.environ[PLAN_ENV]) if os.environ.get(PLAN_ENV) else None,
        help=f"completed golden plan JSON (or set {PLAN_ENV})",
    )
    parser.add_argument(
        "--policy",
        type=Path,
        default=REPOSITORY_ROOT
        / "docs"
        / "golden"
        / "transcription"
        / "qa-policy.v1.json",
    )
    parser.add_argument("--record-dir", type=Path)
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="validate local inputs and versions without loading models",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.plan is None:
        raise GoldenConfigurationError(
            f"provide --plan or set {PLAN_ENV}; the template is not runnable"
        )
    plan_path = args.plan.expanduser().resolve()
    policy_path = args.policy.expanduser().resolve()
    policy = load_json(policy_path)
    validate_policy(policy)
    plan = load_json(plan_path)
    validate_plan(plan, policy, plan_path)
    runtime = _object(plan["runtime"], "plan.runtime")
    inventory = runtime_inventory(runtime["ffmpeg_path"])
    verify_runtime(policy, inventory)
    if args.preflight_only:
        print(json.dumps({"status": "preflight_passed", "runtime": inventory}, indent=2))
        return 0
    require_live_gate(os.environ)
    if args.record_dir is None:
        raise GoldenConfigurationError("real execution requires --record-dir")
    return run_plan(
        plan,
        policy,
        plan_path,
        args.record_dir.expanduser().resolve(),
        inventory,
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except GoldenConfigurationError as error:
        print(f"golden configuration error: {error}", file=sys.stderr)
        raise SystemExit(2)
