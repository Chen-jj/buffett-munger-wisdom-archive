"""Use cases for planning and executing resumable media downloads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePath

from archive_core.application import build_session_workspace
from archive_core.domain import ArtifactType
from media_download.domain import (
    DownloadAction,
    DownloadedArtifact,
    DownloaderResult,
    DownloadPlan,
    DownloadPolicy,
    MediaSource,
)

from .ports import (
    ChecksumCalculator,
    DownloadArtifactStore,
    MediaDownloader,
    MediaUrlResolver,
)


DOWNLOAD_MANIFEST_FILENAME = "download_manifest.json"


@dataclass(frozen=True)
class DownloadExecutionResult:
    """Application result for a planned or executed download."""

    plan: DownloadPlan
    artifact: DownloadedArtifact | None = None
    manifest_path: str | None = None


@dataclass(frozen=True)
class DownloadSessionVideoService:
    """Plan and execute one session video download."""

    resolver: MediaUrlResolver
    downloader: MediaDownloader
    checksum: ChecksumCalculator
    artifacts: DownloadArtifactStore
    output_root: str = "output"

    def plan(
        self,
        source: MediaSource,
        policy: DownloadPolicy | None = None,
    ) -> DownloadPlan:
        selected_policy = policy or DownloadPolicy()
        output_path, manifest_path = self._paths_for(source)

        if self.artifacts.exists(output_path) and not selected_policy.overwrite:
            return DownloadPlan(
                source=source,
                media_url=source.page_url,
                output_path=output_path,
                manifest_path=manifest_path,
                policy=selected_policy,
                action=DownloadAction.SKIP,
                reason="output already exists",
            )

        media_url = self.resolver.resolve(source)
        reason = "dry-run" if selected_policy.dry_run else "download required"
        return DownloadPlan(
            source=source,
            media_url=media_url,
            output_path=output_path,
            manifest_path=manifest_path,
            policy=selected_policy,
            action=DownloadAction.DOWNLOAD,
            reason=reason,
        )

    def execute(
        self,
        source: MediaSource,
        policy: DownloadPolicy | None = None,
    ) -> DownloadExecutionResult:
        plan = self.plan(source, policy)
        if plan.policy.dry_run:
            return DownloadExecutionResult(plan=plan)

        if plan.action == DownloadAction.SKIP:
            if not self.artifacts.exists(plan.manifest_path):
                return DownloadExecutionResult(plan=plan)
            artifact = self.artifacts.read_manifest(plan.manifest_path)
            return DownloadExecutionResult(
                plan=plan,
                artifact=artifact,
                manifest_path=plan.manifest_path,
            )

        downloader_result = self.downloader.download(plan)
        artifact = self._artifact_from_download(plan, downloader_result)
        manifest_path = self.artifacts.write_manifest(plan.manifest_path, artifact)
        return DownloadExecutionResult(
            plan=plan,
            artifact=artifact,
            manifest_path=manifest_path,
        )

    def _paths_for(self, source: MediaSource) -> tuple[str, str]:
        workspace = build_session_workspace(self.output_root, source.session_id)
        output_path = workspace.artifact_path(ArtifactType.SOURCE_VIDEO)
        manifest_path = str(
            PurePath(workspace.workspace_path) / DOWNLOAD_MANIFEST_FILENAME
        )
        return output_path, manifest_path

    def _artifact_from_download(
        self,
        plan: DownloadPlan,
        downloader_result: DownloaderResult,
    ) -> DownloadedArtifact:
        return DownloadedArtifact(
            source=plan.source,
            media_url=plan.media_url,
            output_path=plan.output_path,
            format_selector=downloader_result.format_selector,
            size_bytes=self.artifacts.size(plan.output_path),
            checksum_algorithm="sha256",
            checksum_value=self.checksum.sha256(plan.output_path),
            downloader_name=downloader_result.downloader_name,
            downloader_version=downloader_result.downloader_version,
            downloaded_at=_utc_now(),
            status="downloaded",
        )


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()
