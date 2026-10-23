"""Versioned, provider-neutral contracts for authoritative bilingual subtitles."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import json
import math
import re
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from archive_core.domain import ArtifactType, canonical_filename

from .transcription import SourceAlignmentDTO, reconstruct_sentence_text
from .translation import TranslationResultDTO
from .subtitle_text import character_boundaries, normalize_chinese_text


SUBTITLE_PLAN_SCHEMA_VERSION = "subtitle.plan.v1"
SRT_PROCESSING_REPORT_SCHEMA_VERSION = "srt-processing.report.v1"
SRT_PROCESSING_MANIFEST_SCHEMA_VERSION = "srt-processing.manifest.v1"
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_UTC_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?Z$"
)
_BREAK_METHODS = frozenset(
    ("english_sentence", "english_clause", "english_comma", "english_pause",
     "english_emergency", "chinese_sentence", "chinese_clause", "chinese_comma",
     "chinese_emergency", "local_rule")
)
_TIMING_PURPOSES = ("minimum_duration", "chinese_cps", "gap_closing")
_INPUT_TYPES = {
    "transcription_manifest": ArtifactType.TRANSCRIPTION_MANIFEST,
    "source_alignment": ArtifactType.SOURCE_ALIGNMENT,
    "translation_manifest": ArtifactType.TRANSLATION_MANIFEST,
    "translation_result": ArtifactType.TRANSLATION_RESULT,
    "video": ArtifactType.SOURCE_VIDEO,
}
_OUTPUT_TYPES = {
    "subtitle_plan": ArtifactType.SUBTITLE_PLAN,
    "english_srt": ArtifactType.ENGLISH_SRT,
    "chinese_srt": ArtifactType.CHINESE_SRT,
    "bilingual_srt": ArtifactType.BILINGUAL_SRT,
    "report": ArtifactType.SRT_PROCESSING_REPORT,
}


def _object(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _keys(data: object, expected: tuple[str, ...], name: str) -> Mapping[str, Any]:
    result = _object(data, name)
    if set(result) != set(expected):
        raise ValueError(f"{name} must contain exactly: {', '.join(expected)}")
    return result


def _integer(value: object, name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _hash(value: object, name: str) -> str:
    if not isinstance(value, str) or _HASH_RE.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _id(value: object, prefix: str, name: str) -> str:
    if not isinstance(value, str) or re.fullmatch(rf"{prefix}[1-9][0-9]*", value) is None:
        raise ValueError(f"{name} must use {prefix}<one-based position>")
    return value


def _array(value: object, name: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{name} must be an array")
    return value


def _typed_tuple(value: object, item_type: type, name: str) -> tuple:
    result = tuple(_array(value, name))
    if not all(isinstance(item, item_type) for item in result):
        raise ValueError(f"{name} must contain {item_type.__name__} values")
    return result


def _string_tuple(value: object, name: str) -> tuple[str, ...]:
    result = tuple(_array(value, name))
    for item in result:
        _string(item, name)
    if len(result) != len(set(result)):
        raise ValueError(f"{name} must not contain duplicates")
    return result


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        for key in value:
            _string(key, "JSON key")
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item) for item in value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise ValueError("observed values must be finite JSON values")


def _thaw(value: object) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _logical_text(value: object, name: str) -> str:
    result = _string(value, name)
    if normalize_chinese_text(result) != result:
        raise ValueError(f"{name} must contain normalized logical text, not visual lines")
    return result


@dataclass(frozen=True)
class SubtitleFragmentDTO:
    sentence_id: str
    first_word_id: str
    last_word_id: str
    chinese_start_offset: int
    chinese_end_offset: int
    speaker_label: str | None

    def __post_init__(self) -> None:
        _id(self.sentence_id, "s", "sentence_id")
        _id(self.first_word_id, "w", "first_word_id")
        _id(self.last_word_id, "w", "last_word_id")
        if int(self.last_word_id[1:]) < int(self.first_word_id[1:]):
            raise ValueError("fragment word range must be ordered")
        _integer(self.chinese_start_offset, "chinese_start_offset")
        _integer(self.chinese_end_offset, "chinese_end_offset")
        if self.chinese_end_offset <= self.chinese_start_offset:
            raise ValueError("Chinese range must be non-empty and ordered")
        if self.speaker_label is not None:
            _string(self.speaker_label, "speaker_label")

    def to_dict(self) -> dict[str, Any]:
        return {"sentence_id": self.sentence_id, "first_word_id": self.first_word_id,
                "last_word_id": self.last_word_id,
                "chinese_start_offset": self.chinese_start_offset,
                "chinese_end_offset": self.chinese_end_offset,
                "speaker_label": self.speaker_label}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SubtitleFragmentDTO":
        data = _keys(data, ("sentence_id", "first_word_id", "last_word_id",
                           "chinese_start_offset", "chinese_end_offset", "speaker_label"), "fragment")
        return cls(**data)


@dataclass(frozen=True)
class SubtitleTimingAdjustmentDTO:
    extension_ms: int
    purposes: tuple[str, ...]
    original_gap_ms: int | None
    original_gap_class: str
    space_source: str = "word_gap"

    def __post_init__(self) -> None:
        _integer(self.extension_ms, "extension_ms")
        object.__setattr__(self, "purposes", _string_tuple(self.purposes, "purposes"))
        if any(purpose not in _TIMING_PURPOSES for purpose in self.purposes):
            raise ValueError("unsupported timing purpose")
        if self.purposes != tuple(item for item in _TIMING_PURPOSES if item in self.purposes):
            raise ValueError("timing purposes must use canonical order")
        if bool(self.extension_ms) != bool(self.purposes):
            raise ValueError("timing purposes must describe a positive extension only")
        if self.original_gap_ms is not None:
            _integer(self.original_gap_ms, "original_gap_ms")
        if self.original_gap_class not in ("long_gap", "short_gap", "preserved_gap", "last_cue"):
            raise ValueError("unsupported original_gap_class")
        if (self.original_gap_ms is None) != (self.original_gap_class == "last_cue"):
            raise ValueError("last_cue must have null original gap, and only last_cue may")
        if self.space_source != "word_gap":
            raise ValueError("space_source must be word_gap")

    def to_dict(self) -> dict[str, Any]:
        return {"extension_ms": self.extension_ms, "purposes": list(self.purposes),
                "original_gap_ms": self.original_gap_ms,
                "original_gap_class": self.original_gap_class, "space_source": self.space_source}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SubtitleTimingAdjustmentDTO":
        data = _keys(data, ("extension_ms", "purposes", "original_gap_ms",
                           "original_gap_class", "space_source"), "timing adjustment")
        return cls(**data)


@dataclass(frozen=True)
class SubtitleCueDTO:
    id: str
    section_id: str | None
    start_ms: int
    base_end_ms: int
    end_ms: int
    english_text: str
    chinese_text: str
    fragments: tuple[SubtitleFragmentDTO, ...]
    timing_adjustment: SubtitleTimingAdjustmentDTO
    break_methods: tuple[str, ...]
    mapping_method: str = "monotonic_proportional.v1"

    def __post_init__(self) -> None:
        _id(self.id, "c", "cue id")
        if self.section_id is not None:
            _id(self.section_id, "sec", "section_id")
        for name in ("start_ms", "base_end_ms", "end_ms"):
            _integer(getattr(self, name), name)
        if not self.start_ms < self.base_end_ms <= self.end_ms:
            raise ValueError("cue must satisfy start_ms < base_end_ms <= end_ms")
        _logical_text(self.english_text, "english_text")
        _logical_text(self.chinese_text, "chinese_text")
        object.__setattr__(self, "fragments", _typed_tuple(self.fragments, SubtitleFragmentDTO, "fragments"))
        if not self.fragments:
            raise ValueError("cue must contain fragments")
        labels = {fragment.speaker_label for fragment in self.fragments if fragment.speaker_label is not None}
        if len(labels) > 1:
            raise ValueError("a cue must not contain different known speakers")
        if len({fragment.sentence_id for fragment in self.fragments}) != len(self.fragments):
            raise ValueError("a cue must have at most one fragment per sentence")
        if not isinstance(self.timing_adjustment, SubtitleTimingAdjustmentDTO):
            raise ValueError("timing_adjustment must be a SubtitleTimingAdjustmentDTO")
        if self.end_ms - self.base_end_ms != self.timing_adjustment.extension_ms:
            raise ValueError("extension_ms must match cue end_ms minus base_end_ms")
        if self.mapping_method != "monotonic_proportional.v1":
            raise ValueError("unsupported mapping_method")
        object.__setattr__(self, "break_methods", _string_tuple(self.break_methods, "break_methods"))
        if not self.break_methods or not set(self.break_methods) <= _BREAK_METHODS:
            raise ValueError("break_methods must contain supported boundary methods")

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "section_id": self.section_id, "start_ms": self.start_ms,
                "base_end_ms": self.base_end_ms, "end_ms": self.end_ms,
                "english_text": self.english_text, "chinese_text": self.chinese_text,
                "fragments": [item.to_dict() for item in self.fragments],
                "mapping_method": self.mapping_method, "break_methods": list(self.break_methods),
                "timing_adjustment": self.timing_adjustment.to_dict()}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SubtitleCueDTO":
        data = dict(_keys(data, ("id", "section_id", "start_ms", "base_end_ms", "end_ms",
                                "english_text", "chinese_text", "fragments", "mapping_method",
                                "break_methods", "timing_adjustment"), "cue"))
        data["fragments"] = tuple(SubtitleFragmentDTO.from_dict(item) for item in _array(data["fragments"], "fragments"))
        data["timing_adjustment"] = SubtitleTimingAdjustmentDTO.from_dict(data["timing_adjustment"])
        return cls(**data)


@dataclass(frozen=True)
class SubtitleMediaDTO:
    video_duration_ms: int
    audio_duration_ms: int
    usable_duration_ms: int
    fps_numerator: int
    fps_denominator: int
    gap_threshold_ms: int

    def __post_init__(self) -> None:
        for name in ("video_duration_ms", "audio_duration_ms", "usable_duration_ms",
                     "fps_numerator", "fps_denominator", "gap_threshold_ms"):
            _integer(getattr(self, name), name, 1)
        if self.usable_duration_ms != min(self.video_duration_ms, self.audio_duration_ms):
            raise ValueError("usable duration must be the earlier media end")
        if self.gap_threshold_ms != (2000 * self.fps_denominator + self.fps_numerator - 1) // self.fps_numerator:
            raise ValueError("gap threshold must be ceil(2000 * fps denominator / numerator)")

    def to_dict(self) -> dict[str, int]:
        return {"video_duration_ms": self.video_duration_ms, "audio_duration_ms": self.audio_duration_ms,
                "usable_duration_ms": self.usable_duration_ms, "fps_numerator": self.fps_numerator,
                "fps_denominator": self.fps_denominator, "gap_threshold_ms": self.gap_threshold_ms}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SubtitleMediaDTO":
        data = _keys(data, ("video_duration_ms", "audio_duration_ms", "usable_duration_ms",
                           "fps_numerator", "fps_denominator", "gap_threshold_ms"), "media")
        return cls(**data)


@dataclass(frozen=True)
class SubtitleRulesDTO:
    profile_name: str
    profile_version: str
    profile_sha256: str
    algorithm_version: str
    text_normalization_version: str
    character_count_version: str
    boundary_rules_version: str
    cost_rules_version: str

    def __post_init__(self) -> None:
        for name in ("profile_name", "profile_version", "algorithm_version", "text_normalization_version",
                     "character_count_version", "boundary_rules_version", "cost_rules_version"):
            _string(getattr(self, name), name)
        _hash(self.profile_sha256, "profile_sha256")

    def to_dict(self) -> dict[str, str]:
        return {"profile_name": self.profile_name, "profile_version": self.profile_version,
                "profile_sha256": self.profile_sha256, "algorithm_version": self.algorithm_version,
                "text_normalization_version": self.text_normalization_version,
                "character_count_version": self.character_count_version,
                "boundary_rules_version": self.boundary_rules_version, "cost_rules_version": self.cost_rules_version}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SubtitleRulesDTO":
        data = _keys(data, ("profile_name", "profile_version", "profile_sha256", "algorithm_version",
                           "text_normalization_version", "character_count_version", "boundary_rules_version",
                           "cost_rules_version"), "rules")
        return cls(**data)


@dataclass(frozen=True)
class SubtitlePlanDTO:
    source_alignment_sha256: str
    translation_result_sha256: str
    video_sha256: str
    source_language: str
    target_language: str
    media: SubtitleMediaDTO
    rules: SubtitleRulesDTO
    cues: tuple[SubtitleCueDTO, ...]
    schema_version: str = SUBTITLE_PLAN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SUBTITLE_PLAN_SCHEMA_VERSION:
            raise ValueError(f"unsupported subtitle plan schema: {self.schema_version}")
        for name in ("source_alignment_sha256", "translation_result_sha256", "video_sha256"):
            _hash(getattr(self, name), name)
        if self.source_language != "en" or self.target_language != "zh-Hans":
            raise ValueError("subtitle languages must be en -> zh-Hans")
        if not isinstance(self.media, SubtitleMediaDTO) or not isinstance(self.rules, SubtitleRulesDTO):
            raise ValueError("plan must contain typed media and rules")
        object.__setattr__(self, "cues", _typed_tuple(self.cues, SubtitleCueDTO, "cues"))
        if not self.cues:
            raise ValueError("subtitle plan must contain cues")
        previous_end = 0
        for position, cue in enumerate(self.cues):
            if cue.id != f"c{position + 1}":
                raise ValueError("cue IDs must be c1..cN in document order")
            if cue.start_ms < previous_end or cue.end_ms > self.media.usable_duration_ms:
                raise ValueError("cue timeline must be ordered, non-overlapping and within usable media")
            timing = cue.timing_adjustment
            gap = self.cues[position + 1].start_ms - cue.base_end_ms if position + 1 < len(self.cues) else None
            if gap != timing.original_gap_ms:
                raise ValueError("original gap must match next cue start minus base end")
            expected_class = ("last_cue" if gap is None else "long_gap" if gap >= 500 else
                              "short_gap" if gap > self.media.gap_threshold_ms else "preserved_gap")
            if timing.original_gap_class != expected_class:
                raise ValueError("original gap class must describe the unadjusted gap")
            if expected_class == "preserved_gap" and timing.extension_ms:
                raise ValueError("an existing 0..G gap must be preserved without extension")
            if gap is not None and gap > self.media.gap_threshold_ms and cue.end_ms > self.cues[position + 1].start_ms - self.media.gap_threshold_ms:
                raise ValueError("extension must preserve the two-frame guard")
            if "gap_closing" in timing.purposes and expected_class != "short_gap":
                raise ValueError("gap_closing purpose requires an original short gap")
            previous_end = cue.end_ms

    def validate_against_inputs(self, alignment: SourceAlignmentDTO, translation: TranslationResultDTO) -> None:
        """Check source anchors and ordered, exact bilingual provenance coverage."""
        if not isinstance(alignment, SourceAlignmentDTO) or not isinstance(translation, TranslationResultDTO):
            raise ValueError("subtitle inputs must be public alignment and translation DTOs")
        translation.validate_against_alignment(alignment)
        if translation.source_alignment_sha256 != self.source_alignment_sha256:
            raise ValueError("translation and plan must reference the same alignment checksum")
        if not alignment.words or not alignment.sentences:
            raise ValueError("subtitle inputs must contain source words and sentences")
        if alignment.audio_duration_ms != self.media.audio_duration_ms:
            raise ValueError("plan audio duration must match alignment")
        sentence_by_id = {item.id: item for item in alignment.sentences}
        chinese_by_id = {item.sentence_id: normalize_chinese_text(item.translated_text) for item in translation.sentence_translations}
        sections: dict[str, str] = {}
        for section in alignment.sections:
            for position in range(int(section.first_sentence_id[1:]), int(section.last_sentence_id[1:]) + 1):
                sections[f"s{position}"] = section.id
        expected_word_position = 1
        chinese_positions = {item.id: 0 for item in alignment.sentences}
        for cue in self.cues:
            cue_words = []
            chinese_parts = []
            for fragment in cue.fragments:
                sentence = sentence_by_id.get(fragment.sentence_id)
                if sentence is None:
                    raise ValueError("fragment must reference an existing sentence")
                first, last = int(fragment.first_word_id[1:]), int(fragment.last_word_id[1:])
                if first != expected_word_position:
                    raise ValueError("fragments must cover source words exactly once in order")
                if not int(sentence.first_word_id[1:]) <= first <= last <= int(sentence.last_word_id[1:]):
                    raise ValueError("fragment words must belong to its sentence")
                if fragment.speaker_label != sentence.speaker_label:
                    raise ValueError("fragment must preserve the original speaker label, including null")
                if cue.section_id != sections.get(sentence.id):
                    raise ValueError("cue section must match every source fragment")
                chinese = chinese_by_id[sentence.id]
                start, end = fragment.chinese_start_offset, fragment.chinese_end_offset
                if start != chinese_positions[sentence.id] or end > len(chinese):
                    raise ValueError("fragments must cover normalized Chinese ranges exactly once in order")
                piece = chinese[start:end].strip(" ")
                if not piece:
                    raise ValueError("each fragment must contain non-empty Chinese content")
                # Split boundaries are validated against the same frozen table used by the planner.
                if start not in character_boundaries(chinese) or end not in character_boundaries(chinese):
                    raise ValueError("Chinese ranges must not split combining character sequences")
                chinese_positions[sentence.id] = end
                if last == int(sentence.last_word_id[1:]) and end != len(chinese):
                    raise ValueError("sentence word and Chinese endpoints must coincide")
                if end == len(chinese) and last != int(sentence.last_word_id[1:]):
                    raise ValueError("sentence Chinese and word endpoints must coincide")
                cue_words.extend(alignment.words[first - 1:last])
                chinese_parts.append(piece)
                expected_word_position = last + 1
            if cue.start_ms != cue_words[0].start_ms or cue.base_end_ms != cue_words[-1].end_ms:
                raise ValueError("cue start and base end must be anchored to its source words")
            if cue.english_text != reconstruct_sentence_text(cue_words):
                raise ValueError("cue English must be reconstructed from its source words")
            if cue.chinese_text != "".join(chinese_parts):
                raise ValueError("cue Chinese must be reconstructed from its normalized source ranges")
        if expected_word_position != len(alignment.words) + 1:
            raise ValueError("fragments must cover every source word")
        if any(chinese_positions[key] != len(text) for key, text in chinese_by_id.items()):
            raise ValueError("fragments must cover every normalized Chinese character")

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "source_alignment_sha256": self.source_alignment_sha256,
                "translation_result_sha256": self.translation_result_sha256, "video_sha256": self.video_sha256,
                "source_language": self.source_language, "target_language": self.target_language,
                "media": self.media.to_dict(), "rules": self.rules.to_dict(),
                "cues": [cue.to_dict() for cue in self.cues]}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SubtitlePlanDTO":
        data = dict(_keys(data, ("schema_version", "source_alignment_sha256", "translation_result_sha256",
                                "video_sha256", "source_language", "target_language", "media", "rules", "cues"), "subtitle plan"))
        data["media"] = SubtitleMediaDTO.from_dict(data["media"])
        data["rules"] = SubtitleRulesDTO.from_dict(data["rules"])
        data["cues"] = tuple(SubtitleCueDTO.from_dict(item) for item in _array(data["cues"], "cues"))
        return cls(**data)


@dataclass(frozen=True)
class SubtitleArtifactEvidenceDTO:
    path: str
    size_bytes: int
    sha256: str

    def __post_init__(self) -> None:
        _string(self.path, "evidence path")
        allowed = {canonical_filename(kind) for kind in (*_INPUT_TYPES.values(), *_OUTPUT_TYPES.values())}
        if self.path not in allowed:
            raise ValueError("evidence path must be a canonical subtitle input/output filename")
        _integer(self.size_bytes, "size_bytes", 1)
        _hash(self.sha256, "sha256")

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "size_bytes": self.size_bytes, "sha256": self.sha256}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SubtitleArtifactEvidenceDTO":
        data = _keys(data, ("path", "size_bytes", "sha256"), "artifact evidence")
        return cls(**data)


_PROFILE_STRING_KEYS = ("name", "version", "algorithm_version", "text_normalization_version",
                        "character_count_version", "boundary_rules_version", "cost_rules_version")
_PROFILE_INTEGER_KEYS = ("english_capacity", "chinese_capacity_half_units", "chinese_target_cps",
                         "english_reference_cps", "minimum_duration_ms", "maximum_duration_ms",
                         "maximum_extension_ms", "short_gap_upper_ms", "cross_sentence_gap_upper_ms",
                         "pause_boundary_ms")
_PROFILE_V2_STRING_KEYS = ("chinese_segmentation_engine", "chinese_dictionary_sha256",
                           "chinese_segmentation_mode")
_PROFILE_V2_INTEGER_KEYS = ("english_line_capacity", "english_max_lines")
_PROFILE_V3_INTEGER_KEYS = ("english_capacity", "chinese_target_half_units", "chinese_target_cps",
                            "english_reference_cps", "minimum_duration_ms", "target_duration_ms",
                            "maximum_extension_ms", "short_gap_upper_ms", "cross_sentence_gap_upper_ms",
                            "pause_boundary_ms", "english_line_capacity", "english_max_lines")


def _profile_keys(version: object) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if version == "v1":
        return _PROFILE_STRING_KEYS, _PROFILE_INTEGER_KEYS
    if version == "v2":
        return (_PROFILE_STRING_KEYS + _PROFILE_V2_STRING_KEYS,
                _PROFILE_INTEGER_KEYS + _PROFILE_V2_INTEGER_KEYS)
    if version == "v3":
        return _PROFILE_STRING_KEYS + _PROFILE_V2_STRING_KEYS, _PROFILE_V3_INTEGER_KEYS
    raise ValueError(f"unsupported subtitle profile version: {version}")


@dataclass(frozen=True)
class SubtitleProfileDTO:
    parameters: Mapping[str, object]

    def __post_init__(self) -> None:
        if not isinstance(self.parameters, Mapping):
            raise ValueError("profile parameters must be an object")
        string_keys, integer_keys = _profile_keys(self.parameters.get("version"))
        data = _keys(self.parameters, string_keys + integer_keys, "profile parameters")
        for key in string_keys:
            _string(data[key], key)
        for key in integer_keys:
            _integer(data[key], key, 1)
        if data["version"] in ("v2", "v3"):
            _hash(data["chinese_dictionary_sha256"], "chinese_dictionary_sha256")
        if data["version"] != "v3" and data["minimum_duration_ms"] > data["maximum_duration_ms"]:
            raise ValueError("minimum duration must not exceed maximum duration")
        object.__setattr__(self, "parameters", MappingProxyType(dict(data)))

    @property
    def sha256(self) -> str:
        payload = json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        string_keys, integer_keys = _profile_keys(self.parameters["version"])
        return {key: self.parameters[key] for key in string_keys + integer_keys}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SubtitleProfileDTO":
        return cls(parameters=data)


@dataclass(frozen=True)
class SubtitleProbeDTO:
    ffprobe_version: str
    stream_selector: str = "v:0"
    show_entries: str = "stream=avg_frame_rate:format=duration"

    def __post_init__(self) -> None:
        _string(self.ffprobe_version, "ffprobe_version")
        if self.stream_selector != "v:0" or self.show_entries != "stream=avg_frame_rate:format=duration":
            raise ValueError("unsupported subtitle probe configuration")

    def to_dict(self) -> dict[str, str]:
        return {"ffprobe_version": self.ffprobe_version, "stream_selector": self.stream_selector,
                "show_entries": self.show_entries}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SubtitleProbeDTO":
        data = _keys(data, ("ffprobe_version", "stream_selector", "show_entries"), "probe")
        return cls(**data)


@dataclass(frozen=True)
class SubtitleCodecDTO:
    library_name: str = "pysubs2"
    library_version: str = "1.8.1"
    format: str = "srt"
    encoding: str = "utf-8"
    newline: str = "\n"
    bom: bool = False
    terminal_newline: bool = True
    bilingual_order: tuple[str, ...] = ("zh-Hans", "en")
    time_format: str = "HH:MM:SS,mmm"
    serialization_version: str | None = None

    def __post_init__(self) -> None:
        expected = {"library_name": "pysubs2", "library_version": "1.8.1", "format": "srt",
                    "encoding": "utf-8", "newline": "\n", "time_format": "HH:MM:SS,mmm"}
        for key, value in expected.items():
            if getattr(self, key) != value:
                raise ValueError(f"unsupported codec {key}")
        if self.bom is not False or self.terminal_newline is not True:
            raise ValueError("codec requires no BOM and a terminal newline")
        object.__setattr__(self, "bilingual_order", tuple(_array(self.bilingual_order, "bilingual_order")))
        if self.bilingual_order != ("zh-Hans", "en"):
            raise ValueError("bilingual order must be Chinese then English")
        if self.serialization_version not in (None, "word-wrap-english-2x42.v2"):
            raise ValueError("unsupported codec serialization_version")

    def to_dict(self) -> dict[str, Any]:
        data = {"library_name": self.library_name, "library_version": self.library_version,
                "format": self.format, "encoding": self.encoding, "newline": self.newline,
                "bom": self.bom, "terminal_newline": self.terminal_newline,
                "bilingual_order": list(self.bilingual_order), "time_format": self.time_format}
        if self.serialization_version is not None:
            data["serialization_version"] = self.serialization_version
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SubtitleCodecDTO":
        keys = ("library_name", "library_version", "format", "encoding", "newline",
                "bom", "terminal_newline", "bilingual_order", "time_format")
        if isinstance(data, Mapping) and "serialization_version" in data:
            keys += ("serialization_version",)
            if data["serialization_version"] is None:
                raise ValueError("unsupported codec serialization_version")
        data = _keys(data, keys, "codec")
        return cls(**data)


@dataclass(frozen=True)
class SubtitleFindingDTO:
    code: str
    severity: str
    message: str
    cue_ids: tuple[str, ...] = ()
    sentence_ids: tuple[str, ...] = ()
    word_ids: tuple[str, ...] = ()
    original_start_ms: int | None = None
    original_end_ms: int | None = None
    final_start_ms: int | None = None
    final_end_ms: int | None = None
    observed: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _string(self.code, "finding code")
        _string(self.message, "finding message")
        if self.severity not in ("info", "warning", "error"):
            raise ValueError("finding severity must be info, warning or error")
        for name, prefix in (("cue_ids", "c"), ("sentence_ids", "s"), ("word_ids", "w")):
            object.__setattr__(self, name, _string_tuple(getattr(self, name), name))
            for value in getattr(self, name):
                _id(value, prefix, name)
        for start_name, end_name in (("original_start_ms", "original_end_ms"), ("final_start_ms", "final_end_ms")):
            start, end = getattr(self, start_name), getattr(self, end_name)
            if (start is None) != (end is None):
                raise ValueError("finding time range endpoints must both be set or null")
            if start is not None:
                _integer(start, start_name)
                _integer(end, end_name)
                if end < start:
                    raise ValueError("finding time range must be ordered")
        object.__setattr__(self, "observed", _freeze(_object(self.observed, "observed")))

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "severity": self.severity, "message": self.message,
                "cue_ids": list(self.cue_ids), "sentence_ids": list(self.sentence_ids), "word_ids": list(self.word_ids),
                "original_start_ms": self.original_start_ms, "original_end_ms": self.original_end_ms,
                "final_start_ms": self.final_start_ms, "final_end_ms": self.final_end_ms,
                "observed": _thaw(self.observed)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SubtitleFindingDTO":
        data = _keys(data, ("code", "severity", "message", "cue_ids", "sentence_ids", "word_ids",
                           "original_start_ms", "original_end_ms", "final_start_ms", "final_end_ms", "observed"), "finding")
        return cls(**data)


_SUMMARY_KEYS = ("cue_count", "merged_cue_count", "split_sentence_count", "too_short_count",
                 "chinese_cps_exceeded_count", "english_cps_exceeded_count", "unclosed_gap_count",
                 "extended_cue_count", "average_frame_rate_approximation_count")


@dataclass(frozen=True)
class SubtitleSummaryDTO:
    cue_count: int
    merged_cue_count: int
    split_sentence_count: int
    too_short_count: int
    chinese_cps_exceeded_count: int
    english_cps_exceeded_count: int
    unclosed_gap_count: int
    extended_cue_count: int
    average_frame_rate_approximation_count: int

    def __post_init__(self) -> None:
        for name in _SUMMARY_KEYS:
            _integer(getattr(self, name), name)
        for name in _SUMMARY_KEYS[1:-1]:
            if getattr(self, name) > self.cue_count:
                raise ValueError(f"{name} must not exceed cue_count")

    def to_dict(self) -> dict[str, int]:
        return {key: getattr(self, key) for key in _SUMMARY_KEYS}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SubtitleSummaryDTO":
        data = _keys(data, _SUMMARY_KEYS, "summary")
        return cls(**data)


@dataclass(frozen=True)
class SrtProcessingReportDTO:
    asset_id: str
    status: str
    summary: SubtitleSummaryDTO
    findings: tuple[SubtitleFindingDTO, ...]
    error_code: str | None = None
    schema_version: str = SRT_PROCESSING_REPORT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SRT_PROCESSING_REPORT_SCHEMA_VERSION:
            raise ValueError(f"unsupported srt processing report schema: {self.schema_version}")
        _string(self.asset_id, "asset_id")
        if self.status not in ("succeeded", "failed"):
            raise ValueError("report status must be succeeded or failed")
        if not isinstance(self.summary, SubtitleSummaryDTO):
            raise ValueError("summary must be a SubtitleSummaryDTO")
        object.__setattr__(self, "findings", _typed_tuple(self.findings, SubtitleFindingDTO, "findings"))
        if self.status == "succeeded":
            if self.error_code is not None or any(item.severity == "error" for item in self.findings):
                raise ValueError("a successful report must not contain errors")
        else:
            _string(self.error_code, "error_code")

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "asset_id": self.asset_id, "status": self.status,
                "summary": self.summary.to_dict(), "findings": [item.to_dict() for item in self.findings],
                "error_code": self.error_code}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SrtProcessingReportDTO":
        data = dict(_keys(data, ("schema_version", "asset_id", "status", "summary", "findings", "error_code"), "report"))
        data["summary"] = SubtitleSummaryDTO.from_dict(data["summary"])
        data["findings"] = tuple(SubtitleFindingDTO.from_dict(item) for item in _array(data["findings"], "findings"))
        return cls(**data)


def _evidence_map(value: object, kinds: Mapping[str, ArtifactType], name: str) -> Mapping[str, SubtitleArtifactEvidenceDTO]:
    result = _keys(value, tuple(kinds), name)
    for key, kind in kinds.items():
        evidence = result[key]
        if not isinstance(evidence, SubtitleArtifactEvidenceDTO):
            raise ValueError(f"{name} must contain SubtitleArtifactEvidenceDTO values")
        if evidence.path != canonical_filename(kind):
            raise ValueError(f"{name}.{key} must use its canonical filename")
    return MappingProxyType({key: result[key] for key in kinds})


@dataclass(frozen=True)
class SrtProcessingManifestDTO:
    asset_id: str
    status: str
    completed_at: str
    inputs: Mapping[str, SubtitleArtifactEvidenceDTO]
    rules: SubtitleRulesDTO
    profile: SubtitleProfileDTO
    media: SubtitleMediaDTO
    probe: SubtitleProbeDTO
    codec: SubtitleCodecDTO
    outputs: Mapping[str, SubtitleArtifactEvidenceDTO]
    summary: SubtitleSummaryDTO
    schema_version: str = SRT_PROCESSING_MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SRT_PROCESSING_MANIFEST_SCHEMA_VERSION:
            raise ValueError(f"unsupported srt processing manifest schema: {self.schema_version}")
        _string(self.asset_id, "asset_id")
        if self.status != "succeeded":
            raise ValueError("manifest status must be succeeded")
        if not isinstance(self.completed_at, str) or _UTC_RE.fullmatch(self.completed_at) is None:
            raise ValueError("completed_at must be an ISO 8601 UTC timestamp")
        try:
            datetime.fromisoformat(self.completed_at.removesuffix("Z") + "+00:00")
        except ValueError as error:
            raise ValueError("completed_at must be an ISO 8601 UTC timestamp") from error
        for name, dtype in (("rules", SubtitleRulesDTO), ("profile", SubtitleProfileDTO),
                            ("media", SubtitleMediaDTO), ("probe", SubtitleProbeDTO),
                            ("codec", SubtitleCodecDTO), ("summary", SubtitleSummaryDTO)):
            if not isinstance(getattr(self, name), dtype):
                raise ValueError(f"{name} must be a {dtype.__name__}")
        object.__setattr__(self, "inputs", _evidence_map(self.inputs, _INPUT_TYPES, "inputs"))
        object.__setattr__(self, "outputs", _evidence_map(self.outputs, _OUTPUT_TYPES, "outputs"))
        if self.rules.profile_sha256 != self.profile.sha256:
            raise ValueError("rules profile fingerprint must match complete profile parameters")
        pairs = (("profile_name", "name"), ("profile_version", "version"), ("algorithm_version", "algorithm_version"),
                 ("text_normalization_version", "text_normalization_version"), ("character_count_version", "character_count_version"),
                 ("boundary_rules_version", "boundary_rules_version"), ("cost_rules_version", "cost_rules_version"))
        if any(getattr(self.rules, name) != self.profile.parameters[key] for name, key in pairs):
            raise ValueError("manifest rules must match complete profile identity")
        if self.summary.cue_count < 1:
            raise ValueError("a successful manifest must describe a non-empty plan")

    def validate_against_plan(self, plan: SubtitlePlanDTO) -> None:
        if not isinstance(plan, SubtitlePlanDTO):
            raise ValueError("plan must be a SubtitlePlanDTO")
        for key, digest in (("source_alignment", plan.source_alignment_sha256),
                            ("translation_result", plan.translation_result_sha256), ("video", plan.video_sha256)):
            if self.inputs[key].sha256 != digest:
                raise ValueError("manifest inputs must match plan content fingerprints")
        if self.rules != plan.rules or self.media != plan.media or self.summary.cue_count != len(plan.cues):
            raise ValueError("manifest rules, media and cue count must match plan")

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "asset_id": self.asset_id, "status": self.status,
                "completed_at": self.completed_at,
                "inputs": {key: item.to_dict() for key, item in self.inputs.items()},
                "rules": self.rules.to_dict(), "profile": self.profile.to_dict(), "media": self.media.to_dict(),
                "probe": self.probe.to_dict(), "codec": self.codec.to_dict(),
                "outputs": {key: item.to_dict() for key, item in self.outputs.items()}, "summary": self.summary.to_dict()}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SrtProcessingManifestDTO":
        data = dict(_keys(data, ("schema_version", "asset_id", "status", "completed_at", "inputs", "rules",
                                "profile", "media", "probe", "codec", "outputs", "summary"), "subtitle manifest"))
        for name, kinds in (("inputs", _INPUT_TYPES), ("outputs", _OUTPUT_TYPES)):
            items = _keys(data[name], tuple(kinds), name)
            data[name] = {key: SubtitleArtifactEvidenceDTO.from_dict(value) for key, value in items.items()}
        for name, dtype in (("rules", SubtitleRulesDTO), ("profile", SubtitleProfileDTO),
                            ("media", SubtitleMediaDTO), ("probe", SubtitleProbeDTO),
                            ("codec", SubtitleCodecDTO), ("summary", SubtitleSummaryDTO)):
            data[name] = dtype.from_dict(data[name])
        return cls(**data)
