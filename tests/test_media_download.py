from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from archive_core.domain import SessionId
from infrastructure.infrastructure.process import ProcessResult
from media_download.application import DownloadSessionVideoService
from media_download.domain import (
    DownloadAction,
    DownloadedArtifact,
    DownloadPlan,
    DownloaderResult,
    DownloadPolicy,
    MediaSource,
)
from media_download.infrastructure import (
    LocalDownloadArtifactStore,
    Sha256ChecksumCalculator,
    YtDlpDownloader,
    extract_cnbc_playback_url,
)


class FakeResolver:
    def __init__(self, resolved_url: str = "https://media.example/video.m3u8") -> None:
        self.resolved_url = resolved_url
        self.calls: list[MediaSource] = []

    def resolve(self, source: MediaSource) -> str:
        self.calls.append(source)
        return self.resolved_url


class FakeDownloader:
    def __init__(self, payload: bytes = b"downloaded video") -> None:
        self.payload = payload
        self.plans = []

    def download(self, plan):
        self.plans.append(plan)
        Path(plan.output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(plan.output_path).write_bytes(self.payload)
        return DownloaderResult(
            downloader_name="fake-dlp",
            downloader_version="1.0",
            command=("fake-dlp", plan.media_url),
            format_selector=plan.policy.format_selector,
        )


class MediaDownloadTests(unittest.TestCase):
    def test_extract_cnbc_playback_url_decodes_legacy_html_payload(self) -> None:
        html = r'{"playbackURL":"\/\/cdn.example.com\/path\/video.m3u8"}'

        result = extract_cnbc_playback_url(
            html,
            fallback_url="https://page.example/video",
        )

        self.assertEqual(result, "https://cdn.example.com/path/video.m3u8")

    def test_extract_cnbc_playback_url_falls_back_to_source_page(self) -> None:
        result = extract_cnbc_playback_url(
            "<html></html>",
            fallback_url="https://page.example/video",
        )

        self.assertEqual(result, "https://page.example/video")

    def test_execute_skips_existing_video_without_writing_manifest(self) -> None:
        with TemporaryDirectory() as tmp:
            source = _source()
            video_path = Path(tmp) / "output" / "1994" / "morning" / "video.mp4"
            video_path.parent.mkdir(parents=True)
            video_path.write_bytes(b"existing video")
            resolver = FakeResolver()
            downloader = FakeDownloader()
            service = DownloadSessionVideoService(
                resolver=resolver,
                downloader=downloader,
                checksum=Sha256ChecksumCalculator(),
                artifacts=LocalDownloadArtifactStore(),
                output_root=str(Path(tmp) / "output"),
            )

            result = service.execute(source)

            self.assertEqual(result.plan.action, DownloadAction.SKIP)
            self.assertEqual(result.plan.media_url, source.page_url)
            self.assertEqual(resolver.calls, [])
            self.assertEqual(downloader.plans, [])
            self.assertIsNone(result.artifact)
            self.assertIsNone(result.manifest_path)
            self.assertFalse(
                (video_path.parent / "download_manifest.json").exists()
            )

    def test_execute_skip_preserves_existing_manifest_provenance(self) -> None:
        with TemporaryDirectory() as tmp:
            source = _source()
            video_path = Path(tmp) / "output" / "1994" / "morning" / "video.mp4"
            manifest_path = video_path.parent / "download_manifest.json"
            video_path.parent.mkdir(parents=True)
            video_path.write_bytes(b"existing video")
            original_artifact = DownloadedArtifact(
                source=source,
                media_url="https://media.example/original.m3u8",
                output_path=str(video_path),
                format_selector="bestvideo",
                size_bytes=len(b"existing video"),
                checksum_algorithm="sha256",
                checksum_value="original-checksum",
                downloader_name="yt-dlp",
                downloader_version="2026.01.01",
                downloaded_at="2026-01-01T00:00:00+00:00",
                status="downloaded",
            )
            manifest_path.write_text(
                json.dumps(original_artifact.to_manifest_dict(), indent=2),
                encoding="utf-8",
            )
            service = DownloadSessionVideoService(
                resolver=FakeResolver(),
                downloader=FakeDownloader(),
                checksum=Sha256ChecksumCalculator(),
                artifacts=LocalDownloadArtifactStore(),
                output_root=str(Path(tmp) / "output"),
            )

            result = service.execute(source)

            self.assertEqual(result.plan.action, DownloadAction.SKIP)
            self.assertEqual(result.manifest_path, str(manifest_path))
            self.assertIsNotNone(result.artifact)
            self.assertEqual(
                result.artifact.media_url,
                "https://media.example/original.m3u8",
            )
            self.assertEqual(result.artifact.downloader_name, "yt-dlp")
            self.assertEqual(result.artifact.downloader_version, "2026.01.01")
            self.assertEqual(
                json.loads(manifest_path.read_text(encoding="utf-8")),
                original_artifact.to_manifest_dict(),
            )

    def test_execute_downloads_video_and_writes_manifest_provenance(self) -> None:
        with TemporaryDirectory() as tmp:
            source = _source()
            resolver = FakeResolver("https://media.example/resolved.m3u8")
            downloader = FakeDownloader(payload=b"new video")
            service = DownloadSessionVideoService(
                resolver=resolver,
                downloader=downloader,
                checksum=Sha256ChecksumCalculator(),
                artifacts=LocalDownloadArtifactStore(),
                output_root=str(Path(tmp) / "output"),
            )

            result = service.execute(source)

            self.assertEqual(result.plan.action, DownloadAction.DOWNLOAD)
            self.assertEqual(result.plan.media_url, "https://media.example/resolved.m3u8")
            self.assertEqual(len(resolver.calls), 1)
            self.assertEqual(len(downloader.plans), 1)
            self.assertTrue(Path(result.plan.output_path).exists())
            manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema_version"], "media-download.manifest.v1")
            self.assertEqual(manifest["source"]["media_url"], result.plan.media_url)
            self.assertEqual(manifest["download"]["format"], result.plan.policy.format_selector)
            self.assertEqual(manifest["download"]["downloader"]["version"], "1.0")
            self.assertEqual(manifest["artifact"]["size_bytes"], len(b"new video"))
            self.assertEqual(manifest["artifact"]["checksum"]["algorithm"], "sha256")

    def test_dry_run_returns_plan_without_downloading_or_manifest(self) -> None:
        with TemporaryDirectory() as tmp:
            source = _source()
            downloader = FakeDownloader()
            service = DownloadSessionVideoService(
                resolver=FakeResolver("https://media.example/dry-run.m3u8"),
                downloader=downloader,
                checksum=Sha256ChecksumCalculator(),
                artifacts=LocalDownloadArtifactStore(),
                output_root=str(Path(tmp) / "output"),
            )

            result = service.execute(source, DownloadPolicy(dry_run=True))

            self.assertEqual(result.plan.action, DownloadAction.DOWNLOAD)
            self.assertEqual(result.plan.reason, "dry-run")
            self.assertIsNone(result.artifact)
            self.assertIsNone(result.manifest_path)
            self.assertEqual(downloader.plans, [])
            self.assertFalse(Path(result.plan.output_path).exists())

    def test_overwrite_existing_video_downloads_again(self) -> None:
        with TemporaryDirectory() as tmp:
            source = _source()
            video_path = Path(tmp) / "output" / "1994" / "morning" / "video.mp4"
            video_path.parent.mkdir(parents=True)
            video_path.write_bytes(b"old")
            downloader = FakeDownloader(payload=b"replacement")
            service = DownloadSessionVideoService(
                resolver=FakeResolver("https://media.example/replacement.m3u8"),
                downloader=downloader,
                checksum=Sha256ChecksumCalculator(),
                artifacts=LocalDownloadArtifactStore(),
                output_root=str(Path(tmp) / "output"),
            )

            result = service.execute(source, DownloadPolicy(overwrite=True))

            self.assertEqual(result.plan.action, DownloadAction.DOWNLOAD)
            self.assertEqual(len(downloader.plans), 1)
            self.assertEqual(video_path.read_bytes(), b"replacement")

    def test_yt_dlp_adapter_uses_fallback_without_real_download(self) -> None:
        calls: list[tuple[str, ...]] = []

        def runner(command, **kwargs):
            normalized = tuple(str(part) for part in command)
            calls.append(normalized)
            if normalized == ("yt-dlp", "--version"):
                return ProcessResult(normalized, 0, "2026.01.01\n", "")
            if "-f" in normalized and normalized[normalized.index("-f") + 1] == "best":
                return ProcessResult(normalized, 0, "", "")
            return ProcessResult(normalized, 1, "", "primary failed")

        plan = _download_plan(
            policy=DownloadPolicy(format_selector="bestvideo", rate_limit="1M"),
        )
        adapter = YtDlpDownloader(process_runner=runner)

        result = adapter.download(plan)

        self.assertEqual(result.downloader_version, "2026.01.01")
        self.assertEqual(result.format_selector, "best")
        self.assertEqual(calls[0][calls[0].index("-f") + 1], "bestvideo")
        self.assertEqual(calls[1][calls[1].index("-f") + 1], "best")
        self.assertIn("--continue", calls[1])
        self.assertIn("--limit-rate", calls[1])
        self.assertEqual(calls[1][-1], "https://media.example/video.m3u8")

    def test_yt_dlp_adapter_forces_overwrite_without_resume_flag(self) -> None:
        calls: list[tuple[str, ...]] = []

        def runner(command, **kwargs):
            normalized = tuple(str(part) for part in command)
            calls.append(normalized)
            if normalized == ("yt-dlp", "--version"):
                return ProcessResult(normalized, 0, "2026.01.01\n", "")
            return ProcessResult(normalized, 0, "", "")

        plan = _download_plan(policy=DownloadPolicy(overwrite=True))
        adapter = YtDlpDownloader(process_runner=runner)

        result = adapter.download(plan)

        self.assertEqual(result.downloader_version, "2026.01.01")
        self.assertIn("--force-overwrites", calls[0])
        self.assertNotIn("--continue", calls[0])
        self.assertEqual(calls[0][-1], "https://media.example/video.m3u8")


def _source() -> MediaSource:
    return MediaSource(
        source="cnbc",
        session_id=SessionId(1994, "morning"),
        page_url="https://buffett.cnbc.com/video/1994/morning-session",
    )


def _download_plan(policy: DownloadPolicy) -> DownloadPlan:
    source = _source()
    return DownloadPlan(
        source=source,
        media_url="https://media.example/video.m3u8",
        output_path="output/1994/morning/video.mp4",
        manifest_path="output/1994/morning/download_manifest.json",
        policy=policy,
        action=DownloadAction.DOWNLOAD,
        reason="test",
    )


if __name__ == "__main__":
    unittest.main()
