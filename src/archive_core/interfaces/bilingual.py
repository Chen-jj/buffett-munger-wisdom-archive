"""Current bilingual pipeline contracts; no legacy-format detection or fallback."""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timedelta
from math import isfinite
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Mapping

from .transcription import SourceAlignmentDTO, reconstruct_sentence_text
from .translation import SectionTitleTranslationDTO
from .bilingual_timing import COUNTING_VERSION, maximum_extension_ms


_HASH = re.compile(r"[0-9a-f]{64}")
_WORD = re.compile(r"w[1-9][0-9]*")
_STAGES = frozenset({"acquisition", "media_download", "media_derivation", "transcription", "source_chunking", "translation", "bilingual_postprocessing", "srt_export", "subtitle_rendering"})


def _text(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _int(value: object, name: str, minimum: int = 0) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")


def _hash(value: object, name: str) -> None:
    if not isinstance(value, str) or _HASH.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256")


def _strings(value: object, name: str, *, nonempty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        raise ValueError(f"{name} must be an array")
    result = tuple(value)
    for item in result:
        _text(item, name)
    if len(result) != len(set(result)) or (nonempty and not result):
        raise ValueError(f"{name} must contain unique values")
    return result


def _json(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and isfinite(value):
        return value
    if isinstance(value, Mapping) and all(isinstance(key, str) for key in value):
        return MappingProxyType({key: _json(item) for key, item in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(_json(item) for item in value)
    raise ValueError("identity/diagnostics must contain finite JSON values")


def _plain(value: object) -> Any:
    if is_dataclass(value):
        return {field.name: _plain(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def _keys(data: object, cls: type) -> dict[str, Any]:
    if not isinstance(data, Mapping) or set(data) != {field.name for field in fields(cls)}:
        raise ValueError(f"{cls.__name__} has missing or unknown fields")
    return dict(data)


class _Contract:
    def to_dict(self) -> dict[str, Any]:
        return _plain(self)


def _logical(value: object, name: str) -> None:
    _text(value, name)
    if any(character in value for character in "\n\r\x00"):
        raise ValueError(f"{name} must be logical text without line/control separators")


def _typed(values: object, item_type: type, name: str) -> tuple:
    if not isinstance(values, (list, tuple)) or not all(isinstance(item, item_type) for item in values):
        raise ValueError(f"{name} has invalid items")
    return tuple(values)


@dataclass(frozen=True)
class ArtifactEvidenceDTO(_Contract):
    path: str
    size_bytes: int
    sha256: str

    def __post_init__(self) -> None:
        _text(self.path, "path")
        if not Path(self.path).is_absolute() or ".." in Path(self.path).parts:
            raise ValueError("evidence path must be absolute and normalized")
        _int(self.size_bytes, "size_bytes", 1)
        _hash(self.sha256, "sha256")

    @classmethod
    def from_dict(cls, data: object) -> ArtifactEvidenceDTO:
        return cls(**_keys(data, cls))


@dataclass(frozen=True)
class MediaBoundaryDTO(_Contract):
    video_sha256: str
    duration_ms: int
    frame_timestamps_us: tuple[int, ...] | None
    schema_version: str = "media.boundary.v1"

    def __post_init__(self) -> None:
        if self.schema_version != "media.boundary.v1":
            raise ValueError("unsupported media boundary schema")
        _hash(self.video_sha256, "video_sha256")
        _int(self.duration_ms, "duration_ms", 1)
        if self.frame_timestamps_us is not None:
            if not isinstance(self.frame_timestamps_us, (tuple, list)) or not self.frame_timestamps_us:
                raise ValueError("frame timestamps must be a non-empty array or null")
            timestamps = tuple(self.frame_timestamps_us)
            previous = -1
            for timestamp in timestamps:
                _int(timestamp, "frame timestamp")
                if timestamp <= previous or timestamp >= self.duration_ms * 1000:
                    raise ValueError("actual frame timestamps must be ordered within media")
                previous = timestamp
            object.__setattr__(self, "frame_timestamps_us", timestamps)

    @classmethod
    def from_dict(cls, data: object) -> MediaBoundaryDTO:
        return cls(**_keys(data, cls))


@dataclass(frozen=True)
class ProtectedSpanDTO(_Contract):
    first_word_id: str
    last_word_id: str
    reason: str

    def __post_init__(self) -> None:
        for value in (self.first_word_id, self.last_word_id):
            if not isinstance(value, str) or _WORD.fullmatch(value) is None:
                raise ValueError("protected span must reference word IDs")
        if int(self.last_word_id[1:]) < int(self.first_word_id[1:]):
            raise ValueError("protected span is reversed")
        _text(self.reason, "reason")

    @classmethod
    def from_dict(cls, data: object) -> ProtectedSpanDTO:
        return cls(**_keys(data, cls))


@dataclass(frozen=True)
class ReadingBudgetDTO(_Contract):
    base_units: int
    maximum_units: int
    extension_ms: int
    chinese_line_target_units: int = 16
    counting_version: str = COUNTING_VERSION

    def __post_init__(self) -> None:
        for name in ("base_units", "maximum_units", "extension_ms", "chinese_line_target_units"):
            _int(getattr(self, name), name)
        if self.maximum_units < self.base_units or self.extension_ms > 500:
            raise ValueError("reading budget has invalid extension")
        if self.chinese_line_target_units != 16 or self.counting_version != COUNTING_VERSION:
            raise ValueError("unsupported counting policy")

    @classmethod
    def from_dict(cls, data: object) -> ReadingBudgetDTO:
        return cls(**_keys(data, cls))


def _range_fields(item: object) -> None:
    object.__setattr__(item, "word_ids", _strings(item.word_ids, "word_ids", nonempty=True))
    object.__setattr__(item, "sentence_ids", _strings(item.sentence_ids, "sentence_ids", nonempty=True))
    positions = []
    for word_id in item.word_ids:
        if _WORD.fullmatch(word_id) is None:
            raise ValueError("invalid source word ID")
        positions.append(int(word_id[1:]))
    if positions != list(range(positions[0], positions[-1] + 1)):
        raise ValueError("word IDs must form a continuous range")
    _logical(item.english_text, "english_text")
    _int(item.start_ms, "start_ms")
    _int(item.base_end_ms, "base_end_ms", 1)
    if item.base_end_ms <= item.start_ms:
        raise ValueError("source window must have positive duration")


@dataclass(frozen=True)
class SourceChunkDTO(_Contract):
    id: str
    word_ids: tuple[str, ...]
    sentence_ids: tuple[str, ...]
    english_text: str
    start_ms: int
    base_end_ms: int
    budget: ReadingBudgetDTO
    issues: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or re.fullmatch(r"k[1-9][0-9]*", self.id) is None:
            raise ValueError("chunk ID must use k1..kN")
        _range_fields(self)
        if not isinstance(self.budget, ReadingBudgetDTO):
            raise ValueError("budget must be ReadingBudgetDTO")
        object.__setattr__(self, "issues", _strings(self.issues, "issues"))

    @classmethod
    def from_dict(cls, data: object) -> SourceChunkDTO:
        data = _keys(data, cls)
        data["budget"] = ReadingBudgetDTO.from_dict(data["budget"])
        return cls(**data)


def _validate_ranges(items: tuple, alignment: SourceAlignmentDTO, duration_ms: int) -> None:
    position = 0
    word_positions = {word.id: index for index, word in enumerate(alignment.words)}
    sentence_for_word = {}
    source_sentences = {sentence.id: sentence for sentence in alignment.sentences}
    section_for_sentence = {}
    for sentence in alignment.sentences:
        first, last = word_positions[sentence.first_word_id], word_positions[sentence.last_word_id]
        for word in alignment.words[first:last + 1]:
            sentence_for_word[word.id] = sentence
    for section in alignment.sections:
        first, last = int(section.first_sentence_id[1:]), int(section.last_sentence_id[1:])
        for number in range(first, last + 1):
            section_for_sentence[f"s{number}"] = section.id
    previous_end = 0
    for item in items:
        words = alignment.words[position:position + len(item.word_ids)]
        if not words or tuple(word.id for word in words) != item.word_ids:
            raise ValueError("source words must be covered in order exactly once")
        sentences = tuple(dict.fromkeys(sentence_for_word[word.id].id for word in words))
        if item.sentence_ids != sentences:
            raise ValueError("sentence IDs do not match source words")
        if any(source_sentences[right].start_ms - source_sentences[left].end_ms >= 500
               for left, right in zip(sentences, sentences[1:])):
            raise ValueError("cue crosses a forbidden source sentence gap")
        if len({section_for_sentence[sid] for sid in sentences if sid in section_for_sentence}) > 1:
            raise ValueError("a cue cannot cross section boundaries")
        speakers = {sentence_for_word[word.id].speaker_label for word in words} - {None}
        if len(speakers) > 1:
            raise ValueError("a cue cannot bridge different known speakers")
        if item.english_text != reconstruct_sentence_text(words):
            raise ValueError("English must be reconstructed from the source words")
        if item.start_ms != words[0].start_ms or item.base_end_ms != words[-1].end_ms:
            raise ValueError("source timing anchors must not move")
        end_ms = getattr(item, "final_end_ms", item.base_end_ms)
        if item.start_ms < previous_end or end_ms > duration_ms:
            raise ValueError("cues must not overlap or exceed media")
        previous_end = end_ms
        position += len(words)
    if position != len(alignment.words):
        raise ValueError("source word coverage is incomplete")


@dataclass(frozen=True)
class SourceChunkPlanDTO(_Contract):
    asset_id: str
    source_alignment_sha256: str
    media: MediaBoundaryDTO
    policy: Mapping[str, Any]
    analyzer: Mapping[str, Any]
    chunks: tuple[SourceChunkDTO, ...]
    protected_spans: tuple[ProtectedSpanDTO, ...]
    analyzed_sentence_ids: tuple[str, ...]
    schema_version: str = "subtitle.source-chunks.v1"

    def __post_init__(self) -> None:
        if self.schema_version != "subtitle.source-chunks.v1":
            raise ValueError("unsupported source chunk schema")
        _text(self.asset_id, "asset_id")
        _hash(self.source_alignment_sha256, "source_alignment_sha256")
        if not isinstance(self.media, MediaBoundaryDTO):
            raise ValueError("media must be MediaBoundaryDTO")
        for name in ("policy", "analyzer"):
            if not isinstance(getattr(self, name), Mapping) or not getattr(self, name):
                raise ValueError(f"{name} must be a nonempty identity object")
            object.__setattr__(self, name, _json(getattr(self, name)))
        object.__setattr__(self, "chunks", _typed(self.chunks, SourceChunkDTO, "chunks"))
        object.__setattr__(self, "protected_spans", _typed(self.protected_spans, ProtectedSpanDTO, "protected_spans"))
        object.__setattr__(self, "analyzed_sentence_ids", _strings(self.analyzed_sentence_ids, "analyzed_sentence_ids"))
        if tuple(chunk.id for chunk in self.chunks) != tuple(f"k{n}" for n in range(1, len(self.chunks) + 1)):
            raise ValueError("chunks must use k1..kN in order")

    def validate_against_alignment(self, alignment: SourceAlignmentDTO) -> None:
        _validate_ranges(self.chunks, alignment, self.media.duration_ms)
        words = {word.id for word in alignment.words}
        if any(span.first_word_id not in words or span.last_word_id not in words for span in self.protected_spans):
            raise ValueError("protection references unknown words")
        sentences = {sentence.id for sentence in alignment.sentences}
        if not set(self.analyzed_sentence_ids) <= sentences:
            raise ValueError("analysis coverage references unknown sentences")
        boundaries = {int(chunk.word_ids[-1][1:]) for chunk in self.chunks[:-1]}
        for span in self.protected_spans:
            if any(int(span.first_word_id[1:]) <= boundary < int(span.last_word_id[1:]) for boundary in boundaries):
                raise ValueError("chunk boundary breaks a known protected span")

    @classmethod
    def from_dict(cls, data: object) -> SourceChunkPlanDTO:
        data = _keys(data, cls)
        data["media"] = MediaBoundaryDTO.from_dict(data["media"])
        data["chunks"] = tuple(SourceChunkDTO.from_dict(item) for item in data["chunks"])
        data["protected_spans"] = tuple(ProtectedSpanDTO.from_dict(item) for item in data["protected_spans"])
        return cls(**data)


@dataclass(frozen=True)
class ChunkTranslationDTO(_Contract):
    id: str
    translated_text: str

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or re.fullmatch(r"k[1-9][0-9]*", self.id) is None:
            raise ValueError("translation must reference a chunk ID")
        _logical(self.translated_text, "translated_text")

    @classmethod
    def from_dict(cls, data: object) -> ChunkTranslationDTO:
        return cls(**_keys(data, cls))


def _titles(value: object) -> tuple[SectionTitleTranslationDTO, ...]:
    titles = _typed(value, SectionTitleTranslationDTO, "section_titles")
    ids = tuple(title.section_id for title in titles)
    if len(ids) != len(set(ids)) or any(title.translated_title is None for title in titles):
        raise ValueError("duplicate section title")
    return titles


@dataclass(frozen=True)
class ChunkTranslationResultDTO(_Contract):
    asset_id: str
    source_alignment_sha256: str
    source_chunks_sha256: str
    chunks: tuple[ChunkTranslationDTO, ...]
    section_titles: tuple[SectionTitleTranslationDTO, ...]
    schema_version: str = "translation.chunks.v1"

    def __post_init__(self) -> None:
        if self.schema_version != "translation.chunks.v1":
            raise ValueError("unsupported chunk translation schema")
        _text(self.asset_id, "asset_id")
        _hash(self.source_alignment_sha256, "source_alignment_sha256")
        _hash(self.source_chunks_sha256, "source_chunks_sha256")
        object.__setattr__(self, "chunks", _typed(self.chunks, ChunkTranslationDTO, "chunks"))
        object.__setattr__(self, "section_titles", _titles(self.section_titles))
        if len({chunk.id for chunk in self.chunks}) != len(self.chunks):
            raise ValueError("duplicate chunk translation")

    def validate_against_inputs(self, alignment: SourceAlignmentDTO, chunks: SourceChunkPlanDTO) -> None:
        chunks.validate_against_alignment(alignment)
        if self.asset_id != chunks.asset_id or self.source_alignment_sha256 != chunks.source_alignment_sha256:
            raise ValueError("translation source identity mismatch")
        if tuple(chunk.id for chunk in self.chunks) != tuple(chunk.id for chunk in chunks.chunks):
            raise ValueError("chunk translations must cover every chunk in order exactly once")
        expected_titles = tuple(section.id for section in alignment.sections if section.title.strip())
        if tuple(title.section_id for title in self.section_titles) != expected_titles:
            raise ValueError("section titles must cover non-empty source titles in order")

    @classmethod
    def from_dict(cls, data: object) -> ChunkTranslationResultDTO:
        data = _keys(data, cls)
        data["chunks"] = tuple(ChunkTranslationDTO.from_dict(item) for item in data["chunks"])
        data["section_titles"] = tuple(SectionTitleTranslationDTO.from_dict(item) for item in data["section_titles"])
        return cls(**data)


@dataclass(frozen=True)
class FinalCueDTO(_Contract):
    id: str
    word_ids: tuple[str, ...]
    sentence_ids: tuple[str, ...]
    english_text: str
    chinese_text: str
    start_ms: int
    base_end_ms: int
    final_end_ms: int
    initial_chunk_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or re.fullmatch(r"c[1-9][0-9]*", self.id) is None:
            raise ValueError("cue ID must use c1..cN")
        _range_fields(self)
        _logical(self.chinese_text, "chinese_text")
        _int(self.final_end_ms, "final_end_ms", 1)
        if not self.base_end_ms <= self.final_end_ms <= self.base_end_ms + 500:
            raise ValueError("final end may only extend source end by at most 500ms")
        object.__setattr__(self, "initial_chunk_ids", _strings(self.initial_chunk_ids, "initial_chunk_ids", nonempty=True))

    @property
    def end_ms(self) -> int:
        return self.final_end_ms

    @property
    def extension_ms(self) -> int:
        return self.final_end_ms - self.base_end_ms

    @classmethod
    def from_dict(cls, data: object) -> FinalCueDTO:
        return cls(**_keys(data, cls))


@dataclass(frozen=True)
class FinalBilingualDraftDTO(_Contract):
    asset_id: str
    source_alignment_sha256: str
    source_chunks_sha256: str
    translation_result_sha256: str
    media: MediaBoundaryDTO
    policy: Mapping[str, Any]
    cues: tuple[FinalCueDTO, ...]
    section_titles: tuple[SectionTitleTranslationDTO, ...]
    diagnostics: tuple[Mapping[str, Any], ...]
    schema_version: str = "subtitle.final-draft.v1"

    def __post_init__(self) -> None:
        if self.schema_version != "subtitle.final-draft.v1":
            raise ValueError("unsupported final draft schema")
        _text(self.asset_id, "asset_id")
        for name in ("source_alignment_sha256", "source_chunks_sha256", "translation_result_sha256"):
            _hash(getattr(self, name), name)
        if not isinstance(self.media, MediaBoundaryDTO):
            raise ValueError("media must be MediaBoundaryDTO")
        if not isinstance(self.policy, Mapping) or not self.policy:
            raise ValueError("policy must be a nonempty identity object")
        object.__setattr__(self, "policy", _json(self.policy))
        object.__setattr__(self, "cues", _typed(self.cues, FinalCueDTO, "cues"))
        object.__setattr__(self, "section_titles", _titles(self.section_titles))
        if not isinstance(self.diagnostics, (tuple, list)) or not all(isinstance(item, Mapping) for item in self.diagnostics):
            raise ValueError("diagnostics must be an array of JSON objects")
        object.__setattr__(self, "diagnostics", tuple(_json(item) for item in self.diagnostics))
        previous_end = 0
        for position, cue in enumerate(self.cues, 1):
            if cue.id != f"c{position}" or cue.start_ms < previous_end or cue.end_ms > self.media.duration_ms:
                raise ValueError("final cues must be ordered, non-overlapping and within media")
            previous_end = cue.end_ms

    def validate_against_inputs(self, alignment: SourceAlignmentDTO, source_chunks: SourceChunkPlanDTO, translation: ChunkTranslationResultDTO) -> None:
        translation.validate_against_inputs(alignment, source_chunks)
        if (self.asset_id != source_chunks.asset_id or self.source_alignment_sha256 != source_chunks.source_alignment_sha256
                or self.source_chunks_sha256 != translation.source_chunks_sha256 or self.media != source_chunks.media):
            raise ValueError("final draft source identity mismatch")
        if self.section_titles != translation.section_titles:
            raise ValueError("final draft must preserve initial section titles")
        _validate_ranges(self.cues, alignment, self.media.duration_ms)
        for position, cue in enumerate(self.cues):
            next_start = self.cues[position + 1].start_ms if position + 1 < len(self.cues) else None
            if cue.extension_ms > maximum_extension_ms(self.media, cue.start_ms, cue.base_end_ms, next_start):
                raise ValueError("final cue extension exceeds the verified media/frame limit")
            word_ids = set(cue.word_ids)
            expected = tuple(chunk.id for chunk in source_chunks.chunks if word_ids.intersection(chunk.word_ids))
            if cue.initial_chunk_ids != expected:
                raise ValueError("initial chunk provenance does not match final word range")
        boundaries = {int(cue.word_ids[-1][1:]) for cue in self.cues[:-1]}
        for span in source_chunks.protected_spans:
            if any(int(span.first_word_id[1:]) <= boundary < int(span.last_word_id[1:]) for boundary in boundaries):
                raise ValueError("final boundary breaks a known protected span")

    @classmethod
    def from_dict(cls, data: object) -> FinalBilingualDraftDTO:
        data = _keys(data, cls)
        data["media"] = MediaBoundaryDTO.from_dict(data["media"])
        data["cues"] = tuple(FinalCueDTO.from_dict(item) for item in data["cues"])
        data["section_titles"] = tuple(SectionTitleTranslationDTO.from_dict(item) for item in data["section_titles"])
        return cls(**data)


@dataclass(frozen=True)
class StageManifestDTO(_Contract):
    stage: str
    asset_id: str
    inputs: Mapping[str, ArtifactEvidenceDTO]
    outputs: Mapping[str, ArtifactEvidenceDTO]
    identity: Mapping[str, Any]
    completed_at: str
    execution: Mapping[str, int]
    status: str = "succeeded"
    schema_version: str = "pipeline.stage-manifest.v1"

    def __post_init__(self) -> None:
        if self.schema_version != "pipeline.stage-manifest.v1" or self.status != "succeeded" or self.stage not in _STAGES:
            raise ValueError("unsupported or unsuccessful stage manifest")
        _text(self.asset_id, "asset_id")
        _text(self.completed_at, "completed_at")
        try:
            completed = datetime.fromisoformat(self.completed_at)
        except ValueError as error:
            raise ValueError("completed_at must be an ISO UTC date and time") from error
        if completed.utcoffset() != timedelta(0):
            raise ValueError("completed_at must be an ISO UTC date and time")
        for name in ("inputs", "outputs"):
            value = getattr(self, name)
            if not isinstance(value, Mapping) or (not value and not (name == "inputs" and self.stage == "acquisition")) or not all(isinstance(key, str) and key and isinstance(item, ArtifactEvidenceDTO) for key, item in value.items()):
                raise ValueError(f"{name} must be a nonempty evidence map")
            paths = [item.path for item in value.values()]
            if len(paths) != len(set(paths)):
                raise ValueError(f"{name} has duplicate evidence paths")
            object.__setattr__(self, name, MappingProxyType(dict(value)))
        if not isinstance(self.identity, Mapping) or not self.identity:
            raise ValueError("identity must be a nonempty object")
        object.__setattr__(self, "identity", _json(self.identity))
        if not isinstance(self.execution, Mapping) or not all(isinstance(key, str) and key for key in self.execution):
            raise ValueError("execution must be a counter object")
        for name, value in self.execution.items():
            _int(value, name)
        object.__setattr__(self, "execution", MappingProxyType(dict(self.execution)))

    @classmethod
    def from_dict(cls, data: object) -> StageManifestDTO:
        data = _keys(data, cls)
        for name in ("inputs", "outputs"):
            if not isinstance(data[name], Mapping):
                raise ValueError(f"{name} must be an object")
            data[name] = {key: ArtifactEvidenceDTO.from_dict(item) for key, item in data[name].items()}
        return cls(**data)
