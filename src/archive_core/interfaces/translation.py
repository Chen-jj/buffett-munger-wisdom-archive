"""Public JSON contracts for completed translation artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import math
import re
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from archive_core.domain import ArtifactType, canonical_filename

from .transcription import SourceAlignmentDTO


TRANSLATION_RESULT_SCHEMA_VERSION = "translation.result.v1"
TRANSLATION_MANIFEST_SCHEMA_VERSION = "translation.manifest.v1"

_SECTION_ID_RE = re.compile(r"^sec[1-9][0-9]*$")
_SENTENCE_ID_RE = re.compile(r"^s[1-9][0-9]*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_UTC_TIMESTAMP_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?Z$"
)


def _require_exact_keys(
    data: Mapping[str, Any], expected: tuple[str, ...], field_name: str
) -> None:
    if set(data) != set(expected):
        raise ValueError(f"{field_name} must contain exactly: {', '.join(expected)}")


def _require_non_empty_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _require_sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _require_non_negative_integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def _require_sequence(value: object, field_name: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{field_name} must be an array")
    return value


def _require_mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object")
    return value


def _freeze_json_value(value: object) -> object:
    if isinstance(value, Mapping):
        frozen: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise ValueError("JSON object keys must be non-empty strings")
            frozen[key] = _freeze_json_value(item)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json_value(item) for item in value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON numbers must be finite")
        return value
    raise ValueError(f"value is not JSON serializable: {type(value).__name__}")


def _thaw_json_value(value: object) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json_value(item) for item in value]
    return value


@dataclass(frozen=True)
class SectionTitleTranslationDTO:
    section_id: str
    translated_title: str | None

    def __post_init__(self) -> None:
        _require_non_empty_string(self.section_id, "section_id")
        if _SECTION_ID_RE.fullmatch(self.section_id) is None:
            raise ValueError("section_id must use the format sec<one-based position>")
        if self.translated_title is not None:
            _require_non_empty_string(self.translated_title, "translated_title")

    def to_dict(self) -> dict[str, Any]:
        return {
            "section_id": self.section_id,
            "translated_title": self.translated_title,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SectionTitleTranslationDTO":
        _require_exact_keys(data, ("section_id", "translated_title"), "section title")
        return cls(
            section_id=data["section_id"],
            translated_title=data["translated_title"],
        )


@dataclass(frozen=True)
class SentenceTranslationDTO:
    sentence_id: str
    translated_text: str

    def __post_init__(self) -> None:
        _require_non_empty_string(self.sentence_id, "sentence_id")
        if _SENTENCE_ID_RE.fullmatch(self.sentence_id) is None:
            raise ValueError("sentence_id must use the format s<one-based position>")
        _require_non_empty_string(self.translated_text, "translated_text")

    def to_dict(self) -> dict[str, str]:
        return {
            "sentence_id": self.sentence_id,
            "translated_text": self.translated_text,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SentenceTranslationDTO":
        _require_exact_keys(
            data, ("sentence_id", "translated_text"), "sentence translation"
        )
        return cls(
            sentence_id=data["sentence_id"],
            translated_text=data["translated_text"],
        )


@dataclass(frozen=True)
class TranslationResultDTO:
    source_alignment_sha256: str
    source_language: str
    target_language: str
    section_title_translations: tuple[SectionTitleTranslationDTO, ...] = field(
        default_factory=tuple
    )
    sentence_translations: tuple[SentenceTranslationDTO, ...] = field(
        default_factory=tuple
    )
    schema_version: str = TRANSLATION_RESULT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != TRANSLATION_RESULT_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported translation result schema: {self.schema_version}"
            )
        _require_sha256(self.source_alignment_sha256, "source_alignment_sha256")
        if self.source_language != "en":
            raise ValueError("source_language must be en")
        if self.target_language != "zh-Hans":
            raise ValueError("target_language must be zh-Hans")
        object.__setattr__(
            self, "section_title_translations", tuple(self.section_title_translations)
        )
        object.__setattr__(
            self, "sentence_translations", tuple(self.sentence_translations)
        )
        if not all(
            isinstance(item, SectionTitleTranslationDTO)
            for item in self.section_title_translations
        ):
            raise ValueError(
                "section_title_translations must contain "
                "SectionTitleTranslationDTO values"
            )
        if not all(
            isinstance(item, SentenceTranslationDTO)
            for item in self.sentence_translations
        ):
            raise ValueError(
                "sentence_translations must contain SentenceTranslationDTO values"
            )
        section_ids = [item.section_id for item in self.section_title_translations]
        sentence_ids = [item.sentence_id for item in self.sentence_translations]
        if len(section_ids) != len(set(section_ids)):
            raise ValueError(
                "section_title_translations must not contain duplicate IDs"
            )
        if len(sentence_ids) != len(set(sentence_ids)):
            raise ValueError("sentence_translations must not contain duplicate IDs")

    def validate_against_alignment(self, alignment: SourceAlignmentDTO) -> None:
        if not isinstance(alignment, SourceAlignmentDTO):
            raise ValueError("alignment must be a SourceAlignmentDTO")
        if self.source_language != alignment.language:
            raise ValueError("source_language must match source alignment language")

        expected_section_ids = tuple(section.id for section in alignment.sections)
        actual_section_ids = tuple(
            item.section_id for item in self.section_title_translations
        )
        if actual_section_ids != expected_section_ids:
            raise ValueError(
                "section title translations must exactly cover source sections in order"
            )
        for source, translated in zip(
            alignment.sections, self.section_title_translations, strict=True
        ):
            if not source.title and translated.translated_title is not None:
                raise ValueError("an empty source section title must translate to null")
            if source.title and translated.translated_title is None:
                raise ValueError(
                    "a non-empty source section title must have a translation"
                )

        expected_sentence_ids = tuple(sentence.id for sentence in alignment.sentences)
        actual_sentence_ids = tuple(
            item.sentence_id for item in self.sentence_translations
        )
        if actual_sentence_ids != expected_sentence_ids:
            raise ValueError(
                "sentence translations must exactly cover source sentences in order"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_alignment_sha256": self.source_alignment_sha256,
            "source_language": self.source_language,
            "target_language": self.target_language,
            "section_title_translations": [
                item.to_dict() for item in self.section_title_translations
            ],
            "sentence_translations": [
                item.to_dict() for item in self.sentence_translations
            ],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TranslationResultDTO":
        _require_exact_keys(
            data,
            (
                "schema_version",
                "source_alignment_sha256",
                "source_language",
                "target_language",
                "section_title_translations",
                "sentence_translations",
            ),
            "translation result",
        )
        section_items = _require_sequence(
            data["section_title_translations"], "section_title_translations"
        )
        sentence_items = _require_sequence(
            data["sentence_translations"], "sentence_translations"
        )
        return cls(
            schema_version=data["schema_version"],
            source_alignment_sha256=data["source_alignment_sha256"],
            source_language=data["source_language"],
            target_language=data["target_language"],
            section_title_translations=tuple(
                SectionTitleTranslationDTO.from_dict(
                    _require_mapping(item, "section title translation")
                )
                for item in section_items
            ),
            sentence_translations=tuple(
                SentenceTranslationDTO.from_dict(
                    _require_mapping(item, "sentence translation")
                )
                for item in sentence_items
            ),
        )


@dataclass(frozen=True)
class TranslationInputDTO:
    path: str
    sha256: str

    def __post_init__(self) -> None:
        if self.path != canonical_filename(ArtifactType.SOURCE_ALIGNMENT):
            raise ValueError(
                "input path must be the canonical source alignment filename"
            )
        _require_sha256(self.sha256, "input sha256")

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "sha256": self.sha256}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TranslationInputDTO":
        _require_exact_keys(data, ("path", "sha256"), "translation input")
        return cls(path=data["path"], sha256=data["sha256"])


@dataclass(frozen=True)
class TranslationGenerationParametersDTO:
    parameters: Mapping[str, object]

    def __post_init__(self) -> None:
        if not isinstance(self.parameters, Mapping):
            raise ValueError("generation parameters must be an object")
        object.__setattr__(
            self,
            "parameters",
            _freeze_json_value(self.parameters),
        )

    def to_dict(self) -> dict[str, Any]:
        return _thaw_json_value(self.parameters)

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any]
    ) -> "TranslationGenerationParametersDTO":
        return cls(parameters=_require_mapping(data, "generation parameters"))


@dataclass(frozen=True)
class TranslationProvenanceDTO:
    source_language: str
    target_language: str
    prompt_version: str
    prompt_sha256: str
    glossary_path: str | None
    glossary_sha256: str | None
    provider: str
    model: str
    generation_parameters: TranslationGenerationParametersDTO

    def __post_init__(self) -> None:
        if self.source_language != "en":
            raise ValueError("source_language must be en")
        if self.target_language != "zh-Hans":
            raise ValueError("target_language must be zh-Hans")
        _require_non_empty_string(self.prompt_version, "prompt_version")
        _require_sha256(self.prompt_sha256, "prompt_sha256")
        if (self.glossary_path is None) != (self.glossary_sha256 is None):
            raise ValueError(
                "glossary_path and glossary_sha256 must both be null or set"
            )
        if self.glossary_path is not None:
            _require_non_empty_string(self.glossary_path, "glossary_path")
            _require_sha256(self.glossary_sha256, "glossary_sha256")
        _require_non_empty_string(self.provider, "provider")
        _require_non_empty_string(self.model, "model")
        if not isinstance(
            self.generation_parameters, TranslationGenerationParametersDTO
        ):
            raise ValueError(
                "generation_parameters must be a TranslationGenerationParametersDTO"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_language": self.source_language,
            "target_language": self.target_language,
            "prompt_version": self.prompt_version,
            "prompt_sha256": self.prompt_sha256,
            "glossary_path": self.glossary_path,
            "glossary_sha256": self.glossary_sha256,
            "provider": self.provider,
            "model": self.model,
            "generation_parameters": self.generation_parameters.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TranslationProvenanceDTO":
        _require_exact_keys(
            data,
            (
                "source_language",
                "target_language",
                "prompt_version",
                "prompt_sha256",
                "glossary_path",
                "glossary_sha256",
                "provider",
                "model",
                "generation_parameters",
            ),
            "translation provenance",
        )
        return cls(
            source_language=data["source_language"],
            target_language=data["target_language"],
            prompt_version=data["prompt_version"],
            prompt_sha256=data["prompt_sha256"],
            glossary_path=data["glossary_path"],
            glossary_sha256=data["glossary_sha256"],
            provider=data["provider"],
            model=data["model"],
            generation_parameters=TranslationGenerationParametersDTO.from_dict(
                _require_mapping(data["generation_parameters"], "generation_parameters")
            ),
        )


@dataclass(frozen=True)
class TranslationOutputDTO:
    path: str
    size_bytes: int
    sha256: str

    def __post_init__(self) -> None:
        if self.path != canonical_filename(ArtifactType.TRANSLATION_RESULT):
            raise ValueError(
                "output path must be the canonical translation result filename"
            )
        _require_non_negative_integer(self.size_bytes, "size_bytes")
        _require_sha256(self.sha256, "output sha256")

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TranslationOutputDTO":
        _require_exact_keys(
            data, ("path", "size_bytes", "sha256"), "translation output"
        )
        return cls(
            path=data["path"],
            size_bytes=data["size_bytes"],
            sha256=data["sha256"],
        )


@dataclass(frozen=True)
class TranslationExecutionDTO:
    request_count: int
    checkpoint_reuse_count: int
    attempt_count: int
    input_tokens: int | None
    output_tokens: int | None

    def __post_init__(self) -> None:
        _require_non_negative_integer(self.request_count, "request_count")
        _require_non_negative_integer(
            self.checkpoint_reuse_count, "checkpoint_reuse_count"
        )
        _require_non_negative_integer(self.attempt_count, "attempt_count")
        if self.checkpoint_reuse_count > self.request_count:
            raise ValueError("checkpoint_reuse_count must not exceed request_count")
        if self.input_tokens is not None:
            _require_non_negative_integer(self.input_tokens, "input_tokens")
        if self.output_tokens is not None:
            _require_non_negative_integer(self.output_tokens, "output_tokens")

    def to_dict(self) -> dict[str, int | None]:
        return {
            "request_count": self.request_count,
            "checkpoint_reuse_count": self.checkpoint_reuse_count,
            "attempt_count": self.attempt_count,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TranslationExecutionDTO":
        _require_exact_keys(
            data,
            (
                "request_count",
                "checkpoint_reuse_count",
                "attempt_count",
                "input_tokens",
                "output_tokens",
            ),
            "translation execution",
        )
        return cls(
            request_count=data["request_count"],
            checkpoint_reuse_count=data["checkpoint_reuse_count"],
            attempt_count=data["attempt_count"],
            input_tokens=data["input_tokens"],
            output_tokens=data["output_tokens"],
        )


@dataclass(frozen=True)
class TranslationManifestDTO:
    asset_id: str
    status: str
    completed_at: str
    input: TranslationInputDTO
    translation: TranslationProvenanceDTO
    output: TranslationOutputDTO
    execution: TranslationExecutionDTO
    schema_version: str = TRANSLATION_MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != TRANSLATION_MANIFEST_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported translation manifest schema: {self.schema_version}"
            )
        _require_non_empty_string(self.asset_id, "asset_id")
        if self.status != "succeeded":
            raise ValueError("status must be succeeded")
        if (
            not isinstance(self.completed_at, str)
            or _UTC_TIMESTAMP_RE.fullmatch(self.completed_at) is None
        ):
            raise ValueError("completed_at must be an ISO 8601 UTC timestamp")
        try:
            datetime.fromisoformat(self.completed_at.removesuffix("Z") + "+00:00")
        except ValueError as error:
            raise ValueError(
                "completed_at must be an ISO 8601 UTC timestamp"
            ) from error
        if not isinstance(self.input, TranslationInputDTO):
            raise ValueError("input must be a TranslationInputDTO")
        if not isinstance(self.translation, TranslationProvenanceDTO):
            raise ValueError("translation must be a TranslationProvenanceDTO")
        if not isinstance(self.output, TranslationOutputDTO):
            raise ValueError("output must be a TranslationOutputDTO")
        if not isinstance(self.execution, TranslationExecutionDTO):
            raise ValueError("execution must be a TranslationExecutionDTO")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "asset_id": self.asset_id,
            "status": self.status,
            "completed_at": self.completed_at,
            "input": self.input.to_dict(),
            "translation": self.translation.to_dict(),
            "output": self.output.to_dict(),
            "execution": self.execution.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TranslationManifestDTO":
        _require_exact_keys(
            data,
            (
                "schema_version",
                "asset_id",
                "status",
                "completed_at",
                "input",
                "translation",
                "output",
                "execution",
            ),
            "translation manifest",
        )
        return cls(
            schema_version=data["schema_version"],
            asset_id=data["asset_id"],
            status=data["status"],
            completed_at=data["completed_at"],
            input=TranslationInputDTO.from_dict(
                _require_mapping(data["input"], "input")
            ),
            translation=TranslationProvenanceDTO.from_dict(
                _require_mapping(data["translation"], "translation")
            ),
            output=TranslationOutputDTO.from_dict(
                _require_mapping(data["output"], "output")
            ),
            execution=TranslationExecutionDTO.from_dict(
                _require_mapping(data["execution"], "execution")
            ),
        )
