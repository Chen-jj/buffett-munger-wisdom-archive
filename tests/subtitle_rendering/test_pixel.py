"""Pixel and libass evidence validation on fake RGBA frames, without real tools."""

from dataclasses import replace
from types import SimpleNamespace

from PIL import Image, ImageDraw
import pytest

from subtitle_rendering.infrastructure.ass import AssGenerationError, Pysubs2AssCodec
from subtitle_rendering.infrastructure.fonts import FontValidationError
from subtitle_rendering.infrastructure.pixel import PixelValidationError, preflight, validate_frame
from tests.archive_core.test_rendering_contracts import render_plan, source_plan
from tests.subtitle_rendering.test_fonts import selection


def frame(plan=None, cue=None, *, chinese=(300, 250, 320, 259), english=(300, 290, 320, 299),
          extra=None, breaks=None):
    plan = plan or render_plan()
    cue = cue or plan.cues[0]
    image = Image.new("RGBA", (640, 360))
    draw = ImageDraw.Draw(image)
    if chinese is not None:
        draw.rectangle(chinese, fill=(255, 255, 255, 255))
    if english is not None:
        draw.rectangle(english, fill=(255, 230, 96, 255))
    if extra is not None:
        draw.rectangle(extra[0], fill=extra[1])
    count = len(cue.chinese_lines) + len(cue.english_lines) - 1
    evidence = "\n".join(f"forced line break at {index + 1}" for index in range(count)) if breaks is None else breaks
    return SimpleNamespace(rgba=image.tobytes(), stderr=selection(plan.font) + "\n" + evidence, width=640, height=360)


def test_pixel_checks_actual_alpha_colors_order_geometry_and_libass_breaks():
    plan = render_plan()
    result = validate_frame(frame(plan), plan, plan.cues[0], plan.font)
    assert result.cue_id == "c1" and result.time_ms == 660
    assert result.line_count == 4 and result.font_identity_matches and result.styles_match
    assert result.bounds.to_dict() == {"left": 300, "top": 250, "right": 321, "bottom": 300}


@pytest.mark.parametrize("changes", (
    {"chinese": None, "english": None}, {"chinese": None}, {"english": None},
    {"chinese": (300, 300, 320, 309)},
    {"chinese": (30, 250, 40, 259)}, {"english": (300, 310, 320, 318)},
    {"chinese": (300, 150, 320, 159)}, {"english": (600, 290, 609, 299)},
    {"extra": ((300, 275, 310, 280), (255, 0, 0, 255))},
    {"extra": ((300, 319, 310, 320), (0, 0, 0, 1))},
    {"chinese": (200, 250, 400, 259)},
    {"chinese": (300, 198, 320, 259)},
))
def test_pixels_missing_style_wrong_order_outside_safe_or_measurement_envelope_fail(changes):
    plan = render_plan()
    with pytest.raises(PixelValidationError):
        validate_frame(frame(plan, **changes), plan, plan.cues[0], plan.font)


@pytest.mark.parametrize("breaks", (
    "", "forced line break at 1", "forced line break at 1\nforced line break at 2",
    "\n".join(f"forced line break at {index}" for index in range(4)),
    "forced line break at 1\nforced line break at 2\nline break at 3",
    "forced line break at 1\nforced line break at 2\nforced line break at unknown",
    "\n".join(f"forced line break at {index}" for index in (1, 2, 3, 1, 2, 3)),
))
def test_actual_line_count_requires_current_single_frame_explicit_break_evidence(breaks):
    plan = render_plan()
    with pytest.raises(PixelValidationError, match="line-break"):
        validate_frame(frame(plan, breaks=breaks), plan, plan.cues[0], plan.font)


@pytest.mark.parametrize("mutation", (
    lambda item: setattr(item, "rgba", item.rgba[:-1]),
    lambda item: setattr(item, "width", 1280),
    lambda item: setattr(item, "rgba", bytearray(item.rgba)),
))
def test_frame_dimensions_and_exact_pipe_byte_count_are_checked(mutation):
    plan = render_plan()
    item = frame(plan)
    mutation(item)
    with pytest.raises(PixelValidationError):
        validate_frame(item, plan, plan.cues[0], plan.font)


def test_runtime_font_evidence_is_not_replaced_by_saved_plan_identity():
    plan = render_plan()
    item = frame(plan)
    item.stderr = item.stderr.replace("HiraginoSansGB-W3", "Other")
    with pytest.raises(FontValidationError):
        validate_frame(item, plan, plan.cues[0], plan.font)


def test_thin_antialiased_glyphs_without_exact_primary_rgb_still_have_verified_style_hues():
    plan = render_plan()
    item = frame(plan)
    image = Image.frombytes("RGBA", (640, 360), item.rgba)
    pixels = image.load()
    for y in range(360):
        for x in range(640):
            if pixels[x, y] == (255, 255, 255, 255):
                pixels[x, y] = (160, 160, 160, 255)
            elif pixels[x, y] == (255, 230, 96, 255):
                pixels[x, y] = (188, 170, 71, 255)
    item.rgba = image.tobytes()
    assert validate_frame(item, plan, plan.cues[0], plan.font).styles_match


def test_foreign_antialiased_color_is_not_ignored_only_because_it_is_not_opaque():
    plan = render_plan()
    item = frame(plan, extra=((300, 275, 310, 280), (128, 0, 0, 128)))
    with pytest.raises(PixelValidationError, match="color"):
        validate_frame(item, plan, plan.cues[0], plan.font)


def test_different_font_identity_is_rejected_before_pixel_check():
    plan = render_plan()
    with pytest.raises(PixelValidationError):
        validate_frame(frame(plan), plan, plan.cues[0], replace(plan.font, postscript_name="Other"))


class Renderer:
    def __init__(self, plan):
        self.plan = plan
        self.calls = []

    def render_transparent_frame(self, ass_path, fonts_dir, width, height, time_ms):
        self.calls.append((ass_path, fonts_dir, width, height, time_ms))
        cue = next(item for item in self.plan.cues if (item.ass_start_ms + item.ass_end_ms) // 2 == time_ms)
        return frame(self.plan, cue)


def test_preflight_checks_staged_ass_then_every_cue_with_separate_midpoint_calls(tmp_path):
    plan, source = render_plan(), source_plan()
    ass = tmp_path / "staged.ass"
    ass.write_bytes(Pysubs2AssCodec().encode(plan, source))
    renderer = Renderer(plan)
    results = preflight(plan, source, ass, renderer)
    assert [result.cue_id for result in results] == ["c1", "c2"]
    assert [call[-1] for call in renderer.calls] == [660, 1715]
    assert all(call[1:4] == ("/System/Library/Fonts", 640, 360) for call in renderer.calls)


@pytest.mark.parametrize("missing", (True, False))
def test_preflight_refuses_missing_or_modified_ass_before_any_process(tmp_path, missing):
    plan, source = render_plan(), source_plan()
    ass = tmp_path / "staged.ass"
    if not missing:
        ass.write_bytes(Pysubs2AssCodec().encode(plan, source) + b"; modified\n")
    renderer = Renderer(plan)
    with pytest.raises(AssGenerationError):
        preflight(plan, source, ass, renderer)
    assert renderer.calls == []
