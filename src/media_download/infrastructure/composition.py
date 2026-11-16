"""Explicit production download assembly and read-only completion verification."""

from pathlib import Path

from archive_core.application import build_asset_workspace
from archive_core.interfaces.bilingual import MediaBoundaryDTO
from infrastructure.infrastructure.artifacts import read_json, write_json
from infrastructure.infrastructure.config import load_yaml_config
from infrastructure.infrastructure.process import run_process
from .media_boundary import probe_video_boundary
from media_download.application import DownloadAssetVideoService
from media_download.domain import DownloadPolicy, MediaRef, DownloadInput
from .artifacts import LocalDownloadArtifactStore
from .checksum import Sha256ChecksumCalculator
from .resolver import build_default_resolver_registry
from .yt_dlp import YtDlpDownloader


class LocalDownloadHandler:
    def __init__(self, *, output_root, service=None, process_runner=None):
        self.root = str(Path(output_root).resolve())
        self.process = process_runner or run_process
        self.service = service or DownloadAssetVideoService(
            build_default_resolver_registry(), YtDlpDownloader(process_runner=self.process),
            Sha256ChecksumCalculator(), LocalDownloadArtifactStore(), self.root)

    def verify(self, command):
        workspace = build_asset_workspace(command.asset_id, self.root)
        source = DownloadInput(command.asset_id, MediaRef.from_dict(read_json(workspace / "media_ref.json")))
        artifact = self.service._validate_existing_artifact(source, str(workspace / "video.mp4"), str(workspace / "download_manifest.json"))
        if command.height is not None and artifact.format_selector != f"best[ext=mp4][height={command.height}]":
            raise ValueError("downloaded media selector changed")
        if command.prepare_boundary:
            boundary = MediaBoundaryDTO.from_dict(read_json(workspace / "media_boundary.json"))
            if boundary.video_sha256 != artifact.checksum_value:
                raise ValueError("media boundary belongs to another video")
        return artifact

    def handle(self, command):
        config = load_yaml_config()["download"]
        selector = config["format"] if command.height is None else f"best[ext=mp4][height={command.height}]"
        result = self.service.execute_asset(command.asset_id, DownloadPolicy(
            format_selector=selector, fallback_format="", retries=config["retries"], rate_limit=config["rate_limit"]))
        if command.prepare_boundary:
            workspace = build_asset_workspace(command.asset_id, self.root)
            boundary_path = workspace / "media_boundary.json"
            if not boundary_path.exists():
                boundary, _ = probe_video_boundary(workspace / "video.mp4", self.process)
                write_json(boundary_path, boundary.to_dict())
        self.verify(command)
        return result
