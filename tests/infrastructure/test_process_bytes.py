from pathlib import Path
import subprocess

import pytest

from infrastructure.infrastructure.process import ProcessBytesExecutionError, run_process_bytes


def test_binary_runner_receives_exact_bytes_and_options():
    seen = {}
    def runner(command, **kwargs):
        seen.update(command=command, options=kwargs)
        return subprocess.CompletedProcess(command, 0, b"\x00\xff\x80", b"font \xe4\xb8\xad\xff")
    result = run_process_bytes([Path("/tool"), "arg"], stdin_bytes=b"secret\x00", cwd=Path("/work"),
                               env={"ONE": "two"}, timeout=2, runner=runner)
    assert result.stdout == b"\x00\xff\x80"
    assert result.stderr == "font 中�"
    assert result.ok and not result.dry_run
    assert seen == {"command": ["/tool", "arg"], "options": {"cwd": "/work", "env": {"ONE": "two"},
                    "timeout": 2, "capture_output": True, "text": False, "input": b"secret\x00"}}
    assert "secret" not in repr(result)


def test_binary_dry_run_never_calls_runner():
    result = run_process_bytes(["tool"], dry_run=True, runner=lambda *a, **k: pytest.fail("executed"))
    assert result.dry_run and result.ok and result.stdout == b"" and result.stderr == ""


@pytest.mark.parametrize("stderr,expected", [(b"bad\xff", "bad�"), ("bad", "bad"), (None, "Command timed out after 2 seconds")])
def test_binary_timeout_preserves_bytes_without_dumping_stdout(stderr, expected):
    def runner(*a, **k):
        raise subprocess.TimeoutExpired("tool", 2, output=b"binary-secret\xff", stderr=stderr)
    with pytest.raises(ProcessBytesExecutionError) as caught:
        run_process_bytes(["tool"], runner=runner, timeout=2, check=True)
    assert caught.value.result.returncode == 124
    assert caught.value.result.stdout == b"binary-secret\xff"
    assert caught.value.result.stderr == expected
    assert "binary-secret" not in str(caught.value)


def test_missing_binary_and_empty_command():
    def runner(*a, **k):
        raise FileNotFoundError("missing")
    assert run_process_bytes(["tool"], runner=runner).returncode == 127
    with pytest.raises(ValueError):
        run_process_bytes([])
    with pytest.raises(ValueError):
        run_process_bytes(["tool"], stdin_bytes="wrong")


def test_binary_omitted_stdin_does_not_pass_input():
    def runner(*a, **kwargs):
        assert "input" not in kwargs
        return subprocess.CompletedProcess(a[0], 0, None, None)
    assert run_process_bytes(["tool"], runner=runner).stdout == b""
