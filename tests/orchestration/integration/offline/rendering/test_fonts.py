"""Exact font gates use byte/table/measurement fakes, never system fonts."""

from dataclasses import replace
import hashlib
from types import SimpleNamespace

import pytest

from archive_core.interfaces import RenderFontSpecDTO, RenderLineMetricsDTO
from subtitle_rendering.domain.layout import UNICODE_CLASSIFICATION_VERSION
from subtitle_rendering.infrastructure import fonts
from subtitle_rendering.infrastructure.fonts import (
    ExactFontAdapter, FontValidationError, RegexGraphemeSegmenter, validate_libass_font_selection,
)


DATA = b"ttcf-test-font-bytes"


@pytest.mark.parametrize("token", ("A\u0301", "👩\u200d💻", "✈\ufe0f", "🇨🇳", "👍🏽", "क्\u200dष", "각"))
def test_regex_adapter_emits_complete_grapheme_boundaries(token):
    assert RegexGraphemeSegmenter().boundaries("甲" + token + "乙") == (0, 1, len(token) + 1, len(token) + 2)
    assert RegexGraphemeSegmenter().boundaries("") == (0,)




def test_pinned_chinese_lexical_dictionary_preserves_common_compound_boundaries():
    segmenter = RegexGraphemeSegmenter()
    text = "公司持有的有价证券价值一直超过其净资产。"
    boundaries = segmenter.lexical_boundaries(text)
    assert boundaries == (0, 2, 4, 5, 9, 11, 13, 15, 16, 19, 20)
    assert 10 not in boundaries  # 价/值 is not a word break.
    assert 17 not in boundaries and 18 not in boundaries  # 净资产 stays intact.
    assert segmenter.lexical_boundaries("") == (0,)
    assert "jieba-0.42.1-HMMFalse-7197c321" in segmenter.version



def test_s47_visual_wrap_prefers_value_word_over_equal_character_halves():
    from subtitle_rendering.domain.layout import choose_visual_layout
    from tests.support.render_layout import Measurer
    text = "公司持有的有价证券价值一直超过其净资产。"
    result = choose_visual_layout(text, "chinese", 30, 2, 1, 115, Measurer(), RegexGraphemeSegmenter())
    assert result.break_offsets in ((9,), (11,))
    assert result.break_offsets != (10,)
    offset, = result.break_offsets
    assert text[:offset] + text[offset:] == text
