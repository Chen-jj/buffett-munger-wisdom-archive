"""Canonical ASS/approved word-joiner dialect; no font or external renderer."""

from itertools import product

import pytest

from subtitle_rendering.infrastructure.ass import (
    AssGenerationError, WORD_JOINER, escape_literal, unescape_literal,
)


@pytest.mark.parametrize("text", (
    r"{\pos(1,2)}", r"\N", r"\n", r"\h", "\\", r"\\N", r"{} {{}} \{x\}",
    r"<b>not HTML</b>", r"{\fs1\c&H0000FF&}attack", "slash\\" + WORD_JOINER + "N",
    "中文与Latin 123", "emoji👩\u200d💻", "e\u0301",
))
def test_literal_dialect_is_reversible_and_does_not_double_backslashes(text):
    encoded = escape_literal(text)
    assert unescape_literal(encoded) == text
    assert encoded.count(WORD_JOINER) == text.count(WORD_JOINER) + text.count("\\")


def test_escape_survives_independent_libass_text_grammar_not_only_our_inverse():
    # Mirror ass_get_next_char's renderer grammar, not the adapter's inverse grammar.
    # The selected corpus contains no source WORD JOINER, only inserted display controls.
    def displayed(encoded):
        output, position = [], 0
        while position < len(encoded):
            character = encoded[position]
            if character == "{" and "}" in encoded[position:]:
                position = encoded.index("}", position) + 1
                continue
            if character == "\\" and position + 1 < len(encoded):
                following = encoded[position + 1]
                if following in "Nnh{}":
                    output.append({"N": "\n", "n": "\n", "h": "\u00a0", "{": "{", "}": "}"}[following])
                    position += 2
                    continue
            if character != WORD_JOINER:
                output.append(character)
            position += 1
        return "".join(output)

    for characters in product("\\{}NnhA", repeat=4):
        source = "".join(characters)
        assert displayed(escape_literal(source)) == source
    assert displayed(r"\{}N") != r"\N"  # The rejected empty-override proposal really loses the slash.
    assert displayed(r"\\N") != r"\N"  # Doubling the slash still triggers a renderer newline.


@pytest.mark.parametrize("text", (r"\N", r"\n", r"\h", r"\x", "\\", "{x}", "text\nnext", "\x00"))
def test_uncontrolled_body_syntax_is_rejected(text):
    with pytest.raises(AssGenerationError):
        unescape_literal(text)


@pytest.mark.parametrize("text", ("\n", "\r", "\t", "\x00"))
def test_raw_source_control_characters_cannot_enter_ass(text):
    with pytest.raises(AssGenerationError):
        escape_literal(text)
