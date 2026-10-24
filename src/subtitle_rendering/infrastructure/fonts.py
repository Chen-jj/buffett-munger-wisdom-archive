"""Exact local font bytes, TTC face verification and deterministic measurements."""

from __future__ import annotations

from io import BytesIO
import hashlib
from pathlib import Path
import re
from typing import Iterable

import fontTools
from fontTools.ttLib import TTCollection, TTFont, TTLibError
import PIL
from PIL import ImageFont, features
import regex

from archive_core.interfaces import RenderFontIdentityDTO, RenderFontSpecDTO, RenderLineMetricsDTO
from subtitle_rendering.domain.layout import UNICODE_CLASSIFICATION_VERSION


class FontValidationError(ValueError):
    category = "font_invalid"


class RegexGraphemeSegmenter:
    version = f"unicode-grapheme.regex-{regex.__version__}.v1"

    def boundaries(self, text: str) -> tuple[int, ...]:
        if not isinstance(text, str):
            raise ValueError("grapheme segmentation requires text")
        return (0, *(match.end() for match in regex.finditer(r"\X", text)))


def _names(face: TTFont, name_id: int) -> frozenset[str]:
    return frozenset(record.toUnicode() for record in face["name"].names if record.nameID == name_id)


def _measurement_version() -> str:
    if not features.check_feature("raqm"):
        raise FontValidationError("The required deterministic font shaping adapter is unavailable.")
    versions = ["pillow-raqm-envelope.v1", "ass-alpha-inset-outline-shadow-one-pixel.v1",
                f"Pillow={PIL.__version__}", f"fontTools={fontTools.__version__}"]
    versions.extend(f"{name}={features.version(name)}" for name in ("freetype2", "raqm", "harfbuzz", "fribidi"))
    return ";".join((*versions, RegexGraphemeSegmenter.version, UNICODE_CLASSIFICATION_VERSION))


class ExactFontAdapter:
    def __init__(self, spec: RenderFontSpecDTO, texts: Iterable[str]) -> None:
        if not isinstance(spec, RenderFontSpecDTO):
            raise FontValidationError("An exact font specification is required.")
        self._fonts: dict[int, ImageFont.FreeTypeFont] = {}
        try:
            self._data = Path(spec.path).read_bytes()
            if not self._data or hashlib.sha256(self._data).hexdigest() != spec.sha256:
                raise FontValidationError("The exact font file fingerprint does not match.")
            if self._data[:4] == b"ttcf":
                collection = TTCollection(BytesIO(self._data))
                faces = collection.fonts
            else:
                collection = None
                faces = [TTFont(BytesIO(self._data))]
            try:
                if spec.face_index >= len(faces):
                    raise FontValidationError("The configured font face does not exist.")
                face = faces[spec.face_index]
                families = _names(face, 16) or _names(face, 1)
                styles = _names(face, 17) or _names(face, 2)
                if spec.family not in families or spec.style not in styles:
                    raise FontValidationError("The exact font face family or style does not match.")
                postscript_names = _names(face, 6)
                if len(postscript_names) != 1:
                    raise FontValidationError("The exact font face has no unique PostScript identity.")
                postscript_name = next(iter(postscript_names))
                if [index for index, item in enumerate(faces) if postscript_name in _names(item, 6)] != [spec.face_index]:
                    raise FontValidationError("The PostScript name does not uniquely identify the configured face.")
                self._glyphs = {codepoint for table in face["cmap"].tables if table.isUnicode()
                                for codepoint, glyph in table.cmap.items() if glyph != ".notdef"}
            finally:
                if collection is not None:
                    collection.close()
                else:
                    faces[0].close()
            self.identity = RenderFontIdentityDTO(spec, len(self._data), _measurement_version(), postscript_name)
            self.validate_glyphs(texts)
            # Force the exact bytes/face through the measurement engine now, not at first cue.
            self._font(1)
        except FontValidationError:
            raise
        except (OSError, ValueError, KeyError, IndexError, TypeError, TTLibError) as error:
            raise FontValidationError("The exact local font could not be verified.") from error

    def validate_glyphs(self, texts: Iterable[str]) -> None:
        for text in texts:
            if not isinstance(text, str):
                raise FontValidationError("Glyph validation requires authoritative text.")
            if any(ord(character) not in self._glyphs for character in text):
                raise FontValidationError("The exact font face lacks an authoritative text glyph.")

    def _font(self, size: int) -> ImageFont.FreeTypeFont:
        if size not in self._fonts:
            font = ImageFont.truetype(BytesIO(self._data), size, index=self.identity.spec.face_index,
                                      layout_engine=ImageFont.Layout.RAQM)
            if font.getname() != (self.identity.spec.family, self.identity.spec.style):
                raise FontValidationError("The measurement engine selected a different font face.")
            self._fonts[size] = font
        return self._fonts[size]

    def measure(self, text: str, font_size: int, outline_width: int, shadow: int) -> RenderLineMetricsDTO:
        for value, minimum in ((font_size, 1), (outline_width, 0), (shadow, 0)):
            if type(value) is not int or value < minimum:
                raise FontValidationError("Invalid fixed font measurement parameters.")
        if not isinstance(text, str) or not text.strip():
            raise FontValidationError("Font measurement requires a non-empty logical line.")
        self.validate_glyphs((text,))
        try:
            font = self._font(font_size)
            left, top, right, bottom = font.getbbox(text)
            ascent, descent = font.getmetrics()
            allowance = 2 * outline_width + shadow
            return RenderLineMetricsDTO(max(font.getlength(text), right) - min(0, left) + allowance,
                                        max(font_size, ascent + descent, bottom - top) + allowance)
        except (OSError, ValueError) as error:
            raise FontValidationError("The exact font measurement failed.") from error


_FONT_SELECTION = re.compile(r"fontselect: \((.+), (-?\d+), (-?\d+)\) -> (.+), (-?\d+), ([^\r\n]+)$")


def validate_libass_font_selection(stderr: str, identity: RenderFontIdentityDTO) -> None:
    """CoreText's -1 face is accepted only with the independently unique PS mapping."""
    selections = [line for line in stderr.splitlines() if "fontselect:" in line]
    if not selections:
        raise FontValidationError("The actual renderer supplied no exact font selection evidence.")
    if re.search(r"failed to find.*fallback|selecting.*fallback|glyph .* not found", stderr, re.IGNORECASE):
        raise FontValidationError("The actual renderer reported font fallback or a missing glyph.")
    for line in selections:
        match = _FONT_SELECTION.search(line)
        if match is None:
            raise FontValidationError("The actual font selection evidence is not recognized.")
        family, weight, italic, path, index, postscript_name = match.groups()
        if (family != identity.spec.family or weight != "400" or italic != "0"
                or Path(path).resolve() != Path(identity.spec.path).resolve()
                or int(index) not in (-1, identity.spec.face_index)
                or postscript_name != identity.postscript_name):
            raise FontValidationError("The actual renderer selected a different exact font face.")
