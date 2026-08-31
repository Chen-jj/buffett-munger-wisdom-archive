"""Live integration test: acquisition -> media_download with a stubbed downloader.

Crawls real source pages (CNBC 2000 annual meeting, one YouTube video), writes
the acquisition contract files, then exercises the media download service end
to end with a port stand-in that fulfills the downloader contract without
running yt-dlp. Artifacts are asserted at two levels:

- strict: byte-exact values for every deterministic field (identity, contract
  shapes, checksum of the fixed stub payload, generated yt-dlp command);
- structural: presence/type/pattern checks for volatile fields (page titles,
  timestamps, provider playback URLs).
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path

import pytest

from archive_core.application import build_asset_workspace
from archive_core.domain import AssetId

from acquisition.application import AcquireUseCase, CrawlerRegistry
from acquisition.domain import AcquisitionRequest
from acquisition.infrastructure import (
    CnbcCrawler,
    LocalAcquisitionArtifactWriter,
    YoutubeCrawler,
)
from media_download.application import DownloadAssetVideoService
from media_download.domain import (
    MANIFEST_SCHEMA,
    DownloadAction,
    DownloaderResult,
    DownloadPlan,
)
from media_download.infrastructure import (
    LocalDownloadArtifactStore,
    Sha256ChecksumCalculator,
    YtDlpDownloader,
    build_default_resolver_registry,
)


STUB_PAYLOAD = b"stub-video-payload"
STUB_SIZE = len(STUB_PAYLOAD)
STUB_SHA256 = hashlib.sha256(STUB_PAYLOAD).hexdigest()

YOUTUBE_URL = "https://www.youtube.com/watch?v=QQOWQcnNmr0"
YOUTUBE_VIDEO_ID = "QQOWQcnNmr0"
YOUTUBE_RESOLVED_URL = f"https://www.youtube.com/watch?v={YOUTUBE_VIDEO_ID}"

DEFAULT_FORMAT_SELECTOR = (
    "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
)


class StubDownloader:
    """MediaDownloader port stand-in: no yt-dlp, but the output file appears."""

    def __init__(self) -> None:
        self.plans: list[DownloadPlan] = []

    def download(self, plan: DownloadPlan) -> DownloaderResult:
        self.plans.append(plan)
        output = Path(plan.output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(STUB_PAYLOAD)
        return DownloaderResult(
            downloader_name="yt-dlp",
            downloader_version="mocked",
            command=("yt-dlp", plan.media_url),
            format_selector=plan.policy.format_selector,
        )


def _require_live_dependencies() -> None:
    if os.environ.get("RUN_REAL_NETWORK") != "1":
        pytest.skip("set RUN_REAL_NETWORK=1 to hit live source pages")
    for package in ("requests", "bs4"):
        pytest.importorskip(package)


def _download_service(
    output_root: Path, downloader: StubDownloader
) -> DownloadAssetVideoService:
    return DownloadAssetVideoService(
        resolver_registry=build_default_resolver_registry(),
        downloader=downloader,
        checksum=Sha256ChecksumCalculator(),
        artifacts=LocalDownloadArtifactStore(),
        output_root=str(output_root),
    )


def _assert_iso_timestamp(value: object) -> None:
    assert isinstance(value, str)
    datetime.fromisoformat(str(value))  # raises on invalid timestamps


def _assert_strict_manifest_section(
    manifest: dict,
    *,
    asset: dict[str, str],
    media: dict[str, str],
    output_path: str,
) -> None:
    assert manifest["schema_version"] == MANIFEST_SCHEMA
    assert manifest["asset"] == asset
    assert manifest["media"] == media
    assert manifest["artifact"]["path"] == output_path
    assert manifest["artifact"]["size_bytes"] == STUB_SIZE
    assert manifest["artifact"]["checksum"] == {
        "algorithm": "sha256",
        "value": STUB_SHA256,
    }
    assert manifest["download"]["status"] == "downloaded"
    assert manifest["download"]["format"] == DEFAULT_FORMAT_SELECTOR
    assert manifest["download"]["downloader"] == {
        "name": "yt-dlp",
        "version": "mocked",
    }
    _assert_iso_timestamp(manifest["download"]["downloaded_at"])


def _assert_strict_yt_dlp_command(plan: DownloadPlan) -> None:
    assert (
        YtDlpDownloader().build_command(
            plan, format_selector=plan.policy.format_selector
        )
        == (
            "yt-dlp",
            "-f",
            DEFAULT_FORMAT_SELECTOR,
            "--merge-output-format",
            "mp4",
            "--retries",
            "3",
            "--continue",
            "-o",
            plan.output_path,
            "--no-check-certificates",
            plan.media_url,
        )
    )


@pytest.mark.live
def test_cnbc_2000_crawl_feeds_download_service_end_to_end(tmp_path: Path) -> None:
    _require_live_dependencies()
    output_root = tmp_path / "output"
    registry = CrawlerRegistry([CnbcCrawler(delay_seconds=1.0)])
    writer = LocalAcquisitionArtifactWriter(root=output_root)

    results = AcquireUseCase(registry=registry, writer=writer).execute(
        AcquisitionRequest("cnbc:2000")
    )

    sessions = {result.asset_id.item: result for result in results}
    assert "morning" in sessions
    assert "afternoon" in sessions

    downloader = StubDownloader()
    service = _download_service(output_root, downloader)

    for item in ("morning", "afternoon"):
        asset_id = AssetId("cnbc", "2000", item)
        crawled = sessions[item]
        workspace = build_asset_workspace(asset_id, output_root)

        # --- acquisition contract files (strict cross-check against crawl) ---
        assert workspace.name == f"cnbc_2000_{item}"
        meta = json.loads(
            (workspace / "meta.json").read_text(encoding="utf-8")
        )
        assert meta["schema_version"] == "acquisition.source-metadata.v1"
        assert (
            meta["asset_id"] == {"source": "cnbc", "group": "2000", "item": item}
        )
        assert meta["provenance"]["crawler"] == "cnbc"
        assert meta["provenance"]["transcript_available"] is True
        _assert_iso_timestamp(meta["provenance"]["fetched_at"])
        assert isinstance(meta["title"], str) and "2000" in meta["title"]
        assert isinstance(meta["video_id"], str) and meta["video_id"]
        media_ref_on_disk = json.loads(
            (workspace / "media_ref.json").read_text(encoding="utf-8")
        )
        assert media_ref_on_disk == crawled.media_ref.to_dict()
        assert media_ref_on_disk["kind"] == "page_url"
        assert media_ref_on_disk["value"].startswith(
            "https://buffett.cnbc.com/video/2000/"
        )
        assert crawled.transcript is not None
        assert len(crawled.transcript.chapters) > 0
        assert crawled.transcript.length > 1000
        assert "=== Chapter" in (
            workspace / "transcript.txt"
        ).read_text(encoding="utf-8")

        # --- download execution with stubbed downloader ---
        execution = service.execute_asset(asset_id)

        assert execution.plan.action == DownloadAction.DOWNLOAD
        assert execution.plan.reason == "download required"
        assert execution.plan.media_ref.value == media_ref_on_disk["value"]
        assert execution.plan.media_url.startswith("https://")
        assert "m3u8" in execution.plan.media_url
        assert execution.plan.media_url != media_ref_on_disk["value"]
        assert execution.manifest_path == str(
            workspace / "download_manifest.json"
        )
        assert (workspace / "video.mp4").read_bytes() == STUB_PAYLOAD

        manifest = json.loads(
            Path(execution.manifest_path).read_text(encoding="utf-8")
        )
        _assert_strict_manifest_section(
            manifest,
            asset={"source": "cnbc", "group": "2000", "item": item},
            media={
                "kind": "page_url",
                "ref_value": media_ref_on_disk["value"],
                "resolved_url": execution.plan.media_url,
            },
            output_path=str(workspace / "video.mp4"),
        )
        _assert_strict_yt_dlp_command(execution.plan)

    assert len(downloader.plans) == 2


@pytest.mark.live
def test_youtube_video_crawl_feeds_download_service_end_to_end(
    tmp_path: Path,
) -> None:
    _require_live_dependencies()
    output_root = tmp_path / "output"
    registry = CrawlerRegistry([YoutubeCrawler()])
    writer = LocalAcquisitionArtifactWriter(root=output_root)

    results = AcquireUseCase(registry=registry, writer=writer).execute(
        AcquisitionRequest(YOUTUBE_URL)
    )

    assert len(results) == 1
    crawled = results[0]
    asset_id = AssetId("youtube", "", YOUTUBE_VIDEO_ID)
    assert crawled.asset_id == asset_id

    workspace = build_asset_workspace(asset_id, output_root)

    # --- acquisition contract files (strict) ---
    assert workspace.name == "youtube_qqowqcnnmr0"
    meta = json.loads(
        (workspace / "meta.json").read_text(encoding="utf-8")
    )
    assert meta["schema_version"] == "acquisition.source-metadata.v1"
    assert meta["asset_id"] == {
        "source": "youtube",
        "group": "",
        "item": YOUTUBE_VIDEO_ID,
    }
    assert meta["provenance"]["crawler"] == "youtube"
    assert meta["provenance"]["transcript_available"] is False
    _assert_iso_timestamp(meta["provenance"]["fetched_at"])
    assert isinstance(meta["title"], str) and meta["title"]
    assert meta["video_id"] == YOUTUBE_VIDEO_ID
    assert meta["source_ref"] == YOUTUBE_URL
    assert (
        (workspace / "media_ref.json").read_text(encoding="utf-8")
        == json.dumps(
            {"kind": "embed_id", "value": YOUTUBE_VIDEO_ID, "extra": {}},
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    assert not (workspace / "transcript.txt").exists()
    assert not (workspace / "chapters.json").exists()

    # --- download execution with stubbed downloader ---
    downloader = StubDownloader()
    service = _download_service(output_root, downloader)
    execution = service.execute_asset(asset_id)

    assert execution.plan.action == DownloadAction.DOWNLOAD
    assert execution.plan.media_url == YOUTUBE_RESOLVED_URL
    assert execution.manifest_path == str(workspace / "download_manifest.json")
    assert (workspace / "video.mp4").read_bytes() == STUB_PAYLOAD

    manifest = json.loads(
        Path(execution.manifest_path).read_text(encoding="utf-8")
    )
    _assert_strict_manifest_section(
        manifest,
        asset={"source": "youtube", "group": "", "item": YOUTUBE_VIDEO_ID},
        media={
            "kind": "embed_id",
            "ref_value": YOUTUBE_VIDEO_ID,
            "resolved_url": YOUTUBE_RESOLVED_URL,
        },
        output_path=str(workspace / "video.mp4"),
    )
    _assert_strict_yt_dlp_command(execution.plan)
    assert len(downloader.plans) == 1
