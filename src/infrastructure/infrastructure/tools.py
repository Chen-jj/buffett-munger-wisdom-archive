"""External tool discovery without executing the tools."""

from __future__ import annotations

from dataclasses import dataclass
from shutil import which


DEFAULT_MEDIA_TOOLS = ("ffmpeg", "ffprobe", "yt-dlp")


@dataclass(frozen=True)
class ToolInfo:
    name: str
    path: str | None

    @property
    def available(self) -> bool:
        return self.path is not None


def discover_tool(name: str, *, search_path: str | None = None) -> ToolInfo:
    if not name:
        raise ValueError("tool name must not be empty")
    return ToolInfo(name=name, path=which(name, path=search_path))


def discover_tools(
    names: tuple[str, ...] = DEFAULT_MEDIA_TOOLS,
    *,
    search_path: str | None = None,
) -> dict[str, ToolInfo]:
    return {name: discover_tool(name, search_path=search_path) for name in names}
