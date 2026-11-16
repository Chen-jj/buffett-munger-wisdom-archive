"""Production provider assembly with fake boundary factories."""

import pytest
from infrastructure.infrastructure.config import load_yaml_config
from translation.infrastructure import build_translation_provider
from tests.translation.provider_config_support import FactoryCalls, _build, _config


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
