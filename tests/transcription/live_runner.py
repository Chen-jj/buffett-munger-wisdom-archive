"""Run the explicitly gated CNBC transcription integration."""

from __future__ import annotations

import json
from importlib.metadata import version
import os
from pathlib import Path
import subprocess
from typing import Any, Mapping

from archive_core.application import build_asset_workspace
from archive_core.domain import AssetId
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


class IntegrationConfigurationError(RuntimeError):
    """Raised before a live integration run when its input is invalid."""


def load_json(path: Path) -> Mapping[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise IntegrationConfigurationError(
            f"cannot read JSON file {path}: {error}"
        ) from error
    if not isinstance(data, Mapping):
        raise IntegrationConfigurationError(f"{path} must contain a JSON object")
    return data


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IntegrationConfigurationError(f"{name} must be a non-empty string")
    return value


def _workflow_config(runtime: Mapping[str, Any]) -> TranscriptionWorkflowConfig:
    device = _text(runtime.get("device"), "plan.runtime.device")
    alignment = ForcedAlignmentConfig.from_dict(
        {
            "model": runtime["alignment_model"],
            "model_version": runtime["alignment_model_version"],
            "device": device,
            "language": "en",
            "interpolation": runtime["interpolation"],
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
        matching=MatchingPolicy(
            anchor_ngram_size=runtime.get("matching_anchor_ngram_size", 2)
        ),
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


def run_integration(plan: Mapping[str, Any], plan_path: Path) -> int:
    runtime = plan["runtime"]
    output_root = Path(plan["output_root"])
    if not output_root.is_absolute():
        output_root = (plan_path.parent / output_root).resolve()
    results = []
    for sample in plan["samples"]:
        asset = sample["asset"]
        asset_id = AssetId(asset["source"], asset.get("group", ""), asset["item"])
        workspace = build_asset_workspace(asset_id, output_root)
        events = TranscriptionWorkflowEventRecorder(asset_id.value)
        artifacts = LocalTranscriptionArtifactStore()
        checksum = Sha256ChecksumService()
        packages = {
            "whisperx": version("whisperx"),
            "pyannote.audio": version("pyannote.audio"),
        }
        ffmpeg_path = runtime["ffmpeg_path"]
        ffmpeg_version = subprocess.run(
            [ffmpeg_path, "-version"], check=True, capture_output=True, text=True
        ).stdout.splitlines()[0]
        auth_token = os.environ.get("HF_TOKEN") or os.environ.get(
            "HUGGING_FACE_HUB_TOKEN"
        )
        if auth_token is None:
            from huggingface_hub import get_token

            auth_token = get_token()
        common = {
            "checksum": checksum,
            "artifacts": artifacts,
            "events": events,
            "output_root": str(output_root),
        }
        workflow = TranscriptionWorkflow(
            audio_vad_asr=AudioVadAsrService(
                audio_extractor=FfmpegAudioExtractor(
                    ffmpeg_version=ffmpeg_version, ffmpeg_path=ffmpeg_path
                ),
                vad_detector=PyannoteVadDetector(
                    pyannote_version=packages["pyannote.audio"],
                    auth_token=auth_token,
                ),
                asr_engine=WhisperXAsrEngine(whisperx_version=packages["whisperx"]),
                media_probe=FfprobeMediaProbe(ffprobe_path=runtime["ffprobe_path"]),
                **common,
            ),
            forced_alignment=ForcedAlignmentService(
                aligner=WhisperXForcedAligner(
                    whisperx_version=packages["whisperx"]
                ),
                **common,
            ),
            transcript_fusion=TranscriptFusionService(
                official_aligner=WhisperXOfficialTranscriptAligner(
                    whisperx_version=packages["whisperx"]
                ),
                **common,
            ),
            sentence_boundaries=SentenceBoundaryService(
                detector=RuleBasedSentenceBoundaryDetector(), **common
            ),
            checksum=checksum,
            artifacts=artifacts,
            events=events,
            config=_workflow_config(runtime),
            output_root=str(output_root),
        )
        outcome = workflow.execute(
            TranscriptionWorkflowInput(
                asset_id=asset_id,
                download_manifest_path=str(workspace / "download_manifest.json"),
                chapters_sha256=sample.get("chapters_sha256"),
                overwrite=False,
            )
        )
        results.append(
            {
                "sample_id": sample["id"],
                "source_alignment": outcome.source_alignment_path,
                "manifest": outcome.manifest_path,
                "report": outcome.report_path,
                "cache_hits": list(outcome.cache_hits),
                "event_count": len(events.events),
            }
        )
    print(
        json.dumps(
            {"status": "integration_completed", "samples": results},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args(argv)
    if os.environ.get("RUN_TRANSCRIPTION_INTEGRATION") != "1":
        raise IntegrationConfigurationError("set RUN_TRANSCRIPTION_INTEGRATION=1")
    return run_integration(load_json(args.plan.expanduser().resolve()), args.plan.resolve())
