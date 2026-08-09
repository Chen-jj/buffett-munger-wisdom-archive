"""Use cases for planning and executing resumable media downloads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePath

from archive_core.application import build_asset_workspace
from archive_core.domain import AssetId, ArtifactType, canonical_filename
from media_download.domain import (
    DownloadAction,
    DownloadInput,
    DownloadedArtifact,
    DownloaderResult,
    DownloadPlan,
    DownloadPolicy,
)

from .ports import (
    ChecksumCalculator,
    DownloadArtifactStore,
    MediaDownloader,
    ResolverRegistry,
)


DOWNLOAD_MANIFEST_FILENAME = "download_manifest.json"
MEDIA_REF_FILENAME = "media_ref.json"


@dataclass(frozen=True)
class DownloadExecutionResult:
    """Application result for a planned or executed download."""

    plan: DownloadPlan
    artifact: DownloadedArtifact | None = None
    manifest_path: str | None = None


@dataclass(frozen=True)
class DownloadAssetVideoService:
    """Plan and execute one asset video download."""

    resolver_registry: ResolverRegistry
    downloader: MediaDownloader
    checksum: ChecksumCalculator
    artifacts: DownloadArtifactStore
    output_root: str = "output"

    def plan(
        self,
        input: DownloadInput,
        policy: DownloadPolicy | None = None,
    ) -> DownloadPlan:
        selected_policy = policy or DownloadPolicy()
        output_path, manifest_path = self._paths_for(input.asset_id)

        if self.artifacts.exists(output_path) and not selected_policy.overwrite:
            return DownloadPlan(
                asset_id=input.asset_id,
                media_ref=input.media_ref,
                media_url=input.media_ref.value,
                output_path=output_path,
                manifest_path=manifest_path,
                policy=selected_policy,
                action=DownloadAction.SKIP,
                reason="output already exists",
            )

        media_url = self.resolver_registry.select(input).resolve(input)
        reason = "dry-run" if selected_policy.dry_run else "download required"
        return DownloadPlan(
            asset_id=input.asset_id,
            media_ref=input.media_ref,
            media_url=media_url,
            output_path=output_path,
            manifest_path=manifest_path,
            policy=selected_policy,
            action=DownloadAction.DOWNLOAD,
            reason=reason,
        )

    def execute(
        self,
        input: DownloadInput,
        policy: DownloadPolicy | None = None,
    ) -> DownloadExecutionResult:
        plan = self.plan(input, policy)
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

    def build_input(self, asset_id: AssetId) -> DownloadInput:
        media_ref_path = str(self._workspace_for(asset_id) / MEDIA_REF_FILENAME)
        return DownloadInput(
            asset_id=asset_id,
            media_ref=self.artifacts.read_media_ref(media_ref_path),
        )

    def plan_asset(
        self,
        asset_id: AssetId,
        policy: DownloadPolicy | None = None,
    ) -> DownloadPlan:
        return self.plan(self.build_input(asset_id), policy)

    def execute_asset(
        self,
        asset_id: AssetId,
        policy: DownloadPolicy | None = None,
    ) -> DownloadExecutionResult:
        return self.execute(self.build_input(asset_id), policy)

    def _paths_for(self, asset_id: AssetId) -> tuple[str, str]:
        workspace = self._workspace_for(asset_id)
        output_path = str(workspace / canonical_filename(ArtifactType.SOURCE_VIDEO))
        manifest_path = str(
            PurePath(workspace) / DOWNLOAD_MANIFEST_FILENAME
        )
        return output_path, manifest_path

    def _workspace_for(self, asset_id: AssetId) -> Path:
        return build_asset_workspace(asset_id, self.output_root)

    def _artifact_from_download(
        self,
        plan: DownloadPlan,
        downloader_result: DownloaderResult,
    ) -> DownloadedArtifact:
        return DownloadedArtifact(
            asset_id=plan.asset_id,
            media_kind=plan.media_ref.kind,
            media_ref_value=plan.media_ref.value,
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
