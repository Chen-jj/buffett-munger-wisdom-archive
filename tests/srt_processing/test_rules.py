from __future__ import annotations

from fractions import Fraction
import hashlib
import json

import pytest

from archive_core.interfaces.subtitle_text import character_boundaries, normalize_chinese_text
from archive_core.interfaces.subtitles import SubtitleProfileDTO
from srt_processing.domain.rules import (
    PROFILE,
    adjust_cue_timing,
    chinese_half_units,
    english_characters,
    rules_identity,
    two_frame_gap_ms, wrap_english_text,
)


def timing(**changes):
    values = dict(start_ms=1000, base_end_ms=2000, chinese_units=8,
                  english_count=10, usable_duration_ms=10000,
                  gap_threshold_ms=84, next_start_ms=2800)
    values.update(changes)
    return adjust_cue_timing(**values)


def test_profile_is_fixed_complete_and_hashes_sorted_utf8_json():
    expected = {
        "name": "netflix-audio-gap.zh-priority.v3", "version": "v3",
        "algorithm_version": "bilingual-pause-dp.v3",
        "text_normalization_version": "fixed-layout-whitespace.v1",
        "character_count_version": "unicode14-latin-word.v2",
        "boundary_rules_version": "chinese-pause-closed.v3",
        "cost_rules_version": "d39-pause-rhythm-rational.v3",
        "english_capacity": 84, "chinese_target_half_units": 32,
        "english_line_capacity": 42, "english_max_lines": 2,
        "chinese_segmentation_engine": "jieba-0.42.1",
        "chinese_dictionary_sha256": "7197c3211ddd98962b036cdf40324d1ea2bfaa12bd028e68faa70111a88e12a8",
        "chinese_segmentation_mode": "default-hmm-false",
        "chinese_target_cps": 9, "english_reference_cps": 17,
        "minimum_duration_ms": 834, "target_duration_ms": 7000,
        "maximum_extension_ms": 500, "short_gap_upper_ms": 500,
        "cross_sentence_gap_upper_ms": 500, "pause_boundary_ms": 250,
    }
    assert PROFILE.to_dict() == expected
    payload = json.dumps(expected, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert PROFILE.sha256 == hashlib.sha256(payload.encode("utf-8")).hexdigest()
    assert SubtitleProfileDTO(dict(reversed(tuple(expected.items())))).sha256 == PROFILE.sha256
    assert rules_identity().profile_sha256 == PROFILE.sha256
    with pytest.raises(TypeError):
        PROFILE.parameters["english_capacity"] = 99


@pytest.mark.parametrize(("text", "chinese", "english"), [
    ("中文。", 6, 3), ("A 1,%", 5, 4), ("Ａ１，", 6, 3),
    ("café", 2, 4), ("cafe\u0301", 2, 4), ("\U00020000", 2, 1),
    ("\u0661\u0662", 2, 2), ("ｶﾀｶﾅ", 4, 4), ("\u03a9", 2, 1),
    ("👩🏽\u200d💻", 4, 2), ("✈️", 2, 1), ("\U0010ffff", 2, 1),
    ("\t\n\u00a0\u3000", 0, 0), ("\uffbf", 2, 1), ("", 0, 0),
])
def test_fixed_counts_and_independent_english_capacity(text, chinese, english):
    assert chinese_half_units(text) == chinese
    assert english_characters(text) == english


def test_layout_normalization_and_combining_boundaries_preserve_text():
    assert normalize_chinese_text("\t 中\n  文\u3000cafe\u0301 \r") == "中 文 cafe\u0301"
    text = "中e\u0301👩🏽\u200d💻。"
    assert character_boundaries(text) == (0, 1, 3, 7, 8)
    assert chinese_half_units("x" * 32) == 2
    assert english_characters("x" * 42) == 42


@pytest.mark.parametrize(("p", "q", "expected"), [
    (24, 1, 84), (24000, 1001, 84), (30000, 1001, 67), (25, 1, 80),
    (48, 2, 84), (1, 1, 2000),
])
def test_two_frame_threshold_is_exact_ceiling(p, q, expected):
    assert two_frame_gap_ms(p, q) == expected


@pytest.mark.parametrize(("p", "q"), [(0, 1), (24, 0), (-1, 1), (True, 1), (24, 1.0)])
def test_invalid_frame_rate_is_not_guessed(p, q):
    with pytest.raises(ValueError):
        two_frame_gap_ms(p, q)


def test_long_gap_without_reading_need_is_unchanged():
    result = timing()
    assert result.end_ms == 2000
    assert result.timing_adjustment.original_gap_class == "long_gap"
    assert not result.unclosed_gap


def test_long_gap_reading_extension_keeps_remaining_300_without_second_pass():
    result = timing(chinese_units=32)
    assert result.end_ms == 2500
    assert result.timing_adjustment.extension_ms == 500
    assert result.timing_adjustment.original_gap_ms == 800
    assert result.timing_adjustment.purposes == ("chinese_cps",)
    assert result.chinese_cps_excess == Fraction(5, 3)
    assert not result.unclosed_gap


def test_short_gap_closes_to_two_frames_even_without_reading_need():
    result = timing(next_start_ms=2300)
    assert result.end_ms == 2216
    assert result.timing_adjustment.purposes == ("gap_closing",)
    assert not result.unclosed_gap


def test_short_gap_can_extend_beyond_seven_second_reporting_target():
    result = timing(start_ms=1000, base_end_ms=7900, next_start_ms=8200)
    assert result.end_ms == 8116
    assert not result.unclosed_gap


@pytest.mark.parametrize("gap", [0, 40, 84])
def test_existing_zero_to_two_frame_gap_is_preserved_even_if_too_short(gap):
    result = timing(base_end_ms=1200, next_start_ms=1200 + gap, chinese_units=32)
    assert result.end_ms == 1200
    assert result.too_short
    assert result.timing_adjustment.original_gap_class == "preserved_gap"
    assert result.timing_adjustment.purposes == ()
    assert not result.unclosed_gap


def test_negative_gap_is_a_hard_error_not_beautification():
    with pytest.raises(ValueError, match="overlaps"):
        timing(next_start_ms=1999)


def test_all_readability_and_gap_purposes_share_one_budget_and_one_maximum():
    result = timing(base_end_ms=1200, next_start_ms=1600, chinese_units=12)
    assert result.end_ms == 1516
    assert result.timing_adjustment.extension_ms == 316
    assert result.timing_adjustment.purposes == ("minimum_duration", "chinese_cps", "gap_closing")
    assert result.too_short
    assert not result.unclosed_gap
    assert result.end_ms <= 1200 + 500


def test_reading_and_gap_demands_use_max_not_sum():
    result = timing(base_end_ms=1700, next_start_ms=2000, chinese_units=14)
    assert result.end_ms == 1916  # max(134, 78, 216), not their sum.
    assert result.timing_adjustment.purposes == ("minimum_duration", "chinese_cps", "gap_closing")


def test_last_cue_has_same_budget_and_media_limit():
    result = timing(base_end_ms=1200, next_start_ms=None, usable_duration_ms=1400, chinese_units=32)
    assert result.end_ms == 1400
    assert result.timing_adjustment.original_gap_ms is None
    assert result.timing_adjustment.original_gap_class == "last_cue"
    assert result.too_short
    assert result.chinese_cps_excess == 31
    assert not result.unclosed_gap


def test_last_cue_extension_is_not_an_extra_500_per_purpose():
    result = timing(base_end_ms=1200, next_start_ms=None, chinese_units=32)
    assert result.end_ms == 1700
    assert result.timing_adjustment.extension_ms == 500
    assert result.too_short


def test_minimum_duration_and_chinese_cps_ceiling_are_integer_precise():
    result = timing(base_end_ms=1800, next_start_ms=None, chinese_units=15)
    assert result.end_ms == 1834
    assert not result.too_short
    assert result.chinese_cps_excess == 0
    result = timing(base_end_ms=2000, next_start_ms=None, chinese_units=19)
    assert result.end_ms == 2056  # ceil(9500/9), not truncation.
    assert result.chinese_cps_excess == 0


def test_english_cps_is_only_reported_never_used_for_extension():
    result = timing(english_count=42)
    assert result.end_ms == 2000
    assert result.english_cps_excess == 25
    assert result.chinese_cps_excess == 0


def test_cps_has_no_hidden_hard_limit_and_is_fraction_not_float():
    result = timing(start_ms=0, base_end_ms=1, next_start_ms=1, chinese_units=32, english_count=42)
    assert result.chinese_cps_excess == Fraction(15991)
    assert result.english_cps_excess == Fraction(41983)
    assert result.too_short


@pytest.mark.parametrize("changes", [
    {"start_ms": -1}, {"start_ms": True}, {"base_end_ms": 1000},
    {"base_end_ms": 10001}, {"next_start_ms": -1},
    {"gap_threshold_ms": 0}, {"chinese_units": 1.5}, {"english_count": -1},
])
def test_invalid_hard_timeline_inputs_fail(changes):
    with pytest.raises(ValueError):
        timing(**changes)


def test_exactly_seven_seconds_has_no_special_extension_cap():
    result = timing(base_end_ms=8000, next_start_ms=8300)
    assert result.end_ms == 8216
    assert not result.unclosed_gap


@pytest.mark.parametrize("duration", [7001, 10001, 25000, 100000])
def test_no_hidden_source_duration_cap_replaces_the_reporting_target(duration):
    result = timing(start_ms=0, base_end_ms=duration, next_start_ms=None,
                    usable_duration_ms=duration + 500)
    assert result.end_ms == duration


def test_same_function_is_deterministic_for_estimate_and_materialization():
    inputs = dict(chinese_units=31, base_end_ms=1400, next_start_ms=2200)
    assert timing(**inputs) == timing(**inputs)


@pytest.mark.parametrize(("text", "units"), [
    ("Berkshire Hathaway", 4), ("Coca-Cola", 2), ("See's", 2), ("See’s", 2),
    ("Coca-Cola，26%。", 9), ("a-b-c", 2), ("A--B", 6), ("a'", 3),
    ("a1b", 5), ("cafe\u0301’s", 2), ("foo-", 3), ("foo-bar", 2),
])
def test_chinese_counts_complete_latin_words_without_changing_other_punctuation(text, units):
    assert chinese_half_units(text) == units


def test_english_two_line_layout_is_not_only_a_total_84_character_test():
    assert wrap_english_text("a" * 42) == "a" * 42
    assert wrap_english_text("a" * 42 + " " + "b" * 42) == "a" * 42 + "\n" + "b" * 42
    with pytest.raises(ValueError, match="two word-boundary"):
        wrap_english_text("a" * 30 + " " + "b" * 30 + " " + "c" * 20)
    with pytest.raises(ValueError, match="indivisible"):
        wrap_english_text("a" * 43)
    with pytest.raises(ValueError, match="normalized"):
        wrap_english_text("already\nwrapped")


def test_english_wrap_is_deterministic_and_preserves_all_words():
    text = " ".join(["word"] * 20)
    wrapped = wrap_english_text(text)
    assert wrapped == wrap_english_text(text)
    assert wrapped.replace("\n", " ") == text
    assert len(wrapped.splitlines()) == 2
    assert all(english_characters(line) <= 42 for line in wrapped.splitlines())
