"""Recognized Stanza phrase boundaries protect spoken source text."""
from types import SimpleNamespace as NS
import pytest
from srt_processing.domain.chunking import SyntaxBoundary
from srt_processing.infrastructure.stanza_chunking import analyze_stanza_sentence
from tests.support.current_bilingual import alignment


@pytest.mark.parametrize("damage", ["missing", "changed", "split_sentences"])
def test_nonexact_syntax_mapping_is_not_a_fallback(damage):
    words = alignment().words[:2]
    leaf = lambda label, *children: NS(label=label, children=list(children))
    value = [NS(text="We", start_char=0, end_char=2, words=[NS(text="We", xpos="PRP")]),
             NS(text="agree", start_char=3, end_char=8, words=[NS(text="agree", xpos="VBP")]),
             NS(text=".", start_char=8, end_char=9, words=[NS(text=".", xpos=".")])]
    parse = leaf("ROOT",leaf("S",leaf("PRP",leaf("We")),leaf("VBP",leaf("agree")),leaf(".",leaf("."))))
    sentence = NS(tokens=value,constituency=parse)
    assert analyze_stanza_sentence(words, NS(sentences=[sentence])).boundaries == (SyntaxBoundary(1, ("ordinary",)),)
    if damage == "missing": value.pop()
    if damage == "changed": value[1].text = "decline"
    with pytest.raises(ValueError):
        analyze_stanza_sentence(words, NS(sentences=[sentence,sentence] if damage == "split_sentences" else [sentence]))
