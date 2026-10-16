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
    """Locally align official-only tokens inside a bounded acoustic window."""

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
