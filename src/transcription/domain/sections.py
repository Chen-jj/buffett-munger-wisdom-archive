"""Pure document-section assignment and aggregation rules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Sequence

from archive_core.interfaces import (
    BoundarySource,
    BoundaryStatus,
    SourceSectionDTO,
    SourceSentenceDTO,
    StructuredTranscriptDTO,
    TimedWordDTO,
)

from .fusion import OfficialTranscriptToken


DOCUMENT_SECTION_POLICY_VERSION = "document-sections.v1"


@dataclass(frozen=True)
class DocumentSectionPolicy:
    """Serializable identity for the effective-chapter rules."""

    version: str = DOCUMENT_SECTION_POLICY_VERSION

    def __post_init__(self) -> None:
        if self.version != DOCUMENT_SECTION_POLICY_VERSION:
            raise ValueError(f"unsupported document section policy: {self.version}")

    def to_dict(self) -> dict[str, str]:
        return {"version": self.version}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DocumentSectionPolicy":
        return cls(version=data.get("version"))


class EffectiveChapterSource(str, Enum):
    DIRECT = "direct"
    FIRST_LATER_CHAPTER = "asr_only_first_later_chapter"
    PREVIOUS_CHAPTER = "asr_only_previous_chapter"
    UNAVAILABLE = "unavailable"


class ChapterAssignmentFailureReason(str, Enum):
    DUPLICATE_OFFICIAL_TOKEN = "duplicate_official_token"
    OFFICIAL_TOKEN_NOT_FOUND = "official_token_not_found"
    WORD_CROSSES_CHAPTERS = "word_crosses_chapters"


class ChapterAssignmentError(ValueError):
    def __init__(
        self,
        reason: ChapterAssignmentFailureReason,
        *,
        word_id: str | None = None,
        official_token_id: str | None = None,
    ) -> None:
        self.reason = reason
        self.word_id = word_id
        self.official_token_id = official_token_id
        super().__init__(reason.value)


@dataclass(frozen=True)
class EffectiveChapterAssignment:
    word_id: str
    direct_chapter_index: int | None
    effective_chapter_index: int | None
    source: EffectiveChapterSource


@dataclass(frozen=True)
class EffectiveChapterPlan:
    assignments: tuple[EffectiveChapterAssignment, ...]

    @property
    def has_effective_grouping(self) -> bool:
        return any(
            assignment.effective_chapter_index is not None
            for assignment in self.assignments
        )


@dataclass(frozen=True)
class DocumentSectionBoundary:
    preceding_word_id: str
    word_id: str
    preceding_chapter_index: int
    chapter_index: int


@dataclass(frozen=True)
class BoundarySignal:
    source: BoundarySource
    status: BoundaryStatus


class SectionFallbackReason(str, Enum):
    NO_DIRECT_CHAPTERS = "no_direct_chapters"
    CHAPTER_UNMAPPED = "chapter_unmapped"
    NON_MONOTONIC_CHAPTER_ORDER = "non_monotonic_chapter_order"
    CHAPTER_ORDER_JUMP = "chapter_order_jump"
    SENTENCE_CROSSES_SECTIONS = "sentence_crosses_sections"
    TITLE_ASSOCIATION_FAILED = "title_association_failed"
    SECTION_RANGE_INVALID = "section_range_invalid"


@dataclass(frozen=True)
class SectionAggregationResult:
    sections: tuple[SourceSectionDTO, ...]
    fallback_reason: SectionFallbackReason | None = None


def derive_effective_chapters(
    words: Sequence[TimedWordDTO],
    official_tokens: Sequence[OfficialTranscriptToken],
) -> EffectiveChapterPlan:
    """Assign every word to its direct, first-later, or preceding chapter."""

    tokens_by_id: dict[str, OfficialTranscriptToken] = {}
    for token in official_tokens:
        if token.id in tokens_by_id:
            raise ChapterAssignmentError(
                ChapterAssignmentFailureReason.DUPLICATE_OFFICIAL_TOKEN,
                official_token_id=token.id,
            )
        tokens_by_id[token.id] = token

    direct_indexes: list[int | None] = []
    for word in words:
        chapter_indexes: set[int] = set()
        for token_id in word.official_token_ids:
            try:
                chapter_indexes.add(tokens_by_id[token_id].chapter_index)
            except KeyError as error:
                raise ChapterAssignmentError(
                    ChapterAssignmentFailureReason.OFFICIAL_TOKEN_NOT_FOUND,
                    word_id=word.id,
                    official_token_id=token_id,
                ) from error
        if len(chapter_indexes) > 1:
            raise ChapterAssignmentError(
                ChapterAssignmentFailureReason.WORD_CROSSES_CHAPTERS,
                word_id=word.id,
            )
        direct_indexes.append(next(iter(chapter_indexes), None))

    first_direct = next(
        (chapter for chapter in direct_indexes if chapter is not None), None
    )
    if first_direct is None:
        return EffectiveChapterPlan(
            tuple(
                EffectiveChapterAssignment(
                    word_id=word.id,
                    direct_chapter_index=None,
                    effective_chapter_index=None,
                    source=EffectiveChapterSource.UNAVAILABLE,
                )
                for word in words
            )
        )

    assignments: list[EffectiveChapterAssignment] = []
    previous_chapter: int | None = None
    for word, direct_chapter in zip(words, direct_indexes, strict=True):
        if direct_chapter is not None:
            effective_chapter = direct_chapter
            source = EffectiveChapterSource.DIRECT
            previous_chapter = direct_chapter
        elif previous_chapter is None:
            effective_chapter = first_direct
            source = EffectiveChapterSource.FIRST_LATER_CHAPTER
        else:
            effective_chapter = previous_chapter
            source = EffectiveChapterSource.PREVIOUS_CHAPTER
        assignments.append(
            EffectiveChapterAssignment(
                word_id=word.id,
                direct_chapter_index=direct_chapter,
                effective_chapter_index=effective_chapter,
                source=source,
            )
        )
    return EffectiveChapterPlan(tuple(assignments))


def document_section_boundaries(
    plan: EffectiveChapterPlan,
) -> tuple[DocumentSectionBoundary, ...]:
    """Return boundaries immediately before each effective chapter change."""

    result: list[DocumentSectionBoundary] = []
    for preceding, current in zip(plan.assignments, plan.assignments[1:]):
        preceding_chapter = preceding.effective_chapter_index
        current_chapter = current.effective_chapter_index
        if (
            preceding_chapter is not None
            and current_chapter is not None
            and preceding_chapter != current_chapter
        ):
            result.append(
                DocumentSectionBoundary(
                    preceding_word_id=preceding.word_id,
                    word_id=current.word_id,
                    preceding_chapter_index=preceding_chapter,
                    chapter_index=current_chapter,
                )
            )
    return tuple(result)


def select_boundary_signal(
    existing: BoundarySignal | None,
    *,
    document_section_change: bool,
) -> BoundarySignal | None:
    """Apply a section boundary unless a verified, more specific signal exists."""

    if not document_section_change:
        return existing
    if existing is not None and existing.status is BoundaryStatus.VERIFIED:
        return existing
    return BoundarySignal(
        source=BoundarySource.DOCUMENT_SECTION_CHANGE,
        status=BoundaryStatus.VERIFIED,
    )


def aggregate_source_sections(
    sentences: Sequence[SourceSentenceDTO],
    transcript: StructuredTranscriptDTO,
    plan: EffectiveChapterPlan,
) -> SectionAggregationResult:
    """Aggregate complete sentences or conservatively return no sections."""

    assignments = plan.assignments
    if not plan.has_effective_grouping:
        return _fallback(SectionFallbackReason.NO_DIRECT_CHAPTERS)

    assignment_positions: dict[str, int] = {}
    for position, assignment in enumerate(assignments):
        if assignment.word_id in assignment_positions:
            return _fallback(SectionFallbackReason.SECTION_RANGE_INVALID)
        assignment_positions[assignment.word_id] = position

    effective_order = _effective_chapter_order(assignments)
    if any(
        current < previous
        for previous, current in zip(effective_order, effective_order[1:])
    ):
        return _fallback(SectionFallbackReason.NON_MONOTONIC_CHAPTER_ORDER)

    chapter_count = len(transcript.chapters)
    if any(chapter < 1 or chapter > chapter_count for chapter in effective_order):
        return _fallback(SectionFallbackReason.TITLE_ASSOCIATION_FAILED)

    for previous, current in zip(effective_order, effective_order[1:]):
        if current > previous + 1 and any(
            _chapter_has_spoken_text(transcript, chapter_index)
            for chapter_index in range(previous + 1, current)
        ):
            return _fallback(SectionFallbackReason.CHAPTER_ORDER_JUMP)

    mapped_direct_chapters = {
        assignment.direct_chapter_index
        for assignment in assignments
        if assignment.direct_chapter_index is not None
    }
    for chapter_index in range(1, chapter_count + 1):
        if (
            _chapter_has_spoken_text(transcript, chapter_index)
            and chapter_index not in mapped_direct_chapters
        ):
            return _fallback(SectionFallbackReason.CHAPTER_UNMAPPED)

    sentence_chapters: list[tuple[SourceSentenceDTO, int]] = []
    next_word_position = 0
    seen_sentence_ids: set[str] = set()
    for sentence in sentences:
        if sentence.id in seen_sentence_ids:
            return _fallback(SectionFallbackReason.SECTION_RANGE_INVALID)
        seen_sentence_ids.add(sentence.id)
        try:
            first_position = assignment_positions[sentence.first_word_id]
            last_position = assignment_positions[sentence.last_word_id]
        except KeyError:
            return _fallback(SectionFallbackReason.SECTION_RANGE_INVALID)
        if first_position != next_word_position or last_position < first_position:
            return _fallback(SectionFallbackReason.SECTION_RANGE_INVALID)
        chapter_indexes = {
            assignment.effective_chapter_index
            for assignment in assignments[first_position : last_position + 1]
        }
        if len(chapter_indexes) != 1 or None in chapter_indexes:
            return _fallback(SectionFallbackReason.SENTENCE_CROSSES_SECTIONS)
        sentence_chapters.append((sentence, next(iter(chapter_indexes))))
        next_word_position = last_position + 1

    if next_word_position != len(assignments) or not sentence_chapters:
        return _fallback(SectionFallbackReason.SECTION_RANGE_INVALID)

    sections: list[SourceSectionDTO] = []
    section_chapter = sentence_chapters[0][1]
    first_sentence = sentence_chapters[0][0]
    last_sentence = first_sentence
    for sentence, chapter_index in sentence_chapters[1:]:
        if chapter_index == section_chapter:
            last_sentence = sentence
            continue
        section = _build_section(
            len(sections) + 1,
            section_chapter,
            first_sentence,
            last_sentence,
            transcript,
        )
        if section is None:
            return _fallback(SectionFallbackReason.TITLE_ASSOCIATION_FAILED)
        sections.append(section)
        section_chapter = chapter_index
        first_sentence = sentence
        last_sentence = sentence

    section = _build_section(
        len(sections) + 1,
        section_chapter,
        first_sentence,
        last_sentence,
        transcript,
    )
    if section is None:
        return _fallback(SectionFallbackReason.TITLE_ASSOCIATION_FAILED)
    sections.append(section)

    if not _sections_cover_sentences(sections, sentences):
        return _fallback(SectionFallbackReason.SECTION_RANGE_INVALID)
    return SectionAggregationResult(tuple(sections))


def _effective_chapter_order(
    assignments: Sequence[EffectiveChapterAssignment],
) -> tuple[int, ...]:
    result: list[int] = []
    for assignment in assignments:
        chapter = assignment.effective_chapter_index
        if chapter is not None and (not result or chapter != result[-1]):
            result.append(chapter)
    return tuple(result)


def _chapter_has_spoken_text(
    transcript: StructuredTranscriptDTO, chapter_index: int
) -> bool:
    chapter = transcript.chapters[chapter_index - 1]
    return any(paragraph.text for paragraph in chapter.paragraphs)


def _build_section(
    position: int,
    chapter_index: int,
    first_sentence: SourceSentenceDTO,
    last_sentence: SourceSentenceDTO,
    transcript: StructuredTranscriptDTO,
) -> SourceSectionDTO | None:
    if not 1 <= chapter_index <= len(transcript.chapters):
        return None
    return SourceSectionDTO(
        id=f"sec{position}",
        title=transcript.chapters[chapter_index - 1].title,
        first_sentence_id=first_sentence.id,
        last_sentence_id=last_sentence.id,
    )


def _sections_cover_sentences(
    sections: Sequence[SourceSectionDTO],
    sentences: Sequence[SourceSentenceDTO],
) -> bool:
    sentence_positions = {
        sentence.id: position for position, sentence in enumerate(sentences)
    }
    next_position = 0
    for position, section in enumerate(sections, start=1):
        if section.id != f"sec{position}":
            return False
        try:
            first_position = sentence_positions[section.first_sentence_id]
            last_position = sentence_positions[section.last_sentence_id]
        except KeyError:
            return False
        if first_position != next_position or last_position < first_position:
            return False
        next_position = last_position + 1
    return next_position == len(sentences)


def _fallback(reason: SectionFallbackReason) -> SectionAggregationResult:
    return SectionAggregationResult((), reason)
