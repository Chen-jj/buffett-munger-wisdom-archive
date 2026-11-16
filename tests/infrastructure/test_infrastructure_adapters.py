from __future__ import annotations

import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from src.infrastructure.infrastructure.config import (
    ConfigLoadError,
    default_config_path,
    load_yaml_config,
)
from src.infrastructure.infrastructure.filesystem import write_json_file
from src.infrastructure.infrastructure.process import (
    ProcessExecutionError,
    normalize_process_error,
    run_process,
)
from src.infrastructure.infrastructure.tools import discover_tool, discover_tools


class TestInfrastructureAdapters(unittest.TestCase):






    def test_run_process_rejects_empty_command(self):
        def runner(*args, **kwargs):
            raise AssertionError("runner should not be called")

        with self.assertRaisesRegex(ValueError, "command must not be empty"):
            run_process([], runner=runner)

    def test_run_process_reports_missing_binary_as_127(self):
        def runner(*args, **kwargs):
            raise FileNotFoundError("No such file or directory")

        result = run_process(["missing-tool"], runner=runner)

        self.assertEqual(result.returncode, 127)
        self.assertIn("No such file", result.stderr)

    def test_run_process_reports_timeout_as_124(self):
        stdin_text = "private prompt"

        def runner(*args, **kwargs):
            self.assertEqual(kwargs["input"], stdin_text)
            raise subprocess.TimeoutExpired(
                cmd=["tool"], timeout=5, output="partial out", stderr="partial err"
            )

        result = run_process(
            ["tool"],
            stdin_text=stdin_text,
            runner=runner,
            timeout=5,
        )

        self.assertEqual(result.returncode, 124)
        self.assertEqual(result.stdout, "partial out")
        self.assertEqual(result.stderr, "partial err")
        self.assertNotIn(stdin_text, repr(result))
        self.assertNotIn(stdin_text, normalize_process_error(result))

    def test_normalize_process_error_without_detail_lists_command_only(self):
        result = run_process(["tool", "--flag"], dry_run=True)
        failed_result = result.__class__(
            command=result.command,
            returncode=1,
            stdout="",
            stderr="",
        )

        self.assertEqual(
            normalize_process_error(failed_result),
            "Command failed with exit code 1: tool --flag",
        )

    def test_discover_tool_rejects_empty_name(self):
        with self.assertRaisesRegex(ValueError, "tool name must not be empty"):
            discover_tool("")


    def test_run_process_dry_run_does_not_call_runner(self):
        stdin_text = "private dry-run prompt"

        def runner(*args, **kwargs):
            raise AssertionError("runner should not be called in dry-run")

        result = run_process(
            ["ffmpeg", "-version"],
            stdin_text=stdin_text,
            dry_run=True,
            runner=runner,
        )

        self.assertTrue(result.dry_run)
        self.assertEqual(result.command, ("ffmpeg", "-version"))
        self.assertEqual(result.returncode, 0)
        self.assertNotIn(stdin_text, repr(result))

    def test_run_process_passes_exact_unicode_stdin_and_runner_options(self):
        received = {}

        def runner(*args, **kwargs):
            received["args"] = args
            received["kwargs"] = kwargs
            return subprocess.CompletedProcess(
                args=args[0],
                returncode=0,
                stdout="ok\n",
                stderr="",
            )

        result = run_process(
            [Path("tool"), "--flag"],
            stdin_text="完整句子：Berkshire 不会支付 42 美元。\n",
            cwd=Path("workspace"),
            env={"LANG": "C.UTF-8"},
            timeout=30,
            runner=runner,
        )

        self.assertEqual(received["args"], (["tool", "--flag"],))
        self.assertEqual(
            received["kwargs"],
            {
                "input": "完整句子：Berkshire 不会支付 42 美元。\n",
                "cwd": "workspace",
                "env": {"LANG": "C.UTF-8"},
                "timeout": 30,
                "capture_output": True,
                "text": True,
            },
        )
        self.assertEqual(result.command, ("tool", "--flag"))

    def test_run_process_preserves_runner_arguments_when_stdin_is_omitted(self):
        received = {}

        def runner(*args, **kwargs):
            received.update(kwargs)
            return subprocess.CompletedProcess(
                args=args[0],
                returncode=0,
                stdout="",
                stderr="",
            )

        result = run_process(["tool"], runner=runner)

        self.assertTrue(result.ok)
        self.assertNotIn("input", received)

    def test_run_process_captures_output_from_injected_runner(self):
        def runner(*args, **kwargs):
            return subprocess.CompletedProcess(
                args=args[0],
                returncode=0,
                stdout="ok\n",
                stderr="",
            )

        result = run_process(["python", "--version"], runner=runner)

        self.assertTrue(result.ok)
        self.assertEqual(result.stdout, "ok\n")
        self.assertEqual(result.stderr, "")

    def test_run_process_normalizes_failure_when_check_is_enabled(self):
        stdin_text = "private prompt"

        def runner(*args, **kwargs):
            return subprocess.CompletedProcess(
                args=args[0],
                returncode=2,
                stdout="",
                stderr="bad option",
            )

        with self.assertRaises(ProcessExecutionError) as exc_info:
            run_process(
                ["tool", "--bad"],
                stdin_text=stdin_text,
                runner=runner,
                check=True,
            )

        self.assertEqual(exc_info.exception.result.returncode, 2)
        self.assertIn(
            "Command failed with exit code 2: tool --bad",
            str(exc_info.exception),
        )
        self.assertIn("bad option", str(exc_info.exception))
        self.assertNotIn(stdin_text, str(exc_info.exception))
        self.assertNotIn(stdin_text, repr(exc_info.exception.result))

    def test_normalize_process_error_uses_stdout_when_stderr_is_empty(self):
        result = run_process(["missing-tool"], dry_run=True)
        failed_result = result.__class__(
            command=result.command,
            returncode=1,
            stdout="stdout detail",
            stderr="",
        )

        self.assertTrue(normalize_process_error(failed_result).endswith("stdout detail"))






if __name__ == "__main__":
    unittest.main()
