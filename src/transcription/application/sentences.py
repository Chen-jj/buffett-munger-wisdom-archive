"""Local sentence recovery and canonical source-alignment publication."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from archive_core.application import build_asset_workspace
from archive_core.domain import AssetId, ArtifactType, canonical_filename
from archive_core.interfaces import (
    BoundarySource,
    BoundaryStatus,
    SourceAlignmentDTO,
    SourceSectionDTO,
    SourceSentenceDTO,
    StructuredTranscriptDTO,
    TextSource,
    TimedWordDTO,
    reconstruct_sentence_text,
)
from transcription.domain import (
    AlignedAsrArtifact,
    AlignedAsrWord,
    BoundarySignal,
    DocumentSectionPolicy,
    EffectiveChapterPlan,
    EffectiveChapterSource,
    FusionMode,
    OfficialTranscriptToken,
    SectionFallbackReason,
    SentenceBoundaryPolicy,
    aggregate_source_sections,
    derive_effective_chapters,
    document_section_boundaries,
    is_sentence_terminal,
    select_boundary_signal,
)

from .alignment import ForcedAlignmentResult
from .audio_asr import (
    AudioVadAsrCacheManifest,
    CacheRecord,
    ExistingTranscriptionArtifactConflict,
    SUCCESSFUL_CACHE_STATUS,
    _cache_key,
)
from .fusion import (
    OfficialTranscriptInput,
    TranscriptFusionResult,
    identity_fusion_words,
)
from .observability import EventCode, EventSeverity, TranscriptionEvent, TranscriptionEventSink
from .ports import ChecksumService, SentenceBoundaryDetector, TranscriptionArtifactStore


SENTENCE_BOUNDARY_STAGE_NAME = "sentence_boundaries"


@dataclass(frozen=True)
class SentenceBoundaryPublicationPolicy:
    overwrite: bool = False
    publish: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.overwrite, bool):
            raise ValueError("overwrite must be a bool")
        if not isinstance(self.publish, bool):
            raise ValueError("publish must be a bool")


@dataclass(frozen=True)
class SentenceBoundaryResult:
    path: str
    manifest_path: str
    alignment: SourceAlignmentDTO
    cache_hit: bool
    cache_key: str
    provenance: Mapping[str, object]


@dataclass(frozen=True)
class SentenceBoundaryPlan:
    sentences: tuple[SourceSentenceDTO, ...]
    fallback_count: int


class SentenceBoundaryInputValidationError(RuntimeError):
    pass


class SentenceBoundaryFailure(RuntimeError):
    def __init__(
        self,
        reason: str,
        *,
        diagnostic_plan: SentenceBoundaryPlan | None = None,
    ) -> None:
        self.diagnostic_plan = diagnostic_plan
        super().__init__(reason)


@dataclass(frozen=True)
class _OfficialContext:
    chapter_index: int
    paragraph_index: int
    speaker_label: str | None
    tokens: tuple[OfficialTranscriptToken, ...]


@dataclass(frozen=True)
class _WordContext:
    segment_ids: tuple[str, ...]
    official: _OfficialContext | None

    @property
    def speaker_label(self) -> str | None:
        return self.official.speaker_label if self.official is not None else None


@dataclass(frozen=True)
class _BoundaryDecision:
    source: BoundarySource
    status: BoundaryStatus


def recover_sentences(
    words: Sequence[TimedWordDTO],
    aligned_words: Sequence[AlignedAsrWord],
    official_tokens: Sequence[OfficialTranscriptToken],
    detector_boundaries: Sequence[int],
    policy: SentenceBoundaryPolicy,
    effective_chapters: EffectiveChapterPlan | None = None,
) -> SentenceBoundaryPlan:
    """Recover complete sentences without applying subtitle display constraints."""

    timed_words = tuple(words)
    if not timed_words:
        raise SentenceBoundaryFailure("cannot publish an empty spoken timeline")
    detected = _validate_detector_boundaries(detector_boundaries, len(timed_words))
    contexts = _build_contexts(timed_words, aligned_words, official_tokens)
    chapter_plan = effective_chapters or derive_effective_chapters(
        timed_words, official_tokens
    )
    section_boundary_word_ids = {
        boundary.preceding_word_id
        for boundary in document_section_boundaries(chapter_plan)
    }
    boundary_surfaces, boundary_tail_indices = _boundary_surface_context(
        timed_words, contexts
    )
    sentences: list[SourceSentenceDTO] = []
    start = 0
    known_speaker = contexts[0].speaker_label
    fallback_count = 0

    for index, word in enumerate(timed_words):
        decision: _BoundaryDecision | None = None
        next_index = index + 1
        has_next = next_index < len(timed_words)
        if has_next:
            next_speaker = contexts[next_index].speaker_label
            if (
                known_speaker is not None
                and next_speaker is not None
                and next_speaker != known_speaker
            ):
                decision = _BoundaryDecision(
                    BoundarySource.SPEAKER_CHANGE,
                    BoundaryStatus.VERIFIED,
                )

        official_word = contexts[index].official is not None
        terminal = is_sentence_terminal(
            boundary_surfaces, boundary_tail_indices[index], policy
        )
        if decision is None and official_word and terminal:
            decision = _BoundaryDecision(
                BoundarySource.OFFICIAL_PUNCTUATION,
                BoundaryStatus.VERIFIED,
            )

        pause_ms = _pause_after(timed_words, index)
        segment_change = _segment_change(contexts, index)
        paragraph_change = _paragraph_change(contexts, index)
        if decision is None and not official_word and terminal:
            if pause_ms >= policy.inferred_pause_ms:
                decision = _BoundaryDecision(
                    BoundarySource.PUNCTUATION_AND_PAUSE,
                    BoundaryStatus.INFERRED,
                )
            else:
                decision = _BoundaryDecision(
                    BoundarySource.ASR_PUNCTUATION,
                    BoundaryStatus.INFERRED,
                )

        weak_detector_boundary = index in detected and (
            pause_ms >= policy.inferred_pause_ms
            or segment_change
            or paragraph_change
        )
        paragraph_with_support = paragraph_change and (
            pause_ms >= policy.fallback_pause_ms or segment_change
        )
        if decision is None and (weak_detector_boundary or paragraph_with_support):
            decision = _BoundaryDecision(
                BoundarySource.PAUSE_FALLBACK,
                BoundaryStatus.FALLBACK,
            )

        sentence_length = index - start + 1
        if (
            decision is None
            and sentence_length >= policy.max_words_without_boundary
        ):
            decision = _BoundaryDecision(
                BoundarySource.PAUSE_FALLBACK,
                BoundaryStatus.FALLBACK,
            )
        if decision is None and not has_next:
            decision = _BoundaryDecision(
                BoundarySource.PAUSE_FALLBACK,
                BoundaryStatus.FALLBACK,
            )
        signal = select_boundary_signal(
            (
                BoundarySignal(decision.source, decision.status)
                if decision is not None
                else None
            ),
            document_section_change=word.id in section_boundary_word_ids,
        )
        decision = (
            _BoundaryDecision(signal.source, signal.status)
            if signal is not None
            else None
        )
        if decision is None:
            next_speaker = contexts[next_index].speaker_label
            if known_speaker is None and next_speaker is not None:
                known_speaker = next_speaker
            continue

        sentence_words = timed_words[start : index + 1]
        sentence_speaker = _sentence_speaker(contexts[start : index + 1])
        sentence = SourceSentenceDTO(
            id=f"s{len(sentences) + 1}",
            first_word_id=sentence_words[0].id,
            last_word_id=sentence_words[-1].id,
            start_ms=sentence_words[0].start_ms,
            end_ms=sentence_words[-1].end_ms,
            text=reconstruct_sentence_text(sentence_words),
            speaker_label=sentence_speaker,
            text_source=_sentence_text_source(sentence_words),
            boundary_source=decision.source,
            boundary_status=decision.status,
        )
        sentences.append(sentence)
        if decision.status is BoundaryStatus.FALLBACK:
            fallback_count += 1
        start = index + 1
        known_speaker = contexts[start].speaker_label if start < len(contexts) else None

    plan = SentenceBoundaryPlan(tuple(sentences), fallback_count)
    ratio = fallback_count / len(sentences)
    if (
        fallback_count > policy.max_fallback_sentences
        or ratio > policy.max_fallback_ratio
    ):
        raise SentenceBoundaryFailure(
            "fallback boundary publication gate exceeded "
            f"({fallback_count}/{len(sentences)}, ratio={ratio:.3f})",
            diagnostic_plan=plan,
        )
    return plan


def _validate_detector_boundaries(values: Sequence[int], word_count: int) -> set[int]:
    boundaries: set[int] = set()
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < word_count:
            raise SentenceBoundaryFailure(
                "local sentence detector returned an invalid word index"
            )
        if value in boundaries:
            raise SentenceBoundaryFailure(
                "local sentence detector returned a duplicate word index"
            )
        boundaries.add(value)
    return boundaries


def _build_contexts(
    words: tuple[TimedWordDTO, ...],
    aligned_words: Sequence[AlignedAsrWord],
    official_tokens: Sequence[OfficialTranscriptToken],
) -> tuple[_WordContext, ...]:
    aligned_by_id = {word.id: word for word in aligned_words}
    official_by_id = {token.id: token for token in official_tokens}
    contexts: list[_WordContext] = []
    for word in words:
        try:
            segment_ids = tuple(
                dict.fromkeys(aligned_by_id[word_id].segment_id for word_id in word.asr_word_ids)
            )
            mapped_official = tuple(
                official_by_id[token_id] for token_id in word.official_token_ids
            )
        except KeyError as error:
            raise SentenceBoundaryFailure(
                "fusion word references an unknown aligned or official word"
            ) from error
        official_contexts = {
            (token.chapter_index, token.paragraph_index, token.speaker_label)
            for token in mapped_official
        }
        if len(official_contexts) > 1:
            raise SentenceBoundaryFailure(
                "one fused word must not cross official paragraph or speaker context"
            )
        official = None
        if official_contexts:
            chapter, paragraph, speaker = official_contexts.pop()
            official = _OfficialContext(
                chapter,
                paragraph,
                speaker,
                mapped_official,
            )
        contexts.append(_WordContext(segment_ids, official))
    return tuple(contexts)


def _boundary_surface_context(
    words: tuple[TimedWordDTO, ...],
    contexts: tuple[_WordContext, ...],
) -> tuple[tuple[str, ...], tuple[int, ...]]:
    surfaces: list[str] = []
    tail_indices: list[int] = []
    for word, context in zip(words, contexts, strict=True):
        if context.official is None:
            surfaces.append(word.text)
        else:
            surfaces.extend(token.text for token in context.official.tokens)
        tail_indices.append(len(surfaces) - 1)
    return tuple(surfaces), tuple(tail_indices)


def _pause_after(words: tuple[TimedWordDTO, ...], index: int) -> int:
    if index + 1 >= len(words):
        return 0
    return words[index + 1].start_ms - words[index].end_ms


def _segment_change(contexts: tuple[_WordContext, ...], index: int) -> bool:
    if index + 1 >= len(contexts):
        return False
    left = contexts[index].segment_ids
    right = contexts[index + 1].segment_ids
    return bool(left and right and left[-1] != right[0])


def _paragraph_change(contexts: tuple[_WordContext, ...], index: int) -> bool:
    if index + 1 >= len(contexts):
        return False
    left = contexts[index].official
    right = contexts[index + 1].official
    if left is None or right is None:
        return False
    return (left.chapter_index, left.paragraph_index) != (
        right.chapter_index,
        right.paragraph_index,
    )


def _sentence_speaker(contexts: Sequence[_WordContext]) -> str | None:
    labels = {
        context.speaker_label
        for context in contexts
        if context.speaker_label is not None
    }
    if len(labels) > 1:
        raise SentenceBoundaryFailure("a sentence must not cross reliable speakers")
    return next(iter(labels), None)


def _sentence_text_source(words: Sequence[TimedWordDTO]) -> TextSource:
    sources = {word.text_source for word in words}
    if len(sources) == 1:
        return next(iter(sources))
    return TextSource.MIXED


class SentenceBoundaryService:
    def __init__(
        self,
        *,
        detector: SentenceBoundaryDetector,
        checksum: ChecksumService,
        artifacts: TranscriptionArtifactStore,
        events: TranscriptionEventSink,
        output_root: str = "output",
    ) -> None:
        self.detector = detector
        self.checksum = checksum
        self.artifacts = artifacts
        self.events = events
        self.output_root = output_root

    def execute(
        self,
        aligned: ForcedAlignmentResult,
        fusion: TranscriptFusionResult,
        *,
        official: OfficialTranscriptInput | None = None,
        boundary_policy: SentenceBoundaryPolicy | None = None,
        section_policy: DocumentSectionPolicy | None = None,
        publication_policy: SentenceBoundaryPublicationPolicy | None = None,
    ) -> SentenceBoundaryResult:
        selected_boundary = boundary_policy or SentenceBoundaryPolicy()
        selected_section = section_policy or DocumentSectionPolicy()
        selected_publication = publication_policy or SentenceBoundaryPublicationPolicy()
        (
            asset_id,
            manifest,
            input_sha256,
            official_tokens,
            transcript,
            chapters_sha256,
        ) = self._validate_inputs(aligned, fusion, official)
        workspace = build_asset_workspace(asset_id, self.output_root)
        output_path = str(
            workspace / canonical_filename(ArtifactType.SOURCE_ALIGNMENT)
        )
        cache_key = _cache_key(
            "source_alignment.v1",
            {
                "sentence_input_sha256": input_sha256,
                "fusion_mode": "official" if fusion.used_official else "identity",
                "detector": self.detector.identity.to_dict(),
                "boundary_policy": selected_boundary.to_dict(),
                "section_policy": selected_section.to_dict(),
                "chapter_input_sha256": chapters_sha256,
            },
        )
        provenance = {
            "sentence_input_sha256": input_sha256,
            "fusion_mode": "official" if fusion.used_official else "identity",
            "detector": self.detector.identity.to_dict(),
            "boundary_policy": selected_boundary.to_dict(),
            "section_policy": selected_section.to_dict(),
            "chapter_input_sha256": chapters_sha256,
        }
        cached = self._validated_cache(manifest, output_path, cache_key)
        if cached is not None:
            self._emit(
                asset_id,
                EventCode.BOUNDARY_CACHE_HIT,
                EventSeverity.INFO,
                action="reuse_source_alignment",
                reason="sentence cache key, path, size, checksum, and DTO validated",
                details={"cache_key": cache_key},
            )
            return SentenceBoundaryResult(
                output_path,
                fusion.manifest_path,
                cached,
                cache_hit=True,
                cache_key=cache_key,
                provenance=provenance,
            )
        if self.artifacts.exists(output_path) and not selected_publication.overwrite:
            raise ExistingTranscriptionArtifactConflict(
                "source_alignment", "explicit overwrite required"
            )

        surfaces = tuple(word.text for word in fusion.words)
        try:
            chapter_plan = derive_effective_chapters(fusion.words, official_tokens)
            self._emit_chapter_assignments(asset_id, chapter_plan)
            detector_boundaries = self.detector.detect(surfaces, selected_boundary)
            plan = recover_sentences(
                fusion.words,
                aligned.artifact.words,
                official_tokens,
                detector_boundaries,
                selected_boundary,
                chapter_plan,
            )
            for sentence in plan.sentences:
                self._emit_boundary(asset_id, sentence)
            sections = ()
            if transcript is not None:
                aggregation = aggregate_source_sections(
                    plan.sentences, transcript, chapter_plan
                )
                sections = aggregation.sections
                self._emit_section_publication(
                    asset_id,
                    aggregation.fallback_reason,
                    sections,
                    official_transcript=any(
                        paragraph.text
                        for chapter in transcript.chapters
                        for paragraph in chapter.paragraphs
                    ),
                )
            else:
                self._emit_section_publication(
                    asset_id, SectionFallbackReason.NO_DIRECT_CHAPTERS, ()
                )
            alignment = SourceAlignmentDTO(
                language="en",
                audio_duration_ms=aligned.artifact.audio_duration_ms,
                words=fusion.words,
                sentences=plan.sentences,
                sections=sections,
            )
            # Exercise the public deserializer as the final pre-publication gate.
            if SourceAlignmentDTO.from_dict(alignment.to_dict()) != alignment:
                raise SentenceBoundaryFailure(
                    "public source alignment DTO did not round-trip"
                )
        except SentenceBoundaryFailure as error:
            if error.diagnostic_plan is not None:
                for sentence in error.diagnostic_plan.sentences:
                    self._emit_boundary(asset_id, sentence)
            self._emit(
                asset_id,
                EventCode.STAGE_FAILED,
                EventSeverity.ERROR,
                action="reject_source_alignment",
                reason=str(error),
            )
            raise
        except (TypeError, ValueError) as error:
            failure = SentenceBoundaryFailure(
                f"source alignment invariant failed: {error}"
            )
            self._emit(
                asset_id,
                EventCode.STAGE_FAILED,
                EventSeverity.ERROR,
                action="reject_source_alignment",
                reason=str(failure),
            )
            raise failure from error

        candidate_manifest = AudioVadAsrCacheManifest.from_dict(manifest.to_dict())

        def build_manifest(size_bytes: int, sha256: str) -> Mapping[str, object]:
            candidate_manifest.records["source_alignment"] = CacheRecord(
                path=output_path,
                size_bytes=size_bytes,
                sha256=sha256,
                cache_key=cache_key,
                provenance=provenance,
            )
            return candidate_manifest.to_dict()

        if selected_publication.publish:
            try:
                self.artifacts.publish_json_pair(
                    output_path,
                    alignment.to_dict(),
                    fusion.manifest_path,
                    build_manifest,
                    overwrite=selected_publication.overwrite,
                )
            except Exception as error:
                try:
                    self._emit(
                        asset_id,
                        EventCode.STAGE_FAILED,
                        EventSeverity.ERROR,
                        action="publish_source_alignment",
                        reason=f"source alignment publication failed: {error}",
                    )
                except Exception:
                    pass
                raise
            manifest.records = candidate_manifest.records
        self._emit(
            asset_id,
            EventCode.BOUNDARY_COMPLETED,
            EventSeverity.INFO,
            action=(
                "publish_source_alignment"
                if selected_publication.publish
                else "validate_source_alignment"
            ),
            reason=(
                "public DTO invariants and fallback publication gate passed"
                if selected_publication.publish
                else "public DTO invariants and fallback publication gate passed; publication deferred"
            ),
            details={
                "sentence_count": len(alignment.sentences),
                "fallback_count": plan.fallback_count,
                "section_count": len(alignment.sections),
                "cache_key": cache_key,
            },
        )
        return SentenceBoundaryResult(
            output_path,
            fusion.manifest_path,
            alignment,
            cache_hit=False,
            cache_key=cache_key,
            provenance=provenance,
        )

    def _validate_inputs(
        self,
        aligned: ForcedAlignmentResult,
        fusion: TranscriptFusionResult,
        official: OfficialTranscriptInput | None,
    ) -> tuple[
        AssetId,
        AudioVadAsrCacheManifest,
        str,
        tuple[OfficialTranscriptToken, ...],
        StructuredTranscriptDTO | None,
        str | None,
    ]:
        try:
            manifest = AudioVadAsrCacheManifest.from_dict(
                self.artifacts.read_json(aligned.manifest_path)
            )
        except Exception as error:
            raise SentenceBoundaryInputValidationError(
                "transcription manifest is missing or invalid"
            ) from error
        asset_id = manifest.asset_id
        workspace = build_asset_workspace(asset_id, self.output_root)
        aligned_path = str(workspace / canonical_filename(ArtifactType.ALIGNED_ASR))
        manifest_path = str(
            workspace / canonical_filename(ArtifactType.TRANSCRIPTION_MANIFEST)
        )
        if (
            Path(aligned.path) != Path(aligned_path)
            or Path(aligned.manifest_path) != Path(manifest_path)
            or Path(fusion.manifest_path) != Path(manifest_path)
        ):
            raise SentenceBoundaryInputValidationError("input paths are not canonical")
        aligned_record = self._validated_record(manifest, "aligned_asr", aligned_path)
        try:
            persisted_aligned = AlignedAsrArtifact.from_dict(
                self.artifacts.read_json(aligned_path)
            )
        except Exception as error:
            raise SentenceBoundaryInputValidationError(
                "aligned ASR artifact is invalid"
            ) from error
        if persisted_aligned != aligned.artifact:
            raise SentenceBoundaryInputValidationError(
                "aligned ASR result does not match persisted artifact"
            )
        if aligned_record.cache_key != aligned.artifact.cache_key:
            raise SentenceBoundaryInputValidationError(
                "aligned ASR cache key is inconsistent"
            )

        if fusion.used_official:
            fusion_path = str(
                workspace / canonical_filename(ArtifactType.TRANSCRIPT_FUSION)
            )
            if (
                fusion.path is None
                or Path(fusion.path) != Path(fusion_path)
                or fusion.artifact is None
                or fusion.artifact.mode is not FusionMode.OFFICIAL
            ):
                raise SentenceBoundaryInputValidationError(
                    "official fusion result is incomplete"
                )
            fusion_record = self._validated_record(
                manifest, "transcript_fusion", fusion_path
            )
            try:
                persisted_fusion = type(fusion.artifact).from_dict(
                    self.artifacts.read_json(fusion_path)
                )
            except Exception as error:
                raise SentenceBoundaryInputValidationError(
                    "transcript fusion artifact is invalid"
                ) from error
            if (
                persisted_fusion != fusion.artifact
                or fusion.words != fusion.artifact.words
                or fusion.artifact.aligned_asr_sha256 != aligned_record.sha256
                or fusion.artifact.cache_key != fusion_record.cache_key
            ):
                raise SentenceBoundaryInputValidationError(
                    "official fusion checksum chain is invalid"
                )
            chapters_path = str(
                workspace / canonical_filename(ArtifactType.CHAPTERS)
            )
            if (
                official is None
                or Path(official.path) != Path(chapters_path)
                or not self.artifacts.exists(chapters_path)
                or self.checksum.sha256(chapters_path) != official.sha256
                or fusion.artifact.chapters_sha256 != official.sha256
            ):
                raise SentenceBoundaryInputValidationError(
                    "official transcript checksum chain is invalid"
                )
            try:
                persisted_transcript = StructuredTranscriptDTO.from_dict(
                    self.artifacts.read_json(chapters_path)
                )
            except Exception as error:
                raise SentenceBoundaryInputValidationError(
                    "official transcript artifact is invalid"
                ) from error
            if persisted_transcript != official.transcript:
                raise SentenceBoundaryInputValidationError(
                    "official transcript result does not match persisted artifact"
                )
            return (
                asset_id,
                manifest,
                fusion_record.sha256,
                fusion.artifact.official_tokens,
                official.transcript,
                official.sha256,
            )

        if (
            official is not None
            or fusion.path is not None
            or fusion.artifact is not None
            or fusion.words != identity_fusion_words(aligned.artifact)
        ):
            raise SentenceBoundaryInputValidationError(
                "no-official path must use aligned ASR identity words"
            )
        return asset_id, manifest, aligned_record.sha256, (), None, None

    def _validated_record(
        self,
        manifest: AudioVadAsrCacheManifest,
        name: str,
        expected_path: str,
    ) -> CacheRecord:
        record = manifest.records.get(name)
        if (
            record is None
            or record.status != SUCCESSFUL_CACHE_STATUS
            or Path(record.path) != Path(expected_path)
            or not self.artifacts.exists(expected_path)
            or self.artifacts.size(expected_path) != record.size_bytes
            or self.checksum.sha256(expected_path) != record.sha256
        ):
            raise SentenceBoundaryInputValidationError(
                f"successful {name} manifest evidence is invalid"
            )
        return record

    def _validated_cache(
        self,
        manifest: AudioVadAsrCacheManifest,
        path: str,
        cache_key: str,
    ) -> SourceAlignmentDTO | None:
        record = manifest.records.get("source_alignment")
        if record is None:
            return None
        if (
            record.status != SUCCESSFUL_CACHE_STATUS
            or Path(record.path) != Path(path)
            or record.cache_key != cache_key
            or not self.artifacts.exists(path)
            or self.artifacts.size(path) != record.size_bytes
            or self.checksum.sha256(path) != record.sha256
        ):
            return None
        try:
            return SourceAlignmentDTO.from_dict(self.artifacts.read_json(path))
        except Exception:
            return None

    def _emit_chapter_assignments(
        self, asset_id: AssetId, plan: EffectiveChapterPlan
    ) -> None:
        for assignment in plan.assignments:
            if assignment.source is EffectiveChapterSource.UNAVAILABLE:
                continue
            code, severity, action, reason = {
                EffectiveChapterSource.DIRECT: (
                    EventCode.SECTION_DIRECT_ASSIGNED,
                    EventSeverity.INFO,
                    "assign_direct_document_section",
                    "official token mapping identifies the document section",
                ),
                EffectiveChapterSource.FIRST_LATER_CHAPTER: (
                    EventCode.SECTION_ASR_ONLY_ASSIGNED_TO_FIRST,
                    EventSeverity.WARNING,
                    "assign_leading_asr_only_word",
                    "leading ASR-only word assigned to the first later document section",
                ),
                EffectiveChapterSource.PREVIOUS_CHAPTER: (
                    EventCode.SECTION_ASR_ONLY_ASSIGNED_TO_PREVIOUS,
                    EventSeverity.WARNING,
                    "assign_asr_only_word_to_previous_section",
                    "ASR-only word assigned to the previous document section",
                ),
            }[assignment.source]
            self._emit(
                asset_id,
                code,
                severity,
                action=action,
                reason=reason,
                related_ids={"word_id": assignment.word_id},
                details={
                    "direct_chapter_index": assignment.direct_chapter_index,
                    "effective_chapter_index": assignment.effective_chapter_index,
                },
            )

    def _emit_section_publication(
        self,
        asset_id: AssetId,
        fallback_reason: SectionFallbackReason | None,
        sections: Sequence[SourceSectionDTO],
        *,
        official_transcript: bool = False,
    ) -> None:
        if fallback_reason is None:
            self._emit(
                asset_id,
                EventCode.SECTION_PUBLISHED,
                EventSeverity.INFO,
                action="publish_document_sections",
                reason="document sections reliably cover all source sentences",
                details={"section_count": len(sections)},
            )
            return

        diagnostic_reason = (
            SectionFallbackReason.CHAPTER_UNMAPPED
            if official_transcript
            and fallback_reason is SectionFallbackReason.NO_DIRECT_CHAPTERS
            else fallback_reason
        )
        specific = {
            SectionFallbackReason.CHAPTER_UNMAPPED: (
                EventCode.SECTION_CHAPTER_UNMAPPED,
                "skip_unmapped_document_section",
            ),
            SectionFallbackReason.NON_MONOTONIC_CHAPTER_ORDER: (
                EventCode.SECTION_NON_MONOTONIC,
                "skip_non_monotonic_document_sections",
            ),
            SectionFallbackReason.CHAPTER_ORDER_JUMP: (
                EventCode.SECTION_NON_MONOTONIC,
                "skip_unexplained_document_section_jump",
            ),
            SectionFallbackReason.SENTENCE_CROSSES_SECTIONS: (
                EventCode.SECTION_SENTENCE_CROSSES_SECTIONS,
                "skip_cross_section_sentence",
            ),
        }.get(diagnostic_reason)
        expected_absence = (
            diagnostic_reason is SectionFallbackReason.NO_DIRECT_CHAPTERS
        )
        if specific is not None:
            self._emit(
                asset_id,
                specific[0],
                EventSeverity.WARNING,
                action=specific[1],
                reason=diagnostic_reason.value,
                details={"fallback_reason": diagnostic_reason.value},
            )
        self._emit(
            asset_id,
            EventCode.SECTION_PUBLICATION_SKIPPED,
            (
                EventSeverity.INFO
                if expected_absence or specific is not None
                else EventSeverity.WARNING
            ),
            action="publish_without_document_sections",
            reason=(
                "no reliable document grouping is available"
                if expected_absence
                else diagnostic_reason.value
            ),
            details={"fallback_reason": diagnostic_reason.value},
        )

    def _emit_boundary(self, asset_id: AssetId, sentence: SourceSentenceDTO) -> None:
        code, severity, action, reason = {
            BoundarySource.OFFICIAL_PUNCTUATION: (
                EventCode.BOUNDARY_OFFICIAL_APPLIED,
                EventSeverity.INFO,
                "apply_official_punctuation",
                "verified official punctuation passed sentence exceptions",
            ),
            BoundarySource.SPEAKER_CHANGE: (
                EventCode.BOUNDARY_SPEAKER_CHANGE,
                EventSeverity.INFO,
                "close_before_speaker_change",
                "reliable official speaker metadata changed",
            ),
            BoundarySource.ASR_PUNCTUATION: (
                EventCode.BOUNDARY_ASR_APPLIED,
                EventSeverity.INFO,
                "apply_asr_punctuation",
                "ASR punctuation passed local sentence exceptions",
            ),
            BoundarySource.PUNCTUATION_AND_PAUSE: (
                EventCode.BOUNDARY_PAUSE_INFERRED,
                EventSeverity.INFO,
                "combine_punctuation_and_pause",
                "ASR punctuation and inter-word pause support a boundary",
            ),
            BoundarySource.PAUSE_FALLBACK: (
                EventCode.BOUNDARY_FALLBACK_USED,
                EventSeverity.WARNING,
                "apply_versioned_fallback",
                "weak local signals or abnormal unpunctuated length required fallback",
            ),
            BoundarySource.DOCUMENT_SECTION_CHANGE: (
                EventCode.SECTION_DOCUMENT_CHANGE_BOUNDARY,
                EventSeverity.INFO,
                "close_before_document_section_change",
                "verified document structure changed before the next word",
            ),
        }[sentence.boundary_source]
        self._emit(
            asset_id,
            code,
            severity,
            action=action,
            reason=reason,
            related_ids={
                "sentence_id": sentence.id,
                "first_word_id": sentence.first_word_id,
                "last_word_id": sentence.last_word_id,
            },
            source_text=sentence.text,
            start_ms=sentence.start_ms,
            end_ms=sentence.end_ms,
        )

    def _emit(
        self,
        asset_id: AssetId,
        code: EventCode,
        severity: EventSeverity,
        *,
        action: str,
        reason: str,
        related_ids: Mapping[str, str] | None = None,
        source_text: str | None = None,
        start_ms: int | None = None,
        end_ms: int | None = None,
        details: Mapping[str, str | int | float | bool | None] | None = None,
    ) -> None:
        self.events.emit(
            TranscriptionEvent(
                asset_id=asset_id.value,
                stage=SENTENCE_BOUNDARY_STAGE_NAME,
                code=code,
                severity=severity,
                action=action,
                reason=reason,
                related_ids=related_ids or {},
                source_text=source_text,
                start_ms=start_ms,
                end_ms=end_ms,
                details=details or {},
            )
        )
