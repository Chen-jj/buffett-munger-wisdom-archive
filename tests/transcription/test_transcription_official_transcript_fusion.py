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
    TextSource,
    TimingSource,
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
from transcription.domain.fusion_acoustics import AcousticCandidateEvidence, AcousticWordEvidence


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
        score=None,
    ) -> None:
        self.identity = ProviderIdentity("fake-local-aligner", version)
        self.candidates = candidates
        self.error = error
        self.calls: list[tuple[Any, ...]] = []
        self.comparisons: list[tuple[Any, ...]] = []
        self.score = score

    def align_official_window(self, audio_path, tokens, start_ms, end_ms, config):
        self.calls.append((audio_path, tokens, start_ms, end_ms, config))
        if self.error is not None:
            raise self.error
        return self.candidates

    def score_candidates(self, audio_path, start_ms, end_ms, readings, config):
        self.comparisons.append((start_ms, end_ms, readings))
        if self.score is None:
            return tuple(AcousticCandidateEvidence(None) for _ in readings)
        return self.score(start_ms, end_ms, readings)


def _alignment_config() -> OfficialAlignmentConfig:
    return OfficialAlignmentConfig(
        model="wav2vec2-english",
        model_version="2026.1",
        device="cpu",
        min_alignment_score=0.6,
        min_anchor_alignment_score=0.6,
    )


def _acoustic_path(likelihood, words):
    return AcousticCandidateEvidence(
        likelihood, words[0].start_ms, words[-1].end_ms,
        mean_character_score=sum(word.score for word in words) / len(words),
        energy_coverage=0.8, word_evidence=words,
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
    timings: tuple[tuple[int, int], ...] | None = None,
) -> AlignedAsrArtifact:
    selected_sources = timing_sources or {}
    selected_scores = alignment_scores or {}
    words: list[AlignedAsrWord] = []
    for position, text in enumerate(texts, start=1):
        default_start = 100 + (position - 1) * 300
        start_ms, end_ms = timings[position - 1] if timings else (default_start, default_start + 100)
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
                end_ms=end_ms,
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
        audio_duration_ms=max(2_000, len(words) * 300 + 500, words[-1].end_ms if words else 0),
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
    timings: tuple[tuple[int, int], ...] | None = None,
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
            timings=timings,
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


@pytest.mark.parametrize("spelling", ("See's", "See’s"))
def test_official_sees_candy_spelling_preserves_bilaterally_anchored_asr_time(
    tmp_path: Path, spelling: str,
) -> None:
    store = MemoryArtifactStore()
    aligned = _aligned_input(
        store, tmp_path, ("the", "castle", "Seas", "candy", "has", "a", "moat."),
    )
    official = _official_input(
        store, tmp_path, _transcript(f"the castle {spelling} Candy has a moat."),
    )
    service, _, _ = _service(store, tmp_path)

    result = service.execute(aligned, official=official)

    corrected = result.words[2]
    original = aligned.artifact.words[2]
    assert corrected.text == spelling
    assert corrected.match_type is MatchType.SUBSTITUTION
    assert corrected.asr_word_ids == (original.id,)
    assert corrected.official_token_ids == ("ot3",)
    assert (corrected.start_ms, corrected.end_ms) == (original.start_ms, original.end_ms)
    assert len(result.words) == len(aligned.artifact.words)


@pytest.mark.parametrize(("asr", "official"), (
    (("the", "castle", "Seas", "candy", "has", "a", "moat."), "the castle sees candy has a moat."),
    (("Seas", "candy", "has", "a", "moat."), "See's Candy has a moat."),
))
def test_default_sees_alias_requires_actual_apostrophized_official_word_and_bilateral_anchors(
    asr: tuple[str, ...], official: str,
) -> None:
    tokens, _ = build_official_tokens(_transcript(official), NormalizationPolicy())
    plans = plan_transcript_fusion(
        _aligned_artifact(asr).words, tokens,
        normalization=NormalizationPolicy(), matching=MatchingPolicy(),
    )
    assert MatchType.SUBSTITUTION not in {plan.match_type for plan in plans}


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
    assert not result.artifact.local_validations
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


def test_official_only_keeps_adjacent_shared_timing(
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
    assert aligner.calls[0][2:4] == (800, 1000)


def test_official_only_uses_other_reliable_words_when_an_ngram_member_is_weak(
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

    assert aligner.calls[0][2:4] == (800, 1000)
    assert result.words[3].text == "x"


@pytest.mark.parametrize(
    ("candidates", "timing_sources", "reason"),
    [
        ((), {}, "did not produce"),
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
            "same-utterance acoustic window",
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


def test_shared_boundary_with_low_score_is_fixed_by_nearby_context(
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

    assert aligner.calls[0][2:4] == (500, 700)
    assert result.words[2].text == "truly"


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

    assert tuple(row.official_token_ids for row in result.artifact.excluded_official) == (("ot3", "ot4", "ot5", "ot6"),)
    assert aligner.calls == []


def test_utterance_at_audio_edge_uses_independent_bound_on_one_side(
    tmp_path: Path,
) -> None:
    store = MemoryArtifactStore()
    aligned = _aligned_input(store, tmp_path, ("alpha", "beta", "gamma"))
    official = _official_input(
        store, tmp_path, _transcript("truly alpha beta gamma")
    )
    aligner = FakeOfficialAligner((OfficialAlignmentCandidate("ot1", "truly", 10, 80, 0.9),))
    service, _, _ = _service(store, tmp_path, aligner)

    result = service.execute(aligned, official=official, official_alignment_config=_alignment_config())

    assert aligner.calls[0][2:4] == (0, 100)
    assert result.words[0].text == "truly"


def test_anchor_chain_skips_an_early_match_far_ahead_in_the_transcript() -> None:
    from transcription.application.fusion import _find_monotonic_anchors

    asr = _aligned_artifact(tuple("alpha beta gamma delta epsilon zeta eta theta".split())).words
    policy = NormalizationPolicy()
    official, _ = build_official_tokens(
        _transcript("gamma delta epsilon zeta eta theta alpha beta"), policy
    )

    anchors = _find_monotonic_anchors(asr, official, policy, MatchingPolicy())

    assert [(anchor.asr_start, anchor.official_start) for anchor in anchors] == [(2, 0), (4, 2), (6, 4)]


def test_large_windows_refine_local_matches_without_losing_any_word() -> None:
    from transcription.application.fusion import _align_local_region

    common = tuple("alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu".split())
    asr = _aligned_artifact(("leading",) + common + ("ending",)).words
    policy = NormalizationPolicy()
    official, _ = build_official_tokens(
        _transcript(" ".join(("leading", "extra") + common + ("different",))), policy
    )

    plans = _align_local_region(
        asr, official, 0, len(asr), 0, len(official), policy, MatchingPolicy(),
        left_anchored=True, right_anchored=True,
    )

    assert [index for plan in plans for index in plan.asr_indices] == list(range(len(asr)))
    assert [index for plan in plans for index in plan.official_indices] == list(range(len(official)))
    assert any(plan.anchor for plan in plans)


def test_asr_only_window_handles_two_thousand_aligned_words() -> None:
    asr = _aligned_artifact(tuple(f"word{index}" for index in range(2000))).words

    plans = plan_transcript_fusion(asr, (), normalization=NormalizationPolicy(), matching=MatchingPolicy())

    assert len(plans) == 2000
    assert all(plan.match_type is MatchType.ASR_ONLY for plan in plans)
    assert [plan.asr_indices[0] for plan in plans] == list(range(2000))


def test_sentence_spans_have_provenance_without_publishing_untimed_words(
    tmp_path: Path,
) -> None:
    store = MemoryArtifactStore()
    aligned = _aligned_input(
        store, tmp_path, tuple("Those remarks sound something else to all of us. A unique side thought.".split())
    )
    official = _official_input(store, tmp_path, _transcript("Those remarks sound much better to all of us."))
    service, _, _ = _service(store, tmp_path)

    result = service.execute(aligned, official=official)

    assert result.artifact is not None
    first, = result.artifact.official_sentence_spans
    assert first.asr_word_ids == tuple(f"aw{index}" for index in range(1, 10))
    assert first.official_token_ids == tuple(f"ot{index}" for index in range(1, 10))
    assert result.artifact.excluded_official[0].official_token_ids == ("ot4", "ot5")
    assert " ".join(word.text for word in result.words) == (
        "Those remarks sound something else to all of us. A unique side thought."
    )
    assert result.words[-4].start_ms == aligned.artifact.words[9].start_ms
    assert result.words[-1].end_ms == aligned.artifact.words[-1].end_ms
    data = store.read_json(result.path)
    assert "review_sentences" not in data
    assert TranscriptFusionArtifact.from_dict(data) == result.artifact


def test_fusion_uses_official_equivalences_and_preserves_duplicate_asr(
    tmp_path: Path,
) -> None:
    store = MemoryArtifactStore()
    aligned = _aligned_input(
        store, tmp_path,
        ("Well,", "it's", "345", "in", "Omaha", "and", "this", "is", "a", "very", "logical,",
         "well-structured...", "company", "from", "from", "this", "small", "town."),
    )
    official = _official_input(store, tmp_path, _transcript(
        "Well, it's 3:45 in Omaha and this is a very logical, well structured, company from this small town."
    ))
    service, _, _ = _service(store, tmp_path)

    result = service.execute(aligned, official=official)

    assert result.artifact is not None
    row, = result.artifact.official_sentence_spans
    assert row.asr_word_ids == tuple(word.id for word in aligned.artifact.words)
    assert not result.artifact.excluded_official
    assert [item.asr_word_ids for item in result.words if item.text == "from"] == [("aw14",), ("aw15",)]
    assert result.words[2].text == "3:45"
    assert result.words[2].start_ms == aligned.artifact.words[2].start_ms
    assert result.words[2].end_ms == aligned.artifact.words[2].end_ms
    assert result.words[11].text == "well structured,"


def test_short_official_reply_and_inline_stage_directions_use_their_local_context(tmp_path: Path) -> None:
    store = MemoryArtifactStore()
    aligned = _aligned_input(
        store, tmp_path, tuple("What do you think? No. I agree with that CEO entirely.".split())
    )
    official = _official_input(store, tmp_path, _transcript(
        "(Buffett laughs) What do you think? [Laughter] Nope. I agree with that (CEO) entirely."
    ))
    service, _, _ = _service(store, tmp_path)

    result = service.execute(aligned, official=official)

    assert result.artifact is not None
    assert " ".join(word.text for word in result.words) == "What do you think? No. I agree with that (CEO) entirely."
    assert len(result.artifact.official_sentence_spans) == 2
    assert result.artifact.excluded_official[0].official_token_ids == ("ot5",)
    assert [item.text for item in result.artifact.ignored_content][-2:] == ["(Buffett laughs)", "[Laughter]"]


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
    assert "same-utterance acoustic window" in result.artifact.excluded_official[0].reason


@pytest.mark.parametrize(
    ("mode", "expected"),
    (("official", "many"), ("asr", "lethal"), ("unstable", "many"), ("overlap", "lethal")),
)
def test_conflict_uses_a_shared_fixed_window_and_publishes_only_supported_timing(
    tmp_path: Path, mode: str, expected: str,
) -> None:
    def score(start, end, readings):
        if readings != ("lethal", "many"):
            assert mode == "overlap"
            return tuple(AcousticCandidateEvidence(None) for _ in readings)
        margin = -6 if mode == "asr" or mode == "unstable" and start > 500 else 6
        baseline = AcousticCandidateEvidence(-20, 710, 805, .8, .5, .75, 0,
                                             (AcousticWordEvidence("lethal", 710, 805, .8),))
        candidate = AcousticCandidateEvidence(-20 + margin, start - 1 if mode == "overlap" else 720,
                                              815, .9, .6, .8, 0)
        return baseline, candidate

    store = MemoryArtifactStore()
    aligned = _aligned_input(store, tmp_path, ("consider", "how", "lethal", "it", "is", "because"),
                             alignment_scores={4: .23})
    official = _official_input(store, tmp_path, _transcript("consider how many it is because"))
    aligner = FakeOfficialAligner(score=score)
    service, log, _ = _service(store, tmp_path, aligner)

    result = service.execute(aligned, official=official, official_alignment_config=_alignment_config())

    word = result.words[2]
    assert word.text == expected
    assert word.asr_word_ids == ("aw3",)
    assert (word.start_ms, word.end_ms) == ((720, 815) if expected == "many" else (700, 800))
    assert result.words[3].start_ms == 1000
    assert [call[:2] for call in aligner.comparisons[:5]] == [
        (500, 1000), (540, 1000), (500, 960), (460, 1000), (500, 1040),
    ]
    assert sum(event.action.startswith("score_") for event in log.events) == 10


def test_different_dollar_amount_is_published_between_retimed_shared_words(tmp_path: Path) -> None:
    original_reading = "a million one hundred and seven thousand four hundred"
    official_reading = "a billion one hundred and seven million four hundred thousand"
    left = tuple(AcousticWordEvidence(*fields) for fields in (
        ("i", 400, 420, .86), ("would", 461, 561, .78),
        ("have", 581, 682, .22), ("put", 702, 822, .99),
    ))
    right = tuple(AcousticWordEvidence(*fields) for fields in (
        ("or", 4641, 4681, .54), ("something", 4742, 4963, .98), ("like", 5003, 5164, .88),
    ))
    original = tuple(AcousticWordEvidence(word, 1626 + i * 200, 1726 + i * 200, .40)
                     for i, word in enumerate(original_reading.split()))
    replacement = (*tuple(AcousticWordEvidence(word, 1626 + i * 200, 1726 + i * 200, .90)
                          for i, word in enumerate(official_reading.split()[:-1])),
                   AcousticWordEvidence("thousand", 4380, 4641, .53))
    outer_replacement = (*replacement[:-1], replace(replacement[-1], end_ms=4621))
    paths = {
        (340, 5204, f"I would have put {original_reading} or something like"):
            _acoustic_path(-137, (*left, *original, replace(right[0], start_ms=4501), *right[1:])),
        (340, 5204, f"I would have put {official_reading} or something like"):
            _acoustic_path(-57, (*left, *outer_replacement, *right)),
        (822, 4641, original_reading): _acoustic_path(-159, original),
        (822, 4641, official_reading): _acoustic_path(-30, replacement),
    }
    store = MemoryArtifactStore()
    aligned = _aligned_input(
        store, tmp_path, ("something,", "I", "would", "have", "put", "$1,107,400", "or", "something", "like", "that."),
        alignment_scores={5: .30}, timings=(
            (60, 340), (400, 440), (460, 580), (600, 2282), (2322, 2702),
            (2742, 3402), (3523, 3643), (4724, 4964), (4984, 5164), (5204, 6645),
        ),
    )
    official = _official_input(store, tmp_path, _transcript("something, I would have put $1,107,400,000 or something like that."))
    aligner = FakeOfficialAligner(score=lambda start, end, readings: tuple(
        paths.get((start, end, reading), AcousticCandidateEvidence(None)) for reading in readings
    ))
    service, _, _ = _service(store, tmp_path, aligner)

    result = service.execute(aligned, official=official, matching=_matching(anchor_ngram_size=3),
                             official_alignment_config=replace(_alignment_config(), min_alignment_score=.20,
                                                               min_anchor_alignment_score=.50))

    assert aligner.comparisons[0][:2] == (2702, 3523)
    assert (822, 4641, (original_reading, official_reading)) in aligner.comparisons
    assert [(word.text, word.start_ms, word.end_ms, word.asr_word_ids, word.official_token_ids)
            for word in result.words[4:7]] == [
        ("put", 702, 822, ("aw5",), ("ot5",)),
        ("$1,107,400,000", 1626, 4641, ("aw6",), ("ot6",)),
        ("or", 4641, 4681, ("aw7",), ("ot7",)),
    ]
    assert result.words[5].match_type is MatchType.SUBSTITUTION
    assert not result.artifact.excluded_official


def test_repeated_but_has_two_acoustic_intervals_after_retiming_other(tmp_path: Path) -> None:
    prefix = tuple(AcousticWordEvidence(*fields) for fields in (
        ("we", 274, 314, .18), ("didn't", 375, 536, .67), ("know", 556, 677, .96),
        ("each", 717, 838, .99), ("other", 899, 1060, .99),
    ))
    missing = AcousticWordEvidence("but", 1141, 1282, .82)
    suffix = tuple(AcousticWordEvidence(*fields) for fields in (
        ("but", 1987, 2128, .99), ("my", 2249, 2350, .99),
        ("grandfather", 2390, 2894, .98), ("said", 2975, 3116, .99),
    ))
    paths = {
        (274, 3156, "we didn't know each other. But my grandfather said"):
            _acoustic_path(-30, (*prefix, *suffix)),
        (274, 3156, "we didn't know each other. but— But my grandfather said"):
            _acoustic_path(-26, (*prefix, missing, *suffix)),
        (1060, 1987, ""): AcousticCandidateEvidence(-20),
        (1060, 1987, "but—"): _acoustic_path(-4, (missing,)),
    }
    store = MemoryArtifactStore()
    aligned = _aligned_input(
        store, tmp_path, ("so", "we", "didn't", "know", "each", "other.", "But", "my", "grandfather", "said", "to"),
        timings=((153, 254), (274, 354), (374, 534), (554, 694), (734, 854), (894, 1274),
                 (1975, 2135), (2235, 2355), (2375, 2956), (2976, 3156), (3256, 3296)),
    )
    official = _official_input(store, tmp_path, _transcript("so we didn't know each other— but— but my grandfather said to"))
    aligner = FakeOfficialAligner(
        (OfficialAlignmentCandidate("ot7", "but—", 1274, 1954, .015),),
        score=lambda start, end, readings: tuple(
            paths.get((start, end, reading), AcousticCandidateEvidence(None)) for reading in readings
        ),
    )
    service, _, _ = _service(store, tmp_path, aligner)

    result = service.execute(aligned, official=official, matching=_matching(anchor_ngram_size=3),
                             official_alignment_config=replace(_alignment_config(), min_alignment_score=.20,
                                                               min_anchor_alignment_score=.50))

    assert [(word.text, word.start_ms, word.end_ms, word.asr_word_ids, word.official_token_ids)
            for word in result.words[5:8]] == [
        ("other—", 899, 1060, ("aw6",), ("ot6",)),
        ("but—", 1141, 1282, (), ("ot7",)),
        ("but", 1987, 2128, ("aw7",), ("ot8",)),
    ]


@pytest.mark.parametrize("contextual_extra_score", (0.10, 0.85))
def test_weak_asr_only_removal_requires_no_independent_speech(
    tmp_path: Path, contextual_extra_score: float,
) -> None:
    def score(start, end, readings):
        extra = AcousticWordEvidence("and", 700, 760, contextual_extra_score)
        if readings == ("and", ""):
            return AcousticCandidateEvidence(-26, 700, 760, word_evidence=(extra,)), AcousticCandidateEvidence(-1)
        assert readings == ("alpha and and it continues", "alpha and it continues")
        left = (AcousticWordEvidence("alpha", 100, 200, .9), AcousticWordEvidence("and", 400, 500, .9))
        right = (AcousticWordEvidence("it", 1000, 1100, .9), AcousticWordEvidence("continues", 1300, 1400, .9))
        return (
            AcousticCandidateEvidence(-26, 100, 1400, .70, word_evidence=(*left, extra, *right)),
            AcousticCandidateEvidence(-1, 100, 1400, .90, word_evidence=(*left, *right)),
        )

    store = MemoryArtifactStore()
    aligned = _aligned_input(store, tmp_path, ("alpha", "and", "and", "it", "continues"),
                             alignment_scores={3: .168})
    official = _official_input(store, tmp_path, _transcript("alpha and it continues"))
    aligner = FakeOfficialAligner(score=score)
    service, _, _ = _service(store, tmp_path, aligner)

    result = service.execute(aligned, official=official, official_alignment_config=_alignment_config())

    assert aligner.comparisons[0][2] == ("alpha and and it continues", "alpha and it continues")
    if contextual_extra_score < 0.12:
        assert [word.text for word in result.words] == ["alpha", "and", "it", "continues"]
        omitted, = result.artifact.excluded_asr
        assert (omitted.asr_word_id, omitted.start_ms, omitted.end_ms) == ("aw3", 700, 800)
    else:
        assert [word.text for word in result.words] == ["alpha", "and", "and", "it", "continues"]
        assert (result.words[2].asr_word_ids, result.words[2].start_ms, result.words[2].end_ms) == (("aw3",), 700, 800)
        assert not result.artifact.excluded_asr
    result.artifact.validate_asr_coverage(aligned.artifact.words)
    assert TranscriptFusionArtifact.from_dict(store.read_json(result.path)) == result.artifact


def test_adjacent_weak_asr_extras_remain_in_their_original_order_and_time(tmp_path: Path) -> None:
    store = MemoryArtifactStore()
    aligned = _aligned_input(
        store, tmp_path, ("on", "the", "other", "side", "it", "continues"),
        alignment_scores={2: .08, 3: .12},
    )
    official = _official_input(store, tmp_path, _transcript("on side it continues"))
    aligner = FakeOfficialAligner()
    service, _, _ = _service(store, tmp_path, aligner)

    result = service.execute(aligned, official=official, official_alignment_config=_alignment_config())

    assert aligner.comparisons[0][2] == ("on the other side it", "on side it")
    assert not result.artifact.excluded_asr
    assert [(word.text, word.asr_word_ids, word.start_ms, word.end_ms) for word in result.words] == [
        (word.text, (word.id,), word.start_ms, word.end_ms) for word in aligned.artifact.words
    ]


@pytest.mark.parametrize("context_supported", (False, True))
def test_does_not_have_is_published_as_a_complete_fragment(tmp_path: Path, context_supported: bool) -> None:
    left = AcousticWordEvidence("business", 550, 830, .9)
    old_that = AcousticWordEvidence("that", 3400, 3590, .60)
    new_that = AcousticWordEvidence("that", 902, 1063, .12)
    extra = (
        AcousticWordEvidence("does", 3205, 3345, .88),
        AcousticWordEvidence("not", 3405, 3525, .76),
        AcousticWordEvidence("have", 3605, 3785, .95),
    )
    right = (AcousticWordEvidence("looks", 4987, 5167, .9), AcousticWordEvidence("like", 5207, 5320, .9))

    def score(start, end, readings):
        if context_supported and readings == ("", "does not have—"):
            return AcousticCandidateEvidence(-55), _acoustic_path(-8, extra)
        if context_supported and readings == ("business that looks like", "business that does not have— looks like"):
            return (
                _acoustic_path(-55, (left, old_that, *right)),
                _acoustic_path(-30, (left, new_that, *extra, *right)),
            )
        return tuple(AcousticCandidateEvidence(None) for _ in readings)

    store = MemoryArtifactStore()
    aligned = _aligned_input(
        store, tmp_path, ("we've", "got", "a", "business", "that", "looks", "like", "it", "is", "not", "going", "to"),
        timings=((102, 222), (262, 382), (402, 462), (502, 863), (903, 3365), (4967, 5167), (5207, 5367),
                 (5387, 5447), (5527, 5607), (5647, 5848), (5868, 6188), (6228, 8530)),
    )
    official = _official_input(store, tmp_path, _transcript(
        "we've got a business that's— that does not have— looks like it is not going to"
    ))

    class FragmentAligner(FakeOfficialAligner):
        def align_official_window(self, audio_path, tokens, start_ms, end_ms, config):
            requested = {token.id for token in tokens}
            return tuple(candidate for candidate in super().align_official_window(
                audio_path, tokens, start_ms, end_ms, config
            ) if candidate.official_token_id in requested)

    aligner = FragmentAligner((
        OfficialAlignmentCandidate("ot7", "does", 3385, 3771, .158),
        OfficialAlignmentCandidate("ot8", "not", 3933, 4115, .335),
        OfficialAlignmentCandidate("ot9", "have—", 4136, 4967, .043),
    ), score=score)
    service, _, _ = _service(store, tmp_path, aligner)
    config = replace(_alignment_config(), min_alignment_score=.2, min_anchor_alignment_score=.50)

    result = service.execute(aligned, official=official, matching=_matching(anchor_ngram_size=3),
                             official_alignment_config=config)

    validation = next(row for row in result.artifact.local_validations if row.official_token_ids == ("ot7", "ot8", "ot9"))
    assert not any("that's—" in reading for _, _, readings in aligner.comparisons for reading in readings)
    assert ("not", 5647, 5848) == next(
        (word.text, word.start_ms, word.end_ms) for word in result.words if word.asr_word_ids == ("aw10",)
    )
    if context_supported:
        assert [(word.text, word.start_ms, word.end_ms, word.official_token_ids) for word in result.words[4:9]] == [
            ("that", 902, 1063, ("ot6",)),
            ("does", 3205, 3345, ("ot7",)),
            ("not", 3405, 3525, ("ot8",)),
            ("have—", 3605, 3785, ("ot9",)),
            ("looks", 4987, 5167, ("ot10",)),
        ]
        assert validation.status is LocalValidationStatus.RECOVERED
        assert tuple(word.official_token_id for word in validation.candidates) == ("ot7", "ot8", "ot9")
    else:
        assert [word.text for word in result.words[4:6]] == ["that", "looks"]
        assert (result.words[4].start_ms, result.words[4].end_ms) == (903, 3365)
        assert validation.status is LocalValidationStatus.EXCLUDED
        assert not validation.candidates
        assert ("ot7", "ot8", "ot9") in [item.official_token_ids for item in result.artifact.excluded_official]


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


@pytest.mark.parametrize(("asr_amount", "official_amount", "display", "official_ids"), (
    (("$100", "billion,"), "a hundred billion dollars", "$100 billion", ("ot4", "ot5", "ot6", "ot7")),
    (("$5.5", "billion?"), "5 1/2 billion dollars?", "$5.5 billion?", ("ot4", "ot5", "ot6")),
))
def test_complete_amount_keeps_all_lexical_sources_on_both_sides(
    tmp_path: Path, asr_amount: tuple[str, ...], official_amount: str, display: str, official_ids: tuple[str, ...],
) -> None:
    store = MemoryArtifactStore()
    aligned = _aligned_input(store, tmp_path, ("the", "company", "holds", *asr_amount, "and", "that", "continues"))
    official = _official_input(store, tmp_path, _transcript(f"the company holds {official_amount} and that continues"))
    service, _, report = _service(store, tmp_path)

    result = service.execute(aligned, official=official)

    assert [word.text for word in result.words] == ["the", "company", "holds", display, "and", "that", "continues"]
    merged = result.words[3]
    assert merged.asr_word_ids == ("aw4", "aw5")
    assert merged.official_token_ids == official_ids
    assert merged.start_ms == aligned.artifact.words[3].start_ms
    assert merged.end_ms == aligned.artifact.words[4].end_ms
    assert merged.match_type is MatchType.MANY_TO_MANY
    assert merged.timing_source is TimingSource.MERGED_ACOUSTIC_ALIGNMENT
    assert report.snapshot().counts["many_to_many"] == 1
    assert TranscriptFusionArtifact.from_dict(store.read_json(result.path)) == result.artifact


@pytest.mark.parametrize("article_score", (0.033, 0.95))
def test_complete_amount_owns_only_weak_numeral_article(tmp_path: Path, article_score: float) -> None:
    store = MemoryArtifactStore()
    aligned = _aligned_input(
        store, tmp_path, ("her", "daughter", "had", "a", "$1,000", "or", "$2,000", "or", "something."),
        alignment_scores={4: article_score},
        timings=((42, 142), (162, 362), (402, 502), (582, 602), (1840, 2160),
                 (2180, 2260), (2300, 2621), (2661, 2741), (2761, 3221)),
    )
    official = _official_input(store, tmp_path, _transcript(
        "her daughter had a thousand dollars or two thousand dollars, or something."
    ))
    service, _, _ = _service(store, tmp_path)

    result = service.execute(aligned, official=official)

    first = next(index for index, word in enumerate(result.words) if word.text == "$1,000")
    merged, conjunction, second = result.words[first:first + 3]
    if article_score < 0.20:
        assert merged.asr_word_ids == ("aw4", "aw5")
        assert merged.start_ms == aligned.artifact.words[3].start_ms
        assert merged.official_token_ids == ("ot4", "ot5", "ot6")
    else:
        assert result.words[first - 1].asr_word_ids == ("aw4",)
        assert merged.asr_word_ids == ("aw5",)
    assert merged.end_ms == aligned.artifact.words[4].end_ms
    assert conjunction.text == "or" and conjunction.asr_word_ids == ("aw6",)
    assert second.text == "$2,000," and second.official_token_ids == ("ot8", "ot9", "ot10")


def test_spoken_pounds_without_explicit_currency_keeps_weight_text(tmp_path: Path) -> None:
    store = MemoryArtifactStore()
    surfaces = ("it", "weighed", "fifty", "pounds", "when", "full")
    aligned = _aligned_input(store, tmp_path, surfaces)
    official = _official_input(store, tmp_path, _transcript(" ".join(surfaces)))
    service, _, _ = _service(store, tmp_path)

    assert tuple(word.text for word in service.execute(aligned, official=official).words) == surfaces


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
