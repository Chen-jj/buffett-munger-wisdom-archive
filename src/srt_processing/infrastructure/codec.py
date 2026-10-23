"""Lossless, fixed-version SRT projections through pysubs2 only."""

from __future__ import annotations

import re
import warnings

import pysubs2

from archive_core.interfaces import SubtitleCodecDTO, SubtitlePlanDTO
from srt_processing.application.ports import SrtCue, SubtitleLanguage
from srt_processing.domain.rules import wrap_english_text


_TIMESTAMP_LINE_RE = re.compile(
    r"[0-9]{2}:[0-5][0-9]:[0-5][0-9],[0-9]{3} --> "
    r"[0-9]{2}:[0-5][0-9]:[0-5][0-9],[0-9]{3}"
)


class SubtitleCodecError(ValueError):
    category = "codec_invalid"


class Pysubs2SrtCodec:
    def __init__(self) -> None:
        if pysubs2.__version__ != "1.8.1":
            raise SubtitleCodecError("subtitle codec requires pysubs2 1.8.1")

    @property
    def identity(self) -> SubtitleCodecDTO:
        return SubtitleCodecDTO(serialization_version="word-wrap-english-2x42.v2")

    def encode(self, plan: SubtitlePlanDTO, language: SubtitleLanguage) -> bytes:
        if not isinstance(plan, SubtitlePlanDTO):
            raise SubtitleCodecError("plan must be a SubtitlePlanDTO")
        if language not in ("english", "chinese", "bilingual"):
            raise SubtitleCodecError("unsupported subtitle projection language")

        expected: list[SrtCue] = []
        subtitles = pysubs2.SSAFile()
        for position, cue in enumerate(plan.cues, 1):
            try:
                english = wrap_english_text(cue.english_text)
            except ValueError as error:
                raise SubtitleCodecError("English text cannot fit the fixed two-line projection") from error
            if language == "english":
                text = english
            elif language == "chinese":
                text = cue.chinese_text
            else:
                text = cue.chinese_text + "\n" + english
            expected.append(SrtCue(position, cue.start_ms, cue.end_ms, text))
            # Preserve the fixed text-budget lines through pysubs2's internal separator.
            event = pysubs2.SSAEvent(start=cue.start_ms, end=cue.end_ms)
            event.plaintext = text
            subtitles.append(event)

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error")
                text = subtitles.to_string(
                    "srt", apply_styles=False, keep_ssa_tags=False
                )
            data = text.encode("utf-8")
        except Exception as error:
            raise SubtitleCodecError("pysubs2 could not serialize the projection") from error

        if self.decode(data) != tuple(expected):
            raise SubtitleCodecError("SRT projection did not preserve plan text and timing")
        return data

    def decode(self, data: bytes) -> tuple[SrtCue, ...]:
        try:
            if not isinstance(data, bytes):
                raise ValueError("SRT data must be bytes")
            text = data.decode("utf-8")
            if not text or text.startswith("\ufeff") or "\r" in text or not text.endswith("\n"):
                raise ValueError("SRT must be UTF-8 without BOM, with LF and a terminal newline")

            # pysubs2 discards SRT numbers. Retain just that structural evidence,
            # while leaving timestamp/text decoding to its SubRip implementation.
            blocks = text.rstrip("\n").split("\n\n")
            indices = []
            bodies = []
            for position, block in enumerate(blocks, 1):
                lines = block.split("\n")
                if len(lines) < 3 or lines[0] != str(position):
                    raise ValueError("SRT must contain consecutive indices 1..N and non-empty bodies")
                if _TIMESTAMP_LINE_RE.fullmatch(lines[1]) is None:
                    raise ValueError("SRT must use HH:MM:SS,mmm timestamp lines")
                indices.append(position)
                bodies.append("\n".join(lines[2:]))

            with warnings.catch_warnings():
                warnings.simplefilter("error")
                subtitles = pysubs2.SSAFile.from_string(text, format_="srt")
            if len(subtitles) != len(indices):
                raise ValueError("pysubs2 changed the number of SRT entries")
            result = tuple(
                SrtCue(index, event.start, event.end, event.plaintext)
                for index, event in zip(indices, subtitles, strict=True)
            )
            if tuple(cue.text for cue in result) != tuple(bodies):
                raise ValueError("pysubs2 changed literal subtitle text")
            previous_end = 0
            for cue in result:
                if cue.start_ms < previous_end:
                    raise ValueError("SRT timeline must not overlap or move backward")
                previous_end = cue.end_ms
            return result
        except Exception as error:
            raise SubtitleCodecError("SRT could not be decoded without structural loss") from error
