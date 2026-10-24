"""Deterministic visual-only line breaking; no filesystem or rendering libraries."""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from typing import Mapping

from archive_core.interfaces import (
    RenderArtifactEvidenceDTO, RenderBoundsDTO, RenderCueDTO, RenderFontIdentityDTO,
    RenderLineMetricsDTO, RenderMediaDTO, RenderProfileDTO, RenderScaledStyleDTO,
    RenderToolsDTO, SubtitleCueDTO, SubtitlePlanDTO, SubtitleRenderPlanDTO,
    project_ass_time_ms,
)

from .models import FontMeasurer, GraphemeSegmenter, LayoutError, VisualLayout


# These tables are frozen semantic content of profile layout_version=pixel-wrap.v1.
# Runtime Unicode name/category/decimal classification is separately identity-bound.
NUMERIC_UNIT_RULES_VERSION = "numeric-units.v1"
UNICODE_CLASSIFICATION_VERSION = f"unicode-classification-{unicodedata.unidata_version}"
NUMERIC_UNITS = (
    "人民币", "美元", "美分", "欧元", "英镑", "港元", "日元", "元", "角", "分",
    "平方公里", "平方米", "平方厘米", "平方毫米", "立方米", "立方厘米", "公里", "千米",
    "厘米", "毫米", "米", "英里", "英尺", "英寸", "千克", "公斤", "毫克", "克", "吨",
    "毫升", "升", "摄氏度", "华氏度", "度", "年", "个月", "月", "星期", "周", "天",
    "小时", "分钟", "毫秒", "秒", "日", "岁", "倍", "基点", "个百分点", "百分点", "个", "人", "家",
    "次", "股", "手", "台", "件", "本", "项", "笔", "点", "℃", "℉", "°", "%", "％", "‰", "‱",
)
_STRONG_PUNCTUATION = frozenset("。！？!?；;.")
_WEAK_PUNCTUATION = frozenset("，、,:：")
_OPENING_PUNCTUATION = frozenset("（([［{｛〈《「『【〔〖〘〚“‘«‹")
_CLOSING_PUNCTUATION = frozenset("）)]］}｝〉》」』】〕〗〙〛”’»›，。．、；：！？,.!?;:%％‰‱…")
_LATIN_JOINERS = frozenset("'’ʼ-‐‑.")
_NUMBER_RE = re.compile(r"[+＋\-−－]?[¥￥$€£₩₹₽]?[+＋\-−－]?\d+(?:[.,:．，：/／\-－]\d+)*(?:[eE][+＋\-−－]?\d+)?")
_UNIT_NAMES = "|".join(re.escape(unit) for unit in sorted(NUMERIC_UNITS, key=lambda item: (-len(item), item)))
_UNIT_RE = re.compile(r"(?:" + _UNIT_NAMES + r"|[十百千万亿兆]+(?:" + _UNIT_NAMES + r")?)")
_LATIN_UNIT_RE = re.compile(r"[A-Za-zµμΩ]+(?:[/*·^²³0-9°][A-Za-zµμΩ0-9²³]*)*")


def round_half_up_scaled(base: int, pixels: int, reference: int) -> int:
    for value, name, minimum in ((base, "base", 0), (pixels, "pixels", 1), (reference, "reference", 1)):
        if type(value) is not int or value < minimum:
            raise ValueError(f"{name} must be an integer >= {minimum}")
    return (2 * base * pixels + reference) // (2 * reference)


def scale_profile(profile: RenderProfileDTO, width: int, height: int) -> tuple[RenderScaledStyleDTO, RenderBoundsDTO]:
    if not isinstance(profile, RenderProfileDTO):
        raise ValueError("profile must be a RenderProfileDTO")
    horizontal = lambda value: round_half_up_scaled(value, width, profile.reference_width)
    vertical = lambda value: round_half_up_scaled(value, height, profile.reference_height)
    try:
        style = RenderScaledStyleDTO(
            width, height, horizontal(profile.horizontal_margin), vertical(profile.vertical_margin),
            vertical(profile.maximum_subtitle_height), vertical(profile.chinese.font_size),
            vertical(profile.english.font_size), vertical(profile.outline_width), vertical(profile.shadow),
        )
        bottom = height - style.vertical_margin
        safe_area = RenderBoundsDTO(style.horizontal_margin, bottom - style.maximum_subtitle_height,
                                    width - style.horizontal_margin, bottom)
    except ValueError as error:
        raise LayoutError("The fixed rendering profile has no valid safe area at this resolution.") from error
    return style, safe_area


def _is_latin(character: str) -> bool:
    return unicodedata.category(character).startswith("L") and "LATIN" in unicodedata.name(character, "")


def _latin_spans(text: str) -> tuple[tuple[int, int], ...]:
    spans = []
    position = 0
    while position < len(text):
        if not _is_latin(text[position]):
            position += 1
            continue
        start = position
        position += 1
        while position < len(text):
            if _is_latin(text[position]) or unicodedata.category(text[position]).startswith("M") or text[position].isdigit():
                position += 1
            elif text[position] in _LATIN_JOINERS and position + 1 < len(text) and _is_latin(text[position + 1]):
                position += 2
            else:
                break
        spans.append((start, position))
    return tuple(spans)


def protected_spans(text: str) -> tuple[tuple[int, int], ...]:
    """Protect Latin words and syntactically recognized tight numeric-unit tokens."""
    spans = list(_latin_spans(text))
    for match in _NUMBER_RE.finditer(text):
        start, end = match.span()
        unit = _UNIT_RE.match(text, end)
        if unit is not None:
            end = unit.end()
        latin_unit = _LATIN_UNIT_RE.match(text, end)
        if latin_unit is not None:
            end = latin_unit.end()
        spans.append((start, end))
    return tuple(sorted(set(spans)))


def _grapheme_boundaries(text: str, segmenter: GraphemeSegmenter) -> tuple[int, ...]:
    if not isinstance(segmenter.version, str) or not segmenter.version:
        raise ValueError("grapheme segmenter requires a version identity")
    boundaries = segmenter.boundaries(text)
    if not isinstance(boundaries, tuple) or not boundaries or any(type(value) is not int for value in boundaries):
        raise ValueError("grapheme boundaries must be an integer tuple")
    if boundaries[0] != 0 or boundaries[-1] != len(text) or any(left >= right for left, right in zip(boundaries, boundaries[1:])):
        raise ValueError("grapheme boundaries must strictly cover 0..len(text)")
    return boundaries


def candidate_break_offsets(text: str, language: str, segmenter: GraphemeSegmenter) -> tuple[int, ...]:
    boundaries = _grapheme_boundaries(text, segmenter)
    if language == "chinese":
        protected = protected_spans(text)
        return tuple(offset for offset in boundaries[1:-1]
                     if not any(start < offset < end for start, end in protected))
    if language == "english":
        # Break before the next word, retaining existing whitespace at the prior line's end.
        return tuple(offset for offset in boundaries[1:-1]
                     if text[offset - 1].isspace() and not text[offset].isspace())
    raise ValueError("visual layout language must be chinese or english")


def _punctuation_problem_count(lines: tuple[str, ...]) -> int:
    count = 0
    for line in lines:
        stripped = line.strip()
        if not stripped:
            return len(lines) + 1
        count += stripped[0] in _CLOSING_PUNCTUATION or unicodedata.category(stripped[0]) in ("Pe", "Pf")
        count += stripped[-1] in _OPENING_PUNCTUATION or unicodedata.category(stripped[-1]) in ("Ps", "Pi")
    return count


def _boundary_penalty(text: str, offsets: tuple[int, ...]) -> int:
    penalty = 0
    for offset in offsets:
        previous = text[:offset].rstrip()[-1:]
        penalty += 0 if previous in _STRONG_PUNCTUATION else 1 if previous in _WEAK_PUNCTUATION else 2
    return penalty


def choose_visual_layout(
    text: str, language: str, font_size: int, outline_width: int, shadow: int,
    safe_width: float, measurer: FontMeasurer, segmenter: GraphemeSegmenter,
) -> VisualLayout:
    if not isinstance(text, str) or not text.strip():
        raise LayoutError("Visual layout requires non-empty authoritative logical text.")
    if type(safe_width) not in (int, float) or (type(safe_width) is float and not math.isfinite(safe_width)) or safe_width <= 0:
        raise ValueError("safe_width must be a finite positive number")
    for value, name, minimum in ((font_size, "font_size", 1), (outline_width, "outline_width", 0), (shadow, "shadow", 0)):
        if type(value) is not int or value < minimum:
            raise ValueError(f"{name} must be an integer >= {minimum}")
    paths = ((), *((offset,) for offset in candidate_break_offsets(text, language, segmenter)))
    candidates = []
    for offsets in paths:
        boundaries = (0, *offsets, len(text))
        lines = tuple(text[start:end] for start, end in zip(boundaries, boundaries[1:]))
        problems = _punctuation_problem_count(lines)
        if problems:
            continue
        metrics = tuple(measurer.measure(line, font_size, outline_width, shadow) for line in lines)
        if any(not isinstance(metric, RenderLineMetricsDTO) for metric in metrics):
            raise LayoutError("The font measurement adapter returned invalid line metrics.")
        overflow_count = sum(metric.width > safe_width for metric in metrics)
        if overflow_count:
            continue
        widths = tuple(metric.width for metric in metrics)
        mean = sum(widths) / len(widths)
        score = (overflow_count, _boundary_penalty(text, offsets), problems, max(widths),
                 sum((width - mean) ** 2 for width in widths), offsets)
        candidates.append((score, VisualLayout(offsets, metrics)))
    if not candidates:
        raise LayoutError("Authoritative text cannot fit two visual lines at the fixed font size.")
    return min(candidates, key=lambda item: item[0])[1]


def layout_cue(
    source_cue: SubtitleCueDTO, scaled_style: RenderScaledStyleDTO, safe_area: RenderBoundsDTO,
    measurer: FontMeasurer, segmenter: GraphemeSegmenter,
) -> RenderCueDTO:
    if not isinstance(source_cue, SubtitleCueDTO) or not isinstance(scaled_style, RenderScaledStyleDTO) or not isinstance(safe_area, RenderBoundsDTO):
        raise ValueError("layout_cue requires typed source cue, scaled style and safe area")
    width = safe_area.right - safe_area.left
    chinese = choose_visual_layout(source_cue.chinese_text, "chinese", scaled_style.chinese_font_size,
                                   scaled_style.outline_width, scaled_style.shadow, width, measurer, segmenter)
    english = choose_visual_layout(source_cue.english_text, "english", scaled_style.english_font_size,
                                   scaled_style.outline_width, scaled_style.shadow, width, measurer, segmenter)
    metrics = (*chinese.metrics, *english.metrics)
    block_width, block_height = max(metric.width for metric in metrics), sum(metric.height for metric in metrics)
    if len(metrics) > scaled_style.maximum_total_lines or block_height > safe_area.bottom - safe_area.top:
        raise LayoutError("The selected bilingual visual lines exceed the fixed safe height.")
    left = (scaled_style.play_res_x - block_width) / 2
    bounds = RenderBoundsDTO(left, safe_area.bottom - block_height, left + block_width, safe_area.bottom)
    if not safe_area.contains(bounds):
        raise LayoutError("The selected bilingual visual lines exceed the fixed safe area.")
    start, end = project_ass_time_ms(source_cue.start_ms), project_ass_time_ms(source_cue.end_ms)
    try:
        result = RenderCueDTO(
            source_cue.id, source_cue.start_ms, source_cue.end_ms, start, end,
            start - source_cue.start_ms, end - source_cue.end_ms,
            hashlib.sha256(source_cue.chinese_text.encode("utf-8")).hexdigest(),
            hashlib.sha256(source_cue.english_text.encode("utf-8")).hexdigest(),
            chinese.break_offsets, english.break_offsets, chinese.metrics, english.metrics, bounds,
        )
    except ValueError as error:
        raise LayoutError("The authoritative cue has no valid ASS timing projection.") from error
    result.visual_lines(source_cue)
    return result


def build_render_plan(
    *, asset_id: str, inputs: Mapping[str, RenderArtifactEvidenceDTO], input_media: RenderMediaDTO,
    source_plan: SubtitlePlanDTO, profile: RenderProfileDTO, font: RenderFontIdentityDTO,
    tools: RenderToolsDTO, measurer: FontMeasurer, segmenter: GraphemeSegmenter,
) -> SubtitleRenderPlanDTO:
    if not isinstance(source_plan, SubtitlePlanDTO) or not isinstance(input_media, RenderMediaDTO) or not isinstance(font, RenderFontIdentityDTO):
        raise ValueError("render plan requires typed source, media and font identity")
    measurement_identities = font.measurement_adapter_version.split(";")
    if not isinstance(segmenter.version, str) or not segmenter.version or segmenter.version not in measurement_identities:
        raise ValueError("font measurement identity must bind the grapheme segmentation version")
    if UNICODE_CLASSIFICATION_VERSION not in measurement_identities:
        raise ValueError("font measurement identity must bind the runtime Unicode classification version")
    style, safe = scale_profile(profile, input_media.video.width, input_media.video.height)
    cues = tuple(layout_cue(cue, style, safe, measurer, segmenter) for cue in source_plan.cues)
    try:
        result = SubtitleRenderPlanDTO(asset_id, inputs, input_media, profile, profile.sha256,
                                       font, tools, style, safe, cues)
        result.validate_against_subtitle_plan(source_plan)
    except ValueError as error:
        raise LayoutError("The visual plan does not preserve a valid original/ASS media timeline.") from error
    return result
