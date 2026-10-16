"""Static provider response schema and exact request/response validation."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .models import ProviderResponse, ProviderStatus, TranslationRequest


RESPONSE_SCHEMA_VERSION = "translation.response.v1"

TRANSLATION_RESPONSE_JSON_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "section": {
            "anyOf": [
                {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "translated_title": {
                            "anyOf": [{"type": "string"}, {"type": "null"}]
                        },
                    },
                    "required": ["id", "translated_title"],
                    "additionalProperties": False,
                },
                {"type": "null"},
            ]
        },
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "translated_text": {"type": "string"},
                },
                "required": ["id", "translated_text"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["section", "items"],
    "additionalProperties": False,
}


class TranslationResponseValidationError(ValueError):
    """A provider response failed deterministic correspondence validation."""


@dataclass(frozen=True)
class TranslatedSection:
    id: str
    translated_title: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("translated section id must be a non-blank string")
        if self.translated_title is not None and (
            not isinstance(self.translated_title, str)
            or not self.translated_title.strip()
        ):
            raise ValueError("translated_title must be a non-blank string or null")

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "translated_title": self.translated_title}


@dataclass(frozen=True)
class TranslatedItem:
    id: str
    translated_text: str

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("translated item id must be a non-blank string")
        if not isinstance(self.translated_text, str) or not self.translated_text.strip():
            raise ValueError("translated_text must be a non-blank string")

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "translated_text": self.translated_text}


@dataclass(frozen=True)
class ValidatedTranslationOutput:
    section: TranslatedSection | None
    items: tuple[TranslatedItem, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.section is not None and not isinstance(self.section, TranslatedSection):
            raise ValueError("section must be a TranslatedSection or null")
        object.__setattr__(self, "items", tuple(self.items))
        if not all(isinstance(item, TranslatedItem) for item in self.items):
            raise ValueError("items must contain TranslatedItem values")

    def to_dict(self) -> dict[str, Any]:
        return {
            "section": self.section.to_dict() if self.section is not None else None,
            "items": [item.to_dict() for item in self.items],
        }


def translation_response_schema() -> dict[str, object]:
    """Return an isolated copy of the fixed response JSON Schema."""

    return deepcopy(TRANSLATION_RESPONSE_JSON_SCHEMA)


def _require_exact_keys(
    value: Mapping[str, object], expected: tuple[str, ...], field_name: str
) -> None:
    if set(value) != set(expected):
        raise TranslationResponseValidationError(
            f"{field_name} must contain exactly: {', '.join(expected)}"
        )


def validate_provider_response(
    request: TranslationRequest, response: ProviderResponse
) -> ValidatedTranslationOutput:
    """Validate exact output fields and correspondence with one request."""

    if not isinstance(request, TranslationRequest):
        raise ValueError("request must be a TranslationRequest")
    if not isinstance(response, ProviderResponse):
        raise ValueError("response must be a ProviderResponse")
    if response.status != ProviderStatus.COMPLETED:
        raise TranslationResponseValidationError(
            f"provider response status is {response.status.value}"
        )
    if not isinstance(response.output, Mapping):
        raise TranslationResponseValidationError("provider output must be an object")

    output = response.output
    _require_exact_keys(output, ("section", "items"), "provider output")

    raw_section = output["section"]
    translated_section: TranslatedSection | None
    if request.section is None:
        if raw_section is not None:
            raise TranslationResponseValidationError(
                "document request response section must be null"
            )
        translated_section = None
    else:
        if not isinstance(raw_section, Mapping):
            raise TranslationResponseValidationError(
                "section request response section must be an object"
            )
        _require_exact_keys(
            raw_section, ("id", "translated_title"), "response section"
        )
        if raw_section["id"] != request.section.id:
            raise TranslationResponseValidationError(
                "response section ID must match request section ID"
            )
        translated_title = raw_section["translated_title"]
        if request.section.title:
            if not isinstance(translated_title, str) or not translated_title.strip():
                raise TranslationResponseValidationError(
                    "non-empty source section title requires a non-blank translation"
                )
        elif translated_title is not None:
            raise TranslationResponseValidationError(
                "empty source section title requires a null translation"
            )
        translated_section = TranslatedSection(
            id=request.section.id,
            translated_title=translated_title,
        )

    raw_items = output["items"]
    if not isinstance(raw_items, Sequence) or isinstance(
        raw_items, (str, bytes, bytearray)
    ):
        raise TranslationResponseValidationError("response items must be an array")
    if len(raw_items) != len(request.items):
        raise TranslationResponseValidationError(
            "response item count must match request item count"
        )

    translated_items = []
    for position, (raw_item, request_item) in enumerate(
        zip(raw_items, request.items, strict=True), start=1
    ):
        if not isinstance(raw_item, Mapping):
            raise TranslationResponseValidationError(
                f"response item {position} must be an object"
            )
        _require_exact_keys(
            raw_item, ("id", "translated_text"), f"response item {position}"
        )
        if raw_item["id"] != request_item.id:
            raise TranslationResponseValidationError(
                "response item IDs must exactly match request order and coverage"
            )
        translated_text = raw_item["translated_text"]
        if not isinstance(translated_text, str) or not translated_text.strip():
            raise TranslationResponseValidationError(
                "translated_text must be a non-blank string"
            )
        translated_items.append(
            TranslatedItem(id=request_item.id, translated_text=translated_text)
        )

    return ValidatedTranslationOutput(
        section=translated_section,
        items=tuple(translated_items),
    )
