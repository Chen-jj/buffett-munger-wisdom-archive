from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from archive_core.application import build_asset_workspace
from archive_core.domain import AssetId, ArtifactType, canonical_filename
from archive_core.interfaces import (
    BoundarySource,
    BoundaryStatus,
    MatchType,
    TextSource,
    TimedWordDTO,
    TimingSource,
)
from transcription.application import (
    AudioVadAsrCacheManifest,
    CacheRecord,
    EventCode,
    ForcedAlignmentResult,
    SentenceBoundaryFailure,
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
from transcription.infrastructure import RuleBasedSentenceBoundaryDetector


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
    values = {
        "inferred_pause_ms": 700,
        "fallback_pause_ms": 1_200,
        "max_words_without_boundary": 80,
        "max_fallback_sentences": 20,
        "max_fallback_ratio": 1.0,
    }
    values.update(changes)
    return SentenceBoundaryPolicy(**values)


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
    paragraphs: tuple[int, ...] | None = None,
    speakers: tuple[str | None, ...] | None = None,
) -> tuple[OfficialTranscriptToken, ...]:
    selected_paragraphs = paragraphs or tuple(1 for _ in texts)
    selected_speakers = speakers or tuple("WARREN BUFFETT" for _ in texts)
    return tuple(
        OfficialTranscriptToken(
            id=f"ot{index}",
            text=text,
            normalized=(text.lower().strip(".?!"),),
            chapter_index=1,
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
    speakers: tuple[str | None, ...] | None = None,
    detected: tuple[int, ...] | None = None,
    policy: SentenceBoundaryPolicy | None = None,
):
    aligned = _aligned_words(texts, segments=segments, starts=starts)
    words = _timed_words(aligned, official=official)
    tokens = (
        _official_tokens(texts, paragraphs=paragraphs, speakers=speakers)
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
        sentence.boundary_source is BoundarySource.OFFICIAL_PUNCTUATION
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
        sentence.boundary_source is BoundarySource.OFFICIAL_PUNCTUATION
        for sentence in plan.sentences
    )


def test_official_boundary_uses_last_token_of_one_to_many_mapping() -> None:
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
        detector_boundaries=(),
        policy=_policy(),
    )

    assert [sentence.text for sentence in plan.sentences] == ["can't", "Continue."]
    assert all(
        sentence.boundary_source is BoundarySource.OFFICIAL_PUNCTUATION
        and sentence.boundary_status is BoundaryStatus.VERIFIED
        for sentence in plan.sentences
    )


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


def test_paragraph_change_is_weak_and_requires_another_signal() -> None:
    no_support = _plan(
        ("Good", "morning."),
        official=True,
        paragraphs=(1, 2),
    )
    assert len(no_support.sentences) == 1

    supported = _plan(
        ("Good", "morning."),
        official=True,
        paragraphs=(1, 2),
        starts=(100, 1_500),
    )
    assert len(supported.sentences) == 2
    assert supported.sentences[0].boundary_source is BoundarySource.PAUSE_FALLBACK


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
        sentence.boundary_source is BoundarySource.ASR_PUNCTUATION
        for sentence in plan.sentences
    )


def test_asr_punctuation_and_pause_have_explicit_provenance() -> None:
    plan = _plan(
        ("First.", "Second?"),
        starts=(100, 1_000),
    )

    assert plan.sentences[0].boundary_source is BoundarySource.PUNCTUATION_AND_PAUSE
    assert plan.sentences[0].boundary_status is BoundaryStatus.INFERRED


def test_local_detector_combines_with_pause_or_segment_as_fallback() -> None:
    plan = _plan(
        ("This", "ends", "Another", "thought."),
        segments=("seg1", "seg1", "seg2", "seg2"),
        detected=(1, 3),
    )

    assert [sentence.text for sentence in plan.sentences] == [
        "This ends",
        "Another thought.",
    ]
    assert plan.sentences[0].boundary_source is BoundarySource.PAUSE_FALLBACK
    assert plan.sentences[1].boundary_source is BoundarySource.ASR_PUNCTUATION


def test_fallback_policy_gate_returns_diagnostic_plan() -> None:
    with pytest.raises(SentenceBoundaryFailure, match="publication gate") as captured:
        _plan(
            ("unpunctuated", "ending"),
            detected=(),
            policy=_policy(max_fallback_sentences=0, max_fallback_ratio=0.0),
        )

    assert captured.value.diagnostic_plan is not None
    assert captured.value.diagnostic_plan.fallback_count == 1


def test_abnormally_long_unpunctuated_text_uses_versioned_fallback() -> None:
    plan = _plan(
        ("one", "two", "three", "four."),
        detected=(3,),
        policy=_policy(max_words_without_boundary=3),
    )

    assert [sentence.text for sentence in plan.sentences] == [
        "one two three",
        "four.",
    ]
    assert plan.sentences[0].boundary_source is BoundarySource.PAUSE_FALLBACK


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
        audio_duration_ms=2_000,
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
) -> tuple[ForcedAlignmentResult, TranscriptFusionResult]:
    aligned, _ = _alignment_fixture(store, output_root, texts=("Welcome.",))
    workspace = build_asset_workspace(ASSET_ID, output_root)
    fusion_path = str(
        workspace / canonical_filename(ArtifactType.TRANSCRIPT_FUSION)
    )
    words = _timed_words(aligned.artifact.words, official=True)
    tokens = _official_tokens(
        ("Welcome.",),
        speakers=("WARREN BUFFETT",),
    )
    manifest = AudioVadAsrCacheManifest.from_dict(
        store.read_json(aligned.manifest_path)
    )
    artifact = TranscriptFusionArtifact(
        audio_duration_ms=aligned.artifact.audio_duration_ms,
        aligned_asr_sha256=manifest.records["aligned_asr"].sha256,
        chapters_sha256="chapters-sha",
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
    return aligned, TranscriptFusionResult(
        path=fusion_path,
        manifest_path=aligned.manifest_path,
        words=words,
        artifact=artifact,
        used_official=True,
        cache_hit=False,
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
    aligned, fusion = _official_fusion_fixture(store, tmp_path)
    service = SentenceBoundaryService(
        detector=CountingDetector(),
        checksum=MemoryChecksum(store),
        artifacts=store,
        events=EventSink(),
        output_root=str(tmp_path),
    )

    result = service.execute(aligned, fusion, boundary_policy=_policy())

    assert result.alignment.sentences[0].speaker_label == "WARREN BUFFETT"
    assert (
        result.alignment.sentences[0].boundary_source
        is BoundarySource.OFFICIAL_PUNCTUATION
    )


def test_gate_failure_keeps_events_and_does_not_publish_canonical(tmp_path: Path) -> None:
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

    with pytest.raises(SentenceBoundaryFailure, match="publication gate"):
        service.execute(
            aligned,
            fusion,
            boundary_policy=_policy(
                max_fallback_sentences=0,
                max_fallback_ratio=0.0,
            ),
        )

    canonical = str(
        build_asset_workspace(ASSET_ID, tmp_path)
        / canonical_filename(ArtifactType.SOURCE_ALIGNMENT)
    )
    assert canonical not in store.data
    assert EventCode.BOUNDARY_FALLBACK_USED in [event.code for event in events.events]
    assert EventCode.STAGE_FAILED in [event.code for event in events.events]


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
            boundary_policy=_policy(inferred_pause_ms=800),
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
    service.execute(aligned, fusion, boundary_policy=_policy(inferred_pause_ms=700))

    with pytest.raises(RuntimeError, match="explicit overwrite"):
        service.execute(aligned, fusion, boundary_policy=_policy(inferred_pause_ms=800))

    replaced = service.execute(
        aligned,
        fusion,
        boundary_policy=_policy(inferred_pause_ms=800),
        publication_policy=SentenceBoundaryPublicationPolicy(overwrite=True),
    )
    assert replaced.cache_hit is False
