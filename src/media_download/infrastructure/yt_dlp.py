"""yt-dlp downloader adapter."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from infrastructure.infrastructure.process import (
    ProcessExecutionError,
    ProcessResult,
    run_process,
)
from media_download.domain import DownloaderResult, DownloadPlan


ProcessRunner = Callable[..., ProcessResult]


@dataclass(frozen=True)
class YtDlpDownloader:
    """Build and execute yt-dlp commands for download plans."""

    yt_dlp_path: str = "yt-dlp"
    process_runner: ProcessRunner = run_process

    def download(self, plan: DownloadPlan) -> DownloaderResult:
        command = self.build_command(plan, format_selector=plan.policy.format_selector)
        result = self.process_runner(
            command,
            dry_run=plan.policy.dry_run,
            check=False,
        )
        used_format = plan.policy.format_selector

        if not result.ok and plan.policy.fallback_format:
            fallback_command = self.build_command(
                plan,
                format_selector=plan.policy.fallback_format,
            )
            result = self.process_runner(
                fallback_command,
                dry_run=plan.policy.dry_run,
                check=False,
            )
            used_format = plan.policy.fallback_format

        if not result.ok:
            raise ProcessExecutionError(result)

        return DownloaderResult(
            downloader_name="yt-dlp",
            downloader_version=self.version(dry_run=plan.policy.dry_run),
            command=result.command,
            format_selector=used_format,
        )

    def build_command(
        self,
        plan: DownloadPlan,
        *,
        format_selector: str,
    ) -> tuple[str, ...]:
        command = [
            self.yt_dlp_path,
            "-f",
            format_selector,
            "--merge-output-format",
            plan.policy.merge_output_format,
            "--retries",
            str(plan.policy.retries),
        ]
        if plan.policy.overwrite:
            command.append("--force-overwrites")
        elif plan.policy.resume:
            command.append("--continue")
        command.extend(
            [
                "-o",
                plan.output_path,
                "--no-check-certificates",
            ]
        )
        if plan.policy.rate_limit:
            command.extend(["--limit-rate", plan.policy.rate_limit])
        command.append(plan.media_url)
        return tuple(command)

    def version(self, *, dry_run: bool = False) -> str:
        if dry_run:
            return "dry-run"
        result = self.process_runner([self.yt_dlp_path, "--version"], check=False)
        if not result.ok:
            return "unknown"
        return (result.stdout or "").strip() or "unknown"
