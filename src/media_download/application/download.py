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
SUCCESSFUL_DOWNLOAD_STATUS = "downloaded"


class ExistingDownloadConflict(RuntimeError):
    """Raised when an existing video cannot be verified for safe reuse."""

    def __init__(self, category: str) -> None:
        self.category = category
        super().__init__(
            f"existing download artifact validation failed: {category}"
        )


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
        plan, _ = self._plan_with_existing_artifact(
            input,
            policy or DownloadPolicy(),
        )
        return plan

    def _plan_with_existing_artifact(
        self,
        input: DownloadInput,
        selected_policy: DownloadPolicy,
    ) -> tuple[DownloadPlan, DownloadedArtifact | None]:
        output_path, manifest_path = self._paths_for(input.asset_id)

        if self.artifacts.exists(output_path) and not selected_policy.overwrite:
            artifact = self._validate_existing_artifact(
                input,
                output_path,
                manifest_path,
            )
            return (
                DownloadPlan(
                    asset_id=input.asset_id,
                    media_ref=input.media_ref,
                    media_url=artifact.media_url,
                    output_path=output_path,
                    manifest_path=manifest_path,
                    policy=selected_policy,
                    action=DownloadAction.SKIP,
                    reason="existing output verified",
                ),
                artifact,
            )

        media_url = self.resolver_registry.select(input).resolve(input)
        reason = "dry-run" if selected_policy.dry_run else "download required"
        return (
            DownloadPlan(
                asset_id=input.asset_id,
                media_ref=input.media_ref,
                media_url=media_url,
                output_path=output_path,
                manifest_path=manifest_path,
                policy=selected_policy,
                action=DownloadAction.DOWNLOAD,
                reason=reason,
            ),
            None,
        )

    def execute(
        self,
        input: DownloadInput,
        policy: DownloadPolicy | None = None,
    ) -> DownloadExecutionResult:
        plan, existing_artifact = self._plan_with_existing_artifact(
            input,
            policy or DownloadPolicy(),
        )
        if plan.policy.dry_run:
            return DownloadExecutionResult(plan=plan)

        if plan.action == DownloadAction.SKIP:
            if existing_artifact is None:
                raise RuntimeError("verified existing artifact is missing")
            return DownloadExecutionResult(
                plan=plan,
                artifact=existing_artifact,
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

    def _validate_existing_artifact(
        self,
        input: DownloadInput,
        output_path: str,
        manifest_path: str,
    ) -> DownloadedArtifact:
        if not self.artifacts.exists(manifest_path):
            raise ExistingDownloadConflict("manifest_missing")

        try:
            artifact = self.artifacts.read_manifest(manifest_path)
        except Exception:
            raise ExistingDownloadConflict("manifest_invalid") from None

        if artifact.asset_id != input.asset_id:
            raise ExistingDownloadConflict("asset_mismatch")
        if (
            artifact.media_kind != input.media_ref.kind
            or artifact.media_ref_value != input.media_ref.value
        ):
            raise ExistingDownloadConflict("media_ref_mismatch")
        if artifact.status != SUCCESSFUL_DOWNLOAD_STATUS:
            raise ExistingDownloadConflict("status_not_successful")
        if Path(artifact.output_path) != Path(output_path):
            raise ExistingDownloadConflict("artifact_path_mismatch")

        try:
            actual_size = self.artifacts.size(output_path)
        except Exception:
            raise ExistingDownloadConflict("artifact_unreadable") from None
        if artifact.size_bytes != actual_size:
            raise ExistingDownloadConflict("size_mismatch")
        if artifact.checksum_algorithm != "sha256":
            raise ExistingDownloadConflict("checksum_algorithm_mismatch")

        try:
            actual_checksum = self.checksum.sha256(output_path)
        except Exception:
            raise ExistingDownloadConflict("checksum_unavailable") from None
        if artifact.checksum_value != actual_checksum:
            raise ExistingDownloadConflict("checksum_mismatch")

        return artifact

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
            status=SUCCESSFUL_DOWNLOAD_STATUS,
        )


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()
