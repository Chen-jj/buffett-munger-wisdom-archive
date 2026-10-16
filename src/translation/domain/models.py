"""Immutable provider-neutral translation domain values."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
import re
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .serialization import canonical_json_bytes, canonical_json_sha256


SOURCE_LANGUAGE = "en"
TARGET_LANGUAGE = "zh-Hans"

_SECTION_ID_RE = re.compile(r"^sec[1-9][0-9]*$")
_SENTENCE_ID_RE = re.compile(r"^s[1-9][0-9]*$")


def _require_non_blank(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-blank string")
    return value


def _require_non_negative_integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def _freeze_json(value: object) -> object:
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) and key for key in value):
            raise ValueError("JSON object keys must be non-empty strings")
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return tuple(_freeze_json(item) for item in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        canonical_json_bytes(value)
        return value
    raise ValueError(f"value is not JSON serializable: {type(value).__name__}")


def _thaw_json(value: object) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


@dataclass(frozen=True)
class TranslationRequestItem:
    id: str
    text: str

    def __post_init__(self) -> None:
        _require_non_blank(self.id, "request item id")
        if _SENTENCE_ID_RE.fullmatch(self.id) is None:
            raise ValueError("request item id must use the format s<one-based position>")
        _require_non_blank(self.text, "request item text")

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "text": self.text}


@dataclass(frozen=True)
class TranslationRequestSection:
    id: str
    title: str

    def __post_init__(self) -> None:
        _require_non_blank(self.id, "request section id")
        if _SECTION_ID_RE.fullmatch(self.id) is None:
            raise ValueError(
                "request section id must use the format sec<one-based position>"
            )
        if not isinstance(self.title, str):
            raise ValueError("request section title must be a string")

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "title": self.title}


@dataclass(frozen=True)
class TranslationRequest:
    source_language: str
    target_language: str
    section: TranslationRequestSection | None
    items: tuple[TranslationRequestItem, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.source_language != SOURCE_LANGUAGE:
            raise ValueError(f"source_language must be {SOURCE_LANGUAGE}")
        if self.target_language != TARGET_LANGUAGE:
            raise ValueError(f"target_language must be {TARGET_LANGUAGE}")
        if self.section is not None and not isinstance(
            self.section, TranslationRequestSection
        ):
            raise ValueError("section must be a TranslationRequestSection or null")
        object.__setattr__(self, "items", tuple(self.items))
        if not all(isinstance(item, TranslationRequestItem) for item in self.items):
            raise ValueError("items must contain TranslationRequestItem values")
        item_ids = [item.id for item in self.items]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("request item IDs must not contain duplicates")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_language": self.source_language,
            "target_language": self.target_language,
            "section": self.section.to_dict() if self.section is not None else None,
            "items": [item.to_dict() for item in self.items],
        }

    def canonical_json(self) -> str:
        return canonical_json_bytes(self.to_dict()).decode("utf-8")

    def checksum(self) -> str:
        return canonical_json_sha256(self.to_dict())


@dataclass(frozen=True)
class ProviderIdentity:
    provider: str
    model: str
    generation_parameters: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_blank(self.provider, "provider")
        _require_non_blank(self.model, "model")
        if not isinstance(self.generation_parameters, Mapping):
            raise ValueError("generation_parameters must be an object")
        frozen = _freeze_json(dict(self.generation_parameters))
        canonical_json_bytes(frozen)
        object.__setattr__(self, "generation_parameters", frozen)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "generation_parameters": _thaw_json(self.generation_parameters),
        }


@dataclass(frozen=True)
class ProviderUsage:
    input_tokens: int
    output_tokens: int

    def __post_init__(self) -> None:
        _require_non_negative_integer(self.input_tokens, "input_tokens")
        _require_non_negative_integer(self.output_tokens, "output_tokens")

    def to_dict(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
        }


class ProviderStatus(str, Enum):
    COMPLETED = "completed"
    REFUSED = "refused"
    INCOMPLETE = "incomplete"


@dataclass(frozen=True)
class ProviderCall:
    instructions: str
    request: TranslationRequest
    output_schema: Mapping[str, object]
    max_attempts: int

    def __post_init__(self) -> None:
        _require_non_blank(self.instructions, "instructions")
        if not isinstance(self.request, TranslationRequest):
            raise ValueError("request must be a TranslationRequest")
        if not isinstance(self.output_schema, Mapping):
            raise ValueError("output_schema must be an object")
        if isinstance(self.max_attempts, bool) or not isinstance(self.max_attempts, int):
            raise ValueError("max_attempts must be a positive integer")
        if self.max_attempts <= 0:
            raise ValueError("max_attempts must be a positive integer")
        frozen = _freeze_json(dict(self.output_schema))
        canonical_json_bytes(frozen)
        object.__setattr__(self, "output_schema", frozen)


@dataclass(frozen=True)
class ProviderResponse:
    status: ProviderStatus
    output: object | None
    attempt_count: int
    usage: ProviderUsage | None = None
    provider_request_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, ProviderStatus):
            raise ValueError("status must be a ProviderStatus")
        if isinstance(self.attempt_count, bool) or not isinstance(
            self.attempt_count, int
        ):
            raise ValueError("attempt_count must be a positive integer")
        if self.attempt_count <= 0:
            raise ValueError("attempt_count must be a positive integer")
        if self.usage is not None and not isinstance(self.usage, ProviderUsage):
            raise ValueError("usage must be ProviderUsage or null")
        if self.provider_request_id is not None:
            _require_non_blank(self.provider_request_id, "provider_request_id")
        if self.status == ProviderStatus.COMPLETED and self.output is None:
            raise ValueError("completed provider response must include output")
        if self.status != ProviderStatus.COMPLETED and self.output is not None:
            raise ValueError("non-completed provider response output must be null")
        if self.output is not None:
            object.__setattr__(self, "output", _freeze_json(self.output))


class ProviderErrorCategory(str, Enum):
    TRANSIENT = "transient"
    PERMANENT = "permanent"


class ProviderError(Exception):
    """Provider-neutral failure that application code can classify for retry."""

    def __init__(
        self,
        message: str,
        *,
        category: ProviderErrorCategory,
        code: str,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(_require_non_blank(message, "provider error message"))
        if not isinstance(category, ProviderErrorCategory):
            raise ValueError("category must be a ProviderErrorCategory")
        self.category = category
        self.code = _require_non_blank(code, "provider error code")
        if retry_after_seconds is not None and (
            isinstance(retry_after_seconds, bool)
            or not isinstance(retry_after_seconds, (int, float))
            or not math.isfinite(retry_after_seconds)
            or retry_after_seconds < 0
        ):
            raise ValueError("retry_after_seconds must be non-negative or null")
        self.retry_after_seconds = retry_after_seconds


class TransientProviderError(ProviderError):
    def __init__(
        self,
        message: str,
        *,
        code: str,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(
            message,
            category=ProviderErrorCategory.TRANSIENT,
            code=code,
            retry_after_seconds=retry_after_seconds,
        )


class PermanentProviderError(ProviderError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(
            message,
            category=ProviderErrorCategory.PERMANENT,
            code=code,
        )
