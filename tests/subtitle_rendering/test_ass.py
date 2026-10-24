"""Canonical ASS/approved word-joiner dialect; no font or external renderer."""

from dataclasses import replace
import hashlib
from itertools import product

import pysubs2
import pytest

from subtitle_rendering.infrastructure.ass import (
    AssGenerationError, Pysubs2AssCodec, WORD_JOINER, escape_literal, unescape_literal,
)
from tests.archive_core.test_rendering_contracts import render_plan, source_plan


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


def test_ass_has_fixed_script_style_projected_times_order_offsets_and_bytes():
    codec, plan, source = Pysubs2AssCodec(), render_plan(), source_plan()
    data = codec.encode(plan, source)
    assert data == codec.encode(plan, source)
    assert data.endswith(b"\n") and b"\r" not in data and not data.startswith(b"\xef\xbb\xbf")
    parsed = pysubs2.SSAFile.from_string(data.decode(), "ass")
    assert parsed.info["WrapStyle"] == "2"
    assert parsed.info["PlayResX"] == "640" and parsed.info["PlayResY"] == "360"
    assert parsed.info["ScaledBorderAndShadow"] == "yes"
    assert set(parsed.styles) == {"Bilingual"}
    assert parsed.styles["Bilingual"].fontsize == 30
    assert parsed.styles["Bilingual"].alignment == 2
    assert parsed.styles["Bilingual"].marginv >= 42 + 2 + 1
    assert parsed.events[0].name == "c1"
    assert parsed.events[0].start == plan.cues[0].ass_start_ms
    assert parsed.events[0].end == plan.cues[0].ass_end_ms
    assert parsed.events[0].text.count(r"\N") == 3
    assert parsed.events[1].text.count(r"\N") == 1
    assert r"{\fs20\1c&H0060E6FF&}" in parsed.events[0].text
    assert "WARREN" not in data.decode() and "section" not in data.decode()
    assert codec.library_version == pysubs2.__version__


@pytest.mark.parametrize("text", (r"{\pos(1,2)}", r"literal \N and \h", "trailing \\", r"<b>x</b> and {x}"))
def test_ass_event_roundtrip_preserves_malicious_or_plaintext_source(text):
    source = source_plan()
    first = replace(source.cues[0], english_text=text)
    source = replace(source, cues=(first, source.cues[1]))
    plan = render_plan()
    first_render = replace(plan.cues[0], english_text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                           english_break_offsets=(), english_lines=(plan.cues[0].english_lines[0],))
    plan = replace(plan, cues=(first_render, plan.cues[1]))
    data = Pysubs2AssCodec().encode(plan, source)
    parsed = pysubs2.SSAFile.from_string(data.decode(), "ass")
    encoded_english = parsed.events[0].text.split(r"{\fs20\1c&H0060E6FF&}")[1]
    assert unescape_literal(encoded_english) == text
    assert "\\" + WORD_JOINER + "N" in encoded_english if r"\N" in text else True


@pytest.mark.parametrize("mutation", (
    lambda data: b"\xef\xbb\xbf" + data, lambda data: data.replace(b"\n", b"\r\n"), lambda data: data[:-1],
    lambda data: data + b"; unknown extra content\n", lambda data: data.replace(b"WrapStyle: 2", b"WrapStyle: 0"),
    lambda data: data.replace(b"PlayResX: 640", b"PlayResX: 1280"),
    lambda data: data.replace(b"Hiragino Sans GB", b"Arial"), lambda data: data.replace(b"c1,", b"speaker,"),
    lambda data: data.replace(b"0:00:00.10", b"0:00:00.11"), lambda data: data.replace(b"\\fs20", b"\\fs19"),
    lambda data: data.replace(b"&H0060E6FF&", b"&H000000FF&"),
    lambda data: data.replace(b"We \\Nagree.", b"We agree."),
    lambda data: data.replace(b"[Events]", b"[Fonts]\nfontname: injected\n[Events]"),
))
def test_ass_strict_readback_rejects_all_tampered_bytes(mutation):
    codec, plan, source = Pysubs2AssCodec(), render_plan(), source_plan()
    with pytest.raises(AssGenerationError):
        codec.validate(mutation(codec.encode(plan, source)), plan, source)
