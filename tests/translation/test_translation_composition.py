from __future__ import annotations

from copy import deepcopy

import pytest

from translation.infrastructure import (
    TranslationConfigError,
    parse_translation_config,
)


from tests.translation.provider_config_support import FactoryCalls, _build, _config


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




def test_both_complete_provider_blocks_are_required() -> None:
    for block in ("codex_cli", "openai"):
        config = deepcopy(_config())
        translation = config["translation"]
        assert isinstance(translation, dict)
        translation.pop(block)

        with pytest.raises(TranslationConfigError):
            parse_translation_config(config)
