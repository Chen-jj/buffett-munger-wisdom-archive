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


@dataclass(frozen=True)
class ProcessBytesResult:
    """Binary stdout plus decoded diagnostics; stdin is never retained."""

    command: tuple[str, ...]
    returncode: int
    stdout: bytes
    stderr: str
    dry_run: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class ProcessBytesExecutionError(RuntimeError):
    def __init__(self, result: ProcessBytesResult) -> None:
        self.result = result
        message = f"Command failed with exit code {result.returncode}: {' '.join(result.command)}"
        if result.stderr.strip():
            message += f"\n{result.stderr.strip()}"
        super().__init__(message)


def run_process_bytes(
    command: Sequence[str | Path],
    *,
    stdin_bytes: bytes | None = None,
    dry_run: bool = False,
    check: bool = False,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
    runner: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
) -> ProcessBytesResult:
    """Run a binary pipe without changing the existing text process API."""
    normalized = tuple(str(part) for part in command)
    if not normalized:
        raise ValueError("command must not be empty")
    if stdin_bytes is not None and not isinstance(stdin_bytes, bytes):
        raise ValueError("stdin_bytes must be bytes")
    if dry_run:
        return ProcessBytesResult(normalized, 0, b"", "", True)

    def diagnostic(value: bytes | str | None) -> str:
        return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else (value or "")

    try:
        options = {"cwd": str(cwd) if cwd is not None else None,
                   "env": dict(env) if env is not None else None, "timeout": timeout,
                   "capture_output": True, "text": False}
        if stdin_bytes is not None:
            options["input"] = stdin_bytes
        completed = runner(list(normalized), **options)
        result = ProcessBytesResult(normalized, int(completed.returncode), completed.stdout or b"",
                                    diagnostic(completed.stderr))
    except FileNotFoundError as exc:
        result = ProcessBytesResult(normalized, 127, b"", str(exc))
    except subprocess.TimeoutExpired as exc:
        result = ProcessBytesResult(normalized, 124, exc.stdout or b"",
                                    diagnostic(exc.stderr) or f"Command timed out after {timeout} seconds")
    if check and not result.ok:
        raise ProcessBytesExecutionError(result)
    return result
