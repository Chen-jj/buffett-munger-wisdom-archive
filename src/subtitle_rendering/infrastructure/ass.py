"""Canonical pysubs2 ASS with a reversible, libass-specific plain-text dialect."""

from __future__ import annotations

import pysubs2

from archive_core.interfaces import ASS_SERIALIZATION_VERSION, SubtitlePlanDTO, SubtitleRenderPlanDTO


WORD_JOINER = "\u2060"
STYLE_NAME = "Bilingual"


class AssGenerationError(ValueError):
    category = "ass_generation_failed"


def escape_literal(text: str) -> str:
    if not isinstance(text, str) or any(ord(character) < 32 for character in text):
        raise AssGenerationError("ASS literal text must not contain control characters.")
    return "".join("\\" + WORD_JOINER if character == "\\" else "\\" + character
                   if character in "{}" else character for character in text)


def unescape_literal(text: str) -> str:
    result = []
    position = 0
    while position < len(text):
        character = text[position]
        if character == "\\":
            if position + 1 >= len(text) or text[position + 1] not in (WORD_JOINER, "{", "}"):
                raise AssGenerationError("An uncontrolled ASS text escape was found.")
            result.append("\\" if text[position + 1] == WORD_JOINER else text[position + 1])
            position += 2
        else:
            if character in "{}" or ord(character) < 32:
                raise AssGenerationError("An uncontrolled ASS text token was found.")
            result.append(character)
            position += 1
    return "".join(result)


def _color(value: str) -> pysubs2.Color:
    number = int(value[2:], 16)
    return pysubs2.Color(number & 255, (number >> 8) & 255, (number >> 16) & 255, (number >> 24) & 255)


def _english_override(plan: SubtitleRenderPlanDTO) -> str:
    return "{\\fs" + str(plan.scaled_style.english_font_size) + "\\1c" + plan.profile.english.primary_color + "&}"


def _file(plan: SubtitleRenderPlanDTO, source: SubtitlePlanDTO) -> pysubs2.SSAFile:
    plan.validate_against_subtitle_plan(source)
    if plan.ass_serialization_version != ASS_SERIALIZATION_VERSION:
        raise AssGenerationError("The ASS plain-text serialization identity is unsupported.")
    style = plan.scaled_style
    file = pysubs2.SSAFile()
    file.info = {"ScriptType": "v4.00+", "PlayResX": str(style.play_res_x), "PlayResY": str(style.play_res_y),
                 "WrapStyle": "2", "ScaledBorderAndShadow": "yes", "Collisions": "Normal", "YCbCr Matrix": "None"}
    file.styles = {STYLE_NAME: pysubs2.SSAStyle(
        fontname=plan.font.spec.family, fontsize=style.chinese_font_size,
        primarycolor=_color(plan.profile.chinese.primary_color),
        secondarycolor=_color(plan.profile.chinese.primary_color),
        outlinecolor=_color(plan.profile.outline_color), backcolor=_color(plan.profile.outline_color),
        alignment=pysubs2.Alignment.BOTTOM_CENTER, outline=style.outline_width, shadow=style.shadow,
        marginl=style.horizontal_margin, marginr=style.horizontal_margin,
        # Fixed half-open alpha safety inset; the last pixel may rasterize past the line box.
        marginv=style.vertical_margin + style.outline_width + style.shadow + 1,
    )}
    override = _english_override(plan)
    for cue, source_cue in zip(plan.cues, source.cues):
        if cue.ass_end_ms > 35999990:
            raise AssGenerationError("The ASS timeline exceeds the supported serializer range.")
        chinese, english = cue.visual_lines(source_cue)
        text = r"\N".join(escape_literal(line) for line in chinese) + r"\N" + override
        text += r"\N".join(escape_literal(line) for line in english)
        file.events.append(pysubs2.SSAEvent(start=cue.ass_start_ms, end=cue.ass_end_ms,
                                           text=text, style=STYLE_NAME, name=cue.id))
    return file


class Pysubs2AssCodec:
    version = ASS_SERIALIZATION_VERSION
    library_version = pysubs2.__version__

    def encode(self, plan: SubtitleRenderPlanDTO, source: SubtitlePlanDTO) -> bytes:
        try:
            data = _file(plan, source).to_string("ass").encode("utf-8")
            self.validate(data, plan, source)
            return data
        except AssGenerationError:
            raise
        except (ValueError, TypeError, KeyError, OverflowError) as error:
            raise AssGenerationError("The canonical ASS could not be generated.") from error

    def validate(self, data: bytes, plan: SubtitleRenderPlanDTO, source: SubtitlePlanDTO) -> None:
        try:
            if not isinstance(data, bytes):
                raise AssGenerationError("ASS validation requires canonical UTF-8 bytes.")
            text = data.decode("utf-8")
            expected = _file(plan, source)
            if (text.startswith("\ufeff") or "\r" in text or not text.endswith("\n")
                    or text != expected.to_string("ass")):
                raise AssGenerationError("ASS bytes do not match the canonical serialization.")
            actual = pysubs2.SSAFile.from_string(text, "ass")
            if actual.info != expected.info or actual.styles != expected.styles or len(actual.events) != len(plan.cues):
                raise AssGenerationError("ASS header, style or event count did not survive round-trip.")
            override = _english_override(plan)
            for event, planned, original, expected_event in zip(actual.events, plan.cues, source.cues, expected.events):
                if event != expected_event:
                    raise AssGenerationError("ASS event identity, projected time or controls changed.")
                parts = event.text.split(override)
                if len(parts) != 2 or not parts[0].endswith(r"\N"):
                    raise AssGenerationError("ASS language style boundary did not survive round-trip.")
                chinese = tuple(unescape_literal(line) for line in parts[0][:-2].split(r"\N"))
                english = tuple(unescape_literal(line) for line in parts[1].split(r"\N"))
                if (chinese, english) != planned.visual_lines(original):
                    raise AssGenerationError("ASS logical text or visual offsets changed during round-trip.")
        except AssGenerationError:
            raise
        except (UnicodeError, ValueError, TypeError, KeyError) as error:
            raise AssGenerationError("The canonical ASS round-trip verification failed.") from error
