"""Explicit production transcription assembly, independent of test runners."""

from __future__ import annotations

from importlib.metadata import version
import os
from typing import Any, Mapping

from infrastructure.infrastructure.process import run_process
from transcription.interfaces.workflow import TranscriptionCommand, TranscriptionCommandHandler, TranscriptionResult
from transcription.application import (
    AudioVadAsrService,
    ForcedAlignmentService,
    SentenceBoundaryService,
    TranscriptFusionService,
    TranscriptionWorkflow,
    TranscriptionWorkflowConfig,
    TranscriptionWorkflowEventRecorder,
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


DEFAULT_TRANSCRIPTION_RUNTIME = {
    "alignment_model": "jonatasgrosman/wav2vec2-large-xlsr-53-english",
    "alignment_model_version": "569a6236e92bd5f7652a0420bfe9bb94c5664080",
    "batch_size": 8,
    "beam_size": 5,
    "compute_type": "int8",
    "device": "cpu",
    "ffmpeg_path": "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",
    "ffprobe_path": "/opt/homebrew/opt/ffmpeg-full/bin/ffprobe",
    "interpolation": {
        "allowed_reasons": [
            "alignment_model_no_timing",
            "numeric_or_symbol",
            "out_of_vocabulary",
        ],
        "max_consecutive_words": 1,
        "max_window_ms": 1500,
        "min_anchor_alignment_score": 0.5,
        "min_word_duration_ms": 80,
        "version": "interpolation.v1",
    },
    "matching_anchor_ngram_size": 3,
    "official_min_alignment_score": 0.5,
    "official_min_anchor_alignment_score": 0.5,
    "vad_merge_gap_ms": 500,
    "vad_model": "pyannote/segmentation",
    "vad_model_version": "660b9e20307a2b0cdb400d0f80aadc04a701fc54",
    "vad_offset": 0.5,
    "vad_onset": 0.5,
    "vad_padding_ms": 250,
}

def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
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



class _Observed:
    def __init__(self, delegate, counters, methods):
        self.delegate, self.counters, self.methods = delegate, counters, methods

    def __getattr__(self, name):
        value = getattr(self.delegate, name)
        if name not in self.methods:
            return value
        def observed(*args, **kwargs):
            key = self.methods[name]
            self.counters[key] = self.counters.get(key, 0) + 1
            return value(*args, **kwargs)
        return observed


class LocalTranscriptionHandler:
    """Defer package/tool/auth preflight and adapter construction until execution."""

    def __init__(self, output_root: str, runtime: Mapping[str, Any], process_runner=run_process) -> None:
        self.output_root = output_root
        self.runtime = dict(runtime)
        self.process_runner = process_runner

    def execute(self, command: TranscriptionCommand) -> TranscriptionResult:
        asset_id = command.asset_id
        events = TranscriptionWorkflowEventRecorder(asset_id.value)
        counts = {key: 0 for key in ("audio_encoding_calls", "vad_calls", "asr_calls", "alignment_calls", "official_alignment_calls", "writes")}
        self.last_counts = counts
        artifacts = _Observed(LocalTranscriptionArtifactStore(), counts, {
            "write_json": "writes", "write_text": "writes", "publish_json_pair": "writes"
        })
        checksum = Sha256ChecksumService()
        packages = {
            "whisperx": version("whisperx"),
            "pyannote.audio": version("pyannote.audio"),
        }
        ffmpeg_path = self.runtime["ffmpeg_path"]
        ffmpeg_version = self.process_runner([ffmpeg_path, "-version"], check=True).stdout.splitlines()[0]
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
            "output_root": self.output_root,
        }
        workflow = TranscriptionWorkflow(
            audio_vad_asr=AudioVadAsrService(
                audio_extractor=_Observed(FfmpegAudioExtractor(
                    ffmpeg_version=ffmpeg_version, ffmpeg_path=ffmpeg_path
                ), counts, {"extract": "audio_encoding_calls"}),
                vad_detector=_Observed(PyannoteVadDetector(
                    pyannote_version=packages["pyannote.audio"],
                    auth_token=auth_token,
                ), counts, {"detect": "vad_calls"}),
                asr_engine=_Observed(WhisperXAsrEngine(whisperx_version=packages["whisperx"]), counts, {"transcribe": "asr_calls"}),
                media_probe=FfprobeMediaProbe(ffprobe_path=self.runtime["ffprobe_path"]),
                **common,
            ),
            forced_alignment=ForcedAlignmentService(
                aligner=_Observed(WhisperXForcedAligner(
                    whisperx_version=packages["whisperx"]
                ), counts, {"align": "alignment_calls"}),
                **common,
            ),
            transcript_fusion=TranscriptFusionService(
                official_aligner=_Observed(WhisperXOfficialTranscriptAligner(
                    whisperx_version=packages["whisperx"]
                ), counts, {"align": "official_alignment_calls"}),
                **common,
            ),
            sentence_boundaries=SentenceBoundaryService(
                detector=RuleBasedSentenceBoundaryDetector(), **common
            ),
            checksum=checksum,
            artifacts=artifacts,
            events=events,
            config=_workflow_config(self.runtime),
            output_root=self.output_root,
        )
        return TranscriptionCommandHandler(workflow).execute(command)


def build_transcription_handler(*, output_root: str = "output", runtime: Mapping[str, Any] | None = None, process_runner=run_process) -> LocalTranscriptionHandler:
    """Build without probing tools, loading models, writing, or accessing credentials."""
    selected = dict(DEFAULT_TRANSCRIPTION_RUNTIME if runtime is None else runtime)
    _workflow_config(selected)
    return LocalTranscriptionHandler(str(output_root), selected, process_runner)
