"""Pure rendering ports and immutable visual-layout values."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol

from archive_core.interfaces import RenderLineMetricsDTO, RenderProfileDTO


class LayoutError(ValueError):
    """The fixed rendering profile cannot represent the authoritative cue."""

    category = "layout_failed"


class FontMeasurer(Protocol):
    def measure(self, text: str, font_size: int, outline_width: int, shadow: int) -> RenderLineMetricsDTO:
        """Measure one raw line, including outline and shadow safety allowance."""
        ...


class GraphemeSegmenter(Protocol):
    version: str

    def boundaries(self, text: str) -> tuple[int, ...]:
        """Return complete Unicode grapheme boundaries, including 0 and len(text)."""
        ...


@dataclass(frozen=True)
class VisualLayout:
    break_offsets: tuple[int, ...]
    metrics: tuple[RenderLineMetricsDTO, ...]


def profile_from_config(parameters: Mapping[str, object]) -> RenderProfileDTO:
    """Translate the single explicit config block into the strict public profile."""
    if not isinstance(parameters, Mapping) or "profile" not in parameters:
        raise ValueError("subtitle_rendering configuration requires profile")
    data = dict(parameters)
    if "name" in data or "version" in data or "layout_version" in data:
        raise ValueError("subtitle_rendering configuration must not override profile identity fields")
    data["name"] = data.pop("profile")
    data["version"] = "v1"
    data["layout_version"] = "pixel-wrap.v1"
    return RenderProfileDTO.from_dict(data)
