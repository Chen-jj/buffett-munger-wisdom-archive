"""Pure official-transcript normalization and fusion artifact contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
import re
import unicodedata
from typing import Any, Mapping, Sequence

from archive_core.interfaces import (
    MatchType,
    StructuredTranscriptDTO,
    TextSource,
    TimedWordDTO,
    TimingSource,
)

from .alignment import AlignmentTimingSource, tokenize_surface_text
from .audio_asr import ProviderIdentity, SourceTimeSpan


TRANSCRIPT_FUSION_SCHEMA_VERSION = "transcription.transcript-fusion.v1"

_OFFICIAL_TOKEN_ID_RE = re.compile(r"^ot[1-9][0-9]*$")
_ASR_WORD_ID_RE = re.compile(r"^aw[1-9][0-9]*$")
_CURRENCY_NAMES = {
    "$": ("dollar", "dollars"),
    "£": ("pound", "pounds"),
    "€": ("euro", "euros"),
}
_CONTRACTIONS = {
    "can't": ("can", "not"),
    "cannot": ("can", "not"),
    "couldn't": ("could", "not"),
    "didn't": ("did", "not"),
    "doesn't": ("does", "not"),
    "don't": ("do", "not"),
    "hadn't": ("had", "not"),
    "hasn't": ("has", "not"),
    "haven't": ("have", "not"),
    "he'll": ("he", "will"),
    "i'll": ("i", "will"),
    "i'm": ("i", "am"),
    "isn't": ("is", "not"),
    "it's": ("it", "is"),
    "shouldn't": ("should", "not"),
    "they'll": ("they", "will"),
    "wasn't": ("was", "not"),
    "we'll": ("we", "will"),
    "we're": ("we", "are"),
    "we've": ("we", "have"),
    "weren't": ("were", "not"),
    "won't": ("will", "not"),
    "wouldn't": ("would", "not"),
    "you'll": ("you", "will"),
    "you're": ("you", "are"),
    "you've": ("you", "have"),
}
_ONES = (
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
)
_TENS = (
    "",
    "",
    "twenty",
    "thirty",
    "forty",
    "fifty",
    "sixty",
    "seventy",
    "eighty",
    "ninety",
)


def _require_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _require_int(value: object, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _require_sequence(value: object, name: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{name} must be an array")
    return value


@dataclass(frozen=True)
class NormalizationPolicy:
    version: str = "english-spoken.v1"

    def __post_init__(self) -> None:
        _require_text(self.version, "version")

    def to_dict(self) -> dict[str, Any]:
        return {"version": self.version}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "NormalizationPolicy":
        return cls(version=data.get("version"))


@dataclass(frozen=True)
class MatchingPolicy:
    version: str = "monotonic-local-dp.v1"
    anchor_ngram_size: int = 2
    max_local_window_words: int = 24
    max_unanchored_conflict_words: int = 4
    max_group_size: int = 4
    max_official_only_words: int = 3
    allowed_substitutions: tuple[tuple[str, str], ...] = field(
        default_factory=tuple
    )

    def __post_init__(self) -> None:
        _require_text(self.version, "version")
        _require_int(self.anchor_ngram_size, "anchor_ngram_size", minimum=2)
        _require_int(self.max_local_window_words, "max_local_window_words", minimum=1)
        _require_int(
            self.max_unanchored_conflict_words,
            "max_unanchored_conflict_words",
            minimum=1,
        )
        _require_int(self.max_group_size, "max_group_size", minimum=2)
        _require_int(self.max_official_only_words, "max_official_only_words", minimum=1)
        object.__setattr__(
            self,
            "allowed_substitutions",
            tuple(
                tuple(
                    " ".join(value.casefold().split())
                    if isinstance(value, str)
                    else value
                    for value in pair
                )
                for pair in self.allowed_substitutions
            ),
        )
        if not all(
            len(pair) == 2
            and all(isinstance(value, str) and value.strip() for value in pair)
            for pair in self.allowed_substitutions
        ):
            raise ValueError(
                "allowed_substitutions must contain non-empty ASR/official pairs"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "anchor_ngram_size": self.anchor_ngram_size,
            "max_local_window_words": self.max_local_window_words,
            "max_unanchored_conflict_words": self.max_unanchored_conflict_words,
            "max_group_size": self.max_group_size,
            "max_official_only_words": self.max_official_only_words,
            "allowed_substitutions": [
                list(pair) for pair in self.allowed_substitutions
            ],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MatchingPolicy":
        substitutions = _require_sequence(
            data.get("allowed_substitutions", []), "allowed_substitutions"
        )
        return cls(
            version=data.get("version"),
            anchor_ngram_size=data.get("anchor_ngram_size"),
            max_local_window_words=data.get("max_local_window_words"),
            max_unanchored_conflict_words=data.get(
                "max_unanchored_conflict_words"
            ),
            max_group_size=data.get("max_group_size"),
            max_official_only_words=data.get("max_official_only_words"),
            allowed_substitutions=tuple(
                tuple(_require_sequence(pair, "allowed_substitutions item"))
                for pair in substitutions
            ),
        )


@dataclass(frozen=True)
class OfficialAlignmentConfig:
    model: str
    model_version: str
    device: str
    min_alignment_score: float = 0.5
    min_anchor_alignment_score: float = 0.5
    language: str = "en"

    def __post_init__(self) -> None:
        _require_text(self.model, "model")
        _require_text(self.model_version, "model_version")
        _require_text(self.device, "device")
        if self.language != "en":
            raise ValueError("language must be en")
        for name, value in (
            ("min_alignment_score", self.min_alignment_score),
            ("min_anchor_alignment_score", self.min_anchor_alignment_score),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or not 0 <= float(value) <= 1
            ):
                raise ValueError(f"{name} must be between 0 and 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "model_version": self.model_version,
            "device": self.device,
            "min_alignment_score": self.min_alignment_score,
            "min_anchor_alignment_score": self.min_anchor_alignment_score,
            "language": self.language,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OfficialAlignmentConfig":
        return cls(
            model=data.get("model"),
            model_version=data.get("model_version"),
            device=data.get("device"),
            min_alignment_score=data.get("min_alignment_score"),
            min_anchor_alignment_score=data.get(
                "min_anchor_alignment_score"
            ),
            language=data.get("language"),
        )


def normalize_token(
    surface: str, policy: NormalizationPolicy | None = None
) -> tuple[str, ...]:
    """Return versioned English matching units while preserving surface elsewhere."""

    selected = policy or NormalizationPolicy()
    if selected.version != "english-spoken.v1":
        raise ValueError(f"unsupported normalization policy: {selected.version}")
    text = unicodedata.normalize("NFKC", _require_text(surface, "surface"))
    text = text.casefold().replace("’", "'").replace("‘", "'")
    currency = next((symbol for symbol in _CURRENCY_NAMES if symbol in text), None)
    percent = "%" in text
    text = text.replace("–", "-").replace("—", "-")
    for symbol in _CURRENCY_NAMES:
        text = text.replace(symbol, "")
    text = text.replace("%", "").replace("-", " ")
    text = re.sub(r"[^\w'\s.,]", "", text, flags=re.UNICODE)
    units: list[str] = []
    numeric_value: int | None = None
    for raw_part in text.split():
        part = raw_part.strip(".,")
        if part in _CONTRACTIONS:
            units.extend(_CONTRACTIONS[part])
            continue
        numeric_part = part.replace(",", "")
        if re.fullmatch(r"\d+(?:\.\d+)?", numeric_part):
            whole, separator, fraction = numeric_part.partition(".")
            value = int(whole)
            numeric_value = value
            year_style = (
                currency is None
                and not percent
                and "," not in part
                and len(whole) == 4
            )
            units.extend(_integer_words(value, year_style=year_style))
            if separator:
                units.append("point")
                units.extend(_ONES[int(digit)] for digit in fraction)
            continue
        normalized = part.replace("'", "").replace(",", "").replace(".", "")
        if normalized:
            units.append(normalized)
    if currency is not None:
        singular, plural = _CURRENCY_NAMES[currency]
        units.append(singular if numeric_value == 1 else plural)
    if percent:
        units.append("percent")
    if not units:
        raise ValueError("surface must contain spoken lexical content")
    return tuple(units)


def _integer_words(value: int, *, year_style: bool = False) -> tuple[str, ...]:
    if value < 0 or value > 999_999_999:
        return (str(value),)
    if year_style and 1100 <= value <= 1999:
        first, second = divmod(value, 100)
        suffix = _under_thousand(second) if second else ("hundred",)
        return _under_thousand(first) + suffix
    if value < 1000:
        return _under_thousand(value)
    result: list[str] = []
    for size, label in ((1_000_000, "million"), (1_000, "thousand")):
        if value >= size:
            quotient, value = divmod(value, size)
            result.extend(_under_thousand(quotient))
            result.append(label)
    if value:
        result.extend(_under_thousand(value))
    return tuple(result)


def _under_thousand(value: int) -> tuple[str, ...]:
    if value < 20:
        return (_ONES[value],)
    result: list[str] = []
    if value >= 100:
        hundreds, value = divmod(value, 100)
        result.extend((_ONES[hundreds], "hundred"))
    if value >= 20:
        tens, value = divmod(value, 10)
        result.append(_TENS[tens])
    if value:
        result.append(_ONES[value])
    return tuple(result)


@dataclass(frozen=True)
class OfficialTranscriptToken:
    id: str
    text: str
    normalized: tuple[str, ...]
    chapter_index: int
    chapter_number: int
    paragraph_index: int
    speaker_label: str | None

    def __post_init__(self) -> None:
        _require_text(self.id, "id")
        if _OFFICIAL_TOKEN_ID_RE.fullmatch(self.id) is None:
            raise ValueError("official token id must use ot<one-based position>")
        _require_text(self.text, "text")
        object.__setattr__(self, "normalized", tuple(self.normalized))
        if not self.normalized or not all(
            isinstance(unit, str) and unit for unit in self.normalized
        ):
            raise ValueError("normalized must contain lexical units")
        _require_int(self.chapter_index, "chapter_index", minimum=1)
        _require_int(self.chapter_number, "chapter_number")
        _require_int(self.paragraph_index, "paragraph_index", minimum=1)
        if self.speaker_label is not None:
            _require_text(self.speaker_label, "speaker_label")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "normalized": list(self.normalized),
            "chapter_index": self.chapter_index,
            "chapter_number": self.chapter_number,
            "paragraph_index": self.paragraph_index,
            "speaker_label": self.speaker_label,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OfficialTranscriptToken":
        normalized = _require_sequence(data.get("normalized", []), "normalized")
        return cls(
            id=data.get("id"),
            text=data.get("text"),
            normalized=tuple(normalized),
            chapter_index=data.get("chapter_index"),
            chapter_number=data.get("chapter_number"),
            paragraph_index=data.get("paragraph_index"),
            speaker_label=data.get("speaker_label"),
        )


class IgnoredContentKind(str, Enum):
    CHAPTER_TITLE = "chapter_title"
    STAGE_DIRECTION = "stage_direction"


@dataclass(frozen=True)
class IgnoredOfficialContent:
    kind: IgnoredContentKind
    text: str
    chapter_number: int
    paragraph_index: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, IgnoredContentKind):
            raise ValueError("kind must be an IgnoredContentKind")
        _require_text(self.text, "text")
        _require_int(self.chapter_number, "chapter_number")
        if self.paragraph_index is not None:
            _require_int(self.paragraph_index, "paragraph_index", minimum=1)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "kind": self.kind.value,
            "text": self.text,
            "chapter_number": self.chapter_number,
        }
        if self.paragraph_index is not None:
            data["paragraph_index"] = self.paragraph_index
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "IgnoredOfficialContent":
        return cls(
            kind=IgnoredContentKind(data.get("kind")),
            text=data.get("text"),
            chapter_number=data.get("chapter_number"),
            paragraph_index=data.get("paragraph_index"),
        )


def build_official_tokens(
    transcript: StructuredTranscriptDTO,
    policy: NormalizationPolicy,
) -> tuple[tuple[OfficialTranscriptToken, ...], tuple[IgnoredOfficialContent, ...]]:
    """Tokenize only paragraph spoken text from the public structured DTO."""

    if not isinstance(transcript, StructuredTranscriptDTO):
        raise ValueError("transcript must be a StructuredTranscriptDTO")
    tokens: list[OfficialTranscriptToken] = []
    ignored: list[IgnoredOfficialContent] = []
    for chapter_index, chapter in enumerate(transcript.chapters, start=1):
        if chapter.title.strip():
            ignored.append(
                IgnoredOfficialContent(
                    IgnoredContentKind.CHAPTER_TITLE,
                    chapter.title,
                    chapter.number,
                )
            )
        for paragraph_index, paragraph in enumerate(chapter.paragraphs, start=1):
            if paragraph.text:
                for surface in tokenize_surface_text(paragraph.text):
                    tokens.append(
                        OfficialTranscriptToken(
                            id=f"ot{len(tokens) + 1}",
                            text=surface,
                            normalized=normalize_token(surface, policy),
                            chapter_index=chapter_index,
                            chapter_number=chapter.number,
                            paragraph_index=paragraph_index,
                            speaker_label=paragraph.speaker_label,
                        )
                    )
            ignored.extend(
                IgnoredOfficialContent(
                    IgnoredContentKind.STAGE_DIRECTION,
                    direction,
                    chapter.number,
                    paragraph_index,
                )
                for direction in paragraph.stage_directions
            )
    return tuple(tokens), tuple(ignored)


@dataclass(frozen=True)
class OfficialAlignmentCandidate:
    official_token_id: str
    text: str
    start_ms: int
    end_ms: int
    alignment_score: float

    def __post_init__(self) -> None:
        _require_text(self.official_token_id, "official_token_id")
        if _OFFICIAL_TOKEN_ID_RE.fullmatch(self.official_token_id) is None:
            raise ValueError("official_token_id must use ot<one-based position>")
        _require_text(self.text, "text")
        SourceTimeSpan(self.start_ms, self.end_ms)
        if (
            isinstance(self.alignment_score, bool)
            or not isinstance(self.alignment_score, (int, float))
            or not math.isfinite(float(self.alignment_score))
            or not 0 <= float(self.alignment_score) <= 1
        ):
            raise ValueError("alignment_score must be between 0 and 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "official_token_id": self.official_token_id,
            "text": self.text,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "alignment_score": self.alignment_score,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OfficialAlignmentCandidate":
        return cls(
            official_token_id=data.get("official_token_id"),
            text=data.get("text"),
            start_ms=data.get("start_ms"),
            end_ms=data.get("end_ms"),
            alignment_score=data.get("alignment_score"),
        )


@dataclass(frozen=True)
class ExcludedOfficialTokens:
    official_token_ids: tuple[str, ...]
    reason: str
    left_anchor_id: str | None = None
    right_anchor_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "official_token_ids", tuple(self.official_token_ids))
        if not self.official_token_ids or not all(
            _OFFICIAL_TOKEN_ID_RE.fullmatch(token_id)
            for token_id in self.official_token_ids
        ):
            raise ValueError("official_token_ids must contain stable IDs")
        _require_text(self.reason, "reason")

    def to_dict(self) -> dict[str, Any]:
        return {
            "official_token_ids": list(self.official_token_ids),
            "reason": self.reason,
            "left_anchor_id": self.left_anchor_id,
            "right_anchor_id": self.right_anchor_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ExcludedOfficialTokens":
        token_ids = _require_sequence(
            data.get("official_token_ids", []), "official_token_ids"
        )
        return cls(
            official_token_ids=tuple(token_ids),
            reason=data.get("reason"),
            left_anchor_id=data.get("left_anchor_id"),
            right_anchor_id=data.get("right_anchor_id"),
        )


class LocalValidationStatus(str, Enum):
    RECOVERED = "recovered"
    EXCLUDED = "excluded"


@dataclass(frozen=True)
class LocalAlignmentValidation:
    official_token_ids: tuple[str, ...]
    left_anchor_id: str | None
    right_anchor_id: str | None
    status: LocalValidationStatus
    reason: str
    candidates: tuple[OfficialAlignmentCandidate, ...] = field(
        default_factory=tuple
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "official_token_ids", tuple(self.official_token_ids))
        if not self.official_token_ids:
            raise ValueError("official_token_ids must not be empty")
        if not isinstance(self.status, LocalValidationStatus):
            raise ValueError("status must be a LocalValidationStatus")
        _require_text(self.reason, "reason")
        object.__setattr__(self, "candidates", tuple(self.candidates))
        if not all(
            isinstance(candidate, OfficialAlignmentCandidate)
            for candidate in self.candidates
        ):
            raise ValueError(
                "candidates must contain OfficialAlignmentCandidate values"
            )
        candidate_ids = tuple(
            candidate.official_token_id for candidate in self.candidates
        )
        if self.status is LocalValidationStatus.RECOVERED:
            if candidate_ids != self.official_token_ids:
                raise ValueError(
                    "recovered validation candidates must cover official tokens"
                )
        elif self.candidates:
            raise ValueError("excluded validation must not contain candidates")

    def to_dict(self) -> dict[str, Any]:
        return {
            "official_token_ids": list(self.official_token_ids),
            "left_anchor_id": self.left_anchor_id,
            "right_anchor_id": self.right_anchor_id,
            "status": self.status.value,
            "reason": self.reason,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LocalAlignmentValidation":
        token_ids = _require_sequence(
            data.get("official_token_ids", []), "official_token_ids"
        )
        candidates = _require_sequence(data.get("candidates", []), "candidates")
        return cls(
            official_token_ids=tuple(token_ids),
            left_anchor_id=data.get("left_anchor_id"),
            right_anchor_id=data.get("right_anchor_id"),
            status=LocalValidationStatus(data.get("status")),
            reason=data.get("reason"),
            candidates=tuple(
                OfficialAlignmentCandidate.from_dict(candidate)
                for candidate in candidates
            ),
        )


class FusionMode(str, Enum):
    OFFICIAL = "official"
    NO_OFFICIAL = "no_official"


@dataclass(frozen=True)
class TranscriptFusionArtifact:
    audio_duration_ms: int
    aligned_asr_sha256: str
    chapters_sha256: str | None
    mode: FusionMode
    normalization: NormalizationPolicy
    matching: MatchingPolicy
    official_aligner: ProviderIdentity | None
    official_alignment_config: OfficialAlignmentConfig | None
    official_tokens: tuple[OfficialTranscriptToken, ...]
    ignored_content: tuple[IgnoredOfficialContent, ...]
    words: tuple[TimedWordDTO, ...]
    excluded_official: tuple[ExcludedOfficialTokens, ...]
    local_validations: tuple[LocalAlignmentValidation, ...]
    cache_key: str
    schema_version: str = TRANSCRIPT_FUSION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != TRANSCRIPT_FUSION_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported transcript fusion schema: {self.schema_version}"
            )
        _require_int(self.audio_duration_ms, "audio_duration_ms", minimum=1)
        _require_text(self.aligned_asr_sha256, "aligned_asr_sha256")
        _require_text(self.cache_key, "cache_key")
        if not isinstance(self.mode, FusionMode):
            raise ValueError("mode must be a FusionMode")
        if not isinstance(self.normalization, NormalizationPolicy):
            raise ValueError("normalization must be a NormalizationPolicy")
        if not isinstance(self.matching, MatchingPolicy):
            raise ValueError("matching must be a MatchingPolicy")
        if (self.official_aligner is None) != (self.official_alignment_config is None):
            raise ValueError(
                "official aligner identity and config must appear together"
            )
        for name in (
            "official_tokens",
            "ignored_content",
            "words",
            "excluded_official",
            "local_validations",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        self._validate_mode()
        self._validate_words()
        self._validate_official_coverage()

    def _validate_mode(self) -> None:
        if self.mode is FusionMode.NO_OFFICIAL:
            if self.chapters_sha256 is not None or self.official_tokens:
                raise ValueError("no_official mode must not contain official input")
        else:
            _require_text(self.chapters_sha256, "chapters_sha256")

    def _validate_words(self) -> None:
        previous_end = 0
        all_asr_ids: list[str] = []
        for position, word in enumerate(self.words, start=1):
            if not isinstance(word, TimedWordDTO) or word.id != f"w{position}":
                raise ValueError("fusion words must use stable w1..wN IDs")
            if word.start_ms < previous_end or word.end_ms > self.audio_duration_ms:
                raise ValueError("fusion word timeline must be monotonic and in bounds")
            previous_end = word.end_ms
            all_asr_ids.extend(word.asr_word_ids)
            self._validate_mapping_cardinality(word)
        expected_asr_ids = [
            f"aw{position}" for position in range(1, len(all_asr_ids) + 1)
        ]
        if all_asr_ids != expected_asr_ids:
            raise ValueError(
                "fusion must cover aligned ASR words exactly once in order"
            )

    @staticmethod
    def _validate_mapping_cardinality(word: TimedWordDTO) -> None:
        cardinalities = {
            MatchType.EXACT: (1, 1),
            MatchType.NORMALIZED_EXACT: (1, 1),
            MatchType.SUBSTITUTION: (1, 1),
            MatchType.ONE_TO_MANY: (1, None),
            MatchType.MANY_TO_ONE: (None, 1),
            MatchType.ASR_ONLY: (1, 0),
            MatchType.OFFICIAL_ONLY: (0, 1),
        }
        asr_expected, official_expected = cardinalities[word.match_type]
        if asr_expected is None:
            valid_asr = len(word.asr_word_ids) > 1
        else:
            valid_asr = len(word.asr_word_ids) == asr_expected
        if official_expected is None:
            valid_official = len(word.official_token_ids) > 1
        else:
            valid_official = len(word.official_token_ids) == official_expected
        if not valid_asr or not valid_official:
            raise ValueError("fusion mapping IDs do not match match_type cardinality")
        expected_text_source = {
            MatchType.EXACT: TextSource.OFFICIAL_TRANSCRIPT,
            MatchType.NORMALIZED_EXACT: TextSource.OFFICIAL_TRANSCRIPT,
            MatchType.SUBSTITUTION: TextSource.OFFICIAL_TRANSCRIPT,
            MatchType.ONE_TO_MANY: TextSource.ASR,
            MatchType.MANY_TO_ONE: TextSource.OFFICIAL_TRANSCRIPT,
            MatchType.ASR_ONLY: TextSource.ASR,
            MatchType.OFFICIAL_ONLY: TextSource.OFFICIAL_TRANSCRIPT,
        }[word.match_type]
        if word.text_source is not expected_text_source:
            raise ValueError("fusion text_source does not match match_type")
        if (
            word.match_type is MatchType.MANY_TO_ONE
            and word.timing_source is not TimingSource.MERGED_ACOUSTIC_ALIGNMENT
        ):
            raise ValueError("many_to_one requires merged acoustic timing")
        if (
            word.match_type is not MatchType.MANY_TO_ONE
            and word.timing_source is TimingSource.MERGED_ACOUSTIC_ALIGNMENT
        ):
            raise ValueError("only many_to_one may use merged acoustic timing")
        if (
            word.match_type is MatchType.OFFICIAL_ONLY
            and word.timing_source is not TimingSource.ACOUSTIC_ALIGNMENT
        ):
            raise ValueError("official_only requires acoustic timing")

    def _validate_official_coverage(self) -> None:
        token_ids = [token.id for token in self.official_tokens]
        if token_ids != [f"ot{position}" for position in range(1, len(token_ids) + 1)]:
            raise ValueError("official tokens must use stable ot1..otN IDs")
        covered = [
            token_id
            for word in self.words
            for token_id in word.official_token_ids
        ]
        covered.extend(
            token_id
            for exclusion in self.excluded_official
            for token_id in exclusion.official_token_ids
        )
        if sorted(covered, key=lambda value: int(value[2:])) != token_ids:
            raise ValueError(
                "every official token must be mapped or explicitly excluded once"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "audio_duration_ms": self.audio_duration_ms,
            "aligned_asr_sha256": self.aligned_asr_sha256,
            "chapters_sha256": self.chapters_sha256,
            "mode": self.mode.value,
            "normalization": self.normalization.to_dict(),
            "matching": self.matching.to_dict(),
            "official_aligner": (
                self.official_aligner.to_dict()
                if self.official_aligner is not None
                else None
            ),
            "official_alignment_config": (
                self.official_alignment_config.to_dict()
                if self.official_alignment_config is not None
                else None
            ),
            "official_tokens": [token.to_dict() for token in self.official_tokens],
            "ignored_content": [item.to_dict() for item in self.ignored_content],
            "words": [word.to_dict() for word in self.words],
            "excluded_official": [item.to_dict() for item in self.excluded_official],
            "local_validations": [item.to_dict() for item in self.local_validations],
            "cache_key": self.cache_key,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TranscriptFusionArtifact":
        if data.get("schema_version") != TRANSCRIPT_FUSION_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported transcript fusion schema: {data.get('schema_version')}"
            )
        normalization = data.get("normalization")
        matching = data.get("matching")
        aligner = data.get("official_aligner")
        alignment_config = data.get("official_alignment_config")
        if not isinstance(normalization, Mapping) or not isinstance(matching, Mapping):
            raise ValueError("normalization and matching must be objects")
        sequences = {
            name: _require_sequence(data.get(name, []), name)
            for name in (
                "official_tokens",
                "ignored_content",
                "words",
                "excluded_official",
                "local_validations",
            )
        }
        return cls(
            schema_version=data.get("schema_version"),
            audio_duration_ms=data.get("audio_duration_ms"),
            aligned_asr_sha256=data.get("aligned_asr_sha256"),
            chapters_sha256=data.get("chapters_sha256"),
            mode=FusionMode(data.get("mode")),
            normalization=NormalizationPolicy.from_dict(normalization),
            matching=MatchingPolicy.from_dict(matching),
            official_aligner=(
                ProviderIdentity.from_dict(aligner)
                if isinstance(aligner, Mapping)
                else None
            ),
            official_alignment_config=(
                OfficialAlignmentConfig.from_dict(alignment_config)
                if isinstance(alignment_config, Mapping)
                else None
            ),
            official_tokens=tuple(
                OfficialTranscriptToken.from_dict(item)
                for item in sequences["official_tokens"]
            ),
            ignored_content=tuple(
                IgnoredOfficialContent.from_dict(item)
                for item in sequences["ignored_content"]
            ),
            words=tuple(TimedWordDTO.from_dict(item) for item in sequences["words"]),
            excluded_official=tuple(
                ExcludedOfficialTokens.from_dict(item)
                for item in sequences["excluded_official"]
            ),
            local_validations=tuple(
                LocalAlignmentValidation.from_dict(item)
                for item in sequences["local_validations"]
            ),
            cache_key=data.get("cache_key"),
        )


def aligned_timing_source(source: AlignmentTimingSource) -> TimingSource:
    if source is AlignmentTimingSource.ACOUSTIC_ALIGNMENT:
        return TimingSource.ACOUSTIC_ALIGNMENT
    return TimingSource.INTERPOLATED
