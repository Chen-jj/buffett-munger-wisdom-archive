"""Local ffmpeg, pyannote, WhisperX, checksum, and artifact adapters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Mapping
import unicodedata
import wave

from infrastructure.infrastructure.filesystem import write_json_file
from infrastructure.infrastructure.process import (
    ProcessExecutionError,
    ProcessResult,
    run_process,
)
from transcription.application import AudioExtractionConfig
from transcription.domain import (
    AlignedAsrWord,
    AlignmentCandidate,
    AsrConfig,
    ForcedAlignmentConfig,
    OfficialAlignmentCandidate,
    OfficialAlignmentConfig,
    OfficialTranscriptToken,
    ProviderIdentity,
    RawAsrSegment,
    RawAsrToken,
    VadArtifact,
    VadConfig,
    VadRegion,
    tokenize_surface_text,
)
from transcription.domain.fusion import fusion_candidate_text
from transcription.domain.fusion_acoustics import (
    AcousticCandidateEvidence,
    AcousticWordEvidence,
)


ProcessRunner = Callable[..., ProcessResult]
AlignmentModelResolver = Callable[[str, str], str]
AudioLoader = Callable[[str], Mapping[str, Any]]


def _restore_raw_trailing_punctuation(
    provider_surface: str,
    raw_surface: str,
) -> str:
    if provider_surface == raw_surface or not raw_surface.startswith(provider_surface):
        return provider_surface
    suffix = raw_surface[len(provider_surface) :]
    if suffix and all(
        character != "_" and unicodedata.category(character).startswith("P")
        for character in suffix
    ):
        return raw_surface
    return provider_surface


@dataclass(frozen=True)
class AudioExtractionResult:
    command: tuple[str, ...]


@dataclass(frozen=True)
class FfmpegAudioExtractor:
    ffmpeg_version: str
    ffmpeg_path: str = "ffmpeg"
    process_runner: ProcessRunner = run_process

    @property
    def identity(self) -> ProviderIdentity:
        return ProviderIdentity(name="ffmpeg", version=self.ffmpeg_version)

    def build_command(
        self,
        video_path: str,
        output_path: str,
        config: AudioExtractionConfig,
        *,
        overwrite: bool,
    ) -> tuple[str, ...]:
        return (
            self.ffmpeg_path,
            "-hide_banner",
            "-nostdin",
            "-y" if overwrite else "-n",
            "-i",
            video_path,
            "-vn",
            "-acodec",
            config.codec,
            "-ar",
            str(config.sample_rate_hz),
            "-ac",
            str(config.channels),
            "-sample_fmt",
            config.sample_format,
            output_path,
        )

    def extract(
        self,
        video_path: str,
        output_path: str,
        config: AudioExtractionConfig,
        *,
        overwrite: bool,
    ) -> AudioExtractionResult:
        command = self.build_command(
            video_path, output_path, config, overwrite=overwrite
        )
        result = self.process_runner(command, check=False)
        if not result.ok:
            raise ProcessExecutionError(result)
        return AudioExtractionResult(command=result.command)


@dataclass(frozen=True)
class FfprobeMediaProbe:
    ffprobe_path: str = "ffprobe"
    process_runner: ProcessRunner = run_process

    def duration_ms(self, media_path: str) -> int:
        command = (
            self.ffprobe_path,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            media_path,
        )
        result = self.process_runner(command, check=False)
        if not result.ok:
            raise ProcessExecutionError(result)
        try:
            payload = json.loads(result.stdout)
            seconds = Decimal(str(payload["format"]["duration"]))
            duration = int((seconds * 1000).quantize(Decimal("1"), ROUND_HALF_UP))
        except (KeyError, TypeError, ValueError, InvalidOperation, json.JSONDecodeError) as error:
            raise RuntimeError("ffprobe did not return a valid media duration") from error
        if duration <= 0:
            raise RuntimeError("media duration must be positive")
        return duration


class PyannoteVadDetector:
    def __init__(
        self,
        *,
        pyannote_version: str,
        auth_token: str | None = None,
        pipeline_loader: Callable[..., Any] | None = None,
        audio_loader: AudioLoader | None = None,
    ) -> None:
        self._identity = ProviderIdentity("pyannote", pyannote_version)
        self._auth_token = auth_token
        self._pipeline_loader = pipeline_loader
        self._audio_loader = audio_loader
        self._pipelines: dict[tuple[str, str, float, float], Any] = {}

    @property
    def identity(self) -> ProviderIdentity:
        return self._identity

    def detect(
        self, audio_path: str, config: VadConfig
    ) -> tuple[VadRegion, ...]:
        pipeline = self._pipeline(config)
        loader = self._audio_loader or self._default_audio_loader
        output = pipeline(loader(audio_path))
        timeline = output.get_timeline().support()
        regions = tuple(
            VadRegion(
                id=f"vr{position}",
                start_ms=_seconds_to_ms(segment.start),
                end_ms=_seconds_to_ms(segment.end),
            )
            for position, segment in enumerate(timeline, start=1)
        )
        return regions

    def _pipeline(self, config: VadConfig) -> Any:
        cache_key = (
            config.model,
            config.model_version,
            float(config.onset),
            float(config.offset),
        )
        if cache_key in self._pipelines:
            return self._pipelines[cache_key]
        loader = self._pipeline_loader or self._default_pipeline_loader
        pipeline = loader(
            config.model,
            model_version=config.model_version,
            auth_token=self._auth_token,
        )
        if hasattr(pipeline, "instantiate"):
            pipeline.instantiate(
                {
                    "onset": float(config.onset),
                    "offset": float(config.offset),
                    "min_duration_on": 0.0,
                    "min_duration_off": 0.0,
                }
            )
        self._pipelines[cache_key] = pipeline
        return pipeline

    @staticmethod
    def _default_pipeline_loader(
        model: str, *, model_version: str, auth_token: str | None
    ) -> Any:
        try:
            from pyannote.audio import Model
            from pyannote.audio.pipelines import VoiceActivityDetection
        except ImportError as error:
            raise RuntimeError("pyannote.audio is required for VAD") from error
        kwargs: dict[str, Any] = {}
        if model_version != "default":
            kwargs["revision"] = model_version
        if auth_token is not None:
            kwargs["token"] = auth_token
        segmentation = Model.from_pretrained(model, **kwargs)
        if segmentation is None:
            raise RuntimeError(f"pyannote model could not be loaded: {model}")
        return VoiceActivityDetection(segmentation=segmentation)

    @staticmethod
    def _default_audio_loader(audio_path: str) -> Mapping[str, Any]:
        try:
            import torch
        except ImportError as error:
            raise RuntimeError("torch is required for pyannote VAD") from error
        try:
            with wave.open(audio_path, "rb") as source:
                channels = source.getnchannels()
                sample_width = source.getsampwidth()
                sample_rate = source.getframerate()
                frames = source.readframes(source.getnframes())
        except (OSError, wave.Error) as error:
            raise RuntimeError(f"cannot read canonical WAV audio: {audio_path}") from error
        if channels != 1 or sample_width != 2:
            raise RuntimeError("pyannote VAD requires mono signed 16-bit PCM WAV audio")
        waveform = (
            torch.frombuffer(bytearray(frames), dtype=torch.int16)
            .to(torch.float32)
            .reshape(1, -1)
            / 32768.0
        )
        return {"waveform": waveform, "sample_rate": sample_rate}


class WhisperXAsrEngine:
    PRODUCTION_MODEL = "large-v3"

    def __init__(
        self,
        *,
        whisperx_version: str,
        model_loader: Callable[..., Any] | None = None,
    ) -> None:
        self._identity = ProviderIdentity("whisperx", whisperx_version)
        self._model_loader = model_loader
        self._models: dict[tuple[Any, ...], Any] = {}

    @property
    def identity(self) -> ProviderIdentity:
        return self._identity

    def transcribe(
        self, audio_path: str, vad: VadArtifact, config: AsrConfig
    ) -> tuple[RawAsrSegment, ...]:
        if (
            config.profile.value == "production"
            and config.model != self.PRODUCTION_MODEL
        ):
            raise ValueError("WhisperX production profile must use large-v3")
        model = self._model(config, vad.config)
        result = model.transcribe(
            audio_path,
            batch_size=config.batch_size,
            language=config.language,
            task=config.task,
        )
        raw_segments = result.get("segments", [])
        if not isinstance(raw_segments, list):
            raise RuntimeError("WhisperX result segments must be an array")
        return tuple(
            RawAsrSegment(
                id=f"seg{position}",
                text=segment["text"],
                start_ms=_seconds_to_ms(segment["start"]),
                end_ms=_seconds_to_ms(segment["end"]),
            )
            for position, segment in enumerate(raw_segments, start=1)
        )

    def _model(self, config: AsrConfig, vad_config: VadConfig) -> Any:
        key = (
            config.profile.value,
            config.model,
            config.device,
            config.compute_type,
            config.language,
            config.task,
            config.beam_size,
            float(vad_config.onset),
            float(vad_config.offset),
        )
        if key in self._models:
            return self._models[key]
        loader = self._model_loader or self._default_model_loader
        model = loader(
            config.model,
            config.device,
            compute_type=config.compute_type,
            language=config.language,
            task=config.task,
            asr_options={"beam_size": config.beam_size},
            vad_method="pyannote",
            vad_options={
                "vad_onset": float(vad_config.onset),
                "vad_offset": float(vad_config.offset),
            },
        )
        self._models[key] = model
        return model

    @staticmethod
    def _default_model_loader(*args: Any, **kwargs: Any) -> Any:
        try:
            import whisperx
        except ImportError as error:
            raise RuntimeError("whisperx is required for ASR") from error
        return whisperx.load_model(*args, **kwargs)


class WhisperXForcedAligner:
    def __init__(
        self,
        *,
        whisperx_version: str,
        backend: Any | None = None,
        model_resolver: AlignmentModelResolver | None = None,
    ) -> None:
        self._identity = ProviderIdentity("whisperx", whisperx_version)
        self._backend_instance = backend
        self._model_resolver = model_resolver
        self._models: dict[tuple[str, str, str], tuple[Any, Any]] = {}

    @property
    def identity(self) -> ProviderIdentity:
        return self._identity

    def align(
        self,
        audio_path: str,
        raw_asr: RawAsrArtifact,
        tokens: tuple[RawAsrToken, ...],
        config: ForcedAlignmentConfig,
    ) -> tuple[AlignmentCandidate, ...]:
        backend = self._backend()
        audio = backend.load_audio(audio_path)
        model, metadata = self._alignment_model(backend, config)
        segments = [
            {
                "id": segment.id,
                "text": segment.text,
                "start": segment.start_ms / 1000,
                "end": segment.end_ms / 1000,
            }
            for segment in raw_asr.segments
        ]
        result = backend.align(
            segments,
            model,
            metadata,
            audio,
            config.device,
            return_char_alignments=False,
        )
        word_segments = result.get("word_segments", [])
        if not isinstance(word_segments, list):
            raise RuntimeError("WhisperX alignment word_segments must be an array")
        provider_words: list[tuple[str, int | None, int | None, float | None]] = []
        for provider_word in word_segments:
            text = provider_word.get("word")
            if not isinstance(text, str):
                raise RuntimeError("WhisperX aligned word text must be a string")
            surfaces = tokenize_surface_text(text) if text.strip() else ()
            if not surfaces:
                continue
            start = provider_word.get("start")
            end = provider_word.get("end")
            if (start is None) != (end is None):
                raise RuntimeError("WhisperX returned a partially timed aligned word")
            if start is None:
                spans = ((None, None),) * len(surfaces)
                score = None
            else:
                start_ms = _seconds_to_ms(start)
                end_ms = _seconds_to_ms(end)
                if end_ms - start_ms < len(surfaces):
                    raise RuntimeError("WhisperX compound word timing is too short")
                spans = tuple(
                    (
                        start_ms + (end_ms - start_ms) * index // len(surfaces),
                        start_ms
                        + (end_ms - start_ms) * (index + 1) // len(surfaces),
                    )
                    for index in range(len(surfaces))
                )
                score = float(provider_word.get("score", 1.0))
            provider_words.extend(
                (surface, word_start, word_end, score)
                for surface, (word_start, word_end) in zip(surfaces, spans)
            )
        if len(provider_words) != len(tokens):
            raise RuntimeError(
                "WhisperX alignment did not preserve raw lexical word coverage"
            )
        candidates: list[AlignmentCandidate] = []
        for token, (text, start_ms, end_ms, score) in zip(tokens, provider_words):
            surface = _restore_raw_trailing_punctuation(text.strip(), token.text)
            if start_ms is None:
                candidates.append(
                    AlignmentCandidate(
                        raw_word_id=token.id,
                        segment_id=token.segment_id,
                        text=surface,
                        start_ms=None,
                        end_ms=None,
                        alignment_score=None,
                        unaligned_reason="alignment_model_no_timing",
                    )
                )
                continue
            candidates.append(
                AlignmentCandidate(
                    raw_word_id=token.id,
                    segment_id=token.segment_id,
                    text=surface,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    alignment_score=score,
                )
            )
        return tuple(candidates)

    def _alignment_model(
        self, backend: Any, config: ForcedAlignmentConfig
    ) -> tuple[Any, Any]:
        key = (config.model, config.model_version, config.device)
        if key not in self._models:
            resolver = self._model_resolver or _resolve_huggingface_model_snapshot
            model_path = resolver(config.model, config.model_version)
            self._models[key] = backend.load_align_model(
                language_code=config.language,
                device=config.device,
                model_name=model_path,
            )
        return self._models[key]

    def _backend(self) -> Any:
        if self._backend_instance is None:
            try:
                import whisperx
            except ImportError as error:
                raise RuntimeError("whisperx is required for forced alignment") from error
            self._backend_instance = whisperx
        return self._backend_instance


class WhisperXOfficialTranscriptAligner:
    """Evaluate spoken readings inside a bounded acoustic window."""

    def __init__(
        self,
        *,
        whisperx_version: str,
        backend: Any | None = None,
        model_resolver: AlignmentModelResolver | None = None,
    ) -> None:
        self._identity = ProviderIdentity("whisperx", whisperx_version)
        self._backend_instance = backend
        self._model_resolver = model_resolver
        self._models: dict[tuple[str, str, str], tuple[Any, Any]] = {}

    @property
    def identity(self) -> ProviderIdentity:
        return self._identity

    def align_official(
        self,
        audio_path: str,
        tokens: tuple[OfficialTranscriptToken, ...],
        left_anchor: AlignedAsrWord,
        right_anchor: AlignedAsrWord,
        config: OfficialAlignmentConfig,
    ) -> tuple[OfficialAlignmentCandidate, ...]:
        backend = self._backend()
        audio = backend.load_audio(audio_path)
        model, metadata = self._alignment_model(backend, config)
        result = backend.align(
            [
                {
                    "text": " ".join(token.text for token in tokens),
                    "start": left_anchor.end_ms / 1000,
                    "end": right_anchor.start_ms / 1000,
                }
            ],
            model,
            metadata,
            audio,
            config.device,
            return_char_alignments=False,
        )
        word_segments = result.get("word_segments", [])
        if not isinstance(word_segments, list) or len(word_segments) != len(tokens):
            raise RuntimeError(
                "WhisperX local alignment did not preserve official word coverage"
            )
        candidates: list[OfficialAlignmentCandidate] = []
        for token, provider_word in zip(tokens, word_segments):
            if not isinstance(provider_word, Mapping):
                raise RuntimeError("WhisperX local aligned word must be an object")
            text = provider_word.get("word")
            start = provider_word.get("start")
            end = provider_word.get("end")
            score = provider_word.get("score")
            if not isinstance(text, str) or start is None or end is None or score is None:
                raise RuntimeError(
                    "WhisperX local aligned word requires text, time, and score"
                )
            candidates.append(
                OfficialAlignmentCandidate(
                    official_token_id=token.id,
                    text=text.strip(),
                    start_ms=_seconds_to_ms(start),
                    end_ms=_seconds_to_ms(end),
                    alignment_score=score,
                )
            )
        return tuple(candidates)

    def align_official_window(
        self,
        audio_path: str,
        tokens: tuple[OfficialTranscriptToken, ...],
        start_ms: int,
        end_ms: int,
        config: OfficialAlignmentConfig,
    ) -> tuple[OfficialAlignmentCandidate, ...]:
        token_readings = tuple(fusion_candidate_text(token.text) for token in tokens)
        word_counts = tuple(len(reading.split()) for reading in token_readings)
        readings = (" ".join(token_readings),)
        # A trailing interruption can leave a written currency implicit in
        # speech. Both readings keep the same amount and are scored together.
        if (
            tokens and tokens[-1].text.endswith("—") and word_counts[-1] > 1
            and token_readings[-1] != tokens[-1].text
            and any(unicodedata.category(character) == "Sc" for character in tokens[-1].text)
        ):
            shortened = token_readings[-1].rsplit(" ", 1)[0]
            readings += (" ".join((*token_readings[:-1], shortened)),)
        scores = self.score_candidates(audio_path, start_ms, end_ms, readings, config)
        evidence = scores[0]
        if len(scores) == 2:
            shorthand = scores[1]
            if (
                shorthand.ctc_log_likelihood is not None
                and len(shorthand.word_evidence) == sum(word_counts) - 1
                and (
                    evidence.ctc_log_likelihood is None
                    or (
                        evidence.word_evidence
                        and evidence.word_evidence[-1].score < config.min_alignment_score
                        and shorthand.ctc_log_likelihood >= evidence.ctc_log_likelihood
                    )
                )
            ):
                evidence = shorthand
                word_counts = (*word_counts[:-1], word_counts[-1] - 1)
        if 0 in word_counts or len(evidence.word_evidence) != sum(word_counts):
            raise RuntimeError("local CTC alignment did not preserve official word coverage")

        candidates = []
        offset = 0
        for token, count in zip(tokens, word_counts, strict=True):
            words = evidence.word_evidence[offset:offset + count]
            # A written amount covers its actual spoken components, and its
            # weakest component determines whether the full amount can publish.
            candidates.append(OfficialAlignmentCandidate(
                token.id, token.text, words[0].start_ms, words[-1].end_ms,
                min(word.score for word in words),
            ))
            offset += count
        return tuple(candidates)

    def score_candidates(
        self,
        audio_path: str,
        start_ms: int,
        end_ms: int,
        readings: tuple[str, ...],
        config: OfficialAlignmentConfig,
    ) -> tuple[AcousticCandidateEvidence, ...]:
        import torch

        waveform = _read_pcm_window(audio_path, start_ms, end_ms)
        pcm_end_ms = start_ms + waveform.shape[-1] // 16
        model, metadata = self._alignment_model(self._backend(), config)
        waveform_for_model = waveform.to(config.device)
        if waveform.shape[-1] < 400:
            waveform_for_model = torch.nn.functional.pad(
                waveform_for_model, (0, 400 - waveform.shape[-1])
            )
        with torch.inference_mode():
            if metadata["type"] == "torchaudio":
                logits, _ = model(waveform_for_model)
            elif metadata["type"] == "huggingface":
                logits = model(waveform_for_model).logits
            else:
                raise ValueError("alignment model does not provide CTC logits")
            log_probabilities = logits[0].float().log_softmax(dim=-1).cpu()

        dictionary = metadata["dictionary"]
        blank = dictionary.get("<pad>", dictionary.get("[pad]", 0))
        return tuple(
            _score_ctc_reading(reading, dictionary, blank, log_probabilities, waveform, start_ms, pcm_end_ms)
            for reading in readings
        )

    def _alignment_model(
        self, backend: Any, config: OfficialAlignmentConfig
    ) -> tuple[Any, Any]:
        key = (config.model, config.model_version, config.device)
        if key not in self._models:
            resolver = self._model_resolver or _resolve_huggingface_model_snapshot
            model_path = resolver(config.model, config.model_version)
            self._models[key] = backend.load_align_model(
                language_code=config.language,
                device=config.device,
                model_name=model_path,
            )
        return self._models[key]

    def _backend(self) -> Any:
        if self._backend_instance is None:
            try:
                import whisperx
            except ImportError as error:
                raise RuntimeError(
                    "whisperx is required for official transcript alignment"
                ) from error
            self._backend_instance = whisperx
        return self._backend_instance


def _read_pcm_window(audio_path: str, start_ms: int, end_ms: int) -> Any:
    import torch

    if not 0 <= start_ms < end_ms:
        raise ValueError("local alignment requires a positive audio window")
    frame_start, frame_end = start_ms * 16, end_ms * 16
    with wave.open(audio_path, "rb") as source:
        if (source.getnchannels(), source.getsampwidth(), source.getframerate()) != (1, 2, 16000):
            raise ValueError("local alignment requires mono 16 kHz signed 16-bit PCM WAV audio")
        frame_end = min(frame_end, source.getnframes() // 16 * 16)
        if frame_start >= frame_end:
            raise ValueError("local alignment window contains no recorded PCM audio")
        source.setpos(frame_start)
        frames = source.readframes(frame_end - frame_start)
    if len(frames) != 2 * (frame_end - frame_start):
        raise ValueError("local alignment window contains truncated PCM audio")
    return torch.frombuffer(bytearray(frames), dtype=torch.int16).float().reshape(1, -1) / 32768.0


def _score_ctc_reading(
    reading: str,
    dictionary: Mapping[str, int],
    blank: int,
    log_probabilities: Any,
    waveform: Any,
    start_ms: int,
    end_ms: int,
) -> AcousticCandidateEvidence:
    import math
    import numpy as np
    import torch

    normalized = unicodedata.normalize("NFKC", reading).casefold().replace("’", "'")
    words = tuple(
        word for word in (
            "".join(character for character in chunk if character.isalnum() or character in "'-").strip("'-")
            for chunk in normalized.split()
        ) if word
    )
    if not reading.strip():
        likelihood = float(log_probabilities[:, blank].sum())
        return AcousticCandidateEvidence(likelihood if math.isfinite(likelihood) else None)
    if not words:
        return AcousticCandidateEvidence(None)

    try:
        labels = [dictionary[character] for character in "|".join(words)]
    except KeyError:
        return AcousticCandidateEvidence(None)
    frame_count = log_probabilities.shape[0]
    if len(labels) + sum(left == right for left, right in zip(labels, labels[1:])) > frame_count:
        return AcousticCandidateEvidence(None)
    likelihood = -float(torch.nn.functional.ctc_loss(
        log_probabilities.unsqueeze(1),
        torch.as_tensor(labels, dtype=torch.long),
        (frame_count,),
        (len(labels),),
        blank=blank,
        reduction="sum",
    ))
    if not math.isfinite(likelihood):
        return AcousticCandidateEvidence(None)

    emissions = log_probabilities.numpy()
    path = _ctc_best_state_path(emissions, labels, blank)
    character_frames = tuple(np.flatnonzero(path == 2 * index + 1) for index in range(len(labels)))
    character_scores = tuple(
        float(np.exp(emissions[frames, label]).mean())
        for frames, label in zip(character_frames, labels, strict=True)
    )
    audio_energy = waveform.square()[0]
    total_energy = float(audio_energy.sum())
    covered_energy = 0.0
    evidence = []
    scores = []
    weak_run = longest_weak_run = 0
    index = 0
    for word in words:
        end_index = index + len(word)
        first_frame = int(character_frames[index][0])
        last_frame = int(character_frames[end_index - 1][-1]) + 1
        word_start = start_ms + round(first_frame * (end_ms - start_ms) / frame_count)
        word_end = start_ms + round(last_frame * (end_ms - start_ms) / frame_count)
        if word_start >= word_end:
            return AcousticCandidateEvidence(likelihood)
        word_scores = character_scores[index:end_index]
        evidence.append(AcousticWordEvidence(word, word_start, word_end, sum(word_scores) / len(word_scores)))
        scores.extend(word_scores)
        covered_energy += float(audio_energy[(word_start - start_ms) * 16:(word_end - start_ms) * 16].sum())
        for score in word_scores:
            weak_run = weak_run + 1 if score < 0.05 else 0
            longest_weak_run = max(longest_weak_run, weak_run)
        index = end_index + 1  # Skip the word-delimiter label.

    weakest = sorted(scores)[:2]
    return AcousticCandidateEvidence(
        ctc_log_likelihood=likelihood,
        start_ms=evidence[0].start_ms,
        end_ms=evidence[-1].end_ms,
        mean_character_score=sum(scores) / len(scores),
        weakest_two_mean=sum(weakest) / len(weakest),
        energy_coverage=min(1.0, covered_energy / total_energy) if total_energy else 0.0,
        longest_weak_character_run=longest_weak_run,
        word_evidence=tuple(evidence),
    )


def _ctc_best_state_path(emissions: Any, labels: list[int], blank: int) -> Any:
    """Backtrack the most likely complete path, including CTC blank states."""
    import numpy as np

    states = np.full(2 * len(labels) + 1, blank)
    states[1::2] = labels
    indices = np.arange(len(states))
    # A two-state jump bypasses a blank only between different characters.
    skip_allowed = (states[2:] != blank) & (states[2:] != states[:-2])
    previous = np.full(len(states), -np.inf)
    previous[0] = 0.0
    transitions = np.empty((len(emissions), len(states)), dtype=np.uint8)
    for index, frame in enumerate(emissions):
        stay = previous
        advance = np.concatenate(([-np.inf], previous[:-1]))
        skip = np.concatenate(([-np.inf, -np.inf], np.where(skip_allowed, previous[:-2], -np.inf)))
        candidates = np.stack((stay, advance, skip))
        offsets = candidates.argmax(axis=0)
        transitions[index] = offsets
        previous = candidates[offsets, indices] + frame[states]

    state = len(states) - 1 if previous[-1] >= previous[-2] else len(states) - 2
    path = np.empty(len(emissions), dtype=np.int32)
    for index in range(len(emissions) - 1, -1, -1):
        path[index] = state
        state -= int(transitions[index, state])
    return path


class LocalTranscriptionArtifactStore:
    def exists(self, path: str) -> bool:
        return Path(path).exists()

    def size(self, path: str) -> int:
        return Path(path).stat().st_size

    def read_json(self, path: str) -> Mapping[str, Any]:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("artifact JSON root must be an object")
        return data

    def write_json(
        self, path: str, data: Mapping[str, Any], *, overwrite: bool
    ) -> str:
        return str(write_json_file(path, dict(data), overwrite=overwrite))

    def write_text(self, path: str, text: str, *, overwrite: bool) -> str:
        target = Path(path)
        if target.exists() and not overwrite:
            raise FileExistsError(f"Refusing to overwrite existing file: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                stream.write(text)
                temporary = Path(stream.name)
            temporary.replace(target)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
        return str(target)

    def publish_json_pair(
        self,
        canonical_path: str,
        canonical_data: Mapping[str, Any],
        manifest_path: str,
        manifest_factory: Callable[[int, str], Mapping[str, Any]],
        *,
        overwrite: bool,
    ) -> tuple[int, str]:
        """Atomically replace a canonical JSON file and its manifest together."""
        canonical = Path(canonical_path)
        manifest = Path(manifest_path)
        if canonical.parent != manifest.parent:
            raise ValueError("canonical artifact and manifest must share a directory")
        if not overwrite and canonical.exists():
            raise FileExistsError(f"Refusing to overwrite existing file: {canonical}")
        canonical.parent.mkdir(parents=True, exist_ok=True)

        staged: list[Path] = []
        backups: dict[Path, Path] = {}
        installed: list[Path] = []
        try:
            canonical_stage = self._stage_json(canonical, canonical_data)
            staged.append(canonical_stage)
            canonical_bytes = canonical_stage.read_bytes()
            canonical_sha256 = hashlib.sha256(canonical_bytes).hexdigest()
            manifest_data = manifest_factory(len(canonical_bytes), canonical_sha256)
            manifest_stage = self._stage_json(manifest, manifest_data)
            staged.append(manifest_stage)

            for target in (canonical, manifest):
                if target.exists():
                    backup = self._stage_bytes(target, target.read_bytes())
                    backups[target] = backup
                    staged.append(backup)

            canonical_stage.replace(canonical)
            installed.append(canonical)
            manifest_stage.replace(manifest)
            installed.append(manifest)
            return len(canonical_bytes), canonical_sha256
        except Exception:
            for target in reversed(installed):
                backup = backups.get(target)
                if backup is not None and backup.exists():
                    backup.replace(target)
                elif target.exists():
                    target.unlink()
            raise
        finally:
            for path in staged:
                if path.exists():
                    path.unlink()

    @staticmethod
    def _stage_json(target: Path, data: Mapping[str, Any]) -> Path:
        return LocalTranscriptionArtifactStore._stage_text(
            target,
            json.dumps(dict(data), ensure_ascii=False, indent=2) + "\n",
        )

    @staticmethod
    def _stage_bytes(target: Path, data: bytes) -> Path:
        temporary: Path | None = None
        try:
            with NamedTemporaryFile(
                "wb",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                stream.write(data)
                temporary = Path(stream.name)
            return temporary
        except Exception:
            if temporary is not None and temporary.exists():
                temporary.unlink()
            raise

    @staticmethod
    def _stage_text(target: Path, text: str) -> Path:
        temporary: Path | None = None
        try:
            with NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                stream.write(text)
                temporary = Path(stream.name)
            return temporary
        except Exception:
            if temporary is not None and temporary.exists():
                temporary.unlink()
            raise


class Sha256ChecksumService:
    def sha256(self, path: str) -> str:
        digest = hashlib.sha256()
        with Path(path).open("rb") as file_obj:
            for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()


def _seconds_to_ms(value: object) -> int:
    try:
        milliseconds = int(
            (Decimal(str(value)) * 1000).quantize(Decimal("1"), ROUND_HALF_UP)
        )
    except (InvalidOperation, ValueError) as error:
        raise ValueError("timestamp must be numeric seconds") from error
    if milliseconds < 0:
        raise ValueError("timestamp must be non-negative")
    return milliseconds


def _resolve_huggingface_model_snapshot(model: str, model_version: str) -> str:
    """Resolve the configured Hugging Face revision before WhisperX loads it."""

    try:
        from huggingface_hub import snapshot_download
    except ImportError as error:
        raise RuntimeError(
            "huggingface_hub is required to resolve alignment model revisions"
        ) from error
    return snapshot_download(repo_id=model, revision=model_version)
