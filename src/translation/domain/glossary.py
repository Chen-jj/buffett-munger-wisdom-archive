"""Versioned translation glossary contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


GLOSSARY_SCHEMA_VERSION = "translation.glossary.v1"


def _require_exact_keys(
    value: Mapping[str, object], expected: tuple[str, ...], field_name: str
) -> None:
    if set(value) != set(expected):
        raise ValueError(f"{field_name} must contain exactly: {', '.join(expected)}")


def _require_non_blank(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-blank string")
    return value


@dataclass(frozen=True)
class GlossaryEntry:
    source: str
    target: str

    def __post_init__(self) -> None:
        _require_non_blank(self.source, "glossary source")
        _require_non_blank(self.target, "glossary target")

    def to_dict(self) -> dict[str, str]:
        return {"source": self.source, "target": self.target}

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "GlossaryEntry":
        if not isinstance(value, Mapping):
            raise ValueError("glossary entry must be an object")
        _require_exact_keys(value, ("source", "target"), "glossary entry")
        return cls(source=value["source"], target=value["target"])


@dataclass(frozen=True)
class TranslationGlossary:
    entries: tuple[GlossaryEntry, ...] = field(default_factory=tuple)
    schema_version: str = GLOSSARY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != GLOSSARY_SCHEMA_VERSION:
            raise ValueError(f"unsupported glossary schema: {self.schema_version}")
        object.__setattr__(self, "entries", tuple(self.entries))
        if not all(isinstance(entry, GlossaryEntry) for entry in self.entries):
            raise ValueError("glossary entries must contain GlossaryEntry values")

        targets_by_source: dict[str, str] = {}
        for entry in self.entries:
            prior_target = targets_by_source.setdefault(entry.source, entry.target)
            if prior_target != entry.target:
                raise ValueError(
                    "one glossary source must not map to different targets"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "entries": [entry.to_dict() for entry in self.entries],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "TranslationGlossary":
        if not isinstance(value, Mapping):
            raise ValueError("glossary must be an object")
        _require_exact_keys(value, ("schema_version", "entries"), "glossary")
        entries = value["entries"]
        if not isinstance(entries, Sequence) or isinstance(
            entries, (str, bytes, bytearray)
        ):
            raise ValueError("glossary entries must be an array")
        if not all(isinstance(entry, Mapping) for entry in entries):
            raise ValueError("glossary entries must contain objects")
        return cls(
            schema_version=value["schema_version"],
            entries=tuple(GlossaryEntry.from_dict(entry) for entry in entries),
        )
