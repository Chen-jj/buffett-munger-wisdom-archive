"""Pure visual layout with fake pixel measurement and complete grapheme segmentation."""

from dataclasses import replace
from pathlib import Path

import pytest
import regex
import yaml

from archive_core.interfaces import (
    RenderBoundsDTO, RenderLineMetricsDTO, RenderProfileDTO,
)
from subtitle_rendering.domain import layout
from subtitle_rendering.domain.layout import (
    NUMERIC_UNIT_RULES_VERSION, NUMERIC_UNITS, UNICODE_CLASSIFICATION_VERSION, build_render_plan,
    candidate_break_offsets, choose_visual_layout, layout_cue, protected_spans,
    round_half_up_scaled, scale_profile,
)
from subtitle_rendering.domain.models import LayoutError, profile_from_config
from subtitle_rendering.domain.validation import validate_render_plan
from tests.archive_core.test_rendering_contracts import render_plan as contract_plan
from tests.archive_core.test_subtitle_contracts import plan as source_plan


class Segments:
    version = "unicode-grapheme.regex-2026.7.19.v1"

    def boundaries(self, text):
        return (0, *(match.end() for match in regex.finditer(r"\X", text)))


class Measurer:
    def __init__(self, unit=10, line_height=None):
        self.unit = unit
        self.line_height = line_height
        self.calls = []

    def measure(self, text, font_size, outline_width, shadow):
        self.calls.append((text, font_size, outline_width, shadow))
        width = len(text) * self.unit + 2 * outline_width + shadow
        return RenderLineMetricsDTO(width, self.line_height or font_size + 2 * outline_width + shadow)


def choose(text, language="chinese", width=70, measurer=None):
    return choose_visual_layout(text, language, 30, 2, 1, width, measurer or Measurer(), Segments())


def plan(measurer=None):
    base = contract_plan()
    return build_render_plan(
        asset_id=base.asset_id, inputs=base.inputs, input_media=base.input_media,
        source_plan=source_plan(), profile=base.profile,
        font=replace(base.font, measurement_adapter_version=base.font.measurement_adapter_version + ";" + Segments.version + ";" + UNICODE_CLASSIFICATION_VERSION),
        tools=base.tools, measurer=measurer or Measurer(), segmenter=Segments(),
    )


@pytest.mark.parametrize(("base", "pixels", "reference", "expected"), (
    (1, 1, 2, 1), (1, 5, 2, 3), (1, 3, 2, 2), (2, 1, 4, 1),
    (30, 360, 360, 30), (30, 1080, 360, 90), (1, 359, 360, 1),
    (0, 360, 360, 0), (10**25, 360, 360, 10**25),
))
def test_scaling_is_exact_integer_half_up(base, pixels, reference, expected):
    assert round_half_up_scaled(base, pixels, reference) == expected


@pytest.mark.parametrize("args", ((True, 1, 1), (1, False, 1), (1, 1, True), (1.0, 1, 1), (-1, 1, 1), (1, 0, 1)))
def test_scaling_rejects_invalid_or_bool_values(args):
    with pytest.raises(ValueError):
        round_half_up_scaled(*args)


@pytest.mark.parametrize(("width", "height", "values", "bounds"), (
    (640, 360, (32, 42, 160, 30, 20, 2, 1), (32, 158, 608, 318)),
    (1280, 720, (64, 84, 320, 60, 40, 4, 2), (64, 316, 1216, 636)),
    (1920, 1080, (96, 126, 480, 90, 60, 6, 3), (96, 474, 1824, 954)),
    (320, 180, (16, 21, 80, 15, 10, 1, 1), (16, 79, 304, 159)),
))
def test_scaled_profile_uses_real_resolution_and_safe_rectangle(width, height, values, bounds):
    style, safe = scale_profile(RenderProfileDTO(), width, height)
    assert (style.horizontal_margin, style.vertical_margin, style.maximum_subtitle_height,
            style.chinese_font_size, style.english_font_size, style.outline_width, style.shadow) == values
    assert safe == RenderBoundsDTO(*bounds)
    assert style.play_res_x == width and style.play_res_y == height


def test_tiny_resolution_fails_without_shrinking_fonts_to_zero():
    with pytest.raises(LayoutError, match="safe area"):
        scale_profile(RenderProfileDTO(), 2, 1)


@pytest.mark.parametrize("token", (
    "A\u0301", "👩\u200d💻", "✈\ufe0f", "🇨🇳", "👍🏽", "👨\u200d👩\u200d👧\u200d👦", "क्\u200dष", "각",
))
def test_complete_unicode_graphemes_are_not_split(token):
    text = "甲" + token + "乙"
    assert regex.fullmatch(r"\X", token) is not None
    assert candidate_break_offsets(text, "chinese", Segments()) == (1, len(text) - 1)


@pytest.mark.parametrize("token", (
    "Buffett", "Munger", "O'Reilly", "O’Reilly", "Coca-Cola", "non‑executive", "Berkshire",
    "Café", "A\u0301BC", "U.S.A", "A123", "ＡＢＣ",
))
def test_latin_words_apostrophes_hyphens_and_accents_are_protected(token):
    text = "甲" + token + "乙"
    offsets = candidate_break_offsets(text, "chinese", Segments())
    assert 1 in offsets and len(text) - 1 in offsets
    assert not any(1 < offset < len(text) - 1 for offset in offsets)


@pytest.mark.parametrize("token", (
    "12,345.67", "9:30", "2026-10-24", "1/2", "$1,234.50", "￥１２３．４５", "−3.5%",
    "3.5亿美元", "20个百分点", "10km/h", "10kg/m²", "36°C", "3小时", "5千克", "2平方米",
    "2026年", "24日", "10bps", "15μm", "3.2‰", "5万", "1,234公斤", "-$1.50", "+￥123", "1.2e-3kg",
))
def test_numeric_separators_and_tight_recognized_units_are_not_split(token):
    text = "甲" + token + "乙"
    offsets = candidate_break_offsets(text, "chinese", Segments())
    assert not any(1 < offset < len(text) - 1 for offset in offsets), (token, offsets, protected_spans(text))


def test_numeric_units_table_has_frozen_version_and_common_multi_character_units():
    assert NUMERIC_UNIT_RULES_VERSION == "numeric-units.v1"
    assert {"美元", "人民币", "平方公里", "平方米", "千克", "毫秒", "百分点", "摄氏度"} <= set(NUMERIC_UNITS)
    assert RenderProfileDTO().layout_version == "pixel-wrap.v1"


@pytest.mark.parametrize("unit", NUMERIC_UNITS)
def test_every_frozen_multi_or_single_character_unit_is_preserved(unit):
    text = "甲10" + unit + "乙"
    assert not any(1 < offset < len(text) - 1 for offset in candidate_break_offsets(text, "chinese", Segments()))


def test_fixed_unit_recognition_does_not_claim_arbitrary_chinese_semantics():
    offsets = candidate_break_offsets("3米长的桌子", "chinese", Segments())
    assert 1 not in offsets
    assert 2 in offsets  # Unit 米 is protected; the following prose remains available.


def test_english_breaks_only_at_existing_whitespace_and_keeps_it_in_raw_slices():
    text = "Coca-Cola isn't small."
    offsets = candidate_break_offsets(text, "english", Segments())
    assert offsets == (10, 16)
    result = choose_visual_layout(text, "english", 20, 2, 1, 165, Measurer(), Segments())
    pieces = (text[:result.break_offsets[0]], text[result.break_offsets[0]:])
    assert "".join(pieces) == text
    assert pieces[0].endswith(" ")
    assert all(offset in offsets for offset in result.break_offsets)


@pytest.mark.parametrize("text", ("Supercalifragilisticexpialidocious", "Very-long-unsplittable-word"))
def test_english_long_word_never_gets_split_or_hyphenated(text):
    with pytest.raises(LayoutError, match="two visual lines"):
        choose(text, "english", width=70)


def test_strong_boundary_can_win_even_when_single_line_fits():
    assert choose("甲乙。丙丁", width=100).break_offsets == (3,)
    assert choose("one. two", "english", width=100).break_offsets == (5,)


def test_no_break_has_zero_penalty_so_weak_or_ordinary_break_does_not_win_needlessly():
    assert choose("甲乙，丙丁", width=100).break_offsets == ()
    assert choose("甲乙丙丁", width=100).break_offsets == ()
    assert choose("one two", "english", width=100).break_offsets == ()


def test_boundary_priority_precedes_width_optimization():
    text = "甲乙。丙丁戊己庚辛"
    assert choose(text, width=80).break_offsets == (3,)
    # A more balanced ordinary split cannot outrank an available strong boundary.


@pytest.mark.parametrize("text", ("甲乙）丙丁", "甲乙，丙丁", "甲（乙丙丁", "甲【乙丙丁"))
def test_chosen_lines_never_start_with_closing_or_end_with_opening_punctuation(text):
    result = choose(text, width=45)
    boundaries = (0, *result.break_offsets, len(text))
    pieces = tuple(text[start:end] for start, end in zip(boundaries, boundaries[1:]))
    assert layout._punctuation_problem_count(pieces) == 0
    assert "".join(pieces) == text


@pytest.mark.parametrize("text", ("）甲乙", "甲乙（"))
def test_impossible_original_edge_punctuation_is_controlled_failure(text):
    with pytest.raises(LayoutError):
        choose(text, width=1000)


@pytest.mark.parametrize(("chinese", "english", "chinese_lines", "english_lines"), (
    ("短句", "one", 1, 1), ("甲乙丙丁戊己庚辛", "one", 2, 1),
    ("短句", "one two", 1, 2), ("甲乙丙丁戊己庚辛", "one two", 2, 2),
))
def test_one_or_two_per_language_produces_two_to_four_bilingual_lines(chinese, english, chinese_lines, english_lines):
    style, safe = scale_profile(replace(RenderProfileDTO(), horizontal_margin=285), 640, 360)
    source = replace(source_plan().cues[0], chinese_text=chinese, english_text=english)
    measurer = Measurer()
    cue = layout_cue(source, style, safe, measurer, Segments())
    assert len(cue.chinese_lines) == chinese_lines
    assert len(cue.english_lines) == english_lines
    assert len(cue.chinese_lines) + len(cue.english_lines) <= 4
    assert safe.contains(cue.expected_bounds)
    actual_chinese, actual_english = cue.visual_lines(source)
    assert "".join(actual_chinese) == chinese and "".join(actual_english) == english
    assert cue.start_ms == source.start_ms and cue.end_ms == source.end_ms
    assert {call[1] for call in measurer.calls} == {20, 30}
    assert {call[2:] for call in measurer.calls} == {(2, 1)}


def test_cannot_fit_two_chinese_lines_without_changing_text_or_font():
    with pytest.raises(LayoutError, match="two visual lines"):
        choose("甲" * 20, width=70)


def test_independently_selected_language_lines_must_fit_total_height():
    style, safe = scale_profile(replace(RenderProfileDTO(), horizontal_margin=285), 640, 360)
    source = replace(source_plan().cues[0], chinese_text="甲乙丙丁戊己庚辛", english_text="one two")
    with pytest.raises(LayoutError, match="safe height"):
        layout_cue(source, style, safe, Measurer(line_height=50), Segments())


def test_candidate_enumeration_order_cannot_change_chosen_result(monkeypatch):
    expected = choose("甲乙丙丁戊己庚辛", width=70)
    assert expected.break_offsets == (4,)
    original = layout.candidate_break_offsets
    monkeypatch.setattr(layout, "candidate_break_offsets", lambda *args: tuple(reversed(original(*args))))
    assert choose("甲乙丙丁戊己庚辛", width=70) == expected


def test_ordinary_legal_paths_use_width_balance_before_offset_tie_break():
    text = "甲乙丙丁戊己庚辛"
    class BalancedMeasurer:
        def measure(self, line, font_size, outline_width, shadow):
            widths = {text[:3]: 60, text[3:]: 40, text[:5]: 60, text[5:]: 55}
            return RenderLineMetricsDTO(widths.get(line, 100), 30)
    assert choose(text, width=70, measurer=BalancedMeasurer()).break_offsets == (5,)


def test_equal_ordinary_paths_use_complete_offset_tuple_as_last_tie_break():
    text = "甲乙丙丁戊己庚辛"
    class TiedMeasurer:
        def measure(self, line, font_size, outline_width, shadow):
            widths = {text[:3]: 60, text[3:]: 40, text[:5]: 60, text[5:]: 40}
            return RenderLineMetricsDTO(widths.get(line, 100), 30)
    assert choose(text, width=70, measurer=TiedMeasurer()).break_offsets == (3,)


def test_full_offset_tuple_is_last_deterministic_tie_break(monkeypatch):
    class TiedMeasurer:
        def measure(self, text, font_size, outline_width, shadow):
            return RenderLineMetricsDTO(100 if text == "甲。乙。丙" else 10, 30)
    expected = choose("甲。乙。丙", width=50, measurer=TiedMeasurer())
    assert expected.break_offsets == (2,)
    original = layout.candidate_break_offsets
    monkeypatch.setattr(layout, "candidate_break_offsets", lambda *args: tuple(reversed(original(*args))))
    assert choose("甲。乙。丙", width=50, measurer=TiedMeasurer()) == expected


def test_layout_plan_is_deterministic_source_preserving_and_read_only():
    first, second = plan(), plan()
    assert first == second
    assert first.to_dict() == second.to_dict()
    first.validate_against_subtitle_plan(source_plan())
    validate_render_plan(first, source_plan(), Measurer(), Segments())
    assert len(first.cues) == 2
    assert first.cues[0].end_ms == 1216
    assert first.cues[0].ass_end_ms == 1220


def test_recomputed_layout_qa_detects_resigned_measurement_or_break_tampering():
    original = plan()
    first = original.cues[0]
    corrupt = replace(original, cues=(replace(first, chinese_lines=(RenderLineMetricsDTO(first.chinese_lines[0].width + 1,
                                                                                       first.chinese_lines[0].height),)),
                                     original.cues[1]))
    with pytest.raises(LayoutError, match="deterministic"):
        validate_render_plan(corrupt, source_plan(), Measurer(), Segments())


def test_grapheme_engine_version_must_be_bound_to_font_identity():
    base = contract_plan()
    with pytest.raises(ValueError, match="bind"):
        build_render_plan(asset_id=base.asset_id, inputs=base.inputs, input_media=base.input_media,
                          source_plan=source_plan(), profile=base.profile, font=base.font,
                          tools=base.tools, measurer=Measurer(), segmenter=Segments())


def test_runtime_unicode_classification_is_independently_bound_and_version_change_rejects_reuse(monkeypatch):
    original = plan()
    assert UNICODE_CLASSIFICATION_VERSION in original.font.measurement_adapter_version.split(";")
    missing = replace(original.font, measurement_adapter_version=original.font.measurement_adapter_version.replace(";" + UNICODE_CLASSIFICATION_VERSION, ""))
    with pytest.raises(ValueError, match="Unicode classification"):
        build_render_plan(asset_id=original.asset_id, inputs=original.inputs, input_media=original.input_media,
                          source_plan=source_plan(), profile=original.profile, font=missing,
                          tools=original.tools, measurer=Measurer(), segmenter=Segments())
    monkeypatch.setattr(layout, "UNICODE_CLASSIFICATION_VERSION", "unicode-classification-99.0.0")
    with pytest.raises(ValueError, match="Unicode classification"):
        validate_render_plan(original, source_plan(), Measurer(), Segments())


def test_identity_tokens_cannot_be_forged_by_a_substring():
    original = plan()
    misleading = replace(original.font, measurement_adapter_version=original.font.measurement_adapter_version.replace(";" + UNICODE_CLASSIFICATION_VERSION, ";not-" + UNICODE_CLASSIFICATION_VERSION))
    with pytest.raises(ValueError, match="Unicode classification"):
        build_render_plan(asset_id=original.asset_id, inputs=original.inputs, input_media=original.input_media,
                          source_plan=source_plan(), profile=original.profile, font=misleading,
                          tools=original.tools, measurer=Measurer(), segmenter=Segments())


@pytest.mark.parametrize("boundaries", ((0, True, 4), (0, 4, 3), (1, 4), (0, 3), [0, 4]))
def test_injected_segmenter_must_return_strict_complete_boundary_tuple(boundaries):
    class InvalidSegments:
        version = "bad.v1"
        def boundaries(self, text):
            return boundaries
    with pytest.raises(ValueError, match="boundar"):
        choose_visual_layout("甲乙丙丁", "chinese", 30, 2, 1, 100, Measurer(), InvalidSegments())


def test_invalid_measurement_adapter_result_is_controlled_failure():
    class InvalidMeasurer:
        def measure(self, *args):
            return {"width": 10, "height": 20}
    with pytest.raises(LayoutError, match="invalid line metrics"):
        choose("甲乙丙丁", measurer=InvalidMeasurer())


@pytest.mark.parametrize("width", (True, 0, -1, float("nan"), float("inf")))
def test_visual_layout_does_not_accept_an_unusable_safe_width(width):
    with pytest.raises(ValueError, match="safe_width"):
        choose("甲乙", width=width)


def test_config_replaces_only_old_unconsumed_rendering_blocks_and_matches_default_profile():
    root = Path(__file__).resolve().parents[2]
    data = yaml.safe_load((root / "config.yaml").read_text())
    assert not {"subtitle_style", "bilingual", "ffmpeg"} & set(data)
    assert {"translation", "download", "whisperx", "crawl"} <= set(data)
    assert profile_from_config(data["subtitle_rendering"]) == RenderProfileDTO()
    assert "regex==2026.7.19" in (root / "requirements.txt").read_text().splitlines()


@pytest.mark.parametrize("change", (
    lambda d: d.pop("font"), lambda d: d.update(name="hidden"), lambda d: d.update(version="v2"),
    lambda d: d.update(unknown=True), lambda d: d["font"].update(unknown=True),
    lambda d: d.update(horizontal_margin=True),
))
def test_profile_config_rejects_legacy_unknown_missing_and_untyped_fields(change):
    data = RenderProfileDTO().to_dict()
    data["profile"] = data.pop("name")
    data.pop("version")
    data.pop("layout_version")
    change(data)
    with pytest.raises(ValueError):
        profile_from_config(data)
