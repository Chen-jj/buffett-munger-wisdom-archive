"""Explicit production composition; construction reads configuration, not fonts or tools."""

from pathlib import Path

from infrastructure.infrastructure.config import load_yaml_config
from subtitle_rendering.application.workflow import SubtitleRenderingWorkflow
from subtitle_rendering.domain.models import profile_from_config
from subtitle_rendering.interfaces import SubtitleRenderingCommandHandler

from .ass import Pysubs2AssCodec
from .ffmpeg import FfmpegRenderer
from .fonts import ExactFontAdapter, RegexGraphemeSegmenter
from .local import LocalRenderingArtifactStore, SystemClock
from .pixel import preflight
from .probe import FfprobeMediaProbe, validate_rendered_media


def build_subtitle_rendering_handler(*, output_root: str = "output", config_path: str | Path | None = None,
                                     ffmpeg_executable: str = "ffmpeg", ffprobe_executable: str = "ffprobe",
                                     artifacts=None, probe=None, codec=None, renderer=None, font_factory=None,
                                     segmenter=None, pixel_preflight=None, media_validator=None, clock=None) -> SubtitleRenderingCommandHandler:
    config = load_yaml_config(config_path)
    if "subtitle_rendering" not in config:
        raise ValueError("subtitle_rendering configuration is required")
    profile = profile_from_config(config["subtitle_rendering"])
    workflow = SubtitleRenderingWorkflow(
        artifacts=artifacts if artifacts is not None else LocalRenderingArtifactStore(),
        probe=probe if probe is not None else FfprobeMediaProbe(executable=ffprobe_executable),
        codec=codec if codec is not None else Pysubs2AssCodec(),
        renderer=renderer if renderer is not None else FfmpegRenderer(executable=ffmpeg_executable),
        font_factory=font_factory if font_factory is not None else ExactFontAdapter,
        segmenter=segmenter if segmenter is not None else RegexGraphemeSegmenter(),
        pixel_preflight=pixel_preflight if pixel_preflight is not None else preflight,
        media_validator=media_validator if media_validator is not None else validate_rendered_media,
        clock=clock if clock is not None else SystemClock(), profile=profile, output_root=output_root,
    )
    return SubtitleRenderingCommandHandler(workflow)
