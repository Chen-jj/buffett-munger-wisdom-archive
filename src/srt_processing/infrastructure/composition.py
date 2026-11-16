"""Explicit production final-draft export composition, without model/media calls."""
from srt_processing.application.workflow import SrtProcessingWorkflow
from srt_processing.interfaces.workflow import SrtProcessingCommandHandler
from .codec import Pysubs2SrtCodec
from .local import LocalSubtitleArtifactStore, SystemClock


def build_srt_processing_handler(*, output_root="output", artifacts=None, codec=None, clock=None):
    return SrtProcessingCommandHandler(SrtProcessingWorkflow(
        artifacts=artifacts if artifacts is not None else LocalSubtitleArtifactStore(),
        codec=codec if codec is not None else Pysubs2SrtCodec(),
        clock=clock if clock is not None else SystemClock(), output_root=output_root))
