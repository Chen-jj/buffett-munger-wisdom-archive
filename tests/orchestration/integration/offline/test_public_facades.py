"""Public production entry points with fake network/encoding boundaries."""

from dataclasses import replace
from functools import partial
from hashlib import sha256
from pathlib import Path
import json
import subprocess

import pytest

from archive_core.application import build_asset_workspace
from archive_core.domain import AssetId
from archive_core.interfaces.bilingual import MediaBoundaryDTO
from acquisition.domain import (AcquisitionResult, AcquisitionTarget, Chapter, MediaReference, Provenance,
                                SourceMetadata, Transcript, TranscriptParagraph)
from acquisition.interfaces import AcquisitionCommand, build_acquisition_handler
from media_download.application import DownloadAssetVideoService, ResolverRegistry
from media_download.domain import DownloaderResult
from media_download.infrastructure import DirectUrlResolver, LocalDownloadArtifactStore, Sha256ChecksumCalculator
from media_download.interfaces import DownloadCommand, MediaDerivationCommand, build_download_handler, build_media_derivation_handler
from infrastructure.infrastructure.process import ProcessResult, run_process
from orchestration.domain.models import MediaSelection, PipelineCommand
from orchestration.infrastructure.local import LocalAssetLock, LocalRunStore, AssetBusyError


PARENT = AssetId("cnbc", "2000", "morning")
DERIVED = AssetId("cnbc", "2000", "morning-ch6-7")


class Crawler:
    calls = 0

    def discover(self, request):
        self.calls += 1
        return [AcquisitionTarget(PARENT, "https://example.test/video")]

    def fetch(self, target):
        self.calls += 1
        return AcquisitionResult(PARENT, target.fetch_url, MediaReference("direct_url", "https://example.test/media.mp4"),
                                 Transcript(tuple(Chapter(number, f"Chapter {number}", (TranscriptParagraph("Hello world.", "BUFFETT"),))
                                                  for number in (6, 7))), SourceMetadata("metadata.v1", "Test", None),
                                 Provenance("fake-boundary", "2026-11-05T00:00:00Z", True))


class Registry:
    def __init__(self):
        self.crawler = Crawler()

    def select(self, request):
        return self.crawler


class Downloader:
    calls = 0

    def download(self, plan):
        self.calls += 1
        Path(plan.output_path).write_bytes(b"parent-video")
        return DownloaderResult("fake", "1", ("fake-download",), plan.policy.format_selector)


class Encoder:
    def __init__(self):
        self.calls = []

    def __call__(self, command, **kwargs):
        argv = tuple(map(str, command))
        self.calls.append(argv)
        if "-show_format" in argv and "-show_frames" not in argv:
            stdout = json.dumps({"format": {"duration": "10"}, "streams": [{"codec_type": "video", "height": 360, "width": 640}]})
        elif "-show_frames" in argv:
            stdout = json.dumps({"format": {"duration": "1.0"}, "streams": [{"height": 360, "width": 640}], "frames": [
                {"best_effort_timestamp_time": f"{number / 25:.6f}"} for number in range(25)]})
        elif "-select_streams" in argv and "a" in argv:
            stdout = json.dumps({"streams": [{"codec_name": "aac", "start_time": "0.000000"}]})
        elif "-version" in argv:
            stdout = "ffmpeg fake version\n"
        else:
            Path(argv[-1]).write_bytes(b"derived-video")
            stdout = ""
        return ProcessResult(argv, 0, stdout, "")


def prepare(tmp_path):
    registry = Registry()
    acquisition = build_acquisition_handler(output_root=tmp_path, registry=registry)
    command = AcquisitionCommand(PARENT, "test:source")
    assert acquisition.handle(command).status == "succeeded"
    resolver = ResolverRegistry()
    resolver.register(DirectUrlResolver())
    downloader = Downloader()
    service = DownloadAssetVideoService(resolver, downloader, Sha256ChecksumCalculator(), LocalDownloadArtifactStore(), str(tmp_path))
    download = build_download_handler(output_root=tmp_path, service=service)
    download.handle(DownloadCommand(PARENT))
    return acquisition, command, registry, download, downloader


def snapshot(root):
    return {str(path): (path.read_bytes(), path.stat().st_mtime_ns) for path in Path(root).rglob("*") if path.is_file()}


def test_acquisition_and_download_receipt_reuse_are_zero_write(tmp_path):
    acquisition, command, registry, download, downloader = prepare(tmp_path)
    before = snapshot(tmp_path)
    calls = registry.crawler.calls, downloader.calls
    assert acquisition.handle(command).status == "reused"
    assert download.handle(DownloadCommand(PARENT)).plan.action.value == "skip"
    assert snapshot(tmp_path) == before
    assert (registry.crawler.calls, downloader.calls) == calls
    meta = build_asset_workspace(PARENT, tmp_path) / "meta.json"
    meta.write_text("{}")
    with pytest.raises(ValueError):
        acquisition.verify(command)


def test_download_completes_slow_boundary_scan_without_redownloading(tmp_path):
    prepare(tmp_path)
    workspace = build_asset_workspace(PARENT, tmp_path)
    before = snapshot(workspace)
    video_path = workspace / "video.mp4"
    boundary_path = workspace / "media_boundary.json"
    scans = []

    def slow_probe(argv, *, timeout, **kwargs):
        assert "-show_frames" in argv and argv[-1] == str(video_path)
        scans.append(argv)
        if timeout is not None and timeout < 301:
            raise subprocess.TimeoutExpired(argv, timeout)
        return subprocess.CompletedProcess(argv, 0, json.dumps({
            "format": {"duration": "1.0"},
            "streams": [{"width": 640, "height": 360}],
            "frames": [{"best_effort_timestamp_time": time} for time in ("0.0", "0.032001", "0.089")],
        }), "")

    download = build_download_handler(output_root=tmp_path, process_runner=partial(run_process, runner=slow_probe))
    command = DownloadCommand(PARENT, prepare_boundary=True)
    assert download.handle(command).plan.action.value == "skip"
    assert MediaBoundaryDTO.from_dict(json.loads(boundary_path.read_text())) == MediaBoundaryDTO(
        sha256(video_path.read_bytes()).hexdigest(), 1000, (0, 32001, 89000),
    )
    after = snapshot(workspace)
    assert after.keys() - before.keys() == {str(boundary_path)}
    assert {path: after[path] for path in before} == before
    assert download.handle(command).plan.action.value == "skip"
    assert len(scans) == 1 and snapshot(workspace) == after


def test_production_derivation_keeps_parent_and_binds_exact_source_range(tmp_path):
    prepare(tmp_path)
    parent = build_asset_workspace(PARENT, tmp_path)
    parent_before = snapshot(parent)
    encoder = Encoder()
    handler = build_media_derivation_handler(output_root=tmp_path, process_runner=encoder)
    command = MediaDerivationCommand(PARENT, DERIVED, 1000, 2000, (6, 7))
    result = handler.handle(command)
    assert result["status"] == "succeeded"
    derived = build_asset_workspace(DERIVED, tmp_path)
    manifest = json.loads((derived / "media_derivation_manifest.json").read_text())
    assert manifest["identity"]["request"]["time_mapping"] == {"source_start_ms": 1000, "derived_start_ms": 0, "duration_ms": 1000}
    assert manifest["identity"]["audio_codec"] == "aac"
    assert manifest["identity"]["duration_tolerance_ms"] == 50
    assert snapshot(parent) == parent_before
    before = snapshot(tmp_path)
    calls = len(encoder.calls)
    assert handler.handle(command)["status"] == "reused"
    assert snapshot(tmp_path) == before
    assert len(encoder.calls) == calls
    with pytest.raises(ValueError, match="request changed"):
        handler.verify(replace(command, start_ms=999))


def test_derivation_without_parent_cannot_generate_or_fake_source(tmp_path):
    encoder = Encoder()
    handler = build_media_derivation_handler(output_root=tmp_path, process_runner=encoder)
    with pytest.raises(FileNotFoundError):
        handler.handle(MediaDerivationCommand(PARENT, DERIVED, 1000, 2000, (6, 7)))
    assert not encoder.calls


def test_advisory_asset_lock_competition_and_retained_file(tmp_path):
    command = PipelineCommand(DERIVED, PARENT, "test:source", str(tmp_path), MediaSelection(0, 1000, (6, 7)))
    lock = LocalAssetLock()
    with lock.acquire(command):
        with pytest.raises(AssetBusyError, match="asset_busy"):
            with lock.acquire(command):
                pytest.fail("competing lock was granted")
    with lock.acquire(command):
        assert (build_asset_workspace(DERIVED, tmp_path) / ".pipeline.lock").exists()
        assert (build_asset_workspace(PARENT, tmp_path) / ".pipeline.lock").exists()
