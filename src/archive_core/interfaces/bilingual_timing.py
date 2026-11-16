"""Shared current text counting and exact decoded-frame timing conventions."""

from __future__ import annotations

from bisect import bisect_left
from functools import lru_cache
from typing import TYPE_CHECKING

from .subtitle_text import is_combining_mark, is_layout_whitespace

if TYPE_CHECKING:
    from .bilingual import MediaBoundaryDTO

COUNTING_VERSION = "unicode14-latin-word.v2"
FRAME_GAP_VERSION = "decoded-pts-half-open-two-frames.v1"

# Frozen Unicode 14.0 Latin letter ranges (fullwidth forms deliberately excluded).
# Other scripts and unknown/new code points conservatively count as fullwidth.
_LATIN_RANGES = (
    (0x41, 0x5A), (0x61, 0x7A), (0xC0, 0xD6), (0xD8, 0xF6),
    (0xF8, 0x2AF), (0x1D00, 0x1D25), (0x1D62, 0x1D65), (0x1D6B, 0x1D77),
    (0x1D79, 0x1D9A), (0x1E00, 0x1EFF), (0x2071, 0x2071), (0x207F, 0x207F),
    (0x2090, 0x209C), (0x2184, 0x2184), (0x2C60, 0x2C7C), (0x2C7E, 0x2C7F),
    (0xA722, 0xA76F), (0xA771, 0xA787), (0xA78B, 0xA7CA), (0xA7D0, 0xA7D1),
    (0xA7D3, 0xA7D3), (0xA7D5, 0xA7D9), (0xA7F5, 0xA7F7), (0xA7FA, 0xA7FF),
    (0xAB30, 0xAB5A), (0xAB60, 0xAB64), (0xAB66, 0xAB68), (0xFB00, 0xFB06),
    (0x1DF00, 0x1DF1E),
)
# Frozen Unicode 14.0 decimal digits, except fullwidth U+FF10..FF19.
_DECIMAL_RANGES = (
    (0x30, 0x39), (0x660, 0x669), (0x6F0, 0x6F9), (0x7C0, 0x7C9),
    (0x966, 0x96F), (0x9E6, 0x9EF), (0xA66, 0xA6F), (0xAE6, 0xAEF),
    (0xB66, 0xB6F), (0xBE6, 0xBEF), (0xC66, 0xC6F), (0xCE6, 0xCEF),
    (0xD66, 0xD6F), (0xDE6, 0xDEF), (0xE50, 0xE59), (0xED0, 0xED9),
    (0xF20, 0xF29), (0x1040, 0x1049), (0x1090, 0x1099), (0x17E0, 0x17E9),
    (0x1810, 0x1819), (0x1946, 0x194F), (0x19D0, 0x19D9), (0x1A80, 0x1A89),
    (0x1A90, 0x1A99), (0x1B50, 0x1B59), (0x1BB0, 0x1BB9), (0x1C40, 0x1C49),
    (0x1C50, 0x1C59), (0xA620, 0xA629), (0xA8D0, 0xA8D9), (0xA900, 0xA909),
    (0xA9D0, 0xA9D9), (0xA9F0, 0xA9F9), (0xAA50, 0xAA59), (0xABF0, 0xABF9),
    (0x104A0, 0x104A9), (0x10D30, 0x10D39), (0x11066, 0x1106F), (0x110F0, 0x110F9),
    (0x11136, 0x1113F), (0x111D0, 0x111D9), (0x112F0, 0x112F9), (0x11450, 0x11459),
    (0x114D0, 0x114D9), (0x11650, 0x11659), (0x116C0, 0x116C9), (0x11730, 0x11739),
    (0x118E0, 0x118E9), (0x11950, 0x11959), (0x11C50, 0x11C59), (0x11D50, 0x11D59),
    (0x11DA0, 0x11DA9), (0x16A60, 0x16A69), (0x16AC0, 0x16AC9), (0x16B50, 0x16B59),
    (0x1D7CE, 0x1D7FF), (0x1E140, 0x1E149), (0x1E2F0, 0x1E2F9), (0x1E950, 0x1E959),
    (0x1FBF0, 0x1FBF9),
)


@lru_cache(maxsize=4096)
def _zero_units(character: str) -> bool:
    return (
        is_layout_whitespace(character)
        or is_combining_mark(character)
        or character == "\u200d"
        or 0x1F3FB <= ord(character) <= 0x1F3FF
    )


@lru_cache(maxsize=4096)
def _latin_letter(character: str) -> bool:
    return any(start <= ord(character) <= end for start, end in _LATIN_RANGES)


def latin_word_spans(text: str) -> tuple[tuple[int, int], ...]:
    """Frozen Latin letters/marks with internal hyphen or apostrophe connectors."""
    spans = []
    position = 0
    while position < len(text):
        if not _latin_letter(text[position]):
            position += 1
            continue
        first = position
        position += 1
        while position < len(text):
            character = text[position]
            if (_latin_letter(character)
                    or is_combining_mark(character)):
                position += 1
            elif (character in "-'’\u2010\u2011" and position + 1 < len(text)
                  and _latin_letter(text[position + 1])):
                position += 1
            else:
                break
        spans.append((first, position))
    return tuple(spans)


def chinese_half_units(text: str) -> int:
    """Latin words count two half-units; numbers/other punctuation retain v1."""
    if not isinstance(text, str):
        raise ValueError("text must be a string")
    return _count_chinese_text(text)


@lru_cache(maxsize=16384)
def _count_chinese_text(text: str) -> int:
    result = 0
    word_starts = dict(latin_word_spans(text))
    position = 0
    while position < len(text):
        if position in word_starts:
            result += 2
            position = word_starts[position]
            continue
        character = text[position]
        position += 1
        result += _non_word_half_units(character)
    return result


@lru_cache(maxsize=4096)
def _non_word_half_units(character: str) -> int:
    if _zero_units(character):
        return 0
    codepoint = ord(character)
    halfwidth = (
            0x21 <= codepoint <= 0x7E
            or any(start <= codepoint <= end for start, end in (
                (0xFF61, 0xFFBE), (0xFFC2, 0xFFC7), (0xFFCA, 0xFFCF),
                (0xFFD2, 0xFFD7), (0xFFDA, 0xFFDC),
            ))
            or 0xFFE8 <= codepoint <= 0xFFEE
            or any(start <= codepoint <= end for start, end in _LATIN_RANGES)
            or any(start <= codepoint <= end for start, end in _DECIMAL_RANGES)
    )
    return 1 if halfwidth else 2



def english_characters(text: str) -> int:
    """Count Unicode code points including spaces/punctuation in logical English."""
    if not isinstance(text, str):
        raise ValueError("text must be a string")
    return len(text)


def empty_frame_count(media: MediaBoundaryDTO, end_ms: int, next_start_ms: int) -> int | None:
    """Cue events are [start,end); count decoded PTS in [end,next_start)."""
    if next_start_ms < end_ms:
        raise ValueError("actual cue overlap")
    timestamps = media.frame_timestamps_us
    if timestamps is None:
        return None
    return bisect_left(timestamps, next_start_ms * 1000) - bisect_left(timestamps, end_ms * 1000)


def maximum_extension_ms(media: MediaBoundaryDTO, start_ms: int, base_end_ms: int, next_start_ms: int | None) -> int:
    """Read-only borrowing limit; floor the second-last reserved PTS to milliseconds."""
    available = min(500, 7000 - (base_end_ms - start_ms), media.duration_ms - base_end_ms)
    if next_start_ms is not None:
        if next_start_ms < base_end_ms:
            raise ValueError("source windows overlap")
        timestamps = media.frame_timestamps_us
        if timestamps is None:
            return 0
        position = bisect_left(timestamps, next_start_ms * 1000)
        if position < 2:
            return 0
        available = min(available, timestamps[position - 2] // 1000 - base_end_ms)
    return max(0, available)
