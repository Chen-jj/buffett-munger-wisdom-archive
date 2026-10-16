"""Shared subprocess execution adapter with dry-run support."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
import subprocess


RunCallable = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class ProcessResult:
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    dry_run: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class ProcessExecutionError(RuntimeError):
    """Raised when `check=True` and a command exits unsuccessfully."""

    def __init__(self, result: ProcessResult) -> None:
        self.result = result
        super().__init__(normalize_process_error(result))


def normalize_process_error(result: ProcessResult) -> str:
    detail = (result.stderr or result.stdout or "").strip()
    command = " ".join(result.command)
    if detail:
        return f"Command failed with exit code {result.returncode}: {command}\n{detail}"
    return f"Command failed with exit code {result.returncode}: {command}"


def run_process(
    command: Sequence[str | Path],
    *,
    stdin_text: str | None = None,
    dry_run: bool = False,
    check: bool = False,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
    runner: RunCallable = subprocess.run,
) -> ProcessResult:
    """Run a command or return its dry-run plan without executing it."""

    normalized = tuple(str(part) for part in command)
    if not normalized:
        raise ValueError("command must not be empty")

    if dry_run:
        return ProcessResult(
            command=normalized,
            returncode=0,
            stdout="",
            stderr="",
            dry_run=True,
        )

    try:
        runner_options = {
            "cwd": str(cwd) if cwd is not None else None,
            "env": dict(env) if env is not None else None,
            "timeout": timeout,
            "capture_output": True,
            "text": True,
        }
        if stdin_text is not None:
            runner_options["input"] = stdin_text
        completed = runner(list(normalized), **runner_options)
        result = ProcessResult(
            command=normalized,
            returncode=int(completed.returncode),
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )
    except FileNotFoundError as exc:
        result = ProcessResult(
            command=normalized,
            returncode=127,
            stdout="",
            stderr=str(exc),
        )
    except subprocess.TimeoutExpired as exc:
        result = ProcessResult(
            command=normalized,
            returncode=124,
            stdout=exc.stdout or "",
            stderr=exc.stderr or f"Command timed out after {timeout} seconds",
        )

    if check and not result.ok:
        raise ProcessExecutionError(result)
    return result
