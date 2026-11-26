from __future__ import annotations

import pytest

from archive_core.interfaces import (
    StructuredTranscriptDTO,
    TranscriptChapterDTO,
    TranscriptParagraphDTO,
)
from transcription.domain.fusion import (
    NormalizationPolicy,
    build_official_tokens,
    equivalent_fusion_text,
    fusion_candidate_readings,
    fusion_candidate_text,
    is_explicit_fusion_quantity,
    normalize_token,
    official_surface_text,
)


@pytest.mark.parametrize(("asr", "official", "display"), (
    (("80%",), "80 percent", "80%"),
    (("1.25%",), "1 1/4 percent", "1.25%"),
    (("3", "rd,"), "3rd,", "3rd,"),
    (("18", "th"), "18th", "18th"),
    (("the", "30", "s"), "the' 30 s", "the ’30s"),
    (("30", "s"), "'30s", "’30s"),
    (("9-", "11,"), "9/11,", "9/11,"),
    (("four", "hundred", "and", "twenty", "six", "million", "dollars"),
     "$426 million", "$426 million"),
))
def test_numeric_spans_keep_official_source_and_publish_standard_display(
    asr: tuple[str, ...], official: str, display: str
) -> None:
    transcript = StructuredTranscriptDTO("en", (
        TranscriptChapterDTO(4, "Context", (
            TranscriptParagraphDTO(f"Around {official} then.", "SPEAKER"),
        )),
    ))
    tokens, _ = build_official_tokens(transcript, NormalizationPolicy())

    assert tuple(token.text for token in tokens) == ("Around", official, "then.")
    assert tokens[1].id == "ot2"
    assert tokens[1].paragraph_index == 1
    assert tokens[1].speaker_label == "SPEAKER"
    assert equivalent_fusion_text(asr, (tokens[1].text,))
    assert official_surface_text((tokens[1],)) == display


@pytest.mark.parametrize(("asr", "official"), (
    ("1/4", "14"),
    ("we were", "we’re"),
    ("3:45", "345"),
    ("9-11", "9/11"),
    ("-20", "20"),
    ("1.250%", "1.25%"),
    ("$1,107,400", "$1,107,400,000"),
    ("€426 million", "$426 million"),
))
def test_text_normalization_preserves_distinct_meanings(asr: str, official: str) -> None:
    assert normalize_token(asr) != normalize_token(official)
    assert not equivalent_fusion_text((asr,), (official,))


def test_conflicting_dollar_amounts_expand_to_whole_spoken_readings() -> None:
    assert fusion_candidate_text("$1,107,400") == (
        "one million one hundred seven thousand four hundred dollars"
    )
    assert fusion_candidate_text("$1,107,400,000") == (
        "one billion one hundred seven million four hundred thousand dollars"
    )


@pytest.mark.parametrize(("written", "spoken"), (
    ("100%", ("a", "hundred", "percent")),
    ("125%", ("one", "hundred", "and", "twenty-five", "percent")),
    ("1.50%", ("one", "point", "five", "zero", "percent")),
    ("-10%", ("minus", "ten", "percent")),
))
def test_spoken_percentages_compare_in_both_directions_and_format_the_source(
    written: str, spoken: tuple[str, ...]
) -> None:
    phrase = " ".join(spoken)
    transcript = StructuredTranscriptDTO("en", (
        TranscriptChapterDTO(1, "", (TranscriptParagraphDTO(phrase + "."),)),
    ))
    tokens, _ = build_official_tokens(transcript, NormalizationPolicy())

    assert equivalent_fusion_text((written,), spoken)
    assert equivalent_fusion_text(spoken, (written,))
    assert is_explicit_fusion_quantity(phrase)
    assert official_surface_text(tokens) == written + "."
    assert len(tokens) == len(spoken)


@pytest.mark.parametrize(("written", "spoken"), (
    ("100%", "not a hundred percent"),
    ("100%", "a hundred euros"),
    ("100%", "a hundred and percent"),
    ("100%", "ninety ten percent"),
    ("1.5%", "one point five zero percent"),
    ("10%", "minus ten percent"),
    ("$110", "a hundred and ten euros"),
))
def test_spoken_quantities_do_not_drop_negation_unit_or_precision(written: str, spoken: str) -> None:
    assert not equivalent_fusion_text((written,), tuple(spoken.split()))
    assert not equivalent_fusion_text(tuple(spoken.split()), (written,))


def test_amount_variants_preserve_the_full_integer_and_currency() -> None:
    asr = "$1,107,400"
    official = "$1,107,400,000"
    asr_readings = fusion_candidate_readings(asr, implicit_currency=True)
    official_readings = fusion_candidate_readings(official, implicit_currency=True)

    assert "a million one hundred and seven thousand four hundred" in asr_readings
    assert "a billion one hundred and seven million four hundred thousand" in official_readings
    assert len(asr_readings) == len(official_readings) == 8
    assert not set(asr_readings) & set(official_readings)
    assert all(reading.endswith(" dollars") for reading in fusion_candidate_readings(official))
    assert all(
        equivalent_fusion_text((official,), tuple(reading.split()))
        for reading in official_readings if reading.endswith(" dollars")
    )
    assert fusion_candidate_readings("not one hundred dollars") == ("not one hundred dollars",)


def test_ordinary_counts_keep_official_spelling() -> None:
    transcript = StructuredTranscriptDTO("en", (
        TranscriptChapterDTO(1, "", (TranscriptParagraphDTO("Two months."),)),
    ))
    tokens, _ = build_official_tokens(transcript, NormalizationPolicy())

    assert tuple(token.text for token in tokens) == ("Two", "months.")
    assert official_surface_text(tokens) == "Two months."
