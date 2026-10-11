from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from archive_core.application import build_asset_workspace
from archive_core.domain import AssetId
from archive_core.interfaces import (
    MatchType,
    StructuredTranscriptDTO,
    TranscriptChapterDTO,
    TranscriptParagraphDTO,
)
from transcription.application import (
    AudioVadAsrCacheManifest,
    CacheRecord,
    EventCode,
    ExistingTranscriptionArtifactConflict,
    FUSION_STAGE_NAME,
    ForcedAlignmentResult,
    FusionFailure,
    FusionInputValidationError,
    OfficialTranscriptInput,
    TranscriptFusionPolicy,
    TranscriptFusionService,
    TranscriptionEvent,
    TranscriptionObservability,
    TranscriptionReport,
    TranscriptionReportAggregator,
    plan_transcript_fusion,
)
from transcription.domain import (
    AlignedAsrArtifact,
    AlignedAsrWord,
    AlignmentTimingSource,
    ForcedAlignmentConfig,
    InterpolationPolicy,
    LocalValidationStatus,
    MatchingPolicy,
    NormalizationPolicy,
    OfficialAlignmentCandidate,
    OfficialAlignmentConfig,
    ProviderIdentity,
    TranscriptFusionArtifact,
    build_official_tokens,
    normalize_token,
    tokenize_surface_text,
)
from transcription.infrastructure import WhisperXOfficialTranscriptAligner


ASSET_ID = AssetId("cnbc", "1994", "morning")


class MemoryArtifactStore:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

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


class FakeOfficialAligner:
    def __init__(
        self,
        candidates: tuple[OfficialAlignmentCandidate, ...] = (),
        *,
        version: str = "1.0",
        error: Exception | None = None,
    ) -> None:
        self.identity = ProviderIdentity("fake-local-aligner", version)
        self.candidates = candidates
        self.error = error
        self.calls: list[tuple[Any, ...]] = []

    def align_official(self, audio_path, tokens, left_anchor, right_anchor, config):
        self.calls.append((audio_path, tokens, left_anchor, right_anchor, config))
        if self.error is not None:
            raise self.error
        return self.candidates


def _alignment_config() -> OfficialAlignmentConfig:
    return OfficialAlignmentConfig(
        model="wav2vec2-english",
        model_version="2026.1",
        device="cpu",
        min_alignment_score=0.6,
        min_anchor_alignment_score=0.6,
    )


def _matching(**changes: object) -> MatchingPolicy:
    return replace(
        MatchingPolicy(
            allowed_substitutions=(("buffet", "buffett"),)
        ),
        **changes,
    )


def _forced_config() -> ForcedAlignmentConfig:
    return ForcedAlignmentConfig(
        model="wav2vec2-english",
        model_version="2026.1",
        device="cpu",
        interpolation=InterpolationPolicy(version="interpolation.v1"),
    )


def _aligned_artifact(
    texts: tuple[str, ...],
    *,
    timing_sources: Mapping[int, AlignmentTimingSource] | None = None,
    alignment_scores: Mapping[int, float] | None = None,
) -> AlignedAsrArtifact:
    selected_sources = timing_sources or {}
    selected_scores = alignment_scores or {}
    words: list[AlignedAsrWord] = []
    for position, text in enumerate(texts, start=1):
        start_ms = 100 + (position - 1) * 300
        source = selected_sources.get(
            position, AlignmentTimingSource.ACOUSTIC_ALIGNMENT
        )
        words.append(
            AlignedAsrWord(
                id=f"aw{position}",
                raw_word_id=f"rw{position}",
                segment_id="seg1",
                text=text,
                start_ms=start_ms,
                end_ms=start_ms + 100,
                alignment_score=(
                    selected_scores.get(position, 0.9)
                    if source is AlignmentTimingSource.ACOUSTIC_ALIGNMENT
                    else None
                ),
                timing_source=source,
                left_anchor_id=(
                    "aw1" if source is AlignmentTimingSource.INTERPOLATED else None
                ),
                right_anchor_id=(
                    "aw3" if source is AlignmentTimingSource.INTERPOLATED else None
                ),
            )
        )
    return AlignedAsrArtifact(
        audio_sha256="audio-sha-placeholder",
        raw_asr_sha256="raw-sha",
        audio_duration_ms=max(2_000, len(words) * 300 + 500),
        provider=ProviderIdentity("whisperx", "3.8.5"),
        config=_forced_config(),
        words=tuple(words),
        cache_key="aligned-key",
    )


def _aligned_input(
    store: MemoryArtifactStore,
    output_root: Path,
    texts: tuple[str, ...],
    *,
    timing_sources: Mapping[int, AlignmentTimingSource] | None = None,
    alignment_scores: Mapping[int, float] | None = None,
) -> ForcedAlignmentResult:
    workspace = build_asset_workspace(ASSET_ID, output_root)
    audio_path = str(workspace / "audio.wav")
    aligned_path = str(workspace / "aligned_asr.json")
    manifest_path = str(workspace / "transcription_manifest.json")
    store.files[audio_path] = b"canonical audio"
    audio_sha = MemoryChecksum(store).sha256(audio_path)
    artifact = replace(
        _aligned_artifact(
            texts,
            timing_sources=timing_sources,
            alignment_scores=alignment_scores,
        ),
        audio_sha256=audio_sha,
    )
    store.write_json(aligned_path, artifact.to_dict(), overwrite=False)
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
            "aligned_asr": CacheRecord(
                path=aligned_path,
                size_bytes=store.size(aligned_path),
                sha256=checksum.sha256(aligned_path),
                cache_key=artifact.cache_key,
            ),
        },
    )
    store.write_json(manifest_path, manifest.to_dict(), overwrite=False)
    return ForcedAlignmentResult(
        path=aligned_path,
        manifest_path=manifest_path,
        artifact=artifact,
        cache_hit=False,
    )


def _transcript(text: str) -> StructuredTranscriptDTO:
    return StructuredTranscriptDTO(
        language="en",
        chapters=(
            TranscriptChapterDTO(
                number=1,
                title="Annual Meeting",
                paragraphs=(
                    TranscriptParagraphDTO(
                        text=text,
                        speaker_label="Warren Buffett",
                        stage_directions=("APPLAUSE",),
                    ),
                ),
            ),
        ),
    )


def _official_input(
    store: MemoryArtifactStore,
    output_root: Path,
    transcript: StructuredTranscriptDTO,
) -> OfficialTranscriptInput:
    path = str(build_asset_workspace(ASSET_ID, output_root) / "chapters.json")
    store.write_json(path, transcript.to_dict(), overwrite=store.exists(path))
    return OfficialTranscriptInput(
        path=path,
        sha256=MemoryChecksum(store).sha256(path),
        transcript=transcript,
    )


def _observability():
    log = MemoryLogSink()
    report = TranscriptionReportAggregator(ASSET_ID.value)
    observability = TranscriptionObservability(
        asset_id=ASSET_ID.value,
        stage=FUSION_STAGE_NAME,
        detailed_log=log,
        report=report,
        report_writer=MemoryReportWriter(),
    )
    return observability, log, report


def _service(
    store: MemoryArtifactStore,
    output_root: Path,
    aligner: FakeOfficialAligner | None = None,
):
    observability, log, report = _observability()
    service = TranscriptFusionService(
        checksum=MemoryChecksum(store),
        artifacts=store,
        events=observability,
        official_aligner=aligner,
        output_root=str(output_root),
    )
    return service, log, report


def test_versioned_normalization_covers_required_equivalences() -> None:
    policy = NormalizationPolicy()

    assert normalize_token("10%.", policy) == ("ten", "percent")
    assert normalize_token("$10", policy) == ("ten", "dollars")
    assert normalize_token("1998", policy) == ("nineteen", "ninety", "eight")
    assert normalize_token("Berkshire-Hathaway", policy) == (
        "berkshire",
        "hathaway",
    )
    assert normalize_token("We'll", policy) == ("we", "will")
    assert normalize_token("See's", policy) == normalize_token("Sees", policy)
    assert tokenize_surface_text("$1,000 and 10.5%.") == (
        "$1,000",
        "and",
        "10.5%.",
    )
    assert normalize_token("$1,000", policy) == (
        "one",
        "thousand",
        "dollars",
    )
    assert normalize_token("10.5%", policy) == (
        "ten",
        "point",
        "five",
        "percent",
    )


@pytest.mark.parametrize(
    ("asr_surface", "official_surface"),
    [
        ("$10", "ten dollars"),
        ("We'll", "We will"),
        ("Berkshire-Hathaway", "Berkshire Hathaway"),
    ],
)
def test_proven_equivalences_drive_one_to_many_mapping(
    asr_surface: str,
    official_surface: str,
) -> None:
    asr = _aligned_artifact(
        ("left", "anchor", asr_surface, "right", "anchor")
    ).words
    official, _ = build_official_tokens(
        _transcript(f"left anchor {official_surface} right anchor"),
        NormalizationPolicy(),
    )

    plans = plan_transcript_fusion(
        asr,
        official,
        normalization=NormalizationPolicy(),
        matching=_matching(),
    )

    collapsed = [
        plan for plan in plans if plan.match_type is MatchType.ONE_TO_MANY
    ]
    assert len(collapsed) == 1
    assert len(collapsed[0].asr_indices) == 1
    assert len(collapsed[0].official_indices) == 2


def test_public_dto_metadata_never_becomes_spoken_official_tokens() -> None:
    transcript = StructuredTranscriptDTO(
        language="en",
        chapters=(
            TranscriptChapterDTO(
                number=7,
                title="FORBIDDEN TITLE",
                paragraphs=(
                    TranscriptParagraphDTO(
                        text="Good morning.",
                        speaker_label="FORBIDDEN SPEAKER",
                        stage_directions=("FORBIDDEN APPLAUSE",),
                    ),
                    TranscriptParagraphDTO(
                        text="",
                        stage_directions=("FORBIDDEN MUSIC",),
                    ),
                ),
            ),
        ),
    )

    tokens, ignored = build_official_tokens(transcript, NormalizationPolicy())

    assert [token.text for token in tokens] == ["Good", "morning."]
    assert all(token.speaker_label == "FORBIDDEN SPEAKER" for token in tokens)
    assert [item.text for item in ignored] == [
        "FORBIDDEN TITLE",
        "FORBIDDEN APPLAUSE",
        "FORBIDDEN MUSIC",
    ]


def test_monotonic_local_dp_plans_all_non_official_only_mapping_types() -> None:
    asr = _aligned_artifact(
        (
            "Good",
            "morning.",
            "Buffet",
            "likes",
            "Sees",
            "and",
            "10%",
            "in",
            "nineteen",
            "ninety",
            "eight",
            "aside",
            "thank",
            "you.",
        )
    ).words
    official, _ = build_official_tokens(
        _transcript(
            "Good morning. Buffett likes See's and ten percent in 1998 thank you."
        ),
        NormalizationPolicy(),
    )

    plans = plan_transcript_fusion(
        asr,
        official,
        normalization=NormalizationPolicy(),
        matching=_matching(),
    )

    match_types = {plan.match_type for plan in plans}
    assert {
        MatchType.EXACT,
        MatchType.NORMALIZED_EXACT,
        MatchType.SUBSTITUTION,
        MatchType.ONE_TO_MANY,
        MatchType.MANY_TO_ONE,
        MatchType.ASR_ONLY,
    } <= match_types
    assert [index for plan in plans for index in plan.asr_indices] == list(
        range(len(asr))
    )
    assert [index for plan in plans for index in plan.official_indices] == list(
        range(len(official))
    )


def test_one_to_many_never_collapses_across_speaker_boundary() -> None:
    asr = _aligned_artifact(("left", "anchor", "we'll", "right", "anchor")).words
    transcript = StructuredTranscriptDTO(
        language="en",
        chapters=(
            TranscriptChapterDTO(
                number=1,
                title="",
                paragraphs=(
                    TranscriptParagraphDTO("left anchor we", speaker_label="Buffett"),
                    TranscriptParagraphDTO("will right anchor", speaker_label="Munger"),
                ),
            ),
        ),
    )
    official, _ = build_official_tokens(transcript, NormalizationPolicy())

    plans = plan_transcript_fusion(
        asr,
        official,
        normalization=NormalizationPolicy(),
        matching=MatchingPolicy(),
    )

    assert MatchType.ONE_TO_MANY not in {plan.match_type for plan in plans}


@pytest.mark.parametrize(
    ("asr_surface", "official_surface"),
    [("million", "billion"), ("increase", "decrease")],
)
def test_similar_but_semantically_different_words_are_not_substituted(
    asr_surface: str,
    official_surface: str,
) -> None:
    asr = _aligned_artifact(
        ("left", "anchor", asr_surface, "right", "anchor")
    ).words
    official, _ = build_official_tokens(
        _transcript(f"left anchor {official_surface} right anchor"),
        NormalizationPolicy(),
    )

    plans = plan_transcript_fusion(
        asr,
        official,
        normalization=NormalizationPolicy(),
        matching=MatchingPolicy(),
    )

    assert MatchType.SUBSTITUTION not in {plan.match_type for plan in plans}


def test_many_to_one_never_claims_merged_acoustic_for_interpolated_input() -> None:
    asr = _aligned_artifact(
        (
            "left",
            "anchor",
            "nineteen",
            "ninety",
            "eight",
            "right",
            "anchor",
        ),
        timing_sources={4: AlignmentTimingSource.INTERPOLATED},
    ).words
    official, _ = build_official_tokens(
        _transcript("left anchor 1998 right anchor"),
        NormalizationPolicy(),
    )

    plans = plan_transcript_fusion(
        asr,
        official,
        normalization=NormalizationPolicy(),
        matching=MatchingPolicy(),
    )

    assert MatchType.MANY_TO_ONE not in {plan.match_type for plan in plans}


def test_service_persists_all_mappings_exclusions_events_and_report(
    tmp_path: Path,
) -> None:
    store = MemoryArtifactStore()
    aligned = _aligned_input(
        store,
        tmp_path,
        (
            "Good",
            "morning.",
            "Buffet",
            "likes",
            "Sees",
            "and",
            "10%",
            "in",
            "nineteen",
            "ninety",
            "eight",
            "aside",
            "thank",
            "you.",
        ),
    )
    official = _official_input(
        store,
        tmp_path,
        _transcript(
            "Good morning. Buffett likes See's and ten percent in 1998 "
            "really thank you."
        ),
    )
    service, log, report = _service(store, tmp_path)

    result = service.execute(aligned, official=official, matching=_matching())

    assert result.path == str(
        build_asset_workspace(ASSET_ID, tmp_path) / "transcript_fusion.json"
    )
    assert result.artifact is not None
    assert TranscriptFusionArtifact.from_dict(
        store.read_json(result.path)
    ) == result.artifact
    assert {word.match_type for word in result.words} >= {
        MatchType.SUBSTITUTION,
        MatchType.ONE_TO_MANY,
        MatchType.MANY_TO_ONE,
        MatchType.ASR_ONLY,
    }
    assert result.artifact.excluded_official[0].official_token_ids == ("ot11",)
    assert result.artifact.local_validations[0].status is LocalValidationStatus.EXCLUDED
    codes = [event.code for event in log.events]
    assert EventCode.FUSION_TEXT_REPLACED in codes
    assert EventCode.FUSION_ONE_TO_MANY_COLLAPSED in codes
    assert EventCode.FUSION_MANY_TO_ONE_COLLAPSED in codes
    assert EventCode.FUSION_ASR_ONLY_RETAINED in codes
    assert EventCode.FUSION_OFFICIAL_ONLY_EXCLUDED in codes
    assert codes[-1] is EventCode.FUSION_COMPLETED
    counts = report.snapshot().counts
    assert counts["substitution"] == 1
    assert counts["one_to_many"] == 1
    assert counts["many_to_one"] == 1
    assert counts["asr_only"] == 1
    assert counts["official_only_excluded"] == 1


def test_official_only_is_recovered_only_between_reliable_acoustic_anchors(
    tmp_path: Path,
) -> None:
    store = MemoryArtifactStore()
    aligned = _aligned_input(
        store, tmp_path, ("alpha", "beta", "gamma", "delta")
    )
    official = _official_input(
        store, tmp_path, _transcript("alpha beta truly gamma delta")
    )
    aligner = FakeOfficialAligner(
        (OfficialAlignmentCandidate("ot3", "truly", 550, 650, 0.91),)
    )
    service, log, report = _service(store, tmp_path, aligner)

    result = service.execute(
        aligned,
        official=official,
        official_alignment_config=_alignment_config(),
    )

    assert [word.text for word in result.words] == [
        "alpha",
        "beta",
        "truly",
        "gamma",
        "delta",
    ]
    recovered = result.words[2]
    assert recovered.asr_word_ids == ()
    assert recovered.official_token_ids == ("ot3",)
    assert recovered.match_type is MatchType.OFFICIAL_ONLY
    assert len(aligner.calls) == 1
    assert (
        result.artifact.local_validations[0].status
        is LocalValidationStatus.RECOVERED
    )
    assert result.artifact.local_validations[0].candidates == aligner.candidates
    assert report.snapshot().counts["official_only_recovered"] == 1
    assert EventCode.FUSION_OFFICIAL_ONLY_RECOVERED in [
        event.code for event in log.events
    ]


def test_official_only_uses_nearest_surrounding_ngram_anchors(
    tmp_path: Path,
) -> None:
    store = MemoryArtifactStore()
    aligned = _aligned_input(
        store, tmp_path, ("a", "b", "c", "d", "e", "f", "g")
    )
    official = _official_input(
        store, tmp_path, _transcript("a b c x d e f g")
    )
    aligner = FakeOfficialAligner(
        (OfficialAlignmentCandidate("ot4", "x", 850, 900, 0.91),)
    )
    service, _, _ = _service(store, tmp_path, aligner)

    result = service.execute(
        aligned,
        official=official,
        official_alignment_config=_alignment_config(),
    )

    assert [word.text for word in result.words] == [
        "a",
        "b",
        "c",
        "x",
        "d",
        "e",
        "f",
        "g",
    ]
    assert len(aligner.calls) == 1
    assert aligner.calls[0][2].id == "aw2"
    assert aligner.calls[0][3].id == "aw4"


def test_official_only_requires_every_word_in_surrounding_ngram_anchors(
    tmp_path: Path,
) -> None:
    store = MemoryArtifactStore()
    aligned = _aligned_input(
        store,
        tmp_path,
        ("a", "b", "c", "d", "e", "f", "g"),
        alignment_scores={1: 0.1},
    )
    official = _official_input(
        store, tmp_path, _transcript("a b c x d e f g")
    )
    aligner = FakeOfficialAligner(
        (OfficialAlignmentCandidate("ot4", "x", 850, 900, 0.91),)
    )
    service, _, _ = _service(store, tmp_path, aligner)

    result = service.execute(
        aligned,
        official=official,
        official_alignment_config=_alignment_config(),
    )

    assert aligner.calls == []
    assert "lacks reliable acoustic anchors" in (
        result.artifact.excluded_official[0].reason
    )


@pytest.mark.parametrize(
    ("candidates", "timing_sources", "reason"),
    [
        ((), {}, "coverage"),
        (
            (OfficialAlignmentCandidate("ot3", "truly", 350, 450, 0.9),),
            {},
            "outside anchors or overlaps",
        ),
        (
            (OfficialAlignmentCandidate("ot3", "truly", 550, 650, 0.4),),
            {},
            "below configured minimum",
        ),
        (
            (OfficialAlignmentCandidate("ot3", "truly", 450, 550, 0.9),),
            {2: AlignmentTimingSource.INTERPOLATED},
            "lacks reliable acoustic anchors",
        ),
    ],
)
def test_failed_or_unsafe_official_only_alignment_is_excluded(
    tmp_path: Path,
    candidates: tuple[OfficialAlignmentCandidate, ...],
    timing_sources: Mapping[int, AlignmentTimingSource],
    reason: str,
) -> None:
    store = MemoryArtifactStore()
    aligned = _aligned_input(
        store,
        tmp_path,
        ("alpha", "beta", "gamma", "delta"),
        timing_sources=timing_sources,
    )
    official = _official_input(
        store, tmp_path, _transcript("alpha beta truly gamma delta")
    )
    aligner = FakeOfficialAligner(candidates)
    service, log, report = _service(store, tmp_path, aligner)

    result = service.execute(
        aligned,
        official=official,
        official_alignment_config=_alignment_config(),
    )

    assert [word.text for word in result.words] == [
        "alpha",
        "beta",
        "gamma",
        "delta",
    ]
    assert reason in result.artifact.excluded_official[0].reason
    assert result.artifact.local_validations[0].status is LocalValidationStatus.EXCLUDED
    assert report.snapshot().counts["official_only_excluded"] == 1
    assert EventCode.FUSION_OFFICIAL_ONLY_EXCLUDED in [
        event.code for event in log.events
    ]


def test_low_score_acoustic_word_is_not_a_reliable_official_only_anchor(
    tmp_path: Path,
) -> None:
    store = MemoryArtifactStore()
    aligned = _aligned_input(
        store,
        tmp_path,
        ("alpha", "beta", "gamma", "delta"),
        alignment_scores={2: 0.1},
    )
    official = _official_input(
        store, tmp_path, _transcript("alpha beta truly gamma delta")
    )
    aligner = FakeOfficialAligner(
        (OfficialAlignmentCandidate("ot3", "truly", 550, 650, 0.9),)
    )
    service, log, report = _service(store, tmp_path, aligner)

    result = service.execute(
        aligned,
        official=official,
        official_alignment_config=_alignment_config(),
    )

    assert aligner.calls == []
    assert "lacks reliable acoustic anchors" in (
        result.artifact.excluded_official[0].reason
    )


def test_large_bilaterally_anchored_official_run_is_excluded_not_fatal(
    tmp_path: Path,
) -> None:
    store = MemoryArtifactStore()
    aligned = _aligned_input(
        store, tmp_path, ("alpha", "beta", "gamma", "delta")
    )
    official = _official_input(
        store,
        tmp_path,
        _transcript("alpha beta one two three four gamma delta"),
    )
    aligner = FakeOfficialAligner()
    service, log, report = _service(store, tmp_path, aligner)

    result = service.execute(
        aligned,
        official=official,
        official_alignment_config=_alignment_config(),
    )

    assert len(result.artifact.excluded_official[0].official_token_ids) == 4
    assert "exceeds local acoustic validation limit" in (
        result.artifact.excluded_official[0].reason
    )
    assert aligner.calls == []


def test_one_sided_official_only_word_is_excluded_without_calling_aligner(
    tmp_path: Path,
) -> None:
    store = MemoryArtifactStore()
    aligned = _aligned_input(store, tmp_path, ("alpha", "beta", "gamma"))
    official = _official_input(
        store, tmp_path, _transcript("truly alpha beta gamma")
    )
    aligner = FakeOfficialAligner()
    service, log, report = _service(store, tmp_path, aligner)

    result = service.execute(
        aligned,
        official=official,
        official_alignment_config=_alignment_config(),
    )

    assert aligner.calls == []
    assert "lacks reliable acoustic anchors" in (
        result.artifact.excluded_official[0].reason
    )


def test_official_only_never_recovers_across_speaker_boundary(
    tmp_path: Path,
) -> None:
    store = MemoryArtifactStore()
    aligned = _aligned_input(
        store, tmp_path, ("alpha", "beta", "gamma", "delta")
    )
    transcript = StructuredTranscriptDTO(
        language="en",
        chapters=(
            TranscriptChapterDTO(
                number=1,
                title="",
                paragraphs=(
                    TranscriptParagraphDTO("alpha beta", speaker_label="Buffett"),
                    TranscriptParagraphDTO("truly", speaker_label="Munger"),
                    TranscriptParagraphDTO("gamma delta", speaker_label="Buffett"),
                ),
            ),
        ),
    )
    official = _official_input(store, tmp_path, transcript)
    aligner = FakeOfficialAligner(
        (OfficialAlignmentCandidate("ot3", "truly", 550, 650, 0.9),)
    )
    service, log, report = _service(store, tmp_path, aligner)

    result = service.execute(
        aligned,
        official=official,
        official_alignment_config=_alignment_config(),
    )

    assert aligner.calls == []
    assert "speaker boundary" in result.artifact.excluded_official[0].reason


def test_large_unanchored_conflict_is_hard_failure_without_artifact(
    tmp_path: Path,
) -> None:
    store = MemoryArtifactStore()
    aligned = _aligned_input(store, tmp_path, ("alpha", "beta", "gamma"))
    official = _official_input(store, tmp_path, _transcript("one two three"))
    service, log, report = _service(store, tmp_path)

    with pytest.raises(FusionFailure, match="lacks reliable monotonic"):
        service.execute(aligned, official=official)

    assert not store.exists(
        str(build_asset_workspace(ASSET_ID, tmp_path) / "transcript_fusion.json")
    )
    assert log.events[-1].code is EventCode.FUSION_REGION_UNMATCHED
    assert report.snapshot().counts["conflict"] == 1


def test_no_official_uses_identity_without_file_or_warning_storm(
    tmp_path: Path,
) -> None:
    store = MemoryArtifactStore()
    aligned = _aligned_input(store, tmp_path, ("hello", "world."))
    aligner = FakeOfficialAligner()
    service, log, report = _service(store, tmp_path, aligner)

    result = service.execute(aligned, official=None)

    assert result.path is None
    assert result.artifact is None
    assert result.used_official is False
    assert [word.text for word in result.words] == ["hello", "world."]
    assert [event.code for event in log.events] == [EventCode.FUSION_NO_OFFICIAL]
    assert aligner.calls == []
    assert report.snapshot().counts["warning"] == 0
    assert not store.exists(
        str(build_asset_workspace(ASSET_ID, tmp_path) / "transcript_fusion.json")
    )


def test_canonical_chapters_file_cannot_be_silently_ignored(tmp_path: Path) -> None:
    store = MemoryArtifactStore()
    aligned = _aligned_input(store, tmp_path, ("hello", "world."))
    _official_input(store, tmp_path, _transcript("hello world."))
    service, log, report = _service(store, tmp_path)

    with pytest.raises(FusionInputValidationError, match="no official input"):
        service.execute(aligned, official=None)


def test_cache_hit_and_policy_staleness_do_not_rerun_local_aligner(
    tmp_path: Path,
) -> None:
    store = MemoryArtifactStore()
    aligned = _aligned_input(
        store, tmp_path, ("alpha", "beta", "gamma", "delta")
    )
    official = _official_input(
        store, tmp_path, _transcript("alpha beta truly gamma delta")
    )
    aligner = FakeOfficialAligner(
        (OfficialAlignmentCandidate("ot3", "truly", 550, 650, 0.9),)
    )
    service, log, report = _service(store, tmp_path, aligner)

    first = service.execute(
        aligned,
        official=official,
        official_alignment_config=_alignment_config(),
    )
    cached_service, cached_log, cached_report = _service(
        store, tmp_path, aligner
    )
    second = cached_service.execute(
        aligned,
        official=official,
        official_alignment_config=_alignment_config(),
    )

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert len(aligner.calls) == 1
    assert cached_report.snapshot().counts["exact"] == 4
    assert cached_report.snapshot().counts["official_only_recovered"] == 1
    assert cached_log.events[-1].code is EventCode.FUSION_CACHE_HIT
    changed = replace(MatchingPolicy(), max_local_window_words=30)
    with pytest.raises(ExistingTranscriptionArtifactConflict):
        service.execute(
            aligned,
            official=official,
            matching=changed,
            official_alignment_config=_alignment_config(),
        )
    third = service.execute(
        aligned,
        official=official,
        matching=changed,
        official_alignment_config=_alignment_config(),
        policy=TranscriptFusionPolicy(overwrite=True),
    )
    assert third.artifact.cache_key != first.artifact.cache_key
    assert len(aligner.calls) == 2


def test_empty_spoken_official_cache_hit_keeps_asr_only_debug_summary(
    tmp_path: Path,
) -> None:
    store = MemoryArtifactStore()
    aligned = _aligned_input(store, tmp_path, ("hello", "world."))
    transcript = StructuredTranscriptDTO(
        language="en",
        chapters=(
            TranscriptChapterDTO(
                number=1,
                title="Opening",
                paragraphs=(
                    TranscriptParagraphDTO(
                        text="", stage_directions=("Applause",)
                    ),
                ),
            ),
        ),
    )
    official = _official_input(store, tmp_path, transcript)
    first_service, first_log, first_report = _service(store, tmp_path)

    first = first_service.execute(aligned, official=official)
    cached_service, cached_log, cached_report = _service(store, tmp_path)
    cached = cached_service.execute(aligned, official=official)

    assert first.cache_hit is False
    assert cached.cache_hit is True
    first_asr_only = [
        event
        for event in first_log.events
        if event.code is EventCode.FUSION_ASR_ONLY_RETAINED
    ]
    cached_asr_only = [
        event
        for event in cached_log.events
        if event.code is EventCode.FUSION_ASR_ONLY_RETAINED
    ]
    assert [event.severity for event in cached_asr_only] == [
        event.severity for event in first_asr_only
    ]
    assert all(event.severity.value == "DEBUG" for event in cached_asr_only)
    assert cached_report.snapshot().counts == first_report.snapshot().counts
    assert cached_report.snapshot().counts["asr_only"] == 2
    assert cached_report.snapshot().counts["warning"] == 0


def test_local_aligner_identity_and_config_are_part_of_fusion_cache_key(
    tmp_path: Path,
) -> None:
    store = MemoryArtifactStore()
    aligned = _aligned_input(
        store, tmp_path, ("alpha", "beta", "gamma", "delta")
    )
    official = _official_input(
        store, tmp_path, _transcript("alpha beta truly gamma delta")
    )
    aligner = FakeOfficialAligner(
        (OfficialAlignmentCandidate("ot3", "truly", 550, 650, 0.9),)
    )
    service, log, report = _service(store, tmp_path, aligner)
    first = service.execute(
        aligned,
        official=official,
        official_alignment_config=_alignment_config(),
    )
    aligner.identity = ProviderIdentity("fake-local-aligner", "2.0")

    with pytest.raises(ExistingTranscriptionArtifactConflict):
        service.execute(
            aligned,
            official=official,
            official_alignment_config=_alignment_config(),
        )
    second = service.execute(
        aligned,
        official=official,
        official_alignment_config=_alignment_config(),
        policy=TranscriptFusionPolicy(overwrite=True),
    )
    changed_config = replace(_alignment_config(), model_version="2026.2")
    with pytest.raises(ExistingTranscriptionArtifactConflict):
        service.execute(
            aligned,
            official=official,
            official_alignment_config=changed_config,
        )

    assert second.artifact.cache_key != first.artifact.cache_key


def test_changed_chapters_checksum_stales_only_fusion(tmp_path: Path) -> None:
    store = MemoryArtifactStore()
    aligned = _aligned_input(store, tmp_path, ("hello", "world."))
    original = _official_input(store, tmp_path, _transcript("hello world."))
    service, log, report = _service(store, tmp_path)
    first = service.execute(aligned, official=original)
    changed = _official_input(store, tmp_path, _transcript("Hello world."))

    with pytest.raises(ExistingTranscriptionArtifactConflict):
        service.execute(aligned, official=changed)
    second = service.execute(
        aligned,
        official=changed,
        policy=TranscriptFusionPolicy(overwrite=True),
    )

    assert second.artifact.cache_key != first.artifact.cache_key
    manifest = AudioVadAsrCacheManifest.from_dict(
        store.read_json(aligned.manifest_path)
    )
    assert manifest.records["aligned_asr"].sha256 == first.artifact.aligned_asr_sha256


def test_tampered_alignment_or_chapters_fails_before_matching(tmp_path: Path) -> None:
    store = MemoryArtifactStore()
    aligned = _aligned_input(store, tmp_path, ("hello", "world."))
    official = _official_input(store, tmp_path, _transcript("hello world."))
    service, log, report = _service(store, tmp_path)
    store.files[official.path] = b"tampered"

    with pytest.raises(FusionInputValidationError, match="chapters checksum"):
        service.execute(aligned, official=official)


def test_whisperx_official_alignment_adapter_is_lazy_and_word_only() -> None:
    class Backend:
        def __init__(self) -> None:
            self.load_audio_calls: list[str] = []
            self.load_model_calls: list[dict[str, str]] = []
            self.align_calls: list[tuple[Any, ...]] = []

        def load_audio(self, path: str):
            self.load_audio_calls.append(path)
            return "audio"

        def load_align_model(self, **kwargs):
            self.load_model_calls.append(kwargs)
            return "model", {"language": "en"}

        def align(self, *args, **kwargs):
            self.align_calls.append((args, kwargs))
            return {
                "word_segments": [
                    {"word": "truly", "start": 0.45, "end": 0.55, "score": 0.9}
                ],
                "char_segments": [{"char": "t", "start": 0.45}],
            }

    backend = Backend()
    resolved_models: list[tuple[str, str]] = []

    def resolve_model(model: str, version: str) -> str:
        resolved_models.append((model, version))
        return f"/models/{model}/{version}"

    adapter = WhisperXOfficialTranscriptAligner(
        whisperx_version="3.8.5",
        backend=backend,
        model_resolver=resolve_model,
    )
    transcript = _transcript("truly")
    tokens, _ = build_official_tokens(transcript, NormalizationPolicy())
    aligned = _aligned_artifact(("left", "right")).words

    assert resolved_models == []
    candidates = adapter.align_official(
        "audio.wav", tokens, aligned[0], aligned[1], _alignment_config()
    )
    adapter.align_official(
        "audio.wav",
        tokens,
        aligned[0],
        aligned[1],
        replace(_alignment_config(), model_version="2026.2"),
    )

    assert candidates == (
        OfficialAlignmentCandidate("ot1", "truly", 450, 550, 0.9),
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
