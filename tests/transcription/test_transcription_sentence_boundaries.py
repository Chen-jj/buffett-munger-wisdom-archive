from __future__ import annotations

import copy
from dataclasses import replace
import hashlib
from io import StringIO
import json
from pathlib import Path

import pytest

from archive_core.application import build_asset_workspace
from archive_core.domain import AssetId, ArtifactType, canonical_filename
from archive_core.interfaces import (
    BoundarySource,
    BoundaryStatus,
    MatchType,
    StructuredTranscriptDTO,
    TextSource,
    TimedWordDTO,
    TimingSource,
    TranscriptChapterDTO,
    TranscriptParagraphDTO,
)
from transcription.application import (
    AudioVadAsrCacheManifest,
    CacheRecord,
    EventCode,
    ForcedAlignmentResult,
    OfficialTranscriptInput,
    SentenceBoundaryInputValidationError,
    SentenceBoundaryPublicationPolicy,
    SentenceBoundaryService,
    TranscriptFusionResult,
    recover_sentences,
)
from transcription.domain import (
    AlignedAsrArtifact,
    AlignedAsrWord,
    AlignmentTimingSource,
    ForcedAlignmentConfig,
    FusionMode,
    InterpolationPolicy,
    MatchingPolicy,
    NormalizationPolicy,
    OfficialTranscriptToken,
    ProviderIdentity,
    SentenceBoundaryPolicy,
    TranscriptFusionArtifact,
)
from transcription.infrastructure import JsonLinesEventSink, RuleBasedSentenceBoundaryDetector
from transcription.domain.fusion import ExcludedOfficialTokens, OfficialSentenceSpan, build_official_tokens


ASSET_ID = AssetId("cnbc", "1994", "morning")


class MemoryArtifactStore:
    def __init__(self) -> None:
        self.data: dict[str, dict[str, object]] = {}
        self.fail_manifest_publication = False

    def exists(self, path: str) -> bool:
        return path in self.data

    def size(self, path: str) -> int:
        return len(self._bytes(path))

    def read_json(self, path: str) -> dict[str, object]:
        return copy.deepcopy(self.data[path])

    def write_json(
        self, path: str, data: dict[str, object], *, overwrite: bool
    ) -> str:
        if path in self.data and not overwrite:
            raise FileExistsError(path)
        self.data[path] = copy.deepcopy(data)
        return path

    def publish_json_pair(
        self,
        canonical_path: str,
        canonical_data: dict[str, object],
        manifest_path: str,
        manifest_factory,
        *,
        overwrite: bool,
    ) -> tuple[int, str]:
        if not overwrite and canonical_path in self.data:
            raise FileExistsError(canonical_path)
        canonical_bytes = json.dumps(
            canonical_data, sort_keys=True, separators=(",", ":")
        ).encode()
        sha256 = hashlib.sha256(canonical_bytes).hexdigest()
        manifest_data = manifest_factory(len(canonical_bytes), sha256)
        previous = copy.deepcopy(self.data)
        self.data[canonical_path] = copy.deepcopy(canonical_data)
        if self.fail_manifest_publication:
            self.data = previous
            raise OSError("manifest write failed")
        self.data[manifest_path] = copy.deepcopy(manifest_data)
        return len(canonical_bytes), sha256

    def sha256(self, path: str) -> str:
        return hashlib.sha256(self._bytes(path)).hexdigest()

    def _bytes(self, path: str) -> bytes:
        return json.dumps(
            self.data[path], sort_keys=True, separators=(",", ":")
        ).encode()


class MemoryChecksum:
    def __init__(self, store: MemoryArtifactStore) -> None:
        self.store = store

    def sha256(self, path: str) -> str:
        return self.store.sha256(path)


class EventSink:
    def __init__(self) -> None:
        self.events = []

    def emit(self, event) -> None:
        self.events.append(event)

    def flush(self) -> None:
        pass


class CountingDetector(RuleBasedSentenceBoundaryDetector):
    def __init__(self) -> None:
        self.calls = 0

    def detect(self, words, policy):
        self.calls += 1
        return super().detect(words, policy)


def _policy(**changes: object) -> SentenceBoundaryPolicy:
    return SentenceBoundaryPolicy(**changes)


def _aligned_words(
    texts: tuple[str, ...],
    *,
    segments: tuple[str, ...] | None = None,
    starts: tuple[int, ...] | None = None,
) -> tuple[AlignedAsrWord, ...]:
    selected_segments = segments or tuple("seg1" for _ in texts)
    selected_starts = starts or tuple(100 + index * 200 for index in range(len(texts)))
    return tuple(
        AlignedAsrWord(
            id=f"aw{index}",
            raw_word_id=f"rw{index}",
            segment_id=selected_segments[index - 1],
            text=text,
            start_ms=selected_starts[index - 1],
            end_ms=selected_starts[index - 1] + 100,
            alignment_score=0.9,
            timing_source=AlignmentTimingSource.ACOUSTIC_ALIGNMENT,
        )
        for index, text in enumerate(texts, start=1)
    )


def _timed_words(
    aligned: tuple[AlignedAsrWord, ...],
    *,
    official: bool,
) -> tuple[TimedWordDTO, ...]:
    return tuple(
        TimedWordDTO(
            id=f"w{index}",
            text=word.text,
            start_ms=word.start_ms,
            end_ms=word.end_ms,
            asr_word_ids=(word.id,),
            official_token_ids=(f"ot{index}",) if official else (),
            match_type=MatchType.EXACT if official else MatchType.ASR_ONLY,
            text_source=(
                TextSource.OFFICIAL_TRANSCRIPT if official else TextSource.ASR
            ),
            timing_source=TimingSource.ACOUSTIC_ALIGNMENT,
        )
        for index, word in enumerate(aligned, start=1)
    )


def _official_tokens(
    texts: tuple[str, ...],
    *,
    chapters: tuple[int, ...] | None = None,
    paragraphs: tuple[int, ...] | None = None,
    speakers: tuple[str | None, ...] | None = None,
) -> tuple[OfficialTranscriptToken, ...]:
    selected_paragraphs = paragraphs or tuple(1 for _ in texts)
    selected_speakers = speakers or tuple("WARREN BUFFETT" for _ in texts)
    selected_chapters = chapters or tuple(1 for _ in texts)
    return tuple(
        OfficialTranscriptToken(
            id=f"ot{index}",
            text=text,
            normalized=(text.lower().strip(".?!"),),
            chapter_index=selected_chapters[index - 1],
            chapter_number=1,
            paragraph_index=selected_paragraphs[index - 1],
            speaker_label=selected_speakers[index - 1],
        )
        for index, text in enumerate(texts, start=1)
    )


def _plan(
    texts: tuple[str, ...],
    *,
    official: bool = False,
    segments: tuple[str, ...] | None = None,
    starts: tuple[int, ...] | None = None,
    paragraphs: tuple[int, ...] | None = None,
    chapters: tuple[int, ...] | None = None,
    speakers: tuple[str | None, ...] | None = None,
    detected: tuple[int, ...] | None = None,
    policy: SentenceBoundaryPolicy | None = None,
):
    aligned = _aligned_words(texts, segments=segments, starts=starts)
    words = _timed_words(aligned, official=official)
    tokens = (
        _official_tokens(
            texts,
            chapters=chapters,
            paragraphs=paragraphs,
            speakers=speakers,
        )
        if official
        else ()
    )
    boundaries = (
        RuleBasedSentenceBoundaryDetector().detect(
            texts, policy or _policy()
        )
        if detected is None
        else detected
    )
    return recover_sentences(
        words,
        aligned,
        tokens,
        boundaries,
        policy or _policy(),
    )


def test_official_punctuation_respects_abbreviations_decimals_and_name_initials() -> None:
    texts = (
        "Mr.",
        "W.",
        "E.",
        "Buffett",
        "paid",
        "3.14",
        "dollars.",
        "Why?",
    )

    plan = _plan(texts, official=True)

    assert [sentence.text for sentence in plan.sentences] == [
        "Mr. W. E. Buffett paid 3.14 dollars.",
        "Why?",
    ]
    assert all(
        sentence.boundary_source is BoundarySource.FUSED_PUNCTUATION
        and sentence.boundary_status is BoundaryStatus.VERIFIED
        for sentence in plan.sentences
    )


@pytest.mark.parametrize(
    ("texts", "expected"),
    [
        (
            ("(Mr.", "Buffett", "spoke.", "Next."),
            ["(Mr. Buffett spoke.", "Next."],
        ),
        (
            ('"W.', "E.", "Buffett", "spoke.", "Next."),
            ['"W. E. Buffett spoke.', "Next."],
        ),
        (
            ("We", "bought", "fruit", 'etc."', "Then", "left."),
            ['We bought fruit etc."', "Then left."],
        ),
    ],
)
def test_official_punctuation_uses_wrapping_and_abbreviation_context(
    texts: tuple[str, ...], expected: list[str]
) -> None:
    plan = _plan(texts, official=True)

    assert [sentence.text for sentence in plan.sentences] == expected
    assert all(
        sentence.boundary_source is BoundarySource.FUSED_PUNCTUATION
        for sentence in plan.sentences
    )


def test_official_punctuation_does_not_replace_one_to_many_fused_surface() -> None:
    aligned = _aligned_words(("can't", "Continue."))
    words = (
        TimedWordDTO(
            id="w1",
            text="can't",
            start_ms=aligned[0].start_ms,
            end_ms=aligned[0].end_ms,
            asr_word_ids=("aw1",),
            official_token_ids=("ot1", "ot2"),
            match_type=MatchType.ONE_TO_MANY,
            text_source=TextSource.ASR,
            timing_source=TimingSource.ACOUSTIC_ALIGNMENT,
        ),
        TimedWordDTO(
            id="w2",
            text="Continue.",
            start_ms=aligned[1].start_ms,
            end_ms=aligned[1].end_ms,
            asr_word_ids=("aw2",),
            official_token_ids=("ot3",),
            match_type=MatchType.EXACT,
            text_source=TextSource.OFFICIAL_TRANSCRIPT,
            timing_source=TimingSource.ACOUSTIC_ALIGNMENT,
        ),
    )
    tokens = _official_tokens(("can", "not.", "Continue."))

    plan = recover_sentences(
        words,
        aligned,
        tokens,
        detector_boundaries=(1,),
        policy=_policy(),
    )

    assert [sentence.text for sentence in plan.sentences] == ["can't Continue."]
    assert all(
        sentence.boundary_source is BoundarySource.FUSED_PUNCTUATION
        and sentence.boundary_status is BoundaryStatus.VERIFIED
        for sentence in plan.sentences
    )


@pytest.mark.parametrize("trailing_asr", (False, True))
@pytest.mark.parametrize("exclude_interior", (False, True))
def test_fused_punctuation_does_not_require_official_ending_mapping(
    trailing_asr: bool, exclude_interior: bool,
) -> None:
    first_texts = ("We", "just.", "welcome", "you") + (("stray.",) if trailing_asr else ())
    aligned = _aligned_words(first_texts + ("Next.",))
    words = _timed_words(aligned, official=False)
    mapping = {0: "ot1", 2: "ot2", 3: "ot3", len(first_texts): "ot5"}
    words = tuple(
        replace(word, official_token_ids=(mapping[index],), match_type=MatchType.EXACT,
                text_source=TextSource.OFFICIAL_TRANSCRIPT)
        if index in mapping else word
        for index, word in enumerate(words)
    )
    tokens = _official_tokens(("We", "welcome", "you", "all.", "Next."))
    if exclude_interior:
        words = tuple(
            replace(word, id=f"w{index}")
            for index, word in enumerate(words[:1] + words[2:], start=1)
        )

    boundaries = RuleBasedSentenceBoundaryDetector().detect(tuple(w.text for w in words), _policy())
    plan = recover_sentences(words, aligned, tokens, boundaries, _policy())

    expected = ([] if exclude_interior else ["w2"]) + (
        [f"w{len(words)-1}"] if trailing_asr else []
    ) + [f"w{len(words)}"]
    assert [sentence.last_word_id for sentence in plan.sentences] == expected
    assert plan.sentences[0].boundary_source is BoundarySource.FUSED_PUNCTUATION


def test_speaker_change_forces_boundary_without_guessing_missing_speaker() -> None:
    plan = _plan(
        ("Good", "morning."),
        official=True,
        paragraphs=(1, 2),
        speakers=("WARREN BUFFETT", "CHARLIE MUNGER"),
    )

    assert len(plan.sentences) == 2
    assert plan.sentences[0].boundary_source is BoundarySource.SPEAKER_CHANGE
    assert plan.sentences[0].speaker_label == "WARREN BUFFETT"
    assert plan.sentences[1].speaker_label == "CHARLIE MUNGER"

    identity = _plan(("Good", "morning."))
    assert identity.sentences[0].speaker_label is None


def test_document_section_change_forces_verified_boundary_without_punctuation() -> None:
    plan = _plan(
        ("First", "chapter", "Second", "chapter."),
        official=True,
        chapters=(1, 1, 2, 2),
    )

    assert [sentence.text for sentence in plan.sentences] == [
        "First chapter",
        "Second chapter.",
    ]
    assert plan.sentences[0].boundary_source is BoundarySource.DOCUMENT_SECTION_CHANGE
    assert plan.sentences[0].boundary_status is BoundaryStatus.VERIFIED


def test_official_continuation_survives_paragraph_change_and_weak_signals() -> None:
    plan = _plan(
        ("Good—", "morning."),
        official=True,
        paragraphs=(1, 2),
        starts=(100, 4_195),
        segments=("seg1", "seg2"),
        detected=(0, 1),
    )

    assert len(plan.sentences) == 1
    assert plan.sentences[0].boundary_source is BoundarySource.FUSED_PUNCTUATION


@pytest.mark.parametrize("official", (False, True))
@pytest.mark.parametrize("ellipsis", ("...", "…"))
def test_ellipsis_does_not_mark_a_terminal_boundary(official: bool, ellipsis: str) -> None:
    plan = _plan(
        ("It", f"is{ellipsis}", "ready.", "Next."),
        official=official,
        starts=(100, 300, 4_395, 4_515),
        segments=("seg1", "seg1", "seg2", "seg2"),
    )

    assert [sentence.last_word_id for sentence in plan.sentences] == ["w3", "w4"]


@pytest.mark.parametrize("official", (False, True))
def test_domain_period_is_internal_but_following_period_can_end_sentence(official: bool) -> None:
    plan = _plan(
        ("Visit", "berkshirehathaway.", "com.", "Done."),
        official=official,
        starts=(100, 220, 320, 440),
    )

    assert [sentence.last_word_id for sentence in plan.sentences] == ["w3", "w4"]


def test_segment_change_is_weak_and_does_not_split_complete_sentence() -> None:
    plan = _plan(
        ("I", "think", "this", "works."),
        segments=("seg1", "seg1", "seg2", "seg2"),
    )

    assert len(plan.sentences) == 1
    assert plan.sentences[0].text == "I think this works."


def test_one_asr_segment_can_contain_multiple_sentences() -> None:
    plan = _plan(("First.", "Second?"), segments=("seg1", "seg1"))

    assert [sentence.text for sentence in plan.sentences] == ["First.", "Second?"]
    assert all(
        sentence.boundary_source is BoundarySource.FUSED_PUNCTUATION
        for sentence in plan.sentences
    )


def test_fused_punctuation_provenance_is_independent_of_pause() -> None:
    plan = _plan(
        ("First.", "Second?"),
        starts=(100, 1_000),
    )

    assert plan.sentences[0].boundary_source is BoundarySource.FUSED_PUNCTUATION
    assert plan.sentences[0].boundary_status is BoundaryStatus.VERIFIED


def test_detector_pause_and_segment_cannot_create_unpunctuated_boundary() -> None:
    plan = _plan(
        ("This", "ends", "Another", "thought."),
        segments=("seg1", "seg1", "seg2", "seg2"),
        detected=(1, 3),
    )

    assert [sentence.text for sentence in plan.sentences] == ["This ends Another thought."]
    assert plan.sentences[0].boundary_source is BoundarySource.FUSED_PUNCTUATION


@pytest.mark.parametrize(("fallback_count", "sentence_count"), ((101, 3000), (3, 4)))
def test_detector_candidates_cannot_force_word_count_splits(
    fallback_count: int, sentence_count: int
) -> None:
    plan = _plan(
        ("Fallback",) * fallback_count + ("Confirmed.",) * (sentence_count - fallback_count),
        segments=tuple(f"seg{index}" for index in range(sentence_count)),
        detected=tuple(range(sentence_count)),
    )

    assert len(plan.sentences) == sentence_count - fallback_count
    assert plan.sentences[0].last_word_id == f"w{fallback_count+1}"


def test_long_unpunctuated_text_closes_only_at_end_of_timeline() -> None:
    texts = ("word",) * 221
    plan = _plan(texts)

    assert [sentence.text for sentence in plan.sentences] == [" ".join(texts)]
    assert plan.sentences[0].boundary_source is BoundarySource.DOCUMENT_END
    assert plan.sentences[0].boundary_status is BoundaryStatus.INFERRED


def _alignment_fixture(
    store: MemoryArtifactStore,
    output_root: Path,
    texts: tuple[str, ...] = ("First.", "Second?"),
) -> tuple[ForcedAlignmentResult, TranscriptFusionResult]:
    workspace = build_asset_workspace(ASSET_ID, output_root)
    aligned_path = str(workspace / canonical_filename(ArtifactType.ALIGNED_ASR))
    manifest_path = str(
        workspace / canonical_filename(ArtifactType.TRANSCRIPTION_MANIFEST)
    )
    words = _aligned_words(texts)
    artifact = AlignedAsrArtifact(
        audio_sha256="audio-sha",
        raw_asr_sha256="raw-sha",
        audio_duration_ms=max(2_000, words[-1].end_ms),
        provider=ProviderIdentity("fake-aligner", "1"),
        config=ForcedAlignmentConfig(
            model="fake",
            model_version="1",
            device="cpu",
            interpolation=InterpolationPolicy(version="v1"),
        ),
        words=words,
        cache_key="aligned-key",
    )
    store.write_json(aligned_path, artifact.to_dict(), overwrite=False)
    record = CacheRecord(
        path=aligned_path,
        size_bytes=store.size(aligned_path),
        sha256=store.sha256(aligned_path),
        cache_key=artifact.cache_key,
    )
    manifest = AudioVadAsrCacheManifest(ASSET_ID, {"aligned_asr": record})
    store.write_json(manifest_path, manifest.to_dict(), overwrite=False)
    aligned = ForcedAlignmentResult(aligned_path, manifest_path, artifact, False)
    fusion = TranscriptFusionResult(
        path=None,
        manifest_path=manifest_path,
        words=_timed_words(words, official=False),
        artifact=None,
        used_official=False,
        cache_hit=False,
    )
    return aligned, fusion


def _official_fusion_fixture(
    store: MemoryArtifactStore,
    output_root: Path,
    *,
    texts: tuple[str, ...] = ("Welcome.",),
    chapters: tuple[int, ...] | None = None,
    transcript: StructuredTranscriptDTO | None = None,
) -> tuple[
    ForcedAlignmentResult,
    TranscriptFusionResult,
    OfficialTranscriptInput,
]:
    aligned, _ = _alignment_fixture(store, output_root, texts=texts)
    workspace = build_asset_workspace(ASSET_ID, output_root)
    fusion_path = str(
        workspace / canonical_filename(ArtifactType.TRANSCRIPT_FUSION)
    )
    words = _timed_words(aligned.artifact.words, official=True)
    tokens = _official_tokens(
        texts,
        chapters=chapters,
        speakers=tuple("WARREN BUFFETT" for _ in texts),
    )
    manifest = AudioVadAsrCacheManifest.from_dict(
        store.read_json(aligned.manifest_path)
    )
    transcript = transcript or StructuredTranscriptDTO(
        language="en",
        chapters=(
            TranscriptChapterDTO(
                number=1,
                title="Opening",
                paragraphs=(
                    TranscriptParagraphDTO(
                        speaker_label="WARREN BUFFETT", text="Welcome."
                    ),
                ),
            ),
        ),
    )
    chapters_path = str(workspace / canonical_filename(ArtifactType.CHAPTERS))
    store.write_json(chapters_path, transcript.to_dict(), overwrite=False)
    chapters_sha256 = store.sha256(chapters_path)
    artifact = TranscriptFusionArtifact(
        audio_duration_ms=aligned.artifact.audio_duration_ms,
        aligned_asr_sha256=manifest.records["aligned_asr"].sha256,
        chapters_sha256=chapters_sha256,
        mode=FusionMode.OFFICIAL,
        normalization=NormalizationPolicy(),
        matching=MatchingPolicy(),
        official_aligner=None,
        official_alignment_config=None,
        official_tokens=tokens,
        ignored_content=(),
        words=words,
        excluded_official=(),
        local_validations=(),
        cache_key="fusion-key",
    )
    store.write_json(fusion_path, artifact.to_dict(), overwrite=False)
    manifest.records["transcript_fusion"] = CacheRecord(
        path=fusion_path,
        size_bytes=store.size(fusion_path),
        sha256=store.sha256(fusion_path),
        cache_key=artifact.cache_key,
    )
    store.write_json(aligned.manifest_path, manifest.to_dict(), overwrite=True)
    return (
        aligned,
        TranscriptFusionResult(
            path=fusion_path,
            manifest_path=aligned.manifest_path,
            words=words,
            artifact=artifact,
            used_official=True,
            cache_hit=False,
        ),
        OfficialTranscriptInput(
            path=chapters_path,
            sha256=chapters_sha256,
            transcript=transcript,
        ),
    )


def test_service_publishes_public_dto_then_reuses_sentence_cache(tmp_path: Path) -> None:
    store = MemoryArtifactStore()
    aligned, fusion = _alignment_fixture(store, tmp_path)
    detector = CountingDetector()
    events = EventSink()
    service = SentenceBoundaryService(
        detector=detector,
        checksum=MemoryChecksum(store),
        artifacts=store,
        events=events,
        output_root=str(tmp_path),
    )

    first = service.execute(aligned, fusion, boundary_policy=_policy())
    second = service.execute(aligned, fusion, boundary_policy=_policy())

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert detector.calls == 1
    assert first.alignment == second.alignment
    assert Path(first.path).name == "source_alignment.json"
    assert all(not path.endswith(".srt") for path in store.data)
    assert EventCode.BOUNDARY_COMPLETED in [event.code for event in events.events]
    assert EventCode.BOUNDARY_CACHE_HIT in [event.code for event in events.events]


def test_service_consumes_validated_official_fusion_metadata(tmp_path: Path) -> None:
    store = MemoryArtifactStore()
    aligned, fusion, official = _official_fusion_fixture(store, tmp_path)
    service = SentenceBoundaryService(
        detector=CountingDetector(),
        checksum=MemoryChecksum(store),
        artifacts=store,
        events=EventSink(),
        output_root=str(tmp_path),
    )

    result = service.execute(
        aligned, fusion, official=official, boundary_policy=_policy()
    )

    assert result.alignment.sentences[0].speaker_label == "WARREN BUFFETT"
    assert (
        result.alignment.sentences[0].boundary_source
        is BoundarySource.FUSED_PUNCTUATION
    )
    assert [section.title for section in result.alignment.sections] == ["Opening"]


def test_official_checksum_chain_is_required_for_section_publication(
    tmp_path: Path,
) -> None:
    store = MemoryArtifactStore()
    aligned, fusion, official = _official_fusion_fixture(store, tmp_path)
    service = SentenceBoundaryService(
        detector=CountingDetector(),
        checksum=MemoryChecksum(store),
        artifacts=store,
        events=EventSink(),
        output_root=str(tmp_path),
    )

    with pytest.raises(
        SentenceBoundaryInputValidationError,
        match="official transcript checksum chain",
    ):
        service.execute(
            aligned,
            fusion,
            official=OfficialTranscriptInput(
                path=official.path,
                sha256="wrong-sha256",
                transcript=official.transcript,
            ),
            boundary_policy=_policy(),
        )


def test_section_fallback_preserves_document_boundary_and_emits_finding(
    tmp_path: Path,
) -> None:
    transcript = StructuredTranscriptDTO(
        language="en",
        chapters=tuple(
            TranscriptChapterDTO(
                number=index,
                title=title,
                paragraphs=(TranscriptParagraphDTO(text=text),),
            )
            for index, title, text in (
                (1, "First", "First"),
                (2, "Missing", "Missing"),
                (3, "Third", "Third."),
            )
        ),
    )
    store = MemoryArtifactStore()
    aligned, fusion, official = _official_fusion_fixture(
        store,
        tmp_path,
        texts=("First", "Third."),
        chapters=(1, 3),
        transcript=transcript,
    )
    events = EventSink()
    service = SentenceBoundaryService(
        detector=CountingDetector(),
        checksum=MemoryChecksum(store),
        artifacts=store,
        events=events,
        output_root=str(tmp_path),
    )

    result = service.execute(
        aligned, fusion, official=official, boundary_policy=_policy()
    )

    assert result.alignment.sections == ()
    assert len(result.alignment.sentences) == 2
    assert (
        result.alignment.sentences[0].boundary_source
        is BoundarySource.DOCUMENT_SECTION_CHANGE
    )
    by_code = {event.code: event for event in events.events}
    assert by_code[EventCode.SECTION_NON_MONOTONIC].severity.value == "WARNING"
    assert EventCode.SECTION_PUBLICATION_SKIPPED in by_code
    assert EventCode.SECTION_DOCUMENT_CHANGE_BOUNDARY in by_code


def test_unpunctuated_document_end_publishes_with_diagnostics(tmp_path: Path) -> None:
    store = MemoryArtifactStore()
    aligned, fusion = _alignment_fixture(
        store, tmp_path, texts=("unpunctuated", "ending")
    )
    events = EventSink()
    service = SentenceBoundaryService(
        detector=CountingDetector(),
        checksum=MemoryChecksum(store),
        artifacts=store,
        events=events,
        output_root=str(tmp_path),
    )

    result = service.execute(aligned, fusion)

    assert len(result.alignment.sentences) == 1
    assert result.path in store.data
    completed = next(
        event for event in events.events if event.code is EventCode.BOUNDARY_COMPLETED
    )
    assert completed.details["document_end_count"] == 1
    assert EventCode.BOUNDARY_DOCUMENT_END in [event.code for event in events.events]


def test_long_sentence_is_published_and_logged_in_full(tmp_path: Path) -> None:
    store = MemoryArtifactStore()
    texts = ("We",) + ("some",) * 146 + ("end.",)
    sentence_text = " ".join(texts)
    assert len(sentence_text) == 737
    aligned, fusion = _alignment_fixture(store, tmp_path, texts=texts)
    log = StringIO()
    result = SentenceBoundaryService(
        detector=CountingDetector(),
        checksum=MemoryChecksum(store),
        artifacts=store,
        events=JsonLinesEventSink(log),
        output_root=str(tmp_path),
    ).execute(aligned, fusion)

    assert result.alignment.sentences[0].text == sentence_text
    events = [json.loads(line) for line in log.getvalue().splitlines()]
    boundary = next(event for event in events if event["code"] == "boundary.fused_applied")
    assert boundary["source_text"] == sentence_text


def test_first_publication_manifest_failure_leaves_no_canonical_and_emits_failure(
    tmp_path: Path,
) -> None:
    store = MemoryArtifactStore()
    aligned, fusion = _alignment_fixture(store, tmp_path)
    store.fail_manifest_publication = True
    events = EventSink()
    service = SentenceBoundaryService(
        detector=CountingDetector(),
        checksum=MemoryChecksum(store),
        artifacts=store,
        events=events,
        output_root=str(tmp_path),
    )

    with pytest.raises(OSError, match="manifest write failed"):
        service.execute(aligned, fusion, boundary_policy=_policy())

    canonical = str(
        build_asset_workspace(ASSET_ID, tmp_path)
        / canonical_filename(ArtifactType.SOURCE_ALIGNMENT)
    )
    assert canonical not in store.data
    assert EventCode.STAGE_FAILED in [event.code for event in events.events]


def test_replacement_manifest_failure_preserves_previous_canonical(
    tmp_path: Path,
) -> None:
    store = MemoryArtifactStore()
    aligned, fusion = _alignment_fixture(store, tmp_path)
    service = SentenceBoundaryService(
        detector=CountingDetector(),
        checksum=MemoryChecksum(store),
        artifacts=store,
        events=EventSink(),
        output_root=str(tmp_path),
    )
    first = service.execute(aligned, fusion, boundary_policy=_policy())
    canonical_before = copy.deepcopy(store.data[first.path])
    store.fail_manifest_publication = True

    with pytest.raises(OSError, match="manifest write failed"):
        service.execute(
            aligned,
            fusion,
            boundary_policy=_policy(abbreviations=(*_policy().abbreviations, "dept.")),
            publication_policy=SentenceBoundaryPublicationPolicy(overwrite=True),
        )

    assert store.data[first.path] == canonical_before


def test_sentence_policy_change_invalidates_cache_and_requires_overwrite(
    tmp_path: Path,
) -> None:
    store = MemoryArtifactStore()
    aligned, fusion = _alignment_fixture(store, tmp_path)
    service = SentenceBoundaryService(
        detector=CountingDetector(),
        checksum=MemoryChecksum(store),
        artifacts=store,
        events=EventSink(),
        output_root=str(tmp_path),
    )
    service.execute(aligned, fusion, boundary_policy=_policy())

    with pytest.raises(RuntimeError, match="explicit overwrite"):
        service.execute(aligned, fusion, boundary_policy=_policy(abbreviations=(*_policy().abbreviations, "dept.")))

    replaced = service.execute(
        aligned,
        fusion,
        boundary_policy=_policy(abbreviations=(*_policy().abbreviations, "dept.")),
        publication_policy=SentenceBoundaryPublicationPolicy(overwrite=True),
    )
    assert replaced.cache_hit is False


@pytest.mark.parametrize(
    ("left", "right"),
    [
        pytest.param(
            "Will it eventually come from all businesses through some combination of higher tax rates on corporations, increased wages for the lower-middle class?",
            "Well, I certainly think that increased corporate taxes are a much higher probability than having lower corporate taxes.", id="E01-question-answer",
        ),
        pytest.param("Some years the price will be good, some years the price will be bad, et cetera.", "But you think about the potential of the farm.", id="E02-et-cetera"),
        pytest.param("We still came out okay, or a little bit better than okay.", "But it was not designed what we did was not designed to make a statement.", id="E03-okay"),
        pytest.param("This next question comes from Steven Stoller.", "He's a shareholder in Atlanta, Georgia.", id="E04-name"),
        pytest.param("Certain ideas, in terms of wealth taxes, changed, or taxes on foundations changed.", "But my plan has been thought out and in place for a long time.", id="E05-changed"),
        pytest.param("This question comes from David Cass.", "He is a clinical professor of finance at the University of Maryland.", id="E06-conflict-retained-name"),
        pytest.param("Now, they'll make mistakes in that, but you make mistakes in a lot of business decisions.", "But over that should be the guiding principle.", id="E07-decisions"),
        pytest.param("He just doesn't happen to have market value skills.", "So, I do not think that a very rich company ought to totally abide by what the market dishes out.", id="E08-skills"),
        pytest.param("Fortunately we had a Federal Reserve that knew what to do.", "But money was investment grade companies were essentially going to be frozen out of the market.", id="E09-asr-extra-sentence"),
        pytest.param("Communicate in a very, very straightforward manner about him.", "fairly complex subjects and tell you when he knows something.", id="P01-him"),
        pytest.param("Along with my friend Bill Gates too.", "as to what's going on.", id="P02-too"),
        pytest.param("DEFCON 6 on the other.", "1 on the other side.", id="P03-number-repair"),
        pytest.param("There's a small business in Oman.", "I hate what this what truncating this meeting has done.", id="P04-place"),
        pytest.param("That, view held on.", "and the stock market actually managed to go up.", id="P05-on"),
        pytest.param("All men are created equal and endowed by their Creator, et cetera.", "I think it was self-evident.", id="P06-full-et-cetera"),
        pytest.param("We've had a lot of very good Fed Chairman.", "but Paul Volcker, I had him at the top of the list.", id="P07-chairman"),
        pytest.param("Never... never pay it.", "you don't need to pay attention to them.", id="P08-self-correction"),
        pytest.param("Very big companies that didn't bother them.", "to extend out their borrowings came a couple times.", id="P09-them"),
        pytest.param("But we don't need it.", "we don't need a hundred.", id="P10-repeat"),
        pytest.param("There's a couple of them.", "and and it may be that in effect, what's happened has accelerated the decline.", id="P11-repeat-and"),
        pytest.param("We hope for the best and we wish it.", "everybody the best.", id="P12-wish"),
        pytest.param("We've got three extraordinarily good, minds.", "in terms of allocating capital.", id="P13-minds"),
        pytest.param("They're sure going to give it there.", "their best effort every day.", id="P14-there"),
        pytest.param("And that takes away from the upside down.", "And I don't know, whether two or three years from now.", id="Q01-down"),
        pytest.param("That infrastructure is continuing to, change.", "we're ready for $100 billion of investment opportunities there.", id="Q02-change"),
        pytest.param("But we didn't do anything.", "the price has not gotten to a level.", id="Q03-anything"),
    ],
)
def test_adr0017_real_fused_sentence_endings(left: str, right: str) -> None:
    texts = tuple((left + " " + right).split())
    plan = _plan(texts)

    assert [sentence.text for sentence in plan.sentences] == [left, right]
    assert all(s.boundary_source is BoundarySource.FUSED_PUNCTUATION for s in plan.sentences)


def _persist_fusion_fixture(store, aligned, fusion, artifact):
    store.write_json(fusion.path, artifact.to_dict(), overwrite=True)
    manifest = AudioVadAsrCacheManifest.from_dict(store.read_json(aligned.manifest_path))
    manifest.records["transcript_fusion"] = replace(
        manifest.records["transcript_fusion"], size_bytes=store.size(fusion.path),
        sha256=store.sha256(fusion.path),
    )
    store.write_json(aligned.manifest_path, manifest.to_dict(), overwrite=True)
    return replace(fusion, words=artifact.words, artifact=artifact)


@pytest.mark.parametrize("kind", ("conflict_retained", "extra_word"))
def test_adr0017_asr_only_sentence_end_survives_official_span(
    tmp_path: Path, kind: str,
) -> None:
    left = "This question comes from David Cass."
    right = "He is a clinical professor of finance at the University of Maryland."
    texts = tuple((left + " " + right).split())
    official_text = (left.replace("Cass.", "Kass.") if kind == "conflict_retained"
                     else left.replace(" Cass.", "")) + " " + right
    transcript = StructuredTranscriptDTO(
        language="en", chapters=(TranscriptChapterDTO(
            number=1, title="Question", paragraphs=(TranscriptParagraphDTO(
                speaker_label="WARREN BUFFETT", text=official_text,
            ),),
        ),),
    )
    store = MemoryArtifactStore()
    aligned, fusion, official = _official_fusion_fixture(
        store, tmp_path, texts=texts, transcript=transcript,
    )
    index = len(left.split()) - 1
    artifact = fusion.artifact
    tokens, ignored = build_official_tokens(transcript, artifact.normalization)
    words = tuple(
        replace(w, official_token_ids=(), match_type=MatchType.ASR_ONLY, text_source=TextSource.ASR)
        if i == index else replace(w, official_token_ids=(
            tokens[i - int(kind == "extra_word" and i > index)].id,
        )) for i,w in enumerate(fusion.words)
    )
    span_words = aligned.artifact.words[:index+1] if kind == "conflict_retained" else aligned.artifact.words
    span_tokens = tokens[:index+1] if kind == "conflict_retained" else tokens
    span = OfficialSentenceSpan(
        tuple(w.id for w in span_words),
        tuple(t.id for t in span_tokens),
    )
    excluded = (ExcludedOfficialTokens((tokens[index].id,), kind),) if kind == "conflict_retained" else ()
    artifact = replace(artifact, words=words, official_tokens=tokens, ignored_content=ignored,
        excluded_official=excluded,
        official_sentence_spans=(span,))
    if kind == "extra_word":
        assert all(t.normalized != ("cass",) for t in tokens)
        assert all("Cass" not in p.text for c in transcript.chapters for p in c.paragraphs)
    fusion = _persist_fusion_fixture(store, aligned, fusion, artifact)
    result = SentenceBoundaryService(
        detector=CountingDetector(), checksum=MemoryChecksum(store), artifacts=store,
        events=EventSink(), output_root=str(tmp_path),
    ).execute(aligned, fusion, official=official)

    assert [s.text for s in result.alignment.sentences] == [left, right]
    assert result.alignment.words[index] == words[index]


def test_adr0017_question_unknown_speaker_does_not_acquire_answer_identity() -> None:
    left = "Will it eventually come from all businesses through some combination of higher tax rates on corporations, increased wages for the lower-middle class?"
    right = "Well, I certainly think that increased corporate taxes are a much higher probability than having lower corporate taxes."
    texts = tuple((left + " " + right).split())
    speakers = (None,) * len(left.split()) + ("WARREN BUFFETT",) * len(right.split())
    plan = _plan(texts, official=True, speakers=speakers)

    assert [s.text for s in plan.sentences] == [left, right]
    assert [s.speaker_label for s in plan.sentences] == [None, "WARREN BUFFETT"]


@pytest.mark.parametrize(
    ("left", "right", "expected_count"),
    [
        ("The banks were very involved with the problem in 2008 and' 2009,", "they had done some things they shouldn't have done in some of them.", 1),
        ("We hope for the best and we wish it.", "everybody the best.", 2),
    ],
)
def test_adr0017_reference_punctuation_cannot_override_fused_text(
    left: str, right: str, expected_count: int,
) -> None:
    texts = tuple((left + " " + right).split())
    aligned = _aligned_words(texts)
    words = _timed_words(aligned, official=True)
    tokens = _official_tokens(texts)
    index = len(left.split())-1
    other = "." if texts[index].endswith(",") else ","
    changed = tuple(replace(t, text=t.text[:-1]+other) if i == index else t for i,t in enumerate(tokens))
    detected = RuleBasedSentenceBoundaryDetector().detect(texts, _policy())
    first = recover_sentences(words, aligned, tokens, detected, _policy())
    second = recover_sentences(words, aligned, changed, detected, _policy())

    assert first == second
    assert len(first.sentences) == expected_count


def test_adr0017_editorial_question_is_split_before_publishing(tmp_path: Path) -> None:
    texts = tuple("he called it the what did he call it?— the stock market study.".split())
    store = MemoryArtifactStore()
    aligned, fusion, official = _official_fusion_fixture(store, tmp_path, texts=texts)
    result = SentenceBoundaryService(
        detector=CountingDetector(), checksum=MemoryChecksum(store), artifacts=store,
        events=EventSink(), output_root=str(tmp_path),
    ).execute(aligned, fusion, official=official)

    assert [s.text for s in result.alignment.sentences] == [
        "he called it the what did he call it?", "the stock market study.",
    ]
    assert len(result.alignment.annotations) == 1
    assert fusion.words[8].text == "it?—"


def test_adr0017_separately_timed_sees_and_begins_next_sentence() -> None:
    left = "And Easter is a big sales period for See's."
    right = "And I don't know whether we were halfway through."
    plan = _plan(tuple((left+" "+right).split()), official=True)
    assert [s.text for s in plan.sentences] == [left, right]


def test_adr0017_same_chapter_forward_speaker_preserves_greg_handoff() -> None:
    prefix = "It's just a question of which sweatsuit I wear."
    question = "Greg, would you like to add anything"
    answer = "Really nothing to add, Warren."
    texts = tuple((prefix+" "+question+" "+answer).split())
    speakers = ("WARREN BUFFETT",)*len(prefix.split()) + (None,)*len(question.split()) + ("GREG ABEL",)*len(answer.split())
    plan = _plan(texts, official=True, speakers=speakers)
    assert [s.text for s in plan.sentences] == [prefix, question, answer]
    assert plan.sentences[1].speaker_label is None
    assert plan.sentences[1].boundary_source is BoundarySource.SPEAKER_CHANGE
    assert plan.sentences[2].speaker_label == "GREG ABEL"


def test_forward_speaker_resets_at_chapter_and_unknown_is_not_a_handoff() -> None:
    plan = _plan(
        ("Warren", "Greg,", "anything", "Really", "nothing."), official=True,
        chapters=(1,2,2,2,2), speakers=("WARREN BUFFETT",None,None,"GREG ABEL","GREG ABEL"),
    )
    assert [s.text for s in plan.sentences] == ["Warren", "Greg, anything Really nothing."]
    assert plan.sentences[0].boundary_source is BoundarySource.DOCUMENT_SECTION_CHANGE


@pytest.mark.parametrize(
    ("prefix", "answer", "speaker"),
    [
        ("Okay,", "thank you.", "BECKY QUICK"),
        ("Well,", "I agree that the approach is right.", "WARREN BUFFETT"),
        ("Okay,", "Absolutely.", "BECKY QUICK"),
        ("uh", "Thank you.", "WARREN BUFFETT"),
    ],
)
def test_adr0017_asr_only_answer_prefix_is_not_assigned_to_previous_turn(
    prefix: str, answer: str, speaker: str,
) -> None:
    previous = "A previous speaker has finished."
    previous_speaker = "WARREN BUFFETT" if speaker == "BECKY QUICK" else "BECKY QUICK"
    texts = tuple((previous+" "+prefix+" "+answer).split())
    aligned = _aligned_words(texts)
    words = _timed_words(aligned, official=True)
    prefix_index = len(previous.split())
    words = tuple(
        replace(w, official_token_ids=(), match_type=MatchType.ASR_ONLY, text_source=TextSource.ASR)
        if i == prefix_index else w for i,w in enumerate(words)
    )
    speakers = (previous_speaker,)*prefix_index + (None,) + (speaker,)*len(answer.split())
    tokens = _official_tokens(texts, speakers=speakers)
    detected = RuleBasedSentenceBoundaryDetector().detect(texts, _policy())
    plan = recover_sentences(words, aligned, tokens, detected, _policy())

    assert [s.text for s in plan.sentences] == [previous, prefix+" "+answer]
    assert plan.sentences[1].speaker_label == speaker


@pytest.mark.parametrize("gap", (20, 2_000))
def test_adr0017_but_our_continuation_and_punctuation_ignore_gap(gap: int) -> None:
    texts = ("but", "Our", "Our", "position.", "Next.")
    starts = (100, 200+gap, 400+gap, 600+gap, 700+gap+gap)
    plan = _plan(texts, starts=starts, segments=("seg1","seg2","seg2","seg2","seg3"))
    assert [s.text for s in plan.sentences] == ["but Our Our position.", "Next."]
    assert all(s.boundary_source is BoundarySource.FUSED_PUNCTUATION for s in plan.sentences)


def test_sentence_policy_rejects_previous_pause_configuration() -> None:
    assert _policy().to_dict()["version"] == "sentence-boundary.v3"
    with pytest.raises(ValueError, match="unsupported fields"):
        SentenceBoundaryPolicy.from_dict({**_policy().to_dict(), "inferred_pause_ms": 700})
    with pytest.raises(ValueError, match="unsupported sentence boundary policy"):
        SentenceBoundaryPolicy.from_dict({**_policy().to_dict(), "version": "sentence-boundary.v2"})
