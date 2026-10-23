"""Pure pause-only Chinese boundaries and soft lexical evidence."""

from __future__ import annotations

from dataclasses import dataclass
import re

from archive_core.interfaces import character_boundaries

from .rules import latin_word_spans


_PUNCTUATION_GROUP = re.compile(r"—{2,}|–{2,}|-{2,}|…{2,}|\.{3,}")
_NUMBER_UNIT = re.compile(
    r"(?:[0-9]+(?:[,.][0-9]+)*|[零〇一二两三四五六七八九十百千万亿]+)"
    r"(?:万亿|十亿|千万|百万|美元|人民币|个月|小时|分钟|毫秒|公里|千米|千克|公斤|％|%|元|年|月|天|日|秒|米|克|亿|万)"
)
_LATIN_NAME = re.compile(r"[A-Z][A-Za-z'’\-]*(?: [A-Z][A-Za-z'’\-]*)+")
_PAUSES = frozenset("，,、；;：:。.!！?？…—–")
_CLOSERS = frozenset("\"'”’」』）)]}】》〉")


@dataclass(frozen=True)
class ChineseBoundaries:
    allowed: tuple[int, ...]
    lexical_cuts: frozenset[int]


def _is_pause(text: str, index: int) -> bool:
    character = text[index]
    if character == "-":
        return ((index > 0 and text[index - 1] == "-")
                or (index + 1 < len(text) and text[index + 1] == "-"))
    if character not in _PAUSES:
        return False
    if 0 < index < len(text) - 1:
        left, right = text[index - 1], text[index + 1]
        if character == "." and left.isascii() and right.isascii() and left.isalnum() and right.isalnum():
            return False
        if character in ",:" and left in "0123456789" and right in "0123456789":
            return False
    return True


def _pause_groups(text: str) -> tuple[tuple[int, ...], tuple[int, ...]]:
    forbidden = set()
    for start, end in latin_word_spans(text):
        forbidden.update(range(start + 1, end))
    for match in _PUNCTUATION_GROUP.finditer(text):
        forbidden.update(range(match.start() + 1, match.end()))
    atomic = set(character_boundaries(text)) - forbidden
    allowed = {0, len(text)}
    strong = set()
    index = 0
    while index < len(text):
        if not _is_pause(text, index):
            index += 1
            continue
        end = index + 1
        # Closers and punctuation may alternate: never expose a cut before the
        # comma in “第一；”， or before the punctuation following an ellipsis.
        while end < len(text) and (_is_pause(text, end) or text[end] in _CLOSERS or text[end] == " "):
            end += 1
        if end in atomic:
            allowed.add(end)
            if any(character in ";；" for character in text[index:end]):
                strong.add(end)
        index = end
    return tuple(sorted(allowed)), tuple(sorted(strong))


def chinese_pause_boundaries(text: str) -> tuple[int, ...]:
    """Pause groups absorb alternating closers/punctuation/spaces in full.

    Latin/numeric internal full stops and numeric comma/colon separators are
    not pauses. A single hyphen is lexical; a repeated hyphen group is a pause.
    No lexicon, filesystem or Unicode database classification is consulted.
    """
    return _pause_groups(text)[0]


def hard_chinese_boundaries(text: str) -> tuple[int, ...]:
    return chinese_pause_boundaries(text)


def chinese_semicolon_boundaries(text: str) -> tuple[int, ...]:
    """Strong pauses use the same closure/offset convention as allowed cuts."""
    return _pause_groups(text)[1]


def chinese_boundaries(text: str, spans: tuple[tuple[int, int], ...]) -> ChineseBoundaries:
    """Validate a partition; lexical mistakes remain soft, never a hard veto."""
    cursor = 0
    lexical_cuts = set()
    if not isinstance(spans, (tuple, list)):
        raise ValueError("Chinese word spans must be an ordered partition")
    for span in spans:
        if (not isinstance(span, (tuple, list)) or len(span) != 2
                or any(type(value) is not int for value in span)):
            raise ValueError("Chinese word spans must contain integer start/end pairs")
        start, end = span
        if start != cursor or not start < end <= len(text):
            raise ValueError("Chinese word spans must exactly partition normalized text")
        lexical_cuts.update(range(start + 1, end))
        cursor = end
    if cursor != len(text):
        raise ValueError("Chinese word spans must exactly cover normalized text")
    for pattern in (_NUMBER_UNIT, _LATIN_NAME):
        for match in pattern.finditer(text):
            lexical_cuts.update(range(match.start() + 1, match.end()))
    for position in range(1, len(text)):
        if text[position - 1] in "（([【《「『“‘" or text[position] in "）)]】》」』”’，。、；：！？":
            lexical_cuts.add(position)
    return ChineseBoundaries(hard_chinese_boundaries(text), frozenset(lexical_cuts))
