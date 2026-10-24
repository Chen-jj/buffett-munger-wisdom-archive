"""Actual libass per-cue alpha, style, line-break and font evidence checks."""

from pathlib import Path
import re

from PIL import Image, ImageChops

from archive_core.interfaces import (
    RenderBoundsDTO, RenderCueDTO, RenderFontIdentityDTO, RenderPixelResultDTO,
    SubtitlePlanDTO, SubtitleRenderPlanDTO,
)

from .ass import AssGenerationError, Pysubs2AssCodec
from .fonts import validate_libass_font_selection


class PixelValidationError(ValueError):
    category = "layout_failed"


def _rgb(value: str) -> tuple[int, int, int]:
    number = int(value[2:], 16)
    return number & 255, (number >> 8) & 255, (number >> 16) & 255


def _color_mask(image: Image.Image, color: tuple[int, int, int],
                outline: tuple[int, int, int] = (0, 0, 0)) -> Image.Image:
    """Recognize the controlled fill hue even when a thin glyph has no fully opaque fill."""
    anchor = max(range(3), key=lambda index: abs(color[index] - outline[index]))
    contrast = abs(color[anchor] - outline[anchor])
    if not contrast:
        raise PixelValidationError("The actual fill style cannot be distinguished from the outline.")
    visible = image.convert("RGB").split()[anchor].point(
        lambda value: 255 if abs(value - outline[anchor]) >= max(8, contrast / 4) else 0)
    alpha = image.getchannel("A").point(lambda value: 255 if value >= 16 else 0)
    return ImageChops.multiply(ImageChops.multiply(_blend_mask(image, outline, color), visible), alpha)


def _blend_mask(image: Image.Image, start: tuple[int, int, int], end: tuple[int, int, int]) -> Image.Image:
    """Accept antialias blends on a controlled fill/outline color segment, not arbitrary hues."""
    channels = image.convert("RGB").split()
    anchor = max(range(3), key=lambda index: abs(end[index] - start[index]))
    delta = end[anchor] - start[anchor]
    if delta == 0:
        difference = ImageChops.difference(image.convert("RGB"), Image.new("RGB", image.size, start))
        red, green, blue = difference.split()
        return ImageChops.lighter(ImageChops.lighter(red, green), blue).point(lambda value: 255 if value <= 5 else 0)
    allowed = channels[anchor].point(lambda value: 255 if min(start[anchor], end[anchor]) - 5 <= value
                                     <= max(start[anchor], end[anchor]) + 5 else 0)
    for index, channel in enumerate(channels):
        predicted = channels[anchor].point(lambda value: max(0, min(255, round(
            start[index] + (value - start[anchor]) * (end[index] - start[index]) / delta))))
        matches = ImageChops.difference(channel, predicted).point(lambda value: 255 if value <= 5 else 0)
        allowed = ImageChops.multiply(allowed, matches)
    return allowed


def _bounds(box: tuple[int, int, int, int] | None) -> RenderBoundsDTO:
    if box is None:
        raise PixelValidationError("The actual subtitle frame has no visible pixels.")
    return RenderBoundsDTO(*box)


def validate_frame(frame, plan: SubtitleRenderPlanDTO, cue: RenderCueDTO,
                   font_identity: RenderFontIdentityDTO) -> RenderPixelResultDTO:
    """Called only after strict ASS round-trip by preflight; never infer fonts from family."""
    style = plan.scaled_style
    if font_identity != plan.font or cue not in plan.cues:
        raise PixelValidationError("Pixel evidence does not belong to the current rendering plan.")
    if (frame.width, frame.height) != (style.play_res_x, style.play_res_y):
        raise PixelValidationError("The actual subtitle frame resolution does not match the plan.")
    if not isinstance(frame.rgba, bytes) or len(frame.rgba) != frame.width * frame.height * 4:
        raise PixelValidationError("The actual renderer returned an incomplete RGBA frame.")
    validate_libass_font_selection(frame.stderr, font_identity)
    breaks = re.findall(r"\b(forced )?line break at ([0-9]+)\b", frame.stderr)
    expected_count = len(cue.chinese_lines) + len(cue.english_lines)
    if (len(breaks) != expected_count - 1 or any(kind != "forced " for kind, _ in breaks)
            or frame.stderr.count("line break at") != len(breaks)):
        raise PixelValidationError("Actual libass line-break evidence does not match the explicit visual lines.")
    image = Image.frombytes("RGBA", (frame.width, frame.height), frame.rgba)
    bounds = _bounds(image.getchannel("A").getbbox())
    if not plan.safe_area.contains(bounds):
        raise PixelValidationError("Actual subtitle pixels exceed the fixed safe area.")
    outline_color = _rgb(plan.profile.outline_color)
    chinese_mask = _color_mask(image, _rgb(plan.profile.chinese.primary_color), outline_color)
    english_mask = _color_mask(image, _rgb(plan.profile.english.primary_color), outline_color)
    chinese = _bounds(chinese_mask.getbbox())
    english = _bounds(english_mask.getbbox())
    if chinese.bottom > english.top:
        raise PixelValidationError("Actual Chinese and English style pixels are not in the required order.")
    chinese_color, english_color = _rgb(plan.profile.chinese.primary_color), _rgb(plan.profile.english.primary_color)
    allowed = _blend_mask(image, (0, 0, 0), outline_color)
    for primary in (chinese_color, english_color):
        allowed = ImageChops.lighter(allowed, _blend_mask(image, outline_color, primary))
        allowed = ImageChops.lighter(allowed, _blend_mask(image, (0, 0, 0), primary))
    opaque = image.getchannel("A").point(lambda value: 255 if value >= 16 else 0)
    if ImageChops.subtract(opaque, allowed).getbbox() is not None:
        raise PixelValidationError("Actual subtitle interior pixels contain an unexpected style color.")
    for observed, lines in ((chinese, cue.chinese_lines), (english, cue.english_lines)):
        if (observed.right - observed.left > max(line.width for line in lines) + 1
                or observed.bottom - observed.top > sum(line.height for line in lines) + 1):
            raise PixelValidationError("Actual style geometry exceeds the measured fixed-font envelope.")
    if (bounds.right - bounds.left > cue.expected_bounds.right - cue.expected_bounds.left + 1
            or bounds.bottom - bounds.top > cue.expected_bounds.bottom - cue.expected_bounds.top + 1):
        raise PixelValidationError("Actual subtitle geometry exceeds the planned measurement envelope.")
    return RenderPixelResultDTO(cue.id, (cue.ass_start_ms + cue.ass_end_ms) // 2,
                                bounds, expected_count, True, True)


def preflight(plan: SubtitleRenderPlanDTO, source: SubtitlePlanDTO, ass_path: str | Path,
              renderer) -> tuple[RenderPixelResultDTO, ...]:
    """Validate staged ASS, then render every cue on an independent transparent canvas."""
    try:
        Pysubs2AssCodec().validate(Path(ass_path).read_bytes(), plan, source)
    except OSError as error:
        raise AssGenerationError("The staged ASS could not be read for pixel verification.") from error
    results = []
    for cue in plan.cues:
        midpoint = (cue.ass_start_ms + cue.ass_end_ms) // 2
        frame = renderer.render_transparent_frame(
            ass_path, str(Path(plan.font.spec.path).parent),
            plan.scaled_style.play_res_x, plan.scaled_style.play_res_y, midpoint,
        )
        results.append(validate_frame(frame, plan, cue, plan.font))
    return tuple(results)
