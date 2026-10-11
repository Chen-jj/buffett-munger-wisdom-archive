from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

import pytest

from archive_core.application import build_asset_workspace
from archive_core.domain import AssetId, ArtifactType, canonical_filename
from infrastructure.infrastructure.process import ProcessResult
from transcription.application import (
    AudioExtractionConfig,
    AudioVadAsrPolicy,
    AudioVadAsrService,
    EventCode,
    ExistingTranscriptionArtifactConflict,
    SourceVideoInput,
    SourceVideoValidationError,
    TranscriptionEvent,
)
from transcription.domain import (
    AsrConfig,
    ProviderIdentity,
    RawAsrArtifact,
    RawAsrSegment,
    TranscriptionProfile,
    VadArtifact,
    VadConfig,
    VadRegion,
    build_vad_chunks,
)
from transcription.infrastructure import (
    AudioExtractionResult,
    FfmpegAudioExtractor,
    FfprobeMediaProbe,
    PyannoteVadDetector,
    WhisperXAsrEngine,
)


ASSET_ID = AssetId("cnbc", "1994", "morning")


def _vad_config(**changes: object) -> VadConfig:
    return replace(
        VadConfig(
            model="pyannote/voice-activity-detection",
            model_version="2026.1",
        ),
        **changes,
    )


def _development_asr(model: str = "tiny.en") -> AsrConfig:
    return AsrConfig.development(model=model)


class MemoryArtifactStore:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.json_objects: dict[str, dict[str, Any]] = {}
        self.write_calls: list[tuple[str, bool]] = []

    def exists(self, path: str) -> bool:
        return path in self.files

    def size(self, path: str) -> int:
        return len(self.files[path])

    def read_json(self, path: str) -> Mapping[str, Any]:
        return json.loads(self.files[path].decode("utf-8"))

    def write_json(
        self, path: str, data: Mapping[str, Any], *, overwrite: bool
    ) -> str:
        if path in self.files and not overwrite:
            raise FileExistsError(path)
        copied = json.loads(json.dumps(data))
        self.json_objects[path] = copied
        self.files[path] = json.dumps(
            copied, ensure_ascii=False, sort_keys=True
        ).encode("utf-8")
        self.write_calls.append((path, overwrite))
        return path


class MemoryChecksum:
    def __init__(self, store: MemoryArtifactStore) -> None:
        self.store = store
        self.paths: list[str] = []

    def sha256(self, path: str) -> str:
        self.paths.append(path)
        return hashlib.sha256(self.store.files[path]).hexdigest()


class FakeAudioExtractor:
    def __init__(self, store: MemoryArtifactStore) -> None:
        self.store = store
        self.identity = ProviderIdentity("fake-ffmpeg", "7.1")
        self.calls: list[tuple[str, str, AudioExtractionConfig, bool]] = []

    def extract(
        self,
        video_path: str,
        output_path: str,
        config: AudioExtractionConfig,
        *,
        overwrite: bool,
    ) -> AudioExtractionResult:
        self.calls.append((video_path, output_path, config, overwrite))
        if output_path in self.store.files and not overwrite:
            raise FileExistsError(output_path)
        self.store.files[output_path] = b"canonical wav payload"
        return AudioExtractionResult(("fake-ffmpeg", video_path, output_path))


class FakeVadDetector:
    def __init__(self) -> None:
        self.identity = ProviderIdentity("fake-pyannote", "4.0")
        self.calls: list[tuple[str, VadConfig]] = []

    def detect(self, audio_path: str, config: VadConfig) -> tuple[VadRegion, ...]:
        self.calls.append((audio_path, config))
        return (
            VadRegion("vr1", 1_000, 2_000),
            VadRegion("vr2", 3_000, 3_500),
        )


class FakeAsrEngine:
    def __init__(self) -> None:
        self.identity = ProviderIdentity("fake-whisperx", "3.8.5")
        self.calls: list[tuple[str, VadArtifact, AsrConfig]] = []

    def transcribe(
        self, audio_path: str, vad: VadArtifact, config: AsrConfig
    ) -> tuple[RawAsrSegment, ...]:
        self.calls.append((audio_path, vad, config))
        return (
            RawAsrSegment("seg1", "Good morning.", 1_050, 2_000),
            RawAsrSegment("seg2", "Welcome.", 3_050, 3_450),
        )


class FakeProbe:
    def __init__(self, duration_ms: int = 5_000) -> None:
        self.value = duration_ms
        self.paths: list[str] = []

    def duration_ms(self, media_path: str) -> int:
        self.paths.append(media_path)
        return self.value


class MemoryEventSink:
    def __init__(self) -> None:
        self.events: list[TranscriptionEvent] = []

    def emit(self, event: TranscriptionEvent) -> None:
        self.events.append(event)

    def flush(self) -> None:
        pass


def _source(store: MemoryArtifactStore, output_root: Path) -> SourceVideoInput:
    path = str(
        build_asset_workspace(ASSET_ID, output_root)
        / canonical_filename(ArtifactType.SOURCE_VIDEO)
    )
    store.files.setdefault(path, b"verified source video")
    return SourceVideoInput(
        asset_id=ASSET_ID,
        path=path,
        manifest_asset_id=ASSET_ID,
        manifest_status="downloaded",
        size_bytes=len(store.files[path]),
        checksum_algorithm="sha256",
        checksum_value=hashlib.sha256(store.files[path]).hexdigest(),
    )


def _service(store: MemoryArtifactStore, output_root: Path):
    extractor = FakeAudioExtractor(store)
    vad = FakeVadDetector()
    asr = FakeAsrEngine()
    probe = FakeProbe()
    events = MemoryEventSink()
    service = AudioVadAsrService(
        audio_extractor=extractor,
        vad_detector=vad,
        asr_engine=asr,
        media_probe=probe,
        checksum=MemoryChecksum(store),
        artifacts=store,
        events=events,
        output_root=str(output_root),
    )
    return service, extractor, vad, asr, probe, events


def test_audio_and_asr_configs_fix_canonical_production_behavior() -> None:
    audio = AudioExtractionConfig()
    production = AsrConfig.production(
        model="large-v3",
        device="cuda",
        compute_type="float16",
        batch_size=16,
        beam_size=5,
    )
    development = _development_asr()

    assert audio.to_dict() == {
        "sample_rate_hz": 16_000,
        "channels": 1,
        "sample_format": "s16",
        "codec": "pcm_s16le",
    }
    assert production.profile is TranscriptionProfile.PRODUCTION
    assert production.model == "large-v3"
    assert production.language == "en"
    assert production.task == "transcribe"
    assert development.profile is TranscriptionProfile.DEVELOPMENT
    assert development.model == "tiny.en"

    with pytest.raises(ValueError, match="16 kHz mono"):
        AudioExtractionConfig(sample_rate_hz=44_100)
    with pytest.raises(ValueError, match="language must be en"):
        replace(development, language="zh")
    with pytest.raises(ValueError, match="task must be transcribe"):
        replace(development, task="translate")


def test_vad_chunk_mapping_round_trips_across_cut_regions_without_time_loss() -> None:
    regions = (
        VadRegion("vr1", 1_000, 2_000),
        VadRegion("vr2", 3_000, 3_500),
    )
    config = _vad_config(padding_ms=100, merge_gap_ms=1_000)

    chunks = build_vad_chunks(regions, duration_ms=5_000, config=config)

    assert len(chunks) == 1
    assert chunks[0].to_dict() == {
        "id": "vc1",
        "duration_ms": 1_900,
        "mappings": [
            {
                "chunk_start_ms": 0,
                "chunk_end_ms": 1_200,
                "source_start_ms": 900,
                "source_end_ms": 2_100,
            },
            {
                "chunk_start_ms": 1_200,
                "chunk_end_ms": 1_900,
                "source_start_ms": 2_900,
                "source_end_ms": 3_600,
            },
        ],
    }
    assert [span.to_dict() for span in chunks[0].map_range_to_source(1_100, 1_300)] == [
        {"start_ms": 2_000, "end_ms": 2_100},
        {"start_ms": 2_900, "end_ms": 3_000},
    ]


def test_vad_artifact_round_trips_regions_padding_and_cut_mapping() -> None:
    config = _vad_config(padding_ms=100, merge_gap_ms=1_000)
    regions = (VadRegion("vr1", 1_000, 2_000),)
    artifact = VadArtifact(
        audio_sha256="audio-hash",
        audio_duration_ms=5_000,
        provider=ProviderIdentity("pyannote", "4.0"),
        config=config,
        regions=regions,
        chunks=build_vad_chunks(regions, duration_ms=5_000, config=config),
        cache_key="vad-key",
    )

    assert VadArtifact.from_dict(artifact.to_dict()) == artifact
    assert artifact.to_dict()["config"]["padding_ms"] == 100
    assert artifact.to_dict()["chunks"][0]["mappings"][0]["source_start_ms"] == 900


def test_raw_asr_artifact_round_trips_fixed_language_task_and_profile() -> None:
    artifact = RawAsrArtifact(
        audio_sha256="audio-hash",
        audio_duration_ms=5_000,
        vad_cache_key="vad-key",
        provider=ProviderIdentity("whisperx", "3.8.5"),
        config=_development_asr(),
        segments=(RawAsrSegment("seg1", "Hello.", 100, 500),),
        cache_key="asr-key",
    )

    data = artifact.to_dict()

    assert data["language"] == "en"
    assert data["task"] == "transcribe"
    assert data["profile"] == "development"
    assert RawAsrArtifact.from_dict(data) == artifact


def test_ffmpeg_command_exactly_requests_canonical_pcm_audio() -> None:
    adapter = FfmpegAudioExtractor(ffmpeg_path="/tools/ffmpeg", ffmpeg_version="7.1")

    command = adapter.build_command(
        "/work/video.mp4",
        "/work/audio.wav",
        AudioExtractionConfig(),
        overwrite=False,
    )

    assert command == (
        "/tools/ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-n",
        "-i",
        "/work/video.mp4",
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        "-sample_fmt",
        "s16",
        "/work/audio.wav",
    )
    assert adapter.identity == ProviderIdentity("ffmpeg", "7.1")


def test_ffmpeg_adapter_uses_injected_process_runner() -> None:
    calls: list[tuple[str, ...]] = []

    def runner(command, **kwargs):
        calls.append(tuple(command))
        return ProcessResult(tuple(command), 0, "", "")

    adapter = FfmpegAudioExtractor(
        ffmpeg_version="7.1", process_runner=runner
    )

    result = adapter.extract(
        "video.mp4", "audio.wav", AudioExtractionConfig(), overwrite=True
    )

    assert calls == [result.command]
    assert "-y" in result.command


def test_ffprobe_adapter_parses_duration_without_real_process() -> None:
    def runner(command, **kwargs):
        return ProcessResult(
            tuple(command), 0, json.dumps({"format": {"duration": "5.1256"}}), ""
        )

    assert FfprobeMediaProbe(process_runner=runner).duration_ms("video.mp4") == 5_126


def test_pyannote_adapter_loads_lazily_and_returns_integer_source_regions() -> None:
    loads: list[tuple[str, dict[str, Any]]] = []

    class Pipeline:
        parameters: dict[str, float] | None = None

        def instantiate(self, parameters: dict[str, float]) -> None:
            self.parameters = parameters

        def __call__(self, audio_path: str):
            assert audio_path == "audio.wav"
            timeline = [
                SimpleNamespace(start=1.001, end=2.009),
                SimpleNamespace(start=3.0, end=3.5),
            ]
            return SimpleNamespace(
                get_timeline=lambda: SimpleNamespace(support=lambda: timeline)
            )

    pipeline = Pipeline()

    def loader(model: str, **kwargs):
        loads.append((model, kwargs))
        return pipeline

    detector = PyannoteVadDetector(
        pyannote_version="4.0", auth_token="not-logged", pipeline_loader=loader
    )
    config = _vad_config(onset=0.6, offset=0.4)

    assert loads == []
    assert detector.detect("audio.wav", config) == (
        VadRegion("vr1", 1_001, 2_009),
        VadRegion("vr2", 3_000, 3_500),
    )
    assert loads == [
        (
            "pyannote/voice-activity-detection",
            {"model_version": "2026.1", "auth_token": "not-logged"},
        )
    ]
    assert pipeline.parameters == {"onset": 0.6, "offset": 0.4}


def test_whisperx_adapter_uses_fixed_english_transcribe_and_pyannote() -> None:
    load_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    class Model:
        def transcribe(self, audio_path: str, **kwargs):
            assert audio_path == "audio.wav"
            assert kwargs == {
                "batch_size": 2,
                "language": "en",
                "task": "transcribe",
            }
            return {
                "segments": [
                    {"start": 1.001, "end": 2.009, "text": "Hello."}
                ]
            }

    def loader(*args, **kwargs):
        load_calls.append((args, kwargs))
        return Model()

    engine = WhisperXAsrEngine(whisperx_version="3.8.5", model_loader=loader)
    config = AsrConfig.production(
        model="large-v3",
        device="cpu",
        compute_type="int8",
        batch_size=2,
        beam_size=3,
    )
    vad_config = _vad_config(onset=0.6, offset=0.4)
    regions = (VadRegion("vr1", 1_000, 2_100),)
    vad = VadArtifact(
        audio_sha256="hash",
        audio_duration_ms=5_000,
        provider=ProviderIdentity("pyannote", "4.0"),
        config=vad_config,
        regions=regions,
        chunks=build_vad_chunks(regions, duration_ms=5_000, config=vad_config),
        cache_key="vad-key",
    )

    assert load_calls == []
    assert engine.transcribe("audio.wav", vad, config) == (
        RawAsrSegment("seg1", "Hello.", 1_001, 2_009),
    )
    assert load_calls == [
        (
            ("large-v3", "cpu"),
            {
                "compute_type": "int8",
                "language": "en",
                "task": "transcribe",
                "asr_options": {"beam_size": 3},
                "vad_method": "pyannote",
                "vad_options": {"vad_onset": 0.6, "vad_offset": 0.4},
            },
        )
    ]


def test_whisperx_adapter_rejects_non_large_v3_production_model() -> None:
    engine = WhisperXAsrEngine(
        whisperx_version="3.8.5",
        model_loader=lambda *args, **kwargs: pytest.fail("model must not load"),
    )
    config = AsrConfig.production(
        model="small.en", device="cpu", compute_type="int8"
    )
    vad_config = _vad_config()
    regions = (VadRegion("vr1", 100, 200),)
    vad = VadArtifact(
        audio_sha256="hash",
        audio_duration_ms=500,
        provider=ProviderIdentity("pyannote", "4.0"),
        config=vad_config,
        regions=regions,
        chunks=build_vad_chunks(regions, duration_ms=500, config=vad_config),
        cache_key="vad-key",
    )

    with pytest.raises(ValueError, match="large-v3"):
        engine.transcribe("audio.wav", vad, config)


def test_fake_application_pipeline_persists_canonical_artifacts_and_provenance(
    tmp_path: Path,
) -> None:
    store = MemoryArtifactStore()
    source = _source(store, tmp_path)
    service, extractor, vad, asr, probe, events = _service(store, tmp_path)

    result = service.execute(
        source,
        vad_config=_vad_config(padding_ms=100, merge_gap_ms=1_000),
        asr_config=_development_asr(),
    )

    workspace = build_asset_workspace(ASSET_ID, tmp_path)
    assert result.audio_path == str(workspace / "audio.wav")
    assert result.vad_path == str(workspace / "vad.json")
    assert result.raw_asr_path == str(workspace / "raw_asr.json")
    assert result.manifest_path == str(workspace / "transcription_manifest.json")
    assert len(extractor.calls) == len(vad.calls) == len(asr.calls) == 1
    assert probe.paths == [source.path]
    assert result.cache_hits == ()
    assert store.json_objects[result.vad_path]["provider"] == {
        "name": "fake-pyannote",
        "version": "4.0",
    }
    assert store.json_objects[result.raw_asr_path]["config"]["profile"] == "development"
    manifest = store.json_objects[result.manifest_path]
    assert set(manifest["records"]) == {"audio", "vad", "raw_asr"}
    assert manifest["records"]["audio"]["provenance"]["config"] == (
        AudioExtractionConfig().to_dict()
    )
    assert manifest["records"]["audio"]["provenance"]["video_sha256"] == (
        source.checksum_value
    )
    assert [event.code for event in events.events] == [
        EventCode.INPUT_VIDEO_VALIDATED,
        EventCode.AUDIO_EXTRACTED,
        EventCode.VAD_COMPLETED,
        EventCode.ASR_COMPLETED,
        EventCode.STAGE_COMPLETED,
    ]


def test_verified_cache_hit_skips_all_expensive_providers(tmp_path: Path) -> None:
    store = MemoryArtifactStore()
    source = _source(store, tmp_path)
    service, extractor, vad, asr, probe, events = _service(store, tmp_path)
    config = _development_asr()

    first = service.execute(source, vad_config=_vad_config(), asr_config=config)
    second = service.execute(source, vad_config=_vad_config(), asr_config=config)

    assert first.cache_hits == ()
    assert second.cache_hits == ("audio", "vad", "raw_asr")
    assert len(extractor.calls) == len(vad.calls) == len(asr.calls) == 1
    assert len(probe.paths) == 2
    assert [event.code for event in events.events[-4:]] == [
        EventCode.AUDIO_CACHE_HIT,
        EventCode.VAD_CACHE_HIT,
        EventCode.ASR_CACHE_HIT,
        EventCode.STAGE_COMPLETED,
    ]


@pytest.mark.parametrize(
    ("change", "category"),
    [
        ({"manifest_valid": False}, "manifest_invalid"),
        ({"manifest_asset_id": AssetId("cnbc", "1994", "other")}, "asset_mismatch"),
        ({"manifest_status": "failed"}, "status_not_successful"),
        ({"path": "/wrong/video.mp4"}, "artifact_path_mismatch"),
        ({"checksum_algorithm": "md5"}, "checksum_algorithm_mismatch"),
        ({"size_bytes": 999}, "size_mismatch"),
        ({"checksum_value": "wrong"}, "checksum_mismatch"),
    ],
)
def test_invalid_input_fails_before_probe_ffmpeg_vad_or_asr(
    tmp_path: Path, change: dict[str, object], category: str
) -> None:
    store = MemoryArtifactStore()
    source = replace(_source(store, tmp_path), **change)
    service, extractor, vad, asr, probe, events = _service(store, tmp_path)

    with pytest.raises(SourceVideoValidationError, match=category):
        service.execute(
            source, vad_config=_vad_config(), asr_config=_development_asr()
        )

    assert extractor.calls == []
    assert vad.calls == []
    assert asr.calls == []
    assert probe.paths == []
    assert events.events[-1].code is EventCode.INPUT_VIDEO_REJECTED


def test_file_existence_without_successful_manifest_never_counts_as_cache(
    tmp_path: Path,
) -> None:
    store = MemoryArtifactStore()
    source = _source(store, tmp_path)
    workspace = build_asset_workspace(ASSET_ID, tmp_path)
    store.files[str(workspace / "audio.wav")] = b"unverified audio"
    service, extractor, vad, asr, probe, events = _service(store, tmp_path)

    with pytest.raises(
        ExistingTranscriptionArtifactConflict, match="explicit overwrite required"
    ):
        service.execute(
            source, vad_config=_vad_config(), asr_config=_development_asr()
        )

    assert extractor.calls == []
    assert vad.calls == []
    assert asr.calls == []


def test_tampered_cached_artifact_requires_explicit_overwrite(tmp_path: Path) -> None:
    store = MemoryArtifactStore()
    source = _source(store, tmp_path)
    service, extractor, vad, asr, probe, events = _service(store, tmp_path)
    service.execute(
        source, vad_config=_vad_config(), asr_config=_development_asr()
    )
    audio_path = str(build_asset_workspace(ASSET_ID, tmp_path) / "audio.wav")
    store.files[audio_path] = b"tampered audio content"

    with pytest.raises(
        ExistingTranscriptionArtifactConflict, match="explicit overwrite required"
    ):
        service.execute(
            source, vad_config=_vad_config(), asr_config=_development_asr()
        )

    assert len(extractor.calls) == len(vad.calls) == len(asr.calls) == 1


def test_model_or_profile_change_invalidates_only_asr_and_requires_permission(
    tmp_path: Path,
) -> None:
    store = MemoryArtifactStore()
    source = _source(store, tmp_path)
    service, extractor, vad, asr, probe, events = _service(store, tmp_path)
    service.execute(
        source, vad_config=_vad_config(), asr_config=_development_asr("tiny.en")
    )
    changed = _development_asr("small.en")

    with pytest.raises(
        ExistingTranscriptionArtifactConflict, match="raw_asr"
    ):
        service.execute(source, vad_config=_vad_config(), asr_config=changed)
    assert len(extractor.calls) == len(vad.calls) == len(asr.calls) == 1

    result = service.execute(
        source,
        vad_config=_vad_config(),
        asr_config=changed,
        policy=AudioVadAsrPolicy(overwrite=True),
    )

    assert result.cache_hits == ("audio", "vad")
    assert len(extractor.calls) == 1
    assert len(vad.calls) == 1
    assert len(asr.calls) == 2
    assert result.raw_asr.config.model == "small.en"


def test_vad_config_change_invalidates_vad_and_asr_but_reuses_audio(
    tmp_path: Path,
) -> None:
    store = MemoryArtifactStore()
    source = _source(store, tmp_path)
    service, extractor, vad, asr, probe, events = _service(store, tmp_path)
    asr_config = _development_asr()
    service.execute(
        source, vad_config=_vad_config(padding_ms=100), asr_config=asr_config
    )

    result = service.execute(
        source,
        vad_config=_vad_config(padding_ms=300),
        asr_config=asr_config,
        policy=AudioVadAsrPolicy(overwrite=True),
    )

    assert result.cache_hits == ("audio",)
    assert len(extractor.calls) == 1
    assert len(vad.calls) == 2
    assert len(asr.calls) == 2


def test_production_and_development_profiles_never_share_asr_completion_state(
    tmp_path: Path,
) -> None:
    store = MemoryArtifactStore()
    source = _source(store, tmp_path)
    service, extractor, vad, asr, probe, events = _service(store, tmp_path)
    production = AsrConfig.production(
        model="large-v3", device="cpu", compute_type="int8"
    )
    development = _development_asr()
    service.execute(source, vad_config=_vad_config(), asr_config=production)

    result = service.execute(
        source,
        vad_config=_vad_config(),
        asr_config=development,
        policy=AudioVadAsrPolicy(overwrite=True),
    )

    assert result.cache_hits == ("audio", "vad")
    assert result.raw_asr.config.profile is TranscriptionProfile.DEVELOPMENT
    assert len(asr.calls) == 2


def test_provider_identity_change_makes_relevant_cache_stale(tmp_path: Path) -> None:
    store = MemoryArtifactStore()
    source = _source(store, tmp_path)
    service, extractor, vad, asr, probe, events = _service(store, tmp_path)
    config = _development_asr()
    service.execute(source, vad_config=_vad_config(), asr_config=config)
    asr.identity = ProviderIdentity("fake-whisperx", "3.9.0")

    result = service.execute(
        source,
        vad_config=_vad_config(),
        asr_config=config,
        policy=AudioVadAsrPolicy(overwrite=True),
    )

    assert result.cache_hits == ("audio", "vad")
    assert len(asr.calls) == 2
    assert result.raw_asr.provider.version == "3.9.0"
