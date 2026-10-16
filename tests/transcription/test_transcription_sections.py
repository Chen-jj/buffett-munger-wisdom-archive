from __future__ import annotations

import pytest

from archive_core.interfaces import (
    BoundarySource,
    BoundaryStatus,
    MatchType,
    SourceSentenceDTO,
    StructuredTranscriptDTO,
    TextSource,
    TimedWordDTO,
    TimingSource,
    TranscriptChapterDTO,
    TranscriptParagraphDTO,
)
from transcription.domain import (
    DOCUMENT_SECTION_POLICY_VERSION,
    BoundarySignal,
    ChapterAssignmentError,
    ChapterAssignmentFailureReason,
    DocumentSectionPolicy,
    EffectiveChapterAssignment,
    EffectiveChapterPlan,
    EffectiveChapterSource,
    OfficialTranscriptToken,
    SectionFallbackReason,
    aggregate_source_sections,
    derive_effective_chapters,
    document_section_boundaries,
    select_boundary_signal,
)


def _word(position: int, official_token_ids: tuple[str, ...] = ()) -> TimedWordDTO:
    return TimedWordDTO(
        id=f"w{position}",
        text=f"word{position}",
        start_ms=position * 100,
        end_ms=position * 100 + 50,
        asr_word_ids=(f"aw{position}",),
        official_token_ids=official_token_ids,
        match_type=MatchType.EXACT if official_token_ids else MatchType.ASR_ONLY,
        text_source=(
            TextSource.OFFICIAL_TRANSCRIPT if official_token_ids else TextSource.ASR
        ),
        timing_source=TimingSource.ACOUSTIC_ALIGNMENT,
    )


def _token(position: int, chapter_index: int) -> OfficialTranscriptToken:
    return OfficialTranscriptToken(
        id=f"ot{position}",
        text=f"word{position}",
        normalized=(f"word{position}",),
        chapter_index=chapter_index,
        chapter_number=0,
        paragraph_index=1,
        speaker_label=None,
    )


def _sentence(position: int, first_word: int, last_word: int) -> SourceSentenceDTO:
    return SourceSentenceDTO(
        id=f"s{position}",
        first_word_id=f"w{first_word}",
        last_word_id=f"w{last_word}",
        start_ms=first_word * 100,
        end_ms=last_word * 100 + 50,
        text="sentence",
        speaker_label=None,
        text_source=TextSource.OFFICIAL_TRANSCRIPT,
        boundary_source=BoundarySource.OFFICIAL_PUNCTUATION,
        boundary_status=BoundaryStatus.VERIFIED,
    )


def _transcript(*chapters: tuple[int, str, str]) -> StructuredTranscriptDTO:
    return StructuredTranscriptDTO(
        language="en",
        chapters=tuple(
            TranscriptChapterDTO(
                number=number,
                title=title,
                paragraphs=(
                    (
                        TranscriptParagraphDTO(text=text)
                        if text
                        else TranscriptParagraphDTO(
                            text="", stage_directions=("Pause",)
                        )
                    ),
                ),
            )
            for number, title, text in chapters
        ),
    )


def _assignment(
    position: int,
    chapter_index: int,
    *,
    direct: int | None = None,
) -> EffectiveChapterAssignment:
    selected_direct = chapter_index if direct is None else direct
    return EffectiveChapterAssignment(
        word_id=f"w{position}",
        direct_chapter_index=selected_direct,
        effective_chapter_index=chapter_index,
        source=(
            EffectiveChapterSource.DIRECT
            if selected_direct is not None
            else EffectiveChapterSource.PREVIOUS_CHAPTER
        ),
    )


def test_effective_chapters_cover_single_multiple_and_missing_ot_mappings() -> None:
    words = (
        _word(1, ("ot1",)),
        _word(2, ("ot2", "ot3")),
        _word(3),
    )
    tokens = (_token(1, 1), _token(2, 1), _token(3, 1))

    plan = derive_effective_chapters(words, tokens)

    assert [item.direct_chapter_index for item in plan.assignments] == [1, 1, None]
    assert [item.effective_chapter_index for item in plan.assignments] == [1, 1, 1]
    assert [item.source for item in plan.assignments] == [
        EffectiveChapterSource.DIRECT,
        EffectiveChapterSource.DIRECT,
        EffectiveChapterSource.PREVIOUS_CHAPTER,
    ]


def test_effective_chapters_fill_leading_middle_and_trailing_asr_only_words() -> None:
    words = tuple(
        _word(position, token_ids)
        for position, token_ids in enumerate(
            ((), (), ("ot1",), (), (), ("ot2",), ()), start=1
        )
    )

    plan = derive_effective_chapters(words, (_token(1, 1), _token(2, 2)))

    assert [item.effective_chapter_index for item in plan.assignments] == [
        1,
        1,
        1,
        1,
        1,
        2,
        2,
    ]
    assert [item.source for item in plan.assignments] == [
        EffectiveChapterSource.FIRST_LATER_CHAPTER,
        EffectiveChapterSource.FIRST_LATER_CHAPTER,
        EffectiveChapterSource.DIRECT,
        EffectiveChapterSource.PREVIOUS_CHAPTER,
        EffectiveChapterSource.PREVIOUS_CHAPTER,
        EffectiveChapterSource.DIRECT,
        EffectiveChapterSource.PREVIOUS_CHAPTER,
    ]


def test_all_asr_only_words_have_no_effective_grouping_or_boundaries() -> None:
    plan = derive_effective_chapters((_word(1), _word(2)), ())

    assert not plan.has_effective_grouping
    assert all(
        item.source is EffectiveChapterSource.UNAVAILABLE
        and item.effective_chapter_index is None
        for item in plan.assignments
    )
    assert document_section_boundaries(plan) == ()
    result = aggregate_source_sections(
        (_sentence(1, 1, 2),), _transcript((1, "", "spoken")), plan
    )
    assert result.sections == ()
    assert result.fallback_reason is SectionFallbackReason.NO_DIRECT_CHAPTERS


def test_word_referencing_tokens_across_chapters_is_rejected() -> None:
    with pytest.raises(ChapterAssignmentError) as captured:
        derive_effective_chapters(
            (_word(1, ("ot1", "ot2")),),
            (_token(1, 1), _token(2, 2)),
        )

    assert captured.value.reason is ChapterAssignmentFailureReason.WORD_CROSSES_CHAPTERS
    assert captured.value.word_id == "w1"


def test_unknown_official_token_is_rejected_with_diagnostic_identity() -> None:
    with pytest.raises(ChapterAssignmentError) as captured:
        derive_effective_chapters((_word(1, ("ot99",)),), ())

    assert captured.value.reason is ChapterAssignmentFailureReason.OFFICIAL_TOKEN_NOT_FOUND
    assert captured.value.word_id == "w1"
    assert captured.value.official_token_id == "ot99"


def test_document_section_change_is_reported_before_the_new_chapter_word() -> None:
    plan = derive_effective_chapters(
        (
            _word(1, ("ot1",)),
            _word(2),
            _word(3),
            _word(4, ("ot2",)),
            _word(5),
        ),
        (_token(1, 1), _token(2, 2)),
    )

    boundaries = document_section_boundaries(plan)
    assert len(boundaries) == 1
    boundary = boundaries[0]
    assert (
        boundary.preceding_word_id,
        boundary.word_id,
        boundary.preceding_chapter_index,
        boundary.chapter_index,
    ) == ("w3", "w4", 1, 2)


def test_verified_boundary_wins_while_section_change_replaces_weak_signal() -> None:
    official = BoundarySignal(
        BoundarySource.OFFICIAL_PUNCTUATION, BoundaryStatus.VERIFIED
    )
    weak = BoundarySignal(BoundarySource.ASR_PUNCTUATION, BoundaryStatus.INFERRED)

    assert select_boundary_signal(official, document_section_change=True) == official
    assert select_boundary_signal(weak, document_section_change=True) == BoundarySignal(
        BoundarySource.DOCUMENT_SECTION_CHANGE, BoundaryStatus.VERIFIED
    )
    assert select_boundary_signal(weak, document_section_change=False) == weak


def test_valid_sentences_form_stable_sections_using_index_titles() -> None:
    transcript = _transcript(
        (99, "Capital allocation", "spoken one"),
        (99, "", "spoken two"),
    )
    plan = EffectiveChapterPlan(
        (_assignment(1, 1), _assignment(2, 1), _assignment(3, 2))
    )

    result = aggregate_source_sections(
        (_sentence(1, 1, 2), _sentence(2, 3, 3)), transcript, plan
    )

    assert result.fallback_reason is None
    assert [section.to_dict() for section in result.sections] == [
        {
            "id": "sec1",
            "title": "Capital allocation",
            "first_sentence_id": "s1",
            "last_sentence_id": "s1",
        },
        {
            "id": "sec2",
            "title": "",
            "first_sentence_id": "s2",
            "last_sentence_id": "s2",
        },
    ]


def test_unmapped_spoken_chapter_falls_back_without_partial_sections() -> None:
    result = aggregate_source_sections(
        (_sentence(1, 1, 1),),
        _transcript((1, "One", "spoken"), (2, "Two", "also spoken")),
        EffectiveChapterPlan((_assignment(1, 1),)),
    )

    assert result.sections == ()
    assert result.fallback_reason is SectionFallbackReason.CHAPTER_UNMAPPED


@pytest.mark.parametrize(
    ("chapters", "plan", "expected"),
    [
        (
            ((1, "One", "spoken"), (2, "Two", "spoken")),
            EffectiveChapterPlan((_assignment(1, 2), _assignment(2, 1))),
            SectionFallbackReason.NON_MONOTONIC_CHAPTER_ORDER,
        ),
        (
            (
                (1, "One", "spoken"),
                (2, "Two", "spoken"),
                (3, "Three", "spoken"),
            ),
            EffectiveChapterPlan((_assignment(1, 1), _assignment(2, 3))),
            SectionFallbackReason.CHAPTER_ORDER_JUMP,
        ),
    ],
)
def test_invalid_chapter_order_falls_back_with_specific_reason(
    chapters: tuple[tuple[int, str, str], ...],
    plan: EffectiveChapterPlan,
    expected: SectionFallbackReason,
) -> None:
    result = aggregate_source_sections(
        (_sentence(1, 1, 1), _sentence(2, 2, 2)),
        _transcript(*chapters),
        plan,
    )

    assert result.sections == ()
    assert result.fallback_reason is expected


def test_jump_over_a_chapter_without_spoken_text_is_explainable() -> None:
    result = aggregate_source_sections(
        (_sentence(1, 1, 1), _sentence(2, 2, 2)),
        _transcript(
            (1, "One", "spoken"),
            (2, "Stage only", ""),
            (3, "Three", "spoken"),
        ),
        EffectiveChapterPlan((_assignment(1, 1), _assignment(2, 3))),
    )

    assert result.fallback_reason is None
    assert [section.title for section in result.sections] == ["One", "Three"]


def test_cross_section_sentence_falls_back_without_splitting_it() -> None:
    sentence = _sentence(1, 1, 2)
    result = aggregate_source_sections(
        (sentence,),
        _transcript((1, "One", "spoken"), (2, "Two", "spoken")),
        EffectiveChapterPlan((_assignment(1, 1), _assignment(2, 2))),
    )

    assert result.sections == ()
    assert result.fallback_reason is SectionFallbackReason.SENTENCE_CROSSES_SECTIONS
    assert sentence.first_word_id == "w1"
    assert sentence.last_word_id == "w2"


def test_unknown_chapter_title_association_falls_back() -> None:
    result = aggregate_source_sections(
        (_sentence(1, 1, 1),),
        _transcript((1, "One", "spoken")),
        EffectiveChapterPlan((_assignment(1, 2),)),
    )

    assert result.sections == ()
    assert result.fallback_reason is SectionFallbackReason.TITLE_ASSOCIATION_FAILED


@pytest.mark.parametrize(
    "sentences",
    [
        (_sentence(1, 1, 1),),
        (_sentence(1, 1, 1), _sentence(2, 1, 2)),
    ],
)
def test_incomplete_or_overlapping_sentence_ranges_fall_back(
    sentences: tuple[SourceSentenceDTO, ...],
) -> None:
    result = aggregate_source_sections(
        sentences,
        _transcript((1, "One", "spoken")),
        EffectiveChapterPlan((_assignment(1, 1), _assignment(2, 1))),
    )

    assert result.sections == ()
    assert result.fallback_reason is SectionFallbackReason.SECTION_RANGE_INVALID


def test_document_section_policy_is_strict_and_serializable() -> None:
    policy = DocumentSectionPolicy()

    assert policy.to_dict() == {"version": DOCUMENT_SECTION_POLICY_VERSION}
    assert DocumentSectionPolicy.from_dict(policy.to_dict()) == policy
    with pytest.raises(ValueError, match="unsupported document section policy"):
        DocumentSectionPolicy(version="document-sections.v0")
