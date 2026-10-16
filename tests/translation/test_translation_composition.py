from __future__ import annotations

from copy import deepcopy

import pytest

from infrastructure.infrastructure.config import load_yaml_config
from translation.infrastructure import (
    TranslationConfigError,
    build_translation_provider,
    parse_translation_config,
)


def _config(*, provider: str = "codex-cli-chatgpt") -> dict[str, object]:
    return {
        "translation": {
            "provider": provider,
            "codex_cli": {
                "executable": "codex",
                "model": "gpt-5.6-sol",
                "reasoning_effort": "high",
                "timeout_seconds": 1800,
            },
            "openai": {
                "api_key_env": "OPENAI_API_KEY",
                "model": "gpt-5.6-sol",
                "reasoning_effort": "high",
                "max_output_tokens": 128000,
                "timeout_seconds": 1800,
            },
        }
    }


class FactoryCalls:
    def __init__(self) -> None:
        self.codex: list[dict[str, object]] = []
        self.openai = 0
        self.codex_result = object()
        self.openai_result = object()

    def build_codex(self, **kwargs):
        self.codex.append(kwargs)
        return self.codex_result

    def build_openai(self):
        self.openai += 1
        return self.openai_result


def _build(config: dict[str, object], calls: FactoryCalls):
    return build_translation_provider(
        config,
        codex_provider_factory=calls.build_codex,
        openai_provider_factory=calls.build_openai,
    )


def test_repository_config_explicitly_selects_only_codex() -> None:
    calls = FactoryCalls()

    provider = _build(load_yaml_config(), calls)

    assert provider is calls.codex_result
    assert calls.codex == [{"executable": "codex", "timeout_seconds": 1800.0}]
    assert calls.openai == 0


def test_explicit_openai_selection_constructs_only_openai() -> None:
    calls = FactoryCalls()

    provider = _build(_config(provider="openai-responses"), calls)

    assert provider is calls.openai_result
    assert calls.openai == 1
    assert calls.codex == []


@pytest.mark.parametrize(
    ("location", "value"),
    [
        (("provider",), None),
        (("provider",), "unknown"),
        (("codex_cli", "executable"), "codex --profile translation"),
        (("codex_cli", "executable"), "wrapper"),
        (("codex_cli", "model"), "other"),
        (("codex_cli", "reasoning_effort"), "medium"),
        (("codex_cli", "timeout_seconds"), 60),
        (("openai", "api_key_env"), "OTHER_KEY"),
        (("openai", "model"), "other"),
        (("openai", "reasoning_effort"), "medium"),
        (("openai", "max_output_tokens"), 1000),
        (("openai", "timeout_seconds"), 60),
    ],
)
def test_invalid_selection_or_fixed_setting_fails_before_provider_construction(
    location: tuple[str, ...], value: object
) -> None:
    config = _config()
    target = config["translation"]
    assert isinstance(target, dict)
    for component in location[:-1]:
        target = target[component]
        assert isinstance(target, dict)
    if value is None:
        target.pop(location[-1])
    else:
        target[location[-1]] = value
    calls = FactoryCalls()

    with pytest.raises(TranslationConfigError):
        _build(config, calls)

    assert calls.codex == []
    assert calls.openai == 0


@pytest.mark.parametrize("store", [False, True])
def test_openai_store_cannot_be_overridden_in_configuration(store: bool) -> None:
    config = _config()
    translation = config["translation"]
    assert isinstance(translation, dict)
    openai = translation["openai"]
    assert isinstance(openai, dict)
    openai["store"] = store

    with pytest.raises(TranslationConfigError):
        parse_translation_config(config)


@pytest.mark.parametrize("provider", ["codex-cli-chatgpt", "openai-responses"])
def test_selected_factory_failure_never_falls_back(provider: str) -> None:
    calls = FactoryCalls()

    def fail_codex(**kwargs):
        calls.codex.append(kwargs)
        raise RuntimeError("codex construction failed")

    def fail_openai():
        calls.openai += 1
        raise RuntimeError("openai construction failed")

    with pytest.raises(RuntimeError, match=f"{provider.split('-')[0]} construction"):
        build_translation_provider(
            _config(provider=provider),
            codex_provider_factory=fail_codex,
            openai_provider_factory=fail_openai,
        )

    if provider == "codex-cli-chatgpt":
        assert len(calls.codex) == 1
        assert calls.openai == 0
    else:
        assert calls.codex == []
        assert calls.openai == 1


def test_both_complete_provider_blocks_are_required() -> None:
    for block in ("codex_cli", "openai"):
        config = deepcopy(_config())
        translation = config["translation"]
        assert isinstance(translation, dict)
        translation.pop(block)

        with pytest.raises(TranslationConfigError):
            parse_translation_config(config)
