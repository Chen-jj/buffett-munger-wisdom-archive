"""Versioned text counts and the single cue-end adjustment used by the planner."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache

from archive_core.interfaces.subtitle_text import (
    is_combining_mark,
    is_layout_whitespace,
)
from archive_core.interfaces.subtitles import (
    SubtitleProfileDTO,
    SubtitleRulesDTO,
    SubtitleTimingAdjustmentDTO,
)


PROFILE = SubtitleProfileDTO(
    {
        "name": "netflix-audio-gap.zh-priority.v3",
        "version": "v3",
        "algorithm_version": "bilingual-pause-dp.v3",
        "text_normalization_version": "fixed-layout-whitespace.v1",
        "character_count_version": "unicode14-latin-word.v2",
        "boundary_rules_version": "chinese-pause-closed.v3",
        "cost_rules_version": "d39-pause-rhythm-rational.v3",
        "english_capacity": 84,
        "english_line_capacity": 42,
        "english_max_lines": 2,
        "chinese_segmentation_engine": "jieba-0.42.1",
        "chinese_dictionary_sha256": "7197c3211ddd98962b036cdf40324d1ea2bfaa12bd028e68faa70111a88e12a8",
        "chinese_segmentation_mode": "default-hmm-false",
        "chinese_target_half_units": 32,
        "chinese_target_cps": 9,
        "english_reference_cps": 17,
        "minimum_duration_ms": 834,
        "target_duration_ms": 7000,
        "maximum_extension_ms": 500,
        "short_gap_upper_ms": 500,
        "cross_sentence_gap_upper_ms": 500,
        "pause_boundary_ms": 250,
    }
)

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


def rules_identity() -> SubtitleRulesDTO:
    parameters = PROFILE.parameters
    return SubtitleRulesDTO(
        profile_name=parameters["name"],
        profile_version=parameters["version"],
        profile_sha256=PROFILE.sha256,
        algorithm_version=parameters["algorithm_version"],
        text_normalization_version=parameters["text_normalization_version"],
        character_count_version=parameters["character_count_version"],
        boundary_rules_version=parameters["boundary_rules_version"],
        cost_rules_version=parameters["cost_rules_version"],
    )


@lru_cache(maxsize=4096)
def _zero_units(character: str) -> bool:
    return (
        is_layout_whitespace(character)
        or is_combining_mark(character)
        or character == "\u200d"
        or 0x1F3FB <= ord(character) <= 0x1F3FF
    )


def english_characters(text: str) -> int:
    """Count ordinary non-layout characters, never applying Chinese halfwidth."""
    if not isinstance(text, str):
        raise ValueError("text must be a string")
    return sum(not _zero_units(character) for character in text)


def wrap_english_text(text: str) -> str:
    """Return one/two deterministic lines, never splitting a whitespace word."""
    if not isinstance(text, str) or not text or " ".join(text.split()) != text:
        raise ValueError("English layout requires normalized logical text")
    return _wrap_normalized_english(text)


@lru_cache(maxsize=16384)
def _wrap_normalized_english(text: str) -> str:
    words = text.split(" ")
    counts = tuple(english_characters(word) for word in words)
    capacity = PROFILE.parameters["english_line_capacity"]
    if any(count > capacity for count in counts):
        raise ValueError("an indivisible English word exceeds line capacity")
    total = sum(counts)
    if total <= capacity:
        return text
    prefix = 0
    choices = []
    for position, count in enumerate(counts[:-1], 1):
        prefix += count
        if prefix <= capacity and total - prefix <= capacity:
            choices.append((abs(2 * prefix - total), position))
    if not choices:
        raise ValueError("English text cannot fit two word-boundary lines")
    _, position = min(choices)
    return " ".join(words[:position]) + "\n" + " ".join(words[position:])


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


def _integer(value: int, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def two_frame_gap_ms(fps_numerator: int, fps_denominator: int) -> int:
    """ceil(2000*q/p), retaining rational arithmetic for non-integer fps."""
    _integer(fps_numerator, "fps_numerator", 1)
    _integer(fps_denominator, "fps_denominator", 1)
    return (2000 * fps_denominator + fps_numerator - 1) // fps_numerator


@dataclass(frozen=True)
class TimingResult:
    end_ms: int
    timing_adjustment: SubtitleTimingAdjustmentDTO
    too_short: bool
    chinese_cps_excess: Fraction
    english_cps_excess: Fraction
    unclosed_gap: bool


def adjust_cue_timing(
    *,
    start_ms: int,
    base_end_ms: int,
    chinese_units: int,
    english_count: int,
    usable_duration_ms: int,
    gap_threshold_ms: int,
    next_start_ms: int | None,
) -> TimingResult:
    """Estimate and materialize one cue with the same one-pass timing formula.

    The next unconsumed word is the next speech/section/speaker boundary. No
    earlier boundary in its word gap is invented. CPS values remain exact
    rational diagnostics/readability targets, not DP costs or failure gates.
    """
    for name, value in (("start_ms", start_ms), ("base_end_ms", base_end_ms),
                        ("chinese_units", chinese_units), ("english_count", english_count),
                        ("usable_duration_ms", usable_duration_ms)):
        _integer(value, name)
    _integer(gap_threshold_ms, "gap_threshold_ms", 1)
    if next_start_ms is not None:
        _integer(next_start_ms, "next_start_ms")
    if base_end_ms <= start_ms or base_end_ms > usable_duration_ms:
        raise ValueError("source time range must be positive and within usable media")
    parameters = PROFILE.parameters
    base_duration = base_end_ms - start_ms
    raw_gap = None if next_start_ms is None else next_start_ms - base_end_ms
    if raw_gap is not None and raw_gap < 0:
        raise ValueError("source cue overlaps the next speech anchor")
    if raw_gap is None:
        gap_class = "last_cue"
    elif raw_gap >= parameters["short_gap_upper_ms"]:
        gap_class = "long_gap"
    elif raw_gap > gap_threshold_ms:
        gap_class = "short_gap"
    else:
        gap_class = "preserved_gap"

    # ceil(1000*(half_units/2)/9), without floats or successive budgets.
    target_cps = parameters["chinese_target_cps"]
    cps_duration = (500 * chinese_units + target_cps - 1) // target_cps
    required_duration = max(parameters["minimum_duration_ms"], cps_duration)
    read_extension = max(0, required_duration - base_duration)
    budget = min(
        parameters["maximum_extension_ms"],
        usable_duration_ms - base_end_ms,
    )
    if raw_gap is not None:
        budget = min(budget, max(0, raw_gap - gap_threshold_ms))
    gap_extension = raw_gap - gap_threshold_ms if gap_class == "short_gap" else 0
    extension = min(max(read_extension, gap_extension), budget)
    purposes = []
    if extension:
        if base_duration < parameters["minimum_duration_ms"]:
            purposes.append("minimum_duration")
        if 500 * chinese_units > target_cps * base_duration:
            purposes.append("chinese_cps")
        if gap_class == "short_gap":
            purposes.append("gap_closing")
    duration = base_duration + extension
    return TimingResult(
        end_ms=base_end_ms + extension,
        timing_adjustment=SubtitleTimingAdjustmentDTO(
            extension_ms=extension,
            purposes=tuple(purposes),
            original_gap_ms=raw_gap,
            original_gap_class=gap_class,
        ),
        too_short=duration < parameters["minimum_duration_ms"],
        chinese_cps_excess=max(Fraction(0), Fraction(500 * chinese_units, duration) - target_cps),
        english_cps_excess=max(Fraction(0), Fraction(1000 * english_count, duration) - parameters["english_reference_cps"]),
        unclosed_gap=gap_class == "short_gap" and extension < gap_extension,
    )
