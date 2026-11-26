from __future__ import annotations

from dataclasses import replace

import pytest

from archive_core.interfaces import (
    StructuredTranscriptDTO,
    TranscriptChapterDTO,
    TranscriptParagraphDTO,
)
from transcription.domain.alignment import AlignedAsrWord, AlignmentTimingSource
from transcription.domain.fusion import (
    NormalizationPolicy,
    build_official_tokens,
    same_official_person,
)


def _introduction(surname: str, *, first: str = "Debbie", title: str = "Ms."):
    asr_words = tuple(
        AlignedAsrWord(
            id=f"aw{index}", raw_word_id=f"rw{index}", segment_id="seg1",
            text=text, start_ms=index * 100, end_ms=index * 100 + 80,
            alignment_score=0.75, timing_source=AlignmentTimingSource.ACOUSTIC_ALIGNMENT,
        )
        for index, text in enumerate(("I", "recognize", title, first, surname), 1)
    )
    transcript = StructuredTranscriptDTO("en", (
        TranscriptChapterDTO(1, "", (
            TranscriptParagraphDTO("I recognize Miss Debbie Bosanek,", "CHAIR"),
            TranscriptParagraphDTO("I make a motion.", "DEBBIE BOSANEK"),
        )),
    ))
    tokens, _ = build_official_tokens(transcript, NormalizationPolicy())
    return asr_words, tokens[:4], tokens[4], {token.speaker_label for token in tokens}


@pytest.mark.parametrize("surname", ("Bozonic,", "Pesonic", "Bosonic", "Pisonik"))
def test_same_introduced_person_supports_the_canonical_surname(surname: str) -> None:
    asr_words, preceding, official, labels = _introduction(surname)

    assert same_official_person(asr_words, official, preceding, labels)
    assert official.speaker_label == "CHAIR"
    assert official.text == "Bosanek,"


@pytest.mark.parametrize(("surname", "first", "title"), (
    ("Adams", "Debbie", "Ms."),
    ("Bosonic", "Daisy", "Ms."),
    ("Bosonic", "Debbie", "Mrs."),
))
def test_mismatched_introduction_does_not_prove_same_identity(
    surname: str, first: str, title: str
) -> None:
    asr_words, preceding, official, labels = _introduction(surname, first=first, title=title)

    assert not same_official_person(asr_words, official, preceding, labels)


def test_unresolved_identity_or_timing_does_not_authorize_a_surname_change() -> None:
    asr_words, preceding, official, labels = _introduction("Bosonic")

    assert not same_official_person(asr_words, official, preceding, {"CHAIR"})
    assert not same_official_person(asr_words, official, preceding, labels | {"DEBBIE BOSONIC"})
    assert not same_official_person(
        asr_words, replace(official, paragraph_index=2), preceding, labels
    )
    previous_time = replace(asr_words[-1], start_ms=asr_words[-2].start_ms)
    assert not same_official_person(asr_words[:-1] + (previous_time,), official, preceding, labels)
