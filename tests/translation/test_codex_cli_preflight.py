from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import pytest

from infrastructure.infrastructure.process import ProcessResult
from translation.domain import PermanentProviderError
from translation.infrastructure import CodexCliChatGPTPreflight


RESOLVED_CODEX = "/opt/codex/bin/codex"
VERSION = "codex-cli 0.154.0"
SECRET = "sk-private-api-key"
PATH_ALIAS_WARNING = (
    "WARNING: proceeding, even though we could not create PATH aliases: "
    "Operation not permitted (os error 1)"
)
REQUIRED_HELP = """\
Usage: codex exec [OPTIONS] [PROMPT]
  -c, --config <key=value>
      --ephemeral
      --ignore-user-config
      --json
  -s, --sandbox <SANDBOX_MODE>
      --skip-git-repo-check
  -m, --model <MODEL>
      --output-schema <FILE>
  -o, --output-last-message <FILE>
  -C, --cd <DIR>
"""


@dataclass
class FakeProcessRunner:
    login_stdout: str = "Logged in using ChatGPT\n"
    login_returncode: int = 0
    login_stderr: str = ""
    version_stdout: str = f"{VERSION}\n"
    version_returncode: int = 0
    version_stderr: str = ""
    help_stdout: str = REQUIRED_HELP
    help_returncode: int = 0
    help_stderr: str = ""
    calls: list[tuple[tuple[str, ...], Mapping[str, object]]] = field(
        default_factory=list
    )

    def __call__(self, command: Sequence[str], **kwargs: object) -> ProcessResult:
        normalized = tuple(command)
        self.calls.append((normalized, kwargs))
        if normalized[-1:] == ("--version",):
            return ProcessResult(
                command=normalized,
                returncode=self.version_returncode,
                stdout=self.version_stdout,
                stderr=self.version_stderr,
            )
        if normalized[-2:] == ("exec", "--help"):
            return ProcessResult(
                command=normalized,
                returncode=self.help_returncode,
                stdout=self.help_stdout,
                stderr=self.help_stderr,
            )
        if normalized[-2:] == ("login", "status"):
            return ProcessResult(
                command=normalized,
                returncode=self.login_returncode,
                stdout=self.login_stdout,
                stderr=self.login_stderr,
            )
        raise AssertionError(f"unexpected command shape: {normalized!r}")


def _provider(
    runner: FakeProcessRunner,
    *,
    executable: str = "codex",
) -> CodexCliChatGPTPreflight:
    return CodexCliChatGPTPreflight(
        executable=executable,
        process_runner=runner,
        executable_resolver=lambda value: RESOLVED_CODEX
        if value in {"codex", "/custom/bin/codex"}
        else None,
    )


def test_constructor_verifies_version_and_all_required_exec_capabilities(
    monkeypatch,
):
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    runner = FakeProcessRunner(
        version_stderr="private warning",
        help_stderr="private warning",
    )

    preflight = _provider(runner, executable="/custom/bin/codex")

    assert [call[0] for call in runner.calls] == [
        (RESOLVED_CODEX, "--version"),
        (RESOLVED_CODEX, "exec", "--help"),
    ]
    for _, kwargs in runner.calls:
        assert kwargs["check"] is False
        assert kwargs["timeout"] == 30.0
        assert "OPENAI_API_KEY" not in kwargs["env"]
    assert preflight.executable == RESOLVED_CODEX
    assert preflight.identity.to_dict() == {
        "provider": "codex-cli-chatgpt",
        "model": "gpt-5.6-sol",
        "generation_parameters": {
            "adapter_protocol": "translation.codex-cli.v1",
            "auth_method": "chatgpt",
            "codex_cli_version": VERSION,
            "execution_mode": "exec",
            "reasoning_effort": "high",
            "sandbox": "read-only",
            "session_persistence": "ephemeral",
            "structured_output": True,
        },
    }
    with pytest.raises(TypeError):
        preflight.identity.generation_parameters["sandbox"] = "danger-full-access"


@pytest.mark.parametrize(
    "executable",
    [
        "",
        " codex",
        "codex ",
        "codex --version",
        "sh -c codex",
        "codex;browser",
        "codex|browser",
        "wrapper",
        "/custom/bin/wrapper",
    ],
)
def test_rejects_shell_fragments_and_non_codex_executables(executable):
    runner = FakeProcessRunner()

    with pytest.raises(PermanentProviderError) as caught:
        _provider(runner, executable=executable)

    assert caught.value.code == "configuration"
    assert runner.calls == []


def test_missing_or_non_absolute_resolved_executable_fails_before_process():
    runner = FakeProcessRunner()

    with pytest.raises(PermanentProviderError) as missing:
        CodexCliChatGPTPreflight(
            process_runner=runner,
            executable_resolver=lambda _: None,
        )
    with pytest.raises(PermanentProviderError) as relative:
        CodexCliChatGPTPreflight(
            process_runner=runner,
            executable_resolver=lambda _: "bin/codex",
        )

    assert missing.value.code == "configuration"
    assert relative.value.code == "configuration"
    assert runner.calls == []


@pytest.mark.parametrize(
    ("stdout", "returncode"),
    [
        ("", 0),
        ("codex 0.154.0\n", 0),
        ("codex-cli latest\n", 0),
        (f" {VERSION}\n", 0),
        ("codex-cli 0.154.0\nextra\n", 0),
        (f"{VERSION}\n", 1),
    ],
)
def test_unavailable_or_unrecognized_version_is_configuration_error(
    stdout, returncode
):
    runner = FakeProcessRunner(
        version_stdout=stdout,
        version_returncode=returncode,
        version_stderr="secret raw version failure",
    )

    with pytest.raises(PermanentProviderError) as caught:
        _provider(runner)

    assert caught.value.code == "configuration"
    assert "secret raw version failure" not in str(caught.value)
    assert len(runner.calls) == 1


def test_missing_exec_flag_or_prompt_capability_is_configuration_error():
    for omitted in ("--ephemeral", "PROMPT"):
        runner = FakeProcessRunner(
            help_stdout=REQUIRED_HELP.replace(omitted, "UNSUPPORTED", 1),
            help_stderr="secret raw help failure",
        )

        with pytest.raises(PermanentProviderError) as caught:
            _provider(runner)

        assert caught.value.code == "configuration"
        assert "secret raw help failure" not in str(caught.value)
        assert len(runner.calls) == 2


def test_nonzero_exec_help_is_configuration_error_without_raw_output():
    runner = FakeProcessRunner(
        help_returncode=2,
        help_stdout="private stdout",
        help_stderr="private stderr",
    )

    with pytest.raises(PermanentProviderError) as caught:
        _provider(runner)

    assert caught.value.code == "configuration"
    assert "private" not in str(caught.value)


def test_exact_chatgpt_login_passes_once_and_never_runs_login_or_browser_commands(
    monkeypatch,
):
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    runner = FakeProcessRunner(login_stderr=f"{PATH_ALIAS_WARNING}\n")
    preflight = _provider(runner)

    preflight.ensure_chatgpt_login()
    preflight.ensure_chatgpt_login()

    commands = [call[0] for call in runner.calls]
    assert commands == [
        (RESOLVED_CODEX, "--version"),
        (RESOLVED_CODEX, "exec", "--help"),
        (RESOLVED_CODEX, "login", "status"),
    ]
    assert all(command != (RESOLVED_CODEX, "login") for command in commands)
    assert all("browser" not in command for command in commands)
    assert "OPENAI_API_KEY" not in runner.calls[-1][1]["env"]


def test_exact_chatgpt_login_in_stderr_after_path_alias_warning_passes():
    runner = FakeProcessRunner(
        login_stdout="",
        login_stderr=f"{PATH_ALIAS_WARNING}\nLogged in using ChatGPT\n",
    )
    preflight = _provider(runner)

    preflight.ensure_chatgpt_login()

    assert runner.calls[-1][0] == (RESOLVED_CODEX, "login", "status")


@pytest.mark.parametrize(
    "status",
    ["Logged in using an API key\n", "Logged in with an API key\n"],
)
def test_detected_api_key_login_fails_once_with_billing_code(status):
    runner = FakeProcessRunner(
        login_stdout=status,
        login_stderr=f"{PATH_ALIAS_WARNING}\n",
    )
    preflight = _provider(runner)

    for _ in range(2):
        with pytest.raises(PermanentProviderError) as caught:
            preflight.ensure_chatgpt_login()
        assert caught.value.code == "api_billing_not_allowed"
        assert SECRET not in str(caught.value)

    assert [call[0] for call in runner.calls].count(
        (RESOLVED_CODEX, "login", "status")
    ) == 1


def test_detected_api_key_login_in_controlled_stderr_maps_to_billing_code():
    runner = FakeProcessRunner(
        login_stdout="",
        login_stderr=f"{PATH_ALIAS_WARNING}\nLogged in using an API key\n",
    )
    preflight = _provider(runner)

    with pytest.raises(PermanentProviderError) as caught:
        preflight.ensure_chatgpt_login()

    assert caught.value.code == "api_billing_not_allowed"


@pytest.mark.parametrize(
    ("stdout", "returncode"),
    [
        ("Not logged in\n", 1),
        ("Unknown account state\n", 0),
        ("Logged in using ChatGPT\nextra\n", 0),
        (" Logged in using ChatGPT\n", 0),
        ("logged in using chatgpt\n", 0),
        ("Logged in using ChatGPT\n", 1),
    ],
)
def test_every_ambiguous_or_failed_login_fails_once_closed(stdout, returncode):
    runner = FakeProcessRunner(
        login_stdout=stdout,
        login_returncode=returncode,
        login_stderr=f"raw auth {SECRET}",
    )
    preflight = _provider(runner)

    for _ in range(2):
        with pytest.raises(PermanentProviderError) as caught:
            preflight.ensure_chatgpt_login()
        assert caught.value.code == "authentication"
        assert SECRET not in str(caught.value)
        assert stdout.strip() not in str(caught.value)

    assert [call[0] for call in runner.calls].count(
        (RESOLVED_CODEX, "login", "status")
    ) == 1


@pytest.mark.parametrize(
    "stderr",
    [
        "unexpected warning\n",
        f"{PATH_ALIAS_WARNING}\nunexpected extra line\n",
        f"{PATH_ALIAS_WARNING}\n{PATH_ALIAS_WARNING}\n",
        f"{PATH_ALIAS_WARNING}\nLogged in using ChatGPT\n",
    ],
)
def test_unknown_extra_or_duplicate_login_output_fails_closed(stderr):
    runner = FakeProcessRunner(login_stderr=stderr)
    preflight = _provider(runner)

    with pytest.raises(PermanentProviderError) as caught:
        preflight.ensure_chatgpt_login()

    assert caught.value.code == "authentication"
    assert stderr.strip() not in str(caught.value)
