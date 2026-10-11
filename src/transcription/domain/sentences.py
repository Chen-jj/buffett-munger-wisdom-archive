"""Pure sentence-boundary policy and punctuation rules."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Mapping, Sequence


SENTENCE_BOUNDARY_POLICY_VERSION = "sentence-boundary.v1"

_OPENING_PUNCTUATION = "\"'\u201c\u2018([{"
_CLOSING_PUNCTUATION = "\"'\u201d\u2019)]}"
_INITIAL_RE = re.compile(r"^[A-Za-z]\.$")
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


def _require_int(value: object, name: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


@dataclass(frozen=True)
class SentenceBoundaryPolicy:
    """Versioned rules and publication gate for sentence recovery."""

    inferred_pause_ms: int = 700
    fallback_pause_ms: int = 1_200
    max_words_without_boundary: int = 80
    max_fallback_sentences: int = 10
    max_fallback_ratio: float = 0.25
    abbreviations: tuple[str, ...] = field(default_factory=lambda: _DEFAULT_ABBREVIATIONS)
    version: str = SENTENCE_BOUNDARY_POLICY_VERSION

    def __post_init__(self) -> None:
        if self.version != SENTENCE_BOUNDARY_POLICY_VERSION:
            raise ValueError(f"unsupported sentence boundary policy: {self.version}")
        _require_int(self.inferred_pause_ms, "inferred_pause_ms", minimum=0)
        _require_int(self.fallback_pause_ms, "fallback_pause_ms", minimum=0)
        if self.fallback_pause_ms < self.inferred_pause_ms:
            raise ValueError("fallback_pause_ms must be >= inferred_pause_ms")
        _require_int(
            self.max_words_without_boundary,
            "max_words_without_boundary",
            minimum=2,
        )
        _require_int(
            self.max_fallback_sentences, "max_fallback_sentences", minimum=0
        )
        if (
            isinstance(self.max_fallback_ratio, bool)
            or not isinstance(self.max_fallback_ratio, (int, float))
            or not 0 <= float(self.max_fallback_ratio) <= 1
        ):
            raise ValueError("max_fallback_ratio must be between 0 and 1")
        normalized = tuple(item.strip().lower() for item in self.abbreviations)
        if not normalized or any(not item or not item.endswith(".") for item in normalized):
            raise ValueError("abbreviations must contain period-terminated strings")
        if len(normalized) != len(set(normalized)):
            raise ValueError("abbreviations must not contain duplicates")
        object.__setattr__(self, "abbreviations", normalized)
        object.__setattr__(self, "max_fallback_ratio", float(self.max_fallback_ratio))

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "inferred_pause_ms": self.inferred_pause_ms,
            "fallback_pause_ms": self.fallback_pause_ms,
            "max_words_without_boundary": self.max_words_without_boundary,
            "max_fallback_sentences": self.max_fallback_sentences,
            "max_fallback_ratio": self.max_fallback_ratio,
            "abbreviations": list(self.abbreviations),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SentenceBoundaryPolicy":
        abbreviations = data.get("abbreviations", _DEFAULT_ABBREVIATIONS)
        if not isinstance(abbreviations, Sequence) or isinstance(
            abbreviations, (str, bytes, bytearray)
        ):
            raise ValueError("abbreviations must be an array")
        return cls(
            version=data.get("version"),
            inferred_pause_ms=data.get("inferred_pause_ms"),
            fallback_pause_ms=data.get("fallback_pause_ms"),
            max_words_without_boundary=data.get("max_words_without_boundary"),
            max_fallback_sentences=data.get("max_fallback_sentences"),
            max_fallback_ratio=data.get("max_fallback_ratio"),
            abbreviations=tuple(abbreviations),
        )


def has_terminal_punctuation(text: str) -> bool:
    """Return whether a word surface ends in sentence punctuation."""

    if not isinstance(text, str) or not text.strip():
        raise ValueError("text must be a non-empty string")
    lexical = text.strip().rstrip(_CLOSING_PUNCTUATION)
    return lexical.endswith((".", "?", "!"))


def is_sentence_terminal(
    words: Sequence[str],
    index: int,
    policy: SentenceBoundaryPolicy,
) -> bool:
    """Apply abbreviation and name-initial exceptions to terminal punctuation."""

    if not words:
        raise ValueError("words must not be empty")
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(words):
        raise ValueError("index must identify a word")
    text = _lexical_surface(words[index])
    if text.endswith(("?", "!")):
        return True
    if not text.endswith("."):
        return False
    lowered = text.lower()
    if lowered in policy.abbreviations:
        if lowered in _CONTEXTUAL_ABBREVIATIONS:
            return index + 1 == len(words) or _starts_with_uppercase(words[index + 1])
        return False
    if _INITIAL_RE.fullmatch(text) is not None and index + 1 < len(words):
        return False
    return True


def _lexical_surface(text: str) -> str:
    return text.strip().lstrip(_OPENING_PUNCTUATION).rstrip(_CLOSING_PUNCTUATION)


def _starts_with_uppercase(text: str) -> bool:
    lexical = _lexical_surface(text)
    return bool(lexical) and lexical[0].isupper()
