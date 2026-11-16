"""Fake measurement and abstract grapheme port for rendering unit tests."""
import regex
from archive_core.interfaces import RenderLineMetricsDTO

class Segments:
    version = "unicode-grapheme.regex-2026.7.19.v1"

    def boundaries(self, text):
        return (0, *(match.end() for match in regex.finditer(r"\X", text)))

    def lexical_boundaries(self, text):
        return self.boundaries(text)


class Measurer:
    def __init__(self, unit=10, line_height=None):
        self.unit = unit
        self.line_height = line_height
        self.calls = []

    def measure(self, text, font_size, outline_width, shadow):
        self.calls.append((text, font_size, outline_width, shadow))
        width = len(text) * self.unit + 2 * outline_width + shadow
        return RenderLineMetricsDTO(width, self.line_height or font_size + 2 * outline_width + shadow)
