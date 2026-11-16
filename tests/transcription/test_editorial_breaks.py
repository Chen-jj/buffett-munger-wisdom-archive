"""CNBC source editorial marks are untimed and separate from spoken words."""

from dataclasses import replace

import pytest

from archive_core.interfaces import (
    EditorialBreakDTO, MatchType, SourceAlignmentDTO, TextSource, TimedWordDTO, TimingSource,
)
from transcription.domain.editorial import separate_editorial_breaks
from transcription.domain.fusion import OfficialTranscriptToken


def word(text="go—", *, official=True):
    return TimedWordDTO("w1", text, 100, 500, ("aw1",), ("ot1",) if official else (),
                        MatchType.EXACT if official else MatchType.ASR_ONLY,
                        TextSource.OFFICIAL_TRANSCRIPT if official else TextSource.ASR,
                        TimingSource.ACOUSTIC_ALIGNMENT)


def token(text="go—"):
    return OfficialTranscriptToken("ot1", text, ("go",), 1, 1, 1, None)


@pytest.mark.parametrize("text", ("go", "figures", "sure", "future", "that", "it's", "were", "ago",
                                 "drink", "business", "is", "for", "the", "account", "happen", "now",
                                 "very", "impossible", "figure", "figure", "just", "would", "way", "question",
                                 "businesses", "businesses"))
def test_historical_26_surfaces_use_general_provenance_rule(text):
    original = word(text + "—")
    projected, annotations = separate_editorial_breaks((original,), (token(text + "—"),), source="cnbc")
    assert projected == (replace(original, text=text),)
    assert annotations == (EditorialBreakDTO("e1", "w1", ("ot1",)),)
    assert annotations[0].to_dict().keys() == {"id", "after_word_id", "official_token_ids", "source", "kind", "policy_version"}


@pytest.mark.parametrize("source,original,evidence", (("youtube", word(), token()),
                                                    ("cnbc", word(official=False), token()),
                                                    ("cnbc", word(), token("go")),
                                                    ("cnbc", word("co-operate–"), token("co-operate–"))))
def test_non_target_content_unchanged(source, original, evidence):
    assert separate_editorial_breaks((original,), (evidence,), source=source) == ((original,), ())


def test_multiple_marks_are_ordered_untimed_and_not_restored_if_absent():
    original = word("go——.")
    projected, annotations = separate_editorial_breaks((original,), (token("go——."),), source="cnbc")
    assert projected[0].text == "go."
    assert tuple(item.id for item in annotations) == ("e1", "e2")
    assert all(not any("ms" in key for key in item.to_dict()) for item in annotations)
    assert separate_editorial_breaks((word("go"),), (token(),), source="cnbc")[1] == ()


def test_source_alignment_requires_current_annotations_and_rejects_old_schema():
    dto = SourceAlignmentDTO("en", 0, (), (), ())
    assert SourceAlignmentDTO.from_dict(dto.to_dict()) == dto
    data = dto.to_dict()
    del data["annotations"]
    with pytest.raises(ValueError):
        SourceAlignmentDTO.from_dict(data)
    with pytest.raises(ValueError):
        SourceAlignmentDTO.from_dict({**dto.to_dict(), "schema_version": "transcription.source-alignment.v1"})
