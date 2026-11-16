from srt_processing.interfaces.workflow import build_srt_processing_handler
from srt_processing.interfaces.source_chunking import build_source_chunking_handler
from srt_processing.infrastructure.local import LocalSubtitleArtifactStore
from srt_processing.infrastructure.codec import Pysubs2SrtCodec


def test_default_export_composition_constructs_current_local_adapters_without_probing(tmp_path):
    target = tmp_path / "not-created"
    handler = build_srt_processing_handler(output_root=str(target))
    assert isinstance(handler.workflow.artifacts, LocalSubtitleArtifactStore)
    assert isinstance(handler.workflow.codec, Pysubs2SrtCodec)
    assert not target.exists()
