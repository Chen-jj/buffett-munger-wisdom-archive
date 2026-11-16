"""Real lightweight store/contract/workflow composition, with syntax model fake."""
from dataclasses import replace
import hashlib
import json
import pytest

from archive_core.application import build_asset_workspace
from archive_core.domain import AssetId
from archive_core.interfaces.transcription import *
from archive_core.interfaces.bilingual import MediaBoundaryDTO
from srt_processing.interfaces.source_chunking import (
    SourceChunkingCommand, build_source_chunking_handler, verify_source_chunking,
)
from srt_processing.application.source_chunking import metadata_bytes


class Analyzer:
    identity = {"engine": "fake-syntax"}
    def analyze(self, words):
        raise AssertionError("short sentence must not call analyzer")


class Clock:
    calls = 0
    def now_utc(self):
        self.calls += 1
        return "2026-11-05T00:00:00Z"


def fixture(tmp_path):
    asset = AssetId("synthetic", "test", "source")
    workspace = build_asset_workspace(asset, tmp_path).resolve()
    workspace.mkdir()
    video = workspace / "video.mp4"
    video.write_bytes(b"fake expensive boundary media")
    sha = hashlib.sha256(video.read_bytes()).hexdigest()
    word = TimedWordDTO("w1", "Yes.", 0, 1000, ("aw1",), (), MatchType.ASR_ONLY, TextSource.ASR, TimingSource.ACOUSTIC_ALIGNMENT)
    sentence = SourceSentenceDTO("s1", "w1", "w1", 0, 1000, "Yes.", None, TextSource.ASR, BoundarySource.ASR_PUNCTUATION, BoundaryStatus.VERIFIED)
    source = SourceAlignmentDTO("en", 2000, (word,), (sentence,), ())
    alignment = workspace / "source_alignment.json"
    alignment.write_bytes(metadata_bytes(source.to_dict()))
    manifest = {"schema_version": "transcription.audio-vad-asr-cache.v1", "asset": {"source": asset.source, "group": asset.group, "item": asset.item},
                "workflow": {"status": "succeeded"}, "records": {
                    "source_alignment": {"status": "succeeded", "path": str(alignment), "size_bytes": alignment.stat().st_size, "sha256": hashlib.sha256(alignment.read_bytes()).hexdigest()},
                    "audio": {"provenance": {"video_sha256": sha}}}}
    (workspace / "transcription_manifest.json").write_bytes(metadata_bytes(manifest))
    (workspace / "media_boundary.json").write_bytes(metadata_bytes(MediaBoundaryDTO(sha, 2000, tuple(range(0, 2000000, 40000))).to_dict()))
    command = SourceChunkingCommand(asset.value, str(workspace / "transcription_manifest.json"), str(workspace / "media_boundary.json"))
    return workspace, command


def test_publication_and_independent_handler_reuse_are_zero_write(tmp_path):
    workspace, command = fixture(tmp_path)
    clock = Clock()
    first = build_source_chunking_handler(output_root=str(tmp_path), analyzer=Analyzer(), clock=clock).handle(command)
    assert first.status == "succeeded", first
    assert first.writes == 3 and first.analyzer_calls == 0
    manifest = json.loads((workspace / "source_chunking_manifest.json").read_bytes())
    plan = json.loads((workspace / "source_chunks.json").read_bytes())
    assert manifest["identity"]["policy"] == plan["policy"]
    assert plan["policy"]["english_max_characters"] == 84
    before = {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in workspace.iterdir()}
    second = build_source_chunking_handler(output_root=str(tmp_path), analyzer=Analyzer(), clock=clock).handle(command)
    assert second.status == "reused", second
    assert second.writes == second.analyzer_calls == 0 and clock.calls == 1
    assert before == {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in workspace.iterdir()}


@pytest.mark.parametrize(("legacy_version", "legacy_capacity"), (
    ("english-constituency-two-pass.v1", 42), ("english-typed-cue-dp.v3", 84),
    ("english-typed-cue-dp.v7", 84),
))
def test_legacy_policy_manifest_is_a_readonly_conflict(tmp_path, legacy_version, legacy_capacity):
    workspace, command = fixture(tmp_path)
    handler = build_source_chunking_handler(output_root=str(tmp_path), analyzer=Analyzer(), clock=Clock())
    assert handler.handle(command).status == "succeeded"
    assert verify_source_chunking(command, output_root=str(tmp_path)).status == "reused"
    path = workspace / "source_chunking_manifest.json"
    manifest = json.loads(path.read_bytes())
    manifest["identity"]["policy"].update(version=legacy_version, english_max_characters=legacy_capacity)
    path.write_bytes(metadata_bytes(manifest))
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in workspace.iterdir()}
    assert handler.handle(command).error_category == "artifact_conflict"
    assert verify_source_chunking(command, output_root=str(tmp_path)).error_message == (
        "source chunking manifest policy, analyzer or protection differs"
    )
    assert before == {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in workspace.iterdir()}


def test_corrupt_or_partial_outputs_are_not_silently_regenerated(tmp_path):
    workspace, command = fixture(tmp_path)
    handler = build_source_chunking_handler(output_root=str(tmp_path), analyzer=Analyzer(), clock=Clock())
    (workspace / "source_chunks.json").write_text("{}")
    outcome = handler.handle(command)
    assert outcome.status == "failed" and outcome.error_category == "artifact_conflict"
    assert not (workspace / "source_chunking_manifest.json").exists()
