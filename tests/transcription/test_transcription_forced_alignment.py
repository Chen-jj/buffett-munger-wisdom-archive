from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from archive_core.application import build_asset_workspace
from archive_core.domain import AssetId
from transcription.application import (
    ALIGNMENT_STAGE_NAME,
    AlignmentFailure,
    AlignmentInputValidationError,
    AudioVadAsrCacheManifest,
    AudioVadAsrResult,
    CacheRecord,
    EventCode,
    ExistingTranscriptionArtifactConflict,
    ForcedAlignmentPolicy,
    ForcedAlignmentService,
    TranscriptionEvent,
    TranscriptionObservability,
    TranscriptionReport,
    TranscriptionReportAggregator,
    resolve_alignment_candidates,
)
from transcription.domain import (
    AlignedAsrArtifact,
    AlignedAsrWord,
    AlignmentCandidate,
    AlignmentTimingSource,
    AsrConfig,
    ForcedAlignmentConfig,
    InterpolationPolicy,
    ProviderIdentity,
    RawAsrArtifact,
    RawAsrSegment,
    VadArtifact,
    VadConfig,
    VadRegion,
    build_raw_asr_tokens,
    build_vad_chunks,
    tokenize_surface_text,
)
from transcription.infrastructure import WhisperXForcedAligner


ASSET_ID = AssetId("cnbc", "1994", "morning")


class MemoryArtifactStore:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.writes: list[tuple[str, bool]] = []

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
        self.files[path] = json.dumps(data, sort_keys=True).encode("utf-8")
        self.writes.append((path, overwrite))
        return path


class MemoryChecksum:
    def __init__(self, store: MemoryArtifactStore) -> None:
        self.store = store

    def sha256(self, path: str) -> str:
        return hashlib.sha256(self.store.files[path]).hexdigest()


class MemoryLogSink:
    def __init__(self) -> None:
        self.events: list[TranscriptionEvent] = []

    def emit(self, event: TranscriptionEvent) -> None:
        self.events.append(event)

    def flush(self) -> None:
        pass


class MemoryReportWriter:
    def __init__(self) -> None:
        self.reports: list[TranscriptionReport] = []

    def write(self, report: TranscriptionReport) -> None:
        self.reports.append(report)


class FakeAligner:
    def __init__(self, candidates: tuple[AlignmentCandidate, ...]) -> None:
        self.identity = ProviderIdentity("fake-aligner", "1.0")
        self.candidates = candidates
        self.calls: list[
            tuple[str, RawAsrArtifact, tuple[Any, ...], ForcedAlignmentConfig]
        ] = []

    def align(self, audio_path, raw_asr, tokens, config):
        self.calls.append((audio_path, raw_asr, tokens, config))
        return self.candidates


def _config(**policy_changes: object) -> ForcedAlignmentConfig:
    return ForcedAlignmentConfig(
        model="wav2vec2-english",
        model_version="2026.1",
        device="cpu",
        interpolation=replace(
            InterpolationPolicy(version="interpolation.v1"), **policy_changes
        ),
    )


def _raw_artifact(
    audio_sha256: str,
    *,
    text: str = "We'll start with 10%.",
    start_ms: int = 100,
    end_ms: int = 1_000,
    cache_key: str = "raw-key",
) -> RawAsrArtifact:
    return RawAsrArtifact(
        audio_sha256=audio_sha256,
        audio_duration_ms=2_000,
        vad_cache_key="vad-key",
        provider=ProviderIdentity("fake-whisperx", "3.8.5"),
        config=AsrConfig.development(model="tiny.en"),
        segments=(RawAsrSegment("seg1", text, start_ms, end_ms),),
        cache_key=cache_key,
    )


def _vad(audio_sha256: str) -> VadArtifact:
    config = VadConfig(
        model="pyannote/voice-activity-detection", model_version="2026.1"
    )
    regions = (VadRegion("vr1", 100, 1_000),)
    return VadArtifact(
        audio_sha256=audio_sha256,
        audio_duration_ms=2_000,
        provider=ProviderIdentity("fake-pyannote", "4.0"),
        config=config,
        regions=regions,
        chunks=build_vad_chunks(regions, duration_ms=2_000, config=config),
        cache_key="vad-key",
    )


def _upstream(
    store: MemoryArtifactStore, output_root: Path, *, text: str = "We'll start with 10%."
) -> AudioVadAsrResult:
    workspace = build_asset_workspace(ASSET_ID, output_root)
    audio_path = str(workspace / "audio.wav")
    vad_path = str(workspace / "vad.json")
    raw_path = str(workspace / "raw_asr.json")
    manifest_path = str(workspace / "transcription_manifest.json")
    store.files[audio_path] = b"canonical audio"
    audio_sha = hashlib.sha256(store.files[audio_path]).hexdigest()
    vad = _vad(audio_sha)
    store.write_json(vad_path, vad.to_dict(), overwrite=False)
    raw = _raw_artifact(audio_sha, text=text)
    store.write_json(raw_path, raw.to_dict(), overwrite=False)
    checksum = MemoryChecksum(store)
    manifest = AudioVadAsrCacheManifest(
        asset_id=ASSET_ID,
        records={
            "audio": CacheRecord(
                path=audio_path,
                size_bytes=store.size(audio_path),
                sha256=audio_sha,
                cache_key="audio-key",
            ),
            "vad": CacheRecord(
                path=vad_path,
                size_bytes=store.size(vad_path),
                sha256=checksum.sha256(vad_path),
                cache_key=vad.cache_key,
            ),
            "raw_asr": CacheRecord(
                path=raw_path,
                size_bytes=store.size(raw_path),
                sha256=checksum.sha256(raw_path),
                cache_key=raw.cache_key,
            ),
        },
    )
    store.write_json(manifest_path, manifest.to_dict(), overwrite=False)
    return AudioVadAsrResult(
        audio_path=audio_path,
        vad_path=vad_path,
        raw_asr_path=raw_path,
        manifest_path=manifest_path,
        audio_sha256=audio_sha,
        vad=vad,
        raw_asr=raw,
        cache_hits=(),
    )


def _observability():
    log = MemoryLogSink()
    report = TranscriptionReportAggregator(ASSET_ID.value)
    writer = MemoryReportWriter()
    observability = TranscriptionObservability(
        asset_id=ASSET_ID.value,
        stage=ALIGNMENT_STAGE_NAME,
        detailed_log=log,
        report=report,
        report_writer=writer,
    )
    return observability, log, report


def _service(
    store: MemoryArtifactStore,
    output_root: Path,
    candidates: tuple[AlignmentCandidate, ...],
):
    aligner = FakeAligner(candidates)
    observability, log, report = _observability()
    service = ForcedAlignmentService(
        aligner=aligner,
        checksum=MemoryChecksum(store),
        artifacts=store,
        events=observability,
        output_root=str(output_root),
    )
    return service, aligner, log, report


def _exact_candidates(raw: RawAsrArtifact) -> tuple[AlignmentCandidate, ...]:
    tokens = build_raw_asr_tokens(raw)
    starts = (120, 300, 480, 650)
    ends = (250, 430, 600, 900)
    return tuple(
        AlignmentCandidate(
            raw_word_id=token.id,
            segment_id=token.segment_id,
            text=token.text,
            start_ms=starts[index],
            end_ms=ends[index],
            alignment_score=0.9 - index * 0.05,
        )
        for index, token in enumerate(tokens)
    )


def test_raw_tokenizer_attaches_punctuation_without_standalone_timing_units() -> None:
    assert tokenize_surface_text("\"We'll start with 10%.\"") == (
        '"We\'ll',
        "start",
        "with",
        '10%."',
    )
    assert tokenize_surface_text("Berkshire-Hathaway earned $10.") == (
        "Berkshire-Hathaway",
        "earned",
        "$10.",
    )


def test_aligned_artifact_round_trips_without_character_timestamps() -> None:
    config = _config()
    artifact = AlignedAsrArtifact(
        audio_sha256="audio-hash",
        raw_asr_sha256="raw-hash",
        audio_duration_ms=1_000,
        provider=ProviderIdentity("whisperx", "3.8.5"),
        config=config,
        words=(
            AlignedAsrWord(
                id="aw1",
                raw_word_id="rw1",
                segment_id="seg1",
                text="Hello.",
                start_ms=100,
                end_ms=300,
                alignment_score=0.95,
                timing_source=AlignmentTimingSource.ACOUSTIC_ALIGNMENT,
            ),
        ),
        cache_key="alignment-key",
    )

    data = artifact.to_dict()

    assert data["schema_version"] == "transcription.aligned-asr.v1"
    assert data["words"][0]["id"] == "aw1"
    assert data["words"][0]["segment_id"] == "seg1"
    assert data["words"][0]["timing_source"] == "acoustic_alignment"
    assert "characters" not in data
    assert AlignedAsrArtifact.from_dict(data) == artifact


def test_aligned_word_id_requires_stable_aw_prefix() -> None:
    with pytest.raises(ValueError, match="aw<one-based position>"):
        AlignedAsrWord(
            id="1",
            raw_word_id="rw1",
            segment_id="seg1",
            text="Hello.",
            start_ms=100,
            end_ms=300,
            alignment_score=0.95,
            timing_source=AlignmentTimingSource.ACOUSTIC_ALIGNMENT,
        )


def test_exact_alignment_persists_words_cache_and_debug_events(tmp_path: Path) -> None:
    store = MemoryArtifactStore()
    upstream = _upstream(store, tmp_path)
    candidates = _exact_candidates(upstream.raw_asr)
    service, aligner, log, report = _service(store, tmp_path, candidates)

    result = service.execute(upstream, config=_config())

    assert result.path == str(build_asset_workspace(ASSET_ID, tmp_path) / "aligned_asr.json")
    assert result.cache_hit is False
    assert [word.id for word in result.artifact.words] == ["aw1", "aw2", "aw3", "aw4"]
    assert [word.raw_word_id for word in result.artifact.words] == [
        "rw1",
        "rw2",
        "rw3",
        "rw4",
    ]
    assert [word.text for word in result.artifact.words] == [
        "We'll",
        "start",
        "with",
        "10%.",
    ]
    assert len(aligner.calls) == 1
    assert [event.code for event in log.events] == [
        EventCode.ALIGNMENT_WORD_ALIGNED,
        EventCode.ALIGNMENT_WORD_ALIGNED,
        EventCode.ALIGNMENT_WORD_ALIGNED,
        EventCode.ALIGNMENT_WORD_ALIGNED,
        EventCode.ALIGNMENT_COMPLETED,
    ]
    assert report.snapshot().counts["aligned"] == 4
    manifest = store.read_json(upstream.manifest_path)
    assert manifest["records"]["aligned_asr"]["cache_key"] == result.artifact.cache_key


def test_small_explainable_gap_is_interpolated_between_bilateral_anchors(
    tmp_path: Path,
) -> None:
    store = MemoryArtifactStore()
    upstream = _upstream(store, tmp_path, text="Return was 10% today.")
    tokens = build_raw_asr_tokens(upstream.raw_asr)
    candidates = (
        AlignmentCandidate("rw1", "seg1", "Return", 120, 250, 0.95),
        AlignmentCandidate("rw2", "seg1", "was", 300, 450, 0.94),
        AlignmentCandidate(
            "rw3",
            "seg1",
            "10%",
            None,
            None,
            None,
            "numeric_or_symbol",
        ),
        AlignmentCandidate("rw4", "seg1", "today.", 650, 900, 0.92),
    )
    assert [token.text for token in tokens] == ["Return", "was", "10%", "today."]
    service, aligner, log, report = _service(store, tmp_path, candidates)

    result = service.execute(upstream, config=_config(max_window_ms=500))

    interpolated = result.artifact.words[2]
    assert interpolated.to_dict() == {
        "id": "aw3",
        "raw_word_id": "rw3",
        "segment_id": "seg1",
        "text": "10%",
        "start_ms": 450,
        "end_ms": 650,
        "alignment_score": None,
        "timing_source": "interpolated",
        "left_anchor_id": "aw2",
        "right_anchor_id": "aw4",
    }
    assert [event.code for event in log.events] == [
        EventCode.ALIGNMENT_WORD_UNALIGNED,
        EventCode.ALIGNMENT_WORD_ALIGNED,
        EventCode.ALIGNMENT_WORD_ALIGNED,
        EventCode.ALIGNMENT_WORD_INTERPOLATED,
        EventCode.ALIGNMENT_WORD_ALIGNED,
        EventCode.ALIGNMENT_COMPLETED,
    ]
    snapshot = report.snapshot()
    assert snapshot.counts["aligned"] == 3
    assert snapshot.counts["interpolated"] == 1
    assert snapshot.counts["warning"] == 1
    assert snapshot.findings[0].code is EventCode.ALIGNMENT_WORD_INTERPOLATED


@pytest.mark.parametrize(
    ("candidates", "policy_changes", "reason"),
    [
        (
            (
                AlignmentCandidate(
                    "rw1", "seg1", "We'll", None, None, None, "out_of_vocabulary"
                ),
                AlignmentCandidate("rw2", "seg1", "start", 300, 430, 0.9),
                AlignmentCandidate("rw3", "seg1", "with", 480, 600, 0.9),
                AlignmentCandidate("rw4", "seg1", "10%.", 650, 900, 0.9),
            ),
            {},
            "lacks reliable anchors",
        ),
        (
            (
                AlignmentCandidate("rw1", "seg1", "We'll", 120, 250, 0.9),
                AlignmentCandidate(
                    "rw2", "seg1", "start", None, None, None, "out_of_vocabulary"
                ),
                AlignmentCandidate(
                    "rw3", "seg1", "with", None, None, None, "out_of_vocabulary"
                ),
                AlignmentCandidate("rw4", "seg1", "10%.", 650, 900, 0.9),
            ),
            {"max_consecutive_words": 1},
            "exceeds interpolation word limit",
        ),
        (
            (
                AlignmentCandidate("rw1", "seg1", "We'll", 120, 250, 0.9),
                AlignmentCandidate(
                    "rw2", "seg1", "start", None, None, None, "hallucination"
                ),
                AlignmentCandidate("rw3", "seg1", "with", 480, 600, 0.9),
                AlignmentCandidate("rw4", "seg1", "10%.", 650, 900, 0.9),
            ),
            {},
            "not explainable",
        ),
        (
            (
                AlignmentCandidate("rw1", "seg1", "We'll", 120, 400, 0.9),
                AlignmentCandidate(
                    "rw2", "seg1", "start", None, None, None, "out_of_vocabulary"
                ),
                AlignmentCandidate("rw3", "seg1", "with", 450, 600, 0.9),
                AlignmentCandidate("rw4", "seg1", "10%.", 650, 900, 0.9),
            ),
            {"min_word_duration_ms": 80},
            "too short",
        ),
        (
            (
                AlignmentCandidate("rw1", "seg1", "We'll", 120, 250, 0.4),
                AlignmentCandidate(
                    "rw2", "seg1", "start", None, None, None, "out_of_vocabulary"
                ),
                AlignmentCandidate("rw3", "seg1", "with", 480, 600, 0.9),
                AlignmentCandidate("rw4", "seg1", "10%.", 650, 900, 0.9),
            ),
            {"min_anchor_alignment_score": 0.5},
            "lacks reliable acoustic anchors",
        ),
    ],
)
def test_unsafe_unaligned_regions_fail_and_emit_findings(
    tmp_path: Path,
    candidates: tuple[AlignmentCandidate, ...],
    policy_changes: dict[str, object],
    reason: str,
) -> None:
    store = MemoryArtifactStore()
    upstream = _upstream(store, tmp_path)
    service, aligner, log, report = _service(store, tmp_path, candidates)

    with pytest.raises(AlignmentFailure, match=reason):
        service.execute(upstream, config=_config(**policy_changes))

    aligned_path = str(build_asset_workspace(ASSET_ID, tmp_path) / "aligned_asr.json")
    assert not store.exists(aligned_path)
    assert log.events[-1].code is EventCode.ALIGNMENT_WORD_UNRECOVERABLE
    assert report.snapshot().counts["error"] == 1
    assert report.snapshot().counts["conflict"] == 1


def test_overlap_is_hard_failure_with_specific_event(tmp_path: Path) -> None:
    store = MemoryArtifactStore()
    upstream = _upstream(store, tmp_path)
    candidates = list(_exact_candidates(upstream.raw_asr))
    candidates[1] = replace(candidates[1], start_ms=200)
    service, aligner, log, report = _service(store, tmp_path, tuple(candidates))

    with pytest.raises(AlignmentFailure, match="overlaps"):
        service.execute(upstream, config=_config())

    assert log.events[-1].code is EventCode.ALIGNMENT_WORD_OVERLAP
    assert report.snapshot().counts["conflict"] == 1


def test_out_of_segment_timing_fails_before_persistence(tmp_path: Path) -> None:
    store = MemoryArtifactStore()
    upstream = _upstream(store, tmp_path)
    candidates = list(_exact_candidates(upstream.raw_asr))
    candidates[0] = replace(candidates[0], start_ms=99)
    service, aligner, log, report = _service(store, tmp_path, tuple(candidates))

    with pytest.raises(AlignmentFailure, match="outside its raw ASR segment"):
        service.execute(upstream, config=_config())

    assert log.events[-1].code is EventCode.ALIGNMENT_WORD_UNRECOVERABLE
    assert not store.exists(str(build_asset_workspace(ASSET_ID, tmp_path) / "aligned_asr.json"))


def test_missing_candidate_is_coverage_failure_not_silent_word_drop(tmp_path: Path) -> None:
    store = MemoryArtifactStore()
    upstream = _upstream(store, tmp_path)
    candidates = _exact_candidates(upstream.raw_asr)[:-1]
    service, aligner, log, report = _service(store, tmp_path, candidates)

    with pytest.raises(AlignmentFailure, match="expected 4 candidates, received 3"):
        service.execute(upstream, config=_config())

    assert log.events[-1].code is EventCode.ALIGNMENT_WORD_UNRECOVERABLE
    assert report.snapshot().counts["error"] == 1


def test_alignment_cache_hit_skips_provider(tmp_path: Path) -> None:
    store = MemoryArtifactStore()
    upstream = _upstream(store, tmp_path)
    candidates = _exact_candidates(upstream.raw_asr)
    service, aligner, log, report = _service(store, tmp_path, candidates)

    first = service.execute(upstream, config=_config())
    second = service.execute(upstream, config=_config())

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert second.artifact == first.artifact
    assert len(aligner.calls) == 1
    assert log.events[-1].code is EventCode.ALIGNMENT_CACHE_HIT


def test_alignment_cache_hit_restores_counts_without_replaying_warnings(
    tmp_path: Path,
) -> None:
    store = MemoryArtifactStore()
    upstream = _upstream(store, tmp_path, text="Return was 10% today.")
    candidates = (
        AlignmentCandidate("rw1", "seg1", "Return", 120, 250, 0.95),
        AlignmentCandidate("rw2", "seg1", "was", 300, 450, 0.94),
        AlignmentCandidate(
            "rw3", "seg1", "10%", None, None, None, "numeric_or_symbol"
        ),
        AlignmentCandidate("rw4", "seg1", "today.", 650, 900, 0.92),
    )
    first_service, _, _, _ = _service(store, tmp_path, candidates)
    first_service.execute(upstream, config=_config(max_window_ms=500))
    cached_service, cached_aligner, cached_log, cached_report = _service(
        store, tmp_path, candidates
    )

    result = cached_service.execute(
        upstream, config=_config(max_window_ms=500)
    )

    assert result.cache_hit is True
    assert cached_aligner.calls == []
    assert [event.code for event in cached_log.events] == [
        EventCode.ALIGNMENT_CACHE_HIT
    ]
    assert cached_report.snapshot().counts == {
        "aligned": 3,
        "interpolated": 1,
        "conflict": 0,
        "warning": 0,
        "error": 0,
    }
    assert cached_report.snapshot().findings == ()


def test_alignment_policy_change_stales_only_alignment_and_requires_overwrite(
    tmp_path: Path,
) -> None:
    store = MemoryArtifactStore()
    upstream = _upstream(store, tmp_path)
    candidates = _exact_candidates(upstream.raw_asr)
    service, aligner, log, report = _service(store, tmp_path, candidates)
    service.execute(upstream, config=_config(max_window_ms=500))
    changed = _config(max_window_ms=700)

    with pytest.raises(
        ExistingTranscriptionArtifactConflict, match="explicit overwrite required"
    ):
        service.execute(upstream, config=changed)
    result = service.execute(
        upstream,
        config=changed,
        policy=ForcedAlignmentPolicy(overwrite=True),
    )

    assert result.cache_hit is False
    assert len(aligner.calls) == 2
    assert result.artifact.config.interpolation.max_window_ms == 700


def test_alignment_provider_and_model_identity_are_part_of_cache_key(
    tmp_path: Path,
) -> None:
    store = MemoryArtifactStore()
    upstream = _upstream(store, tmp_path)
    service, aligner, log, report = _service(
        store, tmp_path, _exact_candidates(upstream.raw_asr)
    )
    first = service.execute(upstream, config=_config())
    aligner.identity = ProviderIdentity("fake-aligner", "2.0")

    with pytest.raises(ExistingTranscriptionArtifactConflict):
        service.execute(upstream, config=_config())
    second = service.execute(
        upstream,
        config=_config(),
        policy=ForcedAlignmentPolicy(overwrite=True),
    )
    changed_model = replace(_config(), model_version="2026.2")

    with pytest.raises(ExistingTranscriptionArtifactConflict):
        service.execute(upstream, config=changed_model)
    third = service.execute(
        upstream,
        config=changed_model,
        policy=ForcedAlignmentPolicy(overwrite=True),
    )

    assert len({first.artifact.cache_key, second.artifact.cache_key, third.artifact.cache_key}) == 3


def test_valid_raw_asr_change_stales_alignment_cache(tmp_path: Path) -> None:
    store = MemoryArtifactStore()
    upstream = _upstream(store, tmp_path)
    service, aligner, log, report = _service(
        store, tmp_path, _exact_candidates(upstream.raw_asr)
    )
    first = service.execute(upstream, config=_config())

    changed_raw = _raw_artifact(
        upstream.audio_sha256,
        text="We'll start with 11%.",
        cache_key="raw-key-v2",
    )
    store.write_json(upstream.raw_asr_path, changed_raw.to_dict(), overwrite=True)
    manifest = AudioVadAsrCacheManifest.from_dict(
        store.read_json(upstream.manifest_path)
    )
    manifest.records["raw_asr"] = CacheRecord(
        path=upstream.raw_asr_path,
        size_bytes=store.size(upstream.raw_asr_path),
        sha256=MemoryChecksum(store).sha256(upstream.raw_asr_path),
        cache_key=changed_raw.cache_key,
    )
    store.write_json(upstream.manifest_path, manifest.to_dict(), overwrite=True)
    changed_upstream = replace(upstream, raw_asr=changed_raw)
    aligner.candidates = _exact_candidates(changed_raw)

    with pytest.raises(ExistingTranscriptionArtifactConflict):
        service.execute(changed_upstream, config=_config())
    second = service.execute(
        changed_upstream,
        config=_config(),
        policy=ForcedAlignmentPolicy(overwrite=True),
    )

    assert second.artifact.raw_asr_sha256 == manifest.records["raw_asr"].sha256
    assert second.artifact.cache_key != first.artifact.cache_key


def test_tampered_raw_asr_fails_before_aligner(tmp_path: Path) -> None:
    store = MemoryArtifactStore()
    upstream = _upstream(store, tmp_path)
    raw_path = upstream.raw_asr_path
    store.files[raw_path] = b"tampered"
    service, aligner, log, report = _service(
        store, tmp_path, _exact_candidates(upstream.raw_asr)
    )

    with pytest.raises(AlignmentInputValidationError, match="raw_asr"):
        service.execute(upstream, config=_config())

    assert aligner.calls == []


def test_whisperx_alignment_adapter_is_lazy_and_disables_character_alignment() -> None:
    class Backend:
        def __init__(self) -> None:
            self.load_audio_calls: list[str] = []
            self.load_model_calls: list[dict[str, str]] = []
            self.align_calls: list[tuple[Any, ...]] = []

        def load_audio(self, path: str):
            self.load_audio_calls.append(path)
            return "audio-array"

        def load_align_model(self, **kwargs):
            self.load_model_calls.append(kwargs)
            return "align-model", {"language": "en"}

        def align(self, *args, **kwargs):
            self.align_calls.append((args, kwargs))
            return {
                "word_segments": [
                    {"word": "Hello", "start": 0.1, "end": 0.3, "score": 0.9},
                    {"word": "10%.", "score": 0.5},
                    {"word": "today.", "start": 0.6, "end": 0.9, "score": 0.8},
                ],
                "char_segments": [{"char": "H", "start": 0.1}],
            }

    backend = Backend()
    resolved_models: list[tuple[str, str]] = []

    def resolve_model(model: str, version: str) -> str:
        resolved_models.append((model, version))
        return f"/models/{model}/{version}"

    adapter = WhisperXForcedAligner(
        whisperx_version="3.8.5",
        backend=backend,
        model_resolver=resolve_model,
    )
    raw = RawAsrArtifact(
        audio_sha256="hash",
        audio_duration_ms=1_000,
        vad_cache_key="vad-key",
        provider=ProviderIdentity("whisperx", "3.8.5"),
        config=AsrConfig.development(model="tiny.en"),
        segments=(RawAsrSegment("seg1", "Hello 10%. today.", 0, 1_000),),
        cache_key="raw-key",
    )
    tokens = build_raw_asr_tokens(raw)

    assert resolved_models == []
    candidates = adapter.align("audio.wav", raw, tokens, _config())
    adapter.align(
        "audio.wav",
        raw,
        tokens,
        replace(_config(), model_version="2026.2"),
    )

    assert resolved_models == [
        ("wav2vec2-english", "2026.1"),
        ("wav2vec2-english", "2026.2"),
    ]
    assert backend.load_audio_calls == ["audio.wav", "audio.wav"]
    assert backend.load_model_calls == [
        {
            "language_code": "en",
            "device": "cpu",
            "model_name": "/models/wav2vec2-english/2026.1",
        },
        {
            "language_code": "en",
            "device": "cpu",
            "model_name": "/models/wav2vec2-english/2026.2",
        },
    ]
    assert backend.align_calls[0][1] == {"return_char_alignments": False}
    assert candidates == (
        AlignmentCandidate("rw1", "seg1", "Hello", 100, 300, 0.9),
        AlignmentCandidate(
            "rw2",
            "seg1",
            "10%.",
            None,
            None,
            None,
            "alignment_model_no_timing",
        ),
        AlignmentCandidate("rw3", "seg1", "today.", 600, 900, 0.8),
    )


def test_whisperx_adapter_rejects_provider_word_coverage_mismatch() -> None:
    class Backend:
        def load_audio(self, path: str):
            return "audio"

        def load_align_model(self, **kwargs):
            return "model", {}

        def align(self, *args, **kwargs):
            return {"word_segments": []}

    raw = RawAsrArtifact(
        audio_sha256="hash",
        audio_duration_ms=500,
        vad_cache_key="vad-key",
        provider=ProviderIdentity("whisperx", "3.8.5"),
        config=AsrConfig.development(model="tiny.en"),
        segments=(RawAsrSegment("seg1", "Hello.", 0, 500),),
        cache_key="raw-key",
    )
    adapter = WhisperXForcedAligner(
        whisperx_version="3.8.5",
        backend=Backend(),
        model_resolver=lambda model, version: f"/models/{model}/{version}",
    )

    with pytest.raises(RuntimeError, match="coverage"):
        adapter.align("audio.wav", raw, build_raw_asr_tokens(raw), _config())


def test_whisperx_adapter_splits_compound_words_and_ignores_punctuation_only() -> None:
    class Backend:
        def load_audio(self, path: str):
            return "audio"

        def load_align_model(self, **kwargs):
            return "model", {}

        def align(self, *args, **kwargs):
            return {
                "word_segments": [
                    {"word": "B.C.", "start": 0.1, "end": 0.5, "score": 0.8},
                    {"word": "works.?", "start": 0.6, "end": 0.9, "score": 0.9},
                    {"word": "?"},
                ]
            }

    raw = RawAsrArtifact(
        audio_sha256="hash",
        audio_duration_ms=1_000,
        vad_cache_key="vad-key",
        provider=ProviderIdentity("whisperx", "3.8.5"),
        config=AsrConfig.development(model="tiny.en"),
        segments=(RawAsrSegment("seg1", "B. C. works.?", 0, 1_000),),
        cache_key="raw-key",
    )
    adapter = WhisperXForcedAligner(
        whisperx_version="3.8.5",
        backend=Backend(),
        model_resolver=lambda model, version: f"/models/{model}/{version}",
    )

    assert adapter.align(
        "audio.wav", raw, build_raw_asr_tokens(raw), _config()
    ) == (
        AlignmentCandidate("rw1", "seg1", "B.", 100, 300, 0.8),
        AlignmentCandidate("rw2", "seg1", "C.", 300, 500, 0.8),
        AlignmentCandidate("rw3", "seg1", "works.?", 600, 900, 0.9),
    )


def _run_whisperx_adapter(
    raw_text: str,
    provider_words: list[Mapping[str, object]],
) -> tuple[
    RawAsrArtifact,
    tuple[Any, ...],
    tuple[AlignmentCandidate, ...],
]:
    class Backend:
        def load_audio(self, path: str):
            return "audio"

        def load_align_model(self, **kwargs):
            return "model", {}

        def align(self, *args, **kwargs):
            return {"word_segments": provider_words}

    raw = RawAsrArtifact(
        audio_sha256="hash",
        audio_duration_ms=1_000,
        vad_cache_key="vad-key",
        provider=ProviderIdentity("whisperx", "3.8.5"),
        config=AsrConfig.development(model="tiny.en"),
        segments=(RawAsrSegment("seg1", raw_text, 0, 1_000),),
        cache_key="raw-key",
    )
    tokens = build_raw_asr_tokens(raw)
    adapter = WhisperXForcedAligner(
        whisperx_version="3.8.5",
        backend=Backend(),
        model_resolver=lambda model, version: f"/models/{model}/{version}",
    )
    return raw, tokens, adapter.align("audio.wav", raw, tokens, _config())


@pytest.mark.parametrize(
    ("raw_surface", "provider_surface"),
    [
        ("returns,", "returns"),
        ("figures—", "figures"),
        ("outlook…”", "outlook"),
    ],
)
def test_whisperx_adapter_restores_exact_raw_trailing_punctuation(
    raw_surface: str,
    provider_surface: str,
) -> None:
    raw, tokens, candidates = _run_whisperx_adapter(
        raw_surface,
        [
            {
                "word": provider_surface,
                "start": 0.12,
                "end": 0.34,
                "score": 0.73,
            }
        ],
    )

    assert candidates == (
        AlignmentCandidate("rw1", "seg1", raw_surface, 120, 340, 0.73),
    )
    resolved = resolve_alignment_candidates(raw, tokens, candidates, _config())
    assert resolved[0].text == raw_surface
    assert resolved[0].start_ms == 120
    assert resolved[0].end_ms == 340
    assert resolved[0].alignment_score == 0.73
    assert resolved[0].timing_source is AlignmentTimingSource.ACOUSTIC_ALIGNMENT


def test_whisperx_adapter_restores_surface_without_changing_unaligned_state() -> None:
    _, _, candidates = _run_whisperx_adapter(
        "figures—",
        [{"word": "figures"}],
    )

    assert candidates == (
        AlignmentCandidate(
            "rw1",
            "seg1",
            "figures—",
            None,
            None,
            None,
            "alignment_model_no_timing",
        ),
    )


@pytest.mark.parametrize(
    ("raw_surface", "provider_surface"),
    [
        ('"figures', "figures"),
        ("re-enter", "reenter"),
        ("figures", "figure"),
        ("figures2", "figures"),
        ("Figures—", "figures"),
        ("figures_", "figures"),
    ],
)
def test_whisperx_adapter_does_not_fuzzy_match_non_trailing_punctuation_changes(
    raw_surface: str,
    provider_surface: str,
) -> None:
    raw, tokens, candidates = _run_whisperx_adapter(
        raw_surface,
        [
            {
                "word": provider_surface,
                "start": 0.12,
                "end": 0.34,
                "score": 0.73,
            }
        ],
    )

    assert candidates[0].text == provider_surface
    with pytest.raises(AlignmentFailure, match="surface text does not match"):
        resolve_alignment_candidates(raw, tokens, candidates, _config())


@pytest.mark.parametrize("mutation", ["missing", "extra", "reordered"])
def test_alignment_gate_still_rejects_candidate_coverage_and_order(
    mutation: str,
) -> None:
    raw = _raw_artifact("audio-hash", text="Good morning.")
    tokens = build_raw_asr_tokens(raw)
    candidates = (
        AlignmentCandidate("rw1", "seg1", "Good", 120, 250, 0.9),
        AlignmentCandidate("rw2", "seg1", "morning.", 300, 450, 0.8),
    )
    if mutation == "missing":
        changed = candidates[:-1]
    elif mutation == "extra":
        changed = candidates + (
            AlignmentCandidate("rw3", "seg1", "extra", 500, 600, 0.7),
        )
    else:
        changed = tuple(reversed(candidates))

    with pytest.raises(AlignmentFailure, match="coverage|identity"):
        resolve_alignment_candidates(raw, tokens, changed, _config())
