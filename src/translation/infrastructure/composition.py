"""Strict translation provider configuration and production composition."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any

from translation.application import TranslationProvider

from .codex_cli import CodexCliChatGPTTranslationProvider
from .openai_responses import OpenAIResponsesTranslationProvider


_CODEX_PROVIDER = "codex-cli-chatgpt"
_OPENAI_PROVIDER = "openai-responses"
_MODEL = "gpt-5.6-sol"
_REASONING_EFFORT = "high"
_TIMEOUT_SECONDS = 1800
_MAX_OUTPUT_TOKENS = 128_000
_API_KEY_ENV = "OPENAI_API_KEY"


class TranslationConfigError(ValueError):
    """Raised before provider construction when translation config is invalid."""


@dataclass(frozen=True)
class CodexCliTranslationConfig:
    executable: str
    model: str
    reasoning_effort: str
    timeout_seconds: float


@dataclass(frozen=True)
class OpenAITranslationConfig:
    api_key_env: str
    model: str
    reasoning_effort: str
    max_output_tokens: int
    timeout_seconds: float


@dataclass(frozen=True)
class TranslationProviderConfig:
    provider: str
    codex_cli: CodexCliTranslationConfig
    openai: OpenAITranslationConfig


def _exact_mapping(
    value: object,
    *,
    fields: frozenset[str],
    location: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TranslationConfigError(f"{location} must be a mapping")
    if any(not isinstance(key, str) for key in value) or set(value) != fields:
        raise TranslationConfigError(f"{location} has invalid fields")
    return value


def _fixed_string(value: object, *, expected: str, location: str) -> str:
    if value != expected or not isinstance(value, str):
        raise TranslationConfigError(f"{location} must be {expected!r}")
    return value


def _fixed_number(value: object, *, expected: int, location: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value != expected
    ):
        raise TranslationConfigError(f"{location} must be {expected}")
    return float(value)


def _codex_executable(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or any(character.isspace() or character in "'\";|&$`" for character in value)
        or Path(value).name != "codex"
    ):
        raise TranslationConfigError(
            "translation.codex_cli.executable must be one codex name or path"
        )
    return value


def parse_translation_config(config: Mapping[str, Any]) -> TranslationProviderConfig:
    """Validate the complete translation block without reading credentials."""

    if not isinstance(config, Mapping):
        raise TranslationConfigError("config root must be a mapping")
    translation = _exact_mapping(
        config.get("translation"),
        fields=frozenset({"provider", "codex_cli", "openai"}),
        location="translation",
    )
    provider = translation["provider"]
    if provider not in {_CODEX_PROVIDER, _OPENAI_PROVIDER} or not isinstance(
        provider, str
    ):
        raise TranslationConfigError(
            "translation.provider must be 'codex-cli-chatgpt' or 'openai-responses'"
        )

    codex = _exact_mapping(
        translation["codex_cli"],
        fields=frozenset(
            {"executable", "model", "reasoning_effort", "timeout_seconds"}
        ),
        location="translation.codex_cli",
    )
    openai = _exact_mapping(
        translation["openai"],
        fields=frozenset(
            {
                "api_key_env",
                "model",
                "reasoning_effort",
                "max_output_tokens",
                "timeout_seconds",
            }
        ),
        location="translation.openai",
    )

    codex_config = CodexCliTranslationConfig(
        executable=_codex_executable(codex["executable"]),
        model=_fixed_string(
            codex["model"],
            expected=_MODEL,
            location="translation.codex_cli.model",
        ),
        reasoning_effort=_fixed_string(
            codex["reasoning_effort"],
            expected=_REASONING_EFFORT,
            location="translation.codex_cli.reasoning_effort",
        ),
        timeout_seconds=_fixed_number(
            codex["timeout_seconds"],
            expected=_TIMEOUT_SECONDS,
            location="translation.codex_cli.timeout_seconds",
        ),
    )
    openai_config = OpenAITranslationConfig(
        api_key_env=_fixed_string(
            openai["api_key_env"],
            expected=_API_KEY_ENV,
            location="translation.openai.api_key_env",
        ),
        model=_fixed_string(
            openai["model"],
            expected=_MODEL,
            location="translation.openai.model",
        ),
        reasoning_effort=_fixed_string(
            openai["reasoning_effort"],
            expected=_REASONING_EFFORT,
            location="translation.openai.reasoning_effort",
        ),
        max_output_tokens=int(
            _fixed_number(
                openai["max_output_tokens"],
                expected=_MAX_OUTPUT_TOKENS,
                location="translation.openai.max_output_tokens",
            )
        ),
        timeout_seconds=_fixed_number(
            openai["timeout_seconds"],
            expected=_TIMEOUT_SECONDS,
            location="translation.openai.timeout_seconds",
        ),
    )
    return TranslationProviderConfig(provider, codex_config, openai_config)


def build_translation_provider(
    config: Mapping[str, Any],
    *,
    codex_provider_factory: Callable[..., TranslationProvider] = (
        CodexCliChatGPTTranslationProvider
    ),
    openai_provider_factory: Callable[[], TranslationProvider] = (
        OpenAIResponsesTranslationProvider
    ),
) -> TranslationProvider:
    """Construct exactly the explicitly selected production provider."""

    parsed = parse_translation_config(config)
    if parsed.provider == _CODEX_PROVIDER:
        return codex_provider_factory(
            executable=parsed.codex_cli.executable,
            timeout_seconds=parsed.codex_cli.timeout_seconds,
        )
    return openai_provider_factory()
