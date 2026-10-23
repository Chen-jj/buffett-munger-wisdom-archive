from __future__ import annotations

from srt_processing import SrtProcessingCommand, SrtProcessingCommandHandler
from srt_processing.application import SrtProcessingWorkflow
from srt_processing.infrastructure import (
    FfprobeMediaProbe,
    LocalSubtitleArtifactStore,
    Pysubs2SrtCodec,
    SystemClock,
    build_srt_processing_handler,
)

from tests.srt_processing.workflow_fakes import WorkflowCase


def test_default_composition_constructs_local_adapters_without_probing() -> None:
    handler = build_srt_processing_handler(output_root="/unused/output", ffprobe_executable="/unused/ffprobe")
    assert isinstance(handler, SrtProcessingCommandHandler)
    assert isinstance(handler.workflow, SrtProcessingWorkflow)
    assert isinstance(handler.workflow.artifacts, LocalSubtitleArtifactStore)
    assert isinstance(handler.workflow.codec, Pysubs2SrtCodec)
    assert isinstance(handler.workflow.clock, SystemClock)
    assert isinstance(handler.workflow.probe, FfprobeMediaProbe)
    assert handler.workflow.probe.executable == "/unused/ffprobe"
    assert handler.workflow.output_root == "/unused/output"


def test_explicit_ports_compose_a_complete_offline_handler() -> None:
    case = WorkflowCase()
    handler = build_srt_processing_handler(
        output_root=case.root, artifacts=case.store, probe=case.probe,
        codec=case.codec, clock=case.clock,
        segmenter=case.segmenter,
    )
    assert handler.workflow.artifacts is case.store and handler.workflow.probe is case.probe
    assert case.probe.calls == []
    command = SrtProcessingCommand(case.asset.value, case.paths["transcription_manifest"],
                                   case.paths["translation_manifest"])
    assert handler.handle(command).status == "succeeded"
    before = dict(case.store.files)
    assert handler.handle(command).status == "reused"
    assert case.store.files == before
