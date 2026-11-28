"""Pure sentence-boundary policy and punctuation rules."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Mapping, Sequence


SENTENCE_BOUNDARY_POLICY_VERSION = "sentence-boundary.v3"

_OPENING_PUNCTUATION = "\"'\u201c\u2018([{"
_CLOSING_PUNCTUATION = "\"'\u201d\u2019)]}"
_INITIAL_RE = re.compile(r"^[A-Za-z]\.$")
_DOMAIN_SUFFIXES = frozenset({"com", "edu", "gov", "int", "mil", "net", "org"})
_CONTEXTUAL_ABBREVIATIONS = frozenset({"etc."})
_DEFAULT_ABBREVIATIONS = (
    "co.",
    "corp.",
    "dr.",
    "e.g.",
    "etc.",
    "i.e.",
    "inc.",
    "jr.",
    "mr.",
    "mrs.",
    "ms.",
    "prof.",
    "sr.",
    "st.",
    "vs.",
)


@dataclass(frozen=True)
class SentenceBoundaryPolicy:
    """Versioned evidence rules for sentence recovery."""

    abbreviations: tuple[str, ...] = field(default_factory=lambda: _DEFAULT_ABBREVIATIONS)
    version: str = SENTENCE_BOUNDARY_POLICY_VERSION

    def __post_init__(self) -> None:
        if self.version != SENTENCE_BOUNDARY_POLICY_VERSION:
            raise ValueError(f"unsupported sentence boundary policy: {self.version}")
        normalized = tuple(item.strip().lower() for item in self.abbreviations)
        if not normalized or any(not item or not item.endswith(".") for item in normalized):
            raise ValueError("abbreviations must contain period-terminated strings")
        if len(normalized) != len(set(normalized)):
            raise ValueError("abbreviations must not contain duplicates")
        object.__setattr__(self, "abbreviations", normalized)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "abbreviations": list(self.abbreviations),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SentenceBoundaryPolicy":
        if set(data) - {"version", "abbreviations"}:
            raise ValueError("sentence boundary policy contains unsupported fields")
        abbreviations = data.get("abbreviations", _DEFAULT_ABBREVIATIONS)
        if not isinstance(abbreviations, Sequence) or isinstance(
            abbreviations, (str, bytes, bytearray)
        ):
            raise ValueError("abbreviations must be an array")
        return cls(
            version=data.get("version"),
            abbreviations=tuple(abbreviations),
        )


def has_terminal_punctuation(text: str) -> bool:
    """Return whether a word surface ends in sentence punctuation."""

    if not isinstance(text, str) or not text.strip():
        raise ValueError("text must be a non-empty string")
    lexical = text.strip().rstrip(_CLOSING_PUNCTUATION)
    return lexical.endswith((".", "?", "!")) and not lexical.endswith("...")


def is_sentence_terminal(
    words: Sequence[str],
    index: int,
    policy: SentenceBoundaryPolicy,
) -> bool:
    """Apply punctuation exceptions for continuations and lexical periods."""

    if not words:
        raise ValueError("words must not be empty")
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(words):
        raise ValueError("index must identify a word")
    text = _lexical_surface(words[index])
    if text.endswith(("?", "!")):
        return True
    if not text.endswith(".") or text.endswith("..."):
        return False
    lowered = text.lower()
    if lowered in policy.abbreviations:
        if lowered in _CONTEXTUAL_ABBREVIATIONS:
            return index + 1 == len(words) or _starts_with_uppercase(words[index + 1])
        return False
    if index + 1 < len(words):
        if _INITIAL_RE.fullmatch(text) is not None:
            return False
        next_surface = _lexical_surface(words[index + 1]).rstrip(".,;:?!")
        if next_surface in _DOMAIN_SUFFIXES and text[:-1].replace("-", "").isalnum():
            return False
    return True


def _lexical_surface(text: str) -> str:
    return text.strip().lstrip(_OPENING_PUNCTUATION).rstrip(_CLOSING_PUNCTUATION)


def _starts_with_uppercase(text: str) -> bool:
    lexical = _lexical_surface(text)
    return bool(lexical) and lexical[0].isupper()
