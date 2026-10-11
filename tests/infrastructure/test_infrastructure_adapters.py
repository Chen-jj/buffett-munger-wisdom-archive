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
    def test_load_yaml_config_returns_mapping_without_interpreting_fields(self):
        with TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.yaml"
            config_path.write_text(
                "download:\n  retries: 3\ncustom_section:\n  enabled: true\n",
                encoding="utf-8",
            )

            config = load_yaml_config(config_path)

        self.assertEqual(
            config,
            {
                "download": {"retries": 3},
                "custom_section": {"enabled": True},
            },
        )

    def test_load_yaml_config_rejects_non_mapping_root(self):
        with TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.yaml"
            config_path.write_text("- item\n", encoding="utf-8")

            with self.assertRaisesRegex(
                ConfigLoadError,
                "Config root must be a mapping",
            ):
                load_yaml_config(config_path)

    def test_load_yaml_config_wraps_unreadable_file(self):
        with TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.yaml"

            with self.assertRaisesRegex(ConfigLoadError, "Cannot read config file"):
                load_yaml_config(missing)

    def test_load_yaml_config_wraps_invalid_yaml(self):
        with TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.yaml"
            config_path.write_text("key: [1, 2\n", encoding="utf-8")

            with self.assertRaisesRegex(ConfigLoadError, "Invalid YAML"):
                load_yaml_config(config_path)

    def test_load_yaml_config_returns_empty_mapping_for_empty_file(self):
        with TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.yaml"
            config_path.write_text("", encoding="utf-8")

            self.assertEqual(load_yaml_config(config_path), {})

    def test_default_config_path_points_at_repo_config(self):
        path = default_config_path()

        self.assertEqual(path.name, "config.yaml")
        self.assertIsInstance(load_yaml_config(path), dict)

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
        def runner(*args, **kwargs):
            raise subprocess.TimeoutExpired(
                cmd=["tool"], timeout=5, output="partial out", stderr="partial err"
            )

        result = run_process(["tool"], runner=runner, timeout=5)

        self.assertEqual(result.returncode, 124)
        self.assertEqual(result.stdout, "partial out")
        self.assertEqual(result.stderr, "partial err")

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

    def test_write_json_file_removes_temporary_file_when_replace_fails(self):
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "data.json"

            def failing_replace(self, other):
                raise OSError("replace failed")

            with mock.patch.object(Path, "replace", failing_replace):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    write_json_file(target, {"name": "first"})

            leftovers = [
                entry for entry in Path(tmp).iterdir() if entry.name.startswith(".")
            ]
            self.assertEqual(leftovers, [])
            self.assertFalse(target.exists())

    def test_run_process_dry_run_does_not_call_runner(self):
        def runner(*args, **kwargs):
            raise AssertionError("runner should not be called in dry-run")

        result = run_process(["ffmpeg", "-version"], dry_run=True, runner=runner)

        self.assertTrue(result.dry_run)
        self.assertEqual(result.command, ("ffmpeg", "-version"))
        self.assertEqual(result.returncode, 0)

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
        def runner(*args, **kwargs):
            return subprocess.CompletedProcess(
                args=args[0],
                returncode=2,
                stdout="",
                stderr="bad option",
            )

        with self.assertRaises(ProcessExecutionError) as exc_info:
            run_process(["tool", "--bad"], runner=runner, check=True)

        self.assertEqual(exc_info.exception.result.returncode, 2)
        self.assertIn(
            "Command failed with exit code 2: tool --bad",
            str(exc_info.exception),
        )
        self.assertIn("bad option", str(exc_info.exception))

    def test_normalize_process_error_uses_stdout_when_stderr_is_empty(self):
        result = run_process(["missing-tool"], dry_run=True)
        failed_result = result.__class__(
            command=result.command,
            returncode=1,
            stdout="stdout detail",
            stderr="",
        )

        self.assertTrue(normalize_process_error(failed_result).endswith("stdout detail"))

    def test_discover_tool_uses_search_path_without_executing_binary(self):
        with TemporaryDirectory() as tmp:
            tool_path = Path(tmp) / "sample-tool"
            tool_path.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
            tool_path.chmod(0o755)

            result = discover_tool("sample-tool", search_path=os.fspath(tmp))

        self.assertTrue(result.available)
        self.assertEqual(result.path, os.fspath(tool_path))

    def test_discover_tools_reports_missing_tools_with_none_path(self):
        with TemporaryDirectory() as tmp:
            result = discover_tools(("ffmpeg", "yt-dlp"), search_path=os.fspath(tmp))

        self.assertFalse(result["ffmpeg"].available)
        self.assertIsNone(result["ffmpeg"].path)
        self.assertFalse(result["yt-dlp"].available)

    def test_write_json_file_creates_parent_and_refuses_silent_overwrite(self):
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "nested" / "manifest.json"

            written = write_json_file(target, {"name": "first"})

            self.assertEqual(written, target)
            self.assertEqual(
                target.read_text(encoding="utf-8"),
                '{\n  "name": "first"\n}\n',
            )
            with self.assertRaises(FileExistsError):
                write_json_file(target, {"name": "second"})
            self.assertEqual(
                target.read_text(encoding="utf-8"),
                '{\n  "name": "first"\n}\n',
            )

    def test_write_json_file_overwrites_only_when_requested(self):
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "manifest.json"
            write_json_file(target, {"name": "first"})

            write_json_file(target, {"name": "second"}, overwrite=True)

            self.assertEqual(
                target.read_text(encoding="utf-8"),
                '{\n  "name": "second"\n}\n',
            )


if __name__ == "__main__":
    unittest.main()
