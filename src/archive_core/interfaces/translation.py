"""Shared section title translation value; chunk results live in bilingual."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping

_SECTION_ID_RE = re.compile(r"^sec[1-9][0-9]*$")


def _require_non_empty_string(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


@dataclass(frozen=True)
class SectionTitleTranslationDTO:
    section_id: str
    translated_title: str

    def __post_init__(self) -> None:
        _require_non_empty_string(self.section_id, "section_id")
        if _SECTION_ID_RE.fullmatch(self.section_id) is None:
            raise ValueError("section_id must use the format sec<one-based position>")
        _require_non_empty_string(self.translated_title, "translated_title")

    def to_dict(self) -> dict[str, Any]:
        return {
            "section_id": self.section_id,
            "translated_title": self.translated_title,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SectionTitleTranslationDTO":
        if not isinstance(data, Mapping) or set(data) != {"section_id", "translated_title"}:
            raise ValueError("section title has missing or unknown fields")
        return cls(
            section_id=data["section_id"],
            translated_title=data["translated_title"],
        )
