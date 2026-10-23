"""Explicit local composition without executing media tools during construction."""

from __future__ import annotations

from srt_processing.application import ChineseWordSegmenter, Clock, MediaProbe, SrtCodec, SubtitleArtifactStore, SrtProcessingWorkflow
from srt_processing.interfaces import SrtProcessingCommandHandler

from .codec import Pysubs2SrtCodec
from .local import LocalSubtitleArtifactStore, SystemClock
from .probe import FfprobeMediaProbe
from .segmentation import JiebaChineseWordSegmenter


def build_srt_processing_handler(
    *,
    output_root: str = "output",
    ffprobe_executable: str = "ffprobe",
    artifacts: SubtitleArtifactStore | None = None,
    probe: MediaProbe | None = None,
    codec: SrtCodec | None = None,
    clock: Clock | None = None,
    segmenter: ChineseWordSegmenter | None = None,
) -> SrtProcessingCommandHandler:
    workflow = SrtProcessingWorkflow(
        artifacts=artifacts if artifacts is not None else LocalSubtitleArtifactStore(),
        probe=probe if probe is not None else FfprobeMediaProbe(executable=ffprobe_executable),
        codec=codec if codec is not None else Pysubs2SrtCodec(),
        clock=clock if clock is not None else SystemClock(),
        segmenter=segmenter if segmenter is not None else JiebaChineseWordSegmenter(),
        output_root=output_root,
    )
    return SrtProcessingCommandHandler(workflow)
