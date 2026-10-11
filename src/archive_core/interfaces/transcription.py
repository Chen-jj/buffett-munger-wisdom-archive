"""Public JSON contracts shared by acquisition and transcription consumers."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Any, Mapping, Sequence


STRUCTURED_TRANSCRIPT_SCHEMA_VERSION = "acquisition.transcript.v2"
SOURCE_ALIGNMENT_SCHEMA_VERSION = "transcription.source-alignment.v1"

_TIMED_WORD_ID_RE = re.compile(r"^w[1-9][0-9]*$")
_SOURCE_SENTENCE_ID_RE = re.compile(r"^s[1-9][0-9]*$")
_SPACE_BEFORE_PUNCTUATION_RE = re.compile(r"\s+([,.;:?!%\)\]\}])")
_SPACE_AFTER_OPENING_PUNCTUATION_RE = re.compile(r"([\(\[\{])\s+")


def _require_non_empty_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _require_integer(value: object, field_name: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        qualifier = "non-negative" if minimum == 0 else f">= {minimum}"
        raise ValueError(f"{field_name} must be an integer {qualifier}")
    return value


def _require_sequence(value: object, field_name: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{field_name} must be an array")
    return value


def _string_tuple(values: object, field_name: str) -> tuple[str, ...]:
    items = _require_sequence(values, field_name)
    result = tuple(
        _require_non_empty_string(item, f"{field_name} item") for item in items
    )
    if len(result) != len(set(result)):
        raise ValueError(f"{field_name} must not contain duplicate IDs")
    return result


def timed_word_id(position: int) -> str:
    """Return the stable ID for a timed word at a one-based document position."""

    _require_integer(position, "position", minimum=1)
    return f"w{position}"


def source_sentence_id(position: int) -> str:
    """Return the stable ID for a sentence at a one-based document position."""

    _require_integer(position, "position", minimum=1)
    return f"s{position}"


def normalize_spoken_text(text: str) -> str:
    """Normalize whitespace and spacing around attached punctuation."""

    _require_non_empty_string(text, "text")
    normalized = " ".join(text.split())
    normalized = _SPACE_BEFORE_PUNCTUATION_RE.sub(r"\1", normalized)
    return _SPACE_AFTER_OPENING_PUNCTUATION_RE.sub(r"\1", normalized)


@dataclass(frozen=True)
class TranscriptParagraphDTO:
    text: str
    speaker_label: str | None = None
    stage_directions: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or (self.text and not self.text.strip()):
            raise ValueError("text must be a string containing spoken text or empty")
        if self.speaker_label is not None:
            _require_non_empty_string(self.speaker_label, "speaker_label")
        object.__setattr__(self, "stage_directions", tuple(self.stage_directions))
        if not all(
            isinstance(direction, str) and bool(direction.strip())
            for direction in self.stage_directions
        ):
            raise ValueError("stage_directions must contain non-empty strings")
        if not self.text and not self.stage_directions:
            raise ValueError("paragraph must contain text or stage_directions")

    def to_dict(self) -> dict[str, Any]:
        return {
            "speaker_label": self.speaker_label,
            "text": self.text,
            "stage_directions": list(self.stage_directions),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TranscriptParagraphDTO":
        speaker_label = data.get("speaker_label")
        if speaker_label is not None and not isinstance(speaker_label, str):
            raise ValueError("speaker_label must be a non-empty string or null")
        text = data.get("text")
        if not isinstance(text, str):
            raise ValueError("text must be a string")
        stage_directions = _require_sequence(
            data.get("stage_directions", []), "stage_directions"
        )
        return cls(
            text=text,
            speaker_label=speaker_label,
            stage_directions=tuple(stage_directions),
        )


@dataclass(frozen=True)
class TranscriptChapterDTO:
    number: int
    title: str
    paragraphs: tuple[TranscriptParagraphDTO, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _require_integer(self.number, "number", minimum=0)
        if not isinstance(self.title, str):
            raise ValueError("title must be a string")
        object.__setattr__(self, "paragraphs", tuple(self.paragraphs))
        if not all(
            isinstance(paragraph, TranscriptParagraphDTO)
            for paragraph in self.paragraphs
        ):
            raise ValueError("paragraphs must contain TranscriptParagraphDTO values")

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "title": self.title,
            "paragraphs": [paragraph.to_dict() for paragraph in self.paragraphs],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TranscriptChapterDTO":
        number = data.get("number")
        title = data.get("title")
        if not isinstance(title, str):
            raise ValueError("title must be a string")
        paragraphs = _require_sequence(data.get("paragraphs", []), "paragraphs")
        if not all(isinstance(item, Mapping) for item in paragraphs):
            raise ValueError("paragraphs must contain objects")
        return cls(
            number=_require_integer(number, "number", minimum=0),
            title=title,
            paragraphs=tuple(
                TranscriptParagraphDTO.from_dict(item) for item in paragraphs
            ),
        )


@dataclass(frozen=True)
class StructuredTranscriptDTO:
    language: str
    chapters: tuple[TranscriptChapterDTO, ...] = field(default_factory=tuple)
    schema_version: str = STRUCTURED_TRANSCRIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != STRUCTURED_TRANSCRIPT_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported structured transcript schema: {self.schema_version}"
            )
        if self.language != "en":
            raise ValueError("language must be en")
        object.__setattr__(self, "chapters", tuple(self.chapters))
        if not all(isinstance(chapter, TranscriptChapterDTO) for chapter in self.chapters):
            raise ValueError("chapters must contain TranscriptChapterDTO values")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "language": self.language,
            "chapters": [chapter.to_dict() for chapter in self.chapters],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StructuredTranscriptDTO":
        schema_version = data.get("schema_version")
        if schema_version != STRUCTURED_TRANSCRIPT_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported structured transcript schema: {schema_version}"
            )
        language = data.get("language")
        if not isinstance(language, str):
            raise ValueError("language must be en")
        chapters = _require_sequence(data.get("chapters", []), "chapters")
        if not all(isinstance(item, Mapping) for item in chapters):
            raise ValueError("chapters must contain objects")
        return cls(
            schema_version=schema_version,
            language=language,
            chapters=tuple(TranscriptChapterDTO.from_dict(item) for item in chapters),
        )


class MatchType(str, Enum):
    EXACT = "exact"
    NORMALIZED_EXACT = "normalized_exact"
    SUBSTITUTION = "substitution"
    ONE_TO_MANY = "one_to_many"
    MANY_TO_ONE = "many_to_one"
    ASR_ONLY = "asr_only"
    OFFICIAL_ONLY = "official_only"


class TextSource(str, Enum):
    ASR = "asr"
    OFFICIAL_TRANSCRIPT = "official_transcript"
    MIXED = "mixed"


class TimingSource(str, Enum):
    ACOUSTIC_ALIGNMENT = "acoustic_alignment"
    INTERPOLATED = "interpolated"
    MERGED_ACOUSTIC_ALIGNMENT = "merged_acoustic_alignment"


class BoundarySource(str, Enum):
    OFFICIAL_PUNCTUATION = "official_punctuation"
    SPEAKER_CHANGE = "speaker_change"
    ASR_PUNCTUATION = "asr_punctuation"
    PUNCTUATION_AND_PAUSE = "punctuation_and_pause"
    PAUSE_FALLBACK = "pause_fallback"


class BoundaryStatus(str, Enum):
    VERIFIED = "verified"
    INFERRED = "inferred"
    FALLBACK = "fallback"


@dataclass(frozen=True)
class TimedWordDTO:
    id: str
    text: str
    start_ms: int
    end_ms: int
    asr_word_ids: tuple[str, ...]
    official_token_ids: tuple[str, ...]
    match_type: MatchType
    text_source: TextSource
    timing_source: TimingSource

    def __post_init__(self) -> None:
        _require_non_empty_string(self.id, "id")
        if _TIMED_WORD_ID_RE.fullmatch(self.id) is None:
            raise ValueError("timed word id must use the format w<one-based position>")
        _require_non_empty_string(self.text, "text")
        if not any(character.isalnum() for character in self.text):
            raise ValueError("word text must contain spoken content")
        _require_integer(self.start_ms, "start_ms", minimum=0)
        _require_integer(self.end_ms, "end_ms", minimum=0)
        if self.end_ms <= self.start_ms:
            raise ValueError("word time range must satisfy start_ms < end_ms")
        object.__setattr__(
            self, "asr_word_ids", _string_tuple(self.asr_word_ids, "asr_word_ids")
        )
        object.__setattr__(
            self,
            "official_token_ids",
            _string_tuple(self.official_token_ids, "official_token_ids"),
        )
        if not isinstance(self.match_type, MatchType):
            raise ValueError("match_type must be a MatchType")
        if not isinstance(self.text_source, TextSource):
            raise ValueError("text_source must be a TextSource")
        if not isinstance(self.timing_source, TimingSource):
            raise ValueError("timing_source must be a TimingSource")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "asr_word_ids": list(self.asr_word_ids),
            "official_token_ids": list(self.official_token_ids),
            "match_type": self.match_type.value,
            "text_source": self.text_source.value,
            "timing_source": self.timing_source.value,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TimedWordDTO":
        return cls(
            id=data.get("id"),
            text=data.get("text"),
            start_ms=data.get("start_ms"),
            end_ms=data.get("end_ms"),
            asr_word_ids=_string_tuple(data.get("asr_word_ids", []), "asr_word_ids"),
            official_token_ids=_string_tuple(
                data.get("official_token_ids", []), "official_token_ids"
            ),
            match_type=MatchType(data.get("match_type")),
            text_source=TextSource(data.get("text_source")),
            timing_source=TimingSource(data.get("timing_source")),
        )


@dataclass(frozen=True)
class SourceSentenceDTO:
    id: str
    first_word_id: str
    last_word_id: str
    start_ms: int
    end_ms: int
    text: str
    speaker_label: str | None
    text_source: TextSource
    boundary_source: BoundarySource
    boundary_status: BoundaryStatus

    def __post_init__(self) -> None:
        _require_non_empty_string(self.id, "id")
        if _SOURCE_SENTENCE_ID_RE.fullmatch(self.id) is None:
            raise ValueError("sentence id must use the format s<one-based position>")
        _require_non_empty_string(self.first_word_id, "first_word_id")
        if _TIMED_WORD_ID_RE.fullmatch(self.first_word_id) is None:
            raise ValueError("first_word_id must identify a timed word")
        _require_non_empty_string(self.last_word_id, "last_word_id")
        if _TIMED_WORD_ID_RE.fullmatch(self.last_word_id) is None:
            raise ValueError("last_word_id must identify a timed word")
        _require_integer(self.start_ms, "start_ms", minimum=0)
        _require_integer(self.end_ms, "end_ms", minimum=0)
        if self.end_ms <= self.start_ms:
            raise ValueError("sentence time range must satisfy start_ms < end_ms")
        _require_non_empty_string(self.text, "text")
        if self.speaker_label is not None:
            _require_non_empty_string(self.speaker_label, "speaker_label")
        if not isinstance(self.text_source, TextSource):
            raise ValueError("text_source must be a TextSource")
        if not isinstance(self.boundary_source, BoundarySource):
            raise ValueError("boundary_source must be a BoundarySource")
        if not isinstance(self.boundary_status, BoundaryStatus):
            raise ValueError("boundary_status must be a BoundaryStatus")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "first_word_id": self.first_word_id,
            "last_word_id": self.last_word_id,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "text": self.text,
            "speaker_label": self.speaker_label,
            "text_source": self.text_source.value,
            "boundary_source": self.boundary_source.value,
            "boundary_status": self.boundary_status.value,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SourceSentenceDTO":
        speaker_label = data.get("speaker_label")
        if speaker_label is not None and not isinstance(speaker_label, str):
            raise ValueError("speaker_label must be a non-empty string or null")
        return cls(
            id=data.get("id"),
            first_word_id=data.get("first_word_id"),
            last_word_id=data.get("last_word_id"),
            start_ms=data.get("start_ms"),
            end_ms=data.get("end_ms"),
            text=data.get("text"),
            speaker_label=speaker_label,
            text_source=TextSource(data.get("text_source")),
            boundary_source=BoundarySource(data.get("boundary_source")),
            boundary_status=BoundaryStatus(data.get("boundary_status")),
        )


def reconstruct_sentence_text(words: Sequence[TimedWordDTO]) -> str:
    if not words:
        raise ValueError("a sentence must reference at least one timed word")
    return normalize_spoken_text(" ".join(word.text for word in words))


@dataclass(frozen=True)
class SourceAlignmentDTO:
    language: str
    audio_duration_ms: int
    words: tuple[TimedWordDTO, ...]
    sentences: tuple[SourceSentenceDTO, ...]
    schema_version: str = SOURCE_ALIGNMENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SOURCE_ALIGNMENT_SCHEMA_VERSION:
            raise ValueError(f"unsupported source alignment schema: {self.schema_version}")
        if self.language != "en":
            raise ValueError("language must be en")
        _require_integer(self.audio_duration_ms, "audio_duration_ms", minimum=0)
        object.__setattr__(self, "words", tuple(self.words))
        object.__setattr__(self, "sentences", tuple(self.sentences))
        if not all(isinstance(word, TimedWordDTO) for word in self.words):
            raise ValueError("words must contain TimedWordDTO values")
        if not all(isinstance(sentence, SourceSentenceDTO) for sentence in self.sentences):
            raise ValueError("sentences must contain SourceSentenceDTO values")
        self._validate_timeline_and_ids()
        self._validate_sentence_coverage()

    def _validate_timeline_and_ids(self) -> None:
        previous_end_ms = 0
        for position, word in enumerate(self.words, start=1):
            if word.id != timed_word_id(position):
                raise ValueError("timed word IDs must be w1..wN in document order")
            if word.start_ms < previous_end_ms:
                raise ValueError("timed words must not overlap or move backward")
            if word.end_ms > self.audio_duration_ms:
                raise ValueError("word end_ms must not exceed audio_duration_ms")
            previous_end_ms = word.end_ms

        for position, sentence in enumerate(self.sentences, start=1):
            if sentence.id != source_sentence_id(position):
                raise ValueError("sentence IDs must be s1..sN in document order")
            if sentence.end_ms > self.audio_duration_ms:
                raise ValueError("sentence end_ms must not exceed audio_duration_ms")

    def _validate_sentence_coverage(self) -> None:
        word_positions = {word.id: position for position, word in enumerate(self.words)}
        next_position = 0
        for sentence in self.sentences:
            try:
                first_position = word_positions[sentence.first_word_id]
                last_position = word_positions[sentence.last_word_id]
            except KeyError as error:
                raise ValueError("sentence word range must reference existing words") from error
            if first_position != next_position or last_position < first_position:
                raise ValueError(
                    "sentences must cover consecutive words once in document order"
                )
            referenced_words = self.words[first_position : last_position + 1]
            first_word = referenced_words[0]
            last_word = referenced_words[-1]
            if sentence.start_ms != first_word.start_ms:
                raise ValueError("sentence start_ms must equal its first word start_ms")
            if sentence.end_ms != last_word.end_ms:
                raise ValueError("sentence end_ms must equal its last word end_ms")
            if normalize_spoken_text(sentence.text) != reconstruct_sentence_text(
                referenced_words
            ):
                raise ValueError("sentence text must be reconstructable from its words")
            next_position = last_position + 1

        if next_position != len(self.words):
            raise ValueError("every timed word must belong to exactly one sentence")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "language": self.language,
            "audio_duration_ms": self.audio_duration_ms,
            "words": [word.to_dict() for word in self.words],
            "sentences": [sentence.to_dict() for sentence in self.sentences],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SourceAlignmentDTO":
        schema_version = data.get("schema_version")
        if schema_version != SOURCE_ALIGNMENT_SCHEMA_VERSION:
            raise ValueError(f"unsupported source alignment schema: {schema_version}")
        language = data.get("language")
        if not isinstance(language, str):
            raise ValueError("language must be en")
        words = _require_sequence(data.get("words", []), "words")
        sentences = _require_sequence(data.get("sentences", []), "sentences")
        if not all(isinstance(item, Mapping) for item in words):
            raise ValueError("words must contain objects")
        if not all(isinstance(item, Mapping) for item in sentences):
            raise ValueError("sentences must contain objects")
        return cls(
            schema_version=schema_version,
            language=language,
            audio_duration_ms=data.get("audio_duration_ms"),
            words=tuple(TimedWordDTO.from_dict(item) for item in words),
            sentences=tuple(SourceSentenceDTO.from_dict(item) for item in sentences),
        )
