from __future__ import annotations

import pytest

from srt_processing.domain.boundaries import (
    chinese_boundaries, chinese_pause_boundaries, chinese_semicolon_boundaries, hard_chinese_boundaries,
)
from srt_processing.domain.rules import chinese_half_units


@pytest.mark.parametrize("text", ["Coca-Cola", "See's", "O’Reilly", "cafe\u0301’s", "——", "……", "---"])
def test_latin_words_and_punctuation_groups_are_indivisible(text):
    assert hard_chinese_boundaries(text) == (0, len(text))


def test_latin_and_emoji_combining_sequences_do_not_expose_internal_offsets():
    text = "中cafe\u0301 👩🏽\u200d💻——末"
    boundaries = hard_chinese_boundaries(text)
    assert 2 not in boundaries and 5 not in boundaries
    emoji_start = text.index("👩")
    assert all(position not in boundaries for position in range(emoji_start + 1, emoji_start + 4))
    dash_start = text.index("—")
    assert dash_start + 1 not in boundaries


@pytest.mark.parametrize("text", ["五年", "十五年", "三百亿元", "十亿美元", "两千公斤", "35公里", "26%"])
def test_number_unit_quality_spans_remain_evidence_but_not_pause_boundaries(text):
    fake = tuple((index, index + 1) for index in range(len(text)))
    evidence = chinese_boundaries(text, fake)
    assert all(position in evidence.lexical_cuts for position in range(1, len(text)))
    assert evidence.allowed == (0, len(text))


def test_chinese_dictionary_error_or_long_word_is_only_soft_preference():
    text = "完全错误的超长合并词条，也不能删除标点断点"
    boundaries = chinese_boundaries(text, ((0, len(text)),))
    assert boundaries.allowed == (0, text.index("，") + 1, len(text))
    assert boundaries.lexical_cuts == frozenset(range(1, len(text)))


@pytest.mark.parametrize("spans", [None, ((1, 2),), ((0, 1),), ((0, 2), (1, 2)), ((False, 2),)])
def test_malformed_segmentation_evidence_is_not_silently_replaced(spans):
    with pytest.raises(ValueError):
        chinese_boundaries("中文", spans)


def test_final_chinese_fragment_concatenation_is_not_additive():
    assert chinese_half_units("foo-") + chinese_half_units("bar") == 5
    assert chinese_half_units("foo-bar") == 2
    assert chinese_half_units("a") + chinese_half_units("b") == 4
    assert chinese_half_units("ab") == 2


@pytest.mark.parametrize(("text", "pieces"), [
    ("甲，乙、丙；丁：戊。己！庚？辛", ["甲，", "乙、", "丙；", "丁：", "戊。", "己！", "庚？", "辛"]),
    ("他说：“甲，\"） 乙”。丙", ["他说：", "“甲，\"） ", "乙”。", "丙"]),
    ("Coca-Cola，See's……然后——结束", ["Coca-Cola，", "See's……", "然后——", "结束"]),
    ("数值0.5和U.S.词，cafe\u0301’s。", ["数值0.5和U.S.", "词，", "cafe\u0301’s。"]),
    ("前--后-词", ["前--", "后-词"]),
    ("甲说“第一；”，然后继续。", ["甲说“第一；”，", "然后继续。"]),
    ("先……”，再说；” ） ，最后。", ["先……”，", "再说；” ） ，", "最后。"]),
    ("1,000元和12:30，结束。", ["1,000元和12:30，", "结束。"]),
])
def test_pause_groups_closers_and_spaces_are_consumed_as_single_boundaries(text, pieces):
    expected = [0]
    for piece in pieces:
        expected.append(expected[-1] + len(piece))
    assert chinese_pause_boundaries(text) == tuple(expected)


def test_semicolon_uses_same_closed_boundary_as_other_pauses():
    text = "甲；”） 乙，丙;丁"
    assert chinese_semicolon_boundaries(text) == (len("甲；”） "), len("甲；”） 乙，丙;"))
    mixed = "甲说“第一；”，然后继续。"
    assert chinese_semicolon_boundaries(mixed) == (len("甲说“第一；”，"),)
