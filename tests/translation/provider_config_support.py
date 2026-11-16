from __future__ import annotations

from translation.infrastructure import build_translation_provider


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
