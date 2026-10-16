from copy import deepcopy
from dataclasses import replace

import pytest

from archive_core.domain import ArtifactType, canonical_filename
from archive_core.interfaces import (
    BoundarySource,
    BoundaryStatus,
    MatchType,
    SectionTitleTranslationDTO,
    SentenceTranslationDTO,
    SourceAlignmentDTO,
    SourceSectionDTO,
    SourceSentenceDTO,
    TextSource,
    TimedWordDTO,
    TimingSource,
    TranslationExecutionDTO,
    TranslationGenerationParametersDTO,
    TranslationInputDTO,
    TranslationManifestDTO,
    TranslationOutputDTO,
    TranslationProvenanceDTO,
    TranslationResultDTO,
)


SOURCE_SHA256 = "a" * 64
PROMPT_SHA256 = "b" * 64
RESULT_SHA256 = "c" * 64


def _alignment(*, sections: bool = True) -> SourceAlignmentDTO:
    words = (
        TimedWordDTO(
            id="w1",
            text="First.",
            start_ms=0,
            end_ms=500,
            asr_word_ids=("a1",),
            official_token_ids=("o1",),
            match_type=MatchType.EXACT,
            text_source=TextSource.OFFICIAL_TRANSCRIPT,
            timing_source=TimingSource.ACOUSTIC_ALIGNMENT,
        ),
        TimedWordDTO(
            id="w2",
            text="Second.",
            start_ms=600,
            end_ms=1000,
            asr_word_ids=("a2",),
            official_token_ids=("o2",),
            match_type=MatchType.EXACT,
            text_source=TextSource.OFFICIAL_TRANSCRIPT,
            timing_source=TimingSource.ACOUSTIC_ALIGNMENT,
        ),
    )
    sentences = (
        SourceSentenceDTO(
            id="s1",
            first_word_id="w1",
            last_word_id="w1",
            start_ms=0,
            end_ms=500,
            text="First.",
            speaker_label=None,
            text_source=TextSource.OFFICIAL_TRANSCRIPT,
            boundary_source=BoundarySource.OFFICIAL_PUNCTUATION,
            boundary_status=BoundaryStatus.VERIFIED,
        ),
        SourceSentenceDTO(
            id="s2",
            first_word_id="w2",
            last_word_id="w2",
            start_ms=600,
            end_ms=1000,
            text="Second.",
            speaker_label="Warren Buffett",
            text_source=TextSource.OFFICIAL_TRANSCRIPT,
            boundary_source=BoundarySource.DOCUMENT_SECTION_CHANGE,
            boundary_status=BoundaryStatus.VERIFIED,
        ),
    )
    source_sections = (
        SourceSectionDTO(
            id="sec1",
            title="First section",
            first_sentence_id="s1",
            last_sentence_id="s1",
        ),
        SourceSectionDTO(
            id="sec2",
            title="",
            first_sentence_id="s2",
            last_sentence_id="s2",
        ),
    )
    return SourceAlignmentDTO(
        language="en",
        audio_duration_ms=1000,
        words=words,
        sentences=sentences,
        sections=source_sections if sections else (),
    )


def _result(*, sections: bool = True) -> TranslationResultDTO:
    return TranslationResultDTO(
        source_alignment_sha256=SOURCE_SHA256,
        source_language="en",
        target_language="zh-Hans",
        section_title_translations=(
            (
                SectionTitleTranslationDTO("sec1", "第一节"),
                SectionTitleTranslationDTO("sec2", None),
            )
            if sections
            else ()
        ),
        sentence_translations=(
            SentenceTranslationDTO("s1", "第一句。"),
            SentenceTranslationDTO("s2", "第二句。"),
        ),
    )


def _manifest() -> TranslationManifestDTO:
    return TranslationManifestDTO(
        asset_id="cnbc:2000:annual-meeting",
        status="succeeded",
        completed_at="2026-10-15T12:34:56Z",
        input=TranslationInputDTO(
            path="source_alignment.json", sha256=SOURCE_SHA256
        ),
        translation=TranslationProvenanceDTO(
            source_language="en",
            target_language="zh-Hans",
            prompt_version="translation.zh-hans.v1",
            prompt_sha256=PROMPT_SHA256,
            glossary_path=None,
            glossary_sha256=None,
            provider="openai-responses",
            model="gpt-5.6-sol",
            generation_parameters=TranslationGenerationParametersDTO(
                {
                    "reasoning_effort": "high",
                    "temperature": None,
                    "max_output_tokens": 128000,
                    "store": False,
                }
            ),
        ),
        output=TranslationOutputDTO(
            path="translation_result.json",
            size_bytes=12345,
            sha256=RESULT_SHA256,
        ),
        execution=TranslationExecutionDTO(
            request_count=2,
            checkpoint_reuse_count=1,
            attempt_count=1,
            input_tokens=1100,
            output_tokens=700,
        ),
    )


def test_translation_result_round_trips_with_deterministic_field_order() -> None:
    result = _result()

    data = result.to_dict()

    assert list(data) == [
        "schema_version",
        "source_alignment_sha256",
        "source_language",
        "target_language",
        "section_title_translations",
        "sentence_translations",
    ]
    assert list(data["section_title_translations"][0]) == [
        "section_id",
        "translated_title",
    ]
    assert list(data["sentence_translations"][0]) == [
        "sentence_id",
        "translated_text",
    ]
    assert TranslationResultDTO.from_dict(data).to_dict() == data
    result.validate_against_alignment(_alignment())


def test_translation_manifest_round_trips_with_deterministic_field_order() -> None:
    manifest = _manifest()

    data = manifest.to_dict()

    assert list(data) == [
        "schema_version",
        "asset_id",
        "status",
        "completed_at",
        "input",
        "translation",
        "output",
        "execution",
    ]
    assert list(data["translation"]) == [
        "source_language",
        "target_language",
        "prompt_version",
        "prompt_sha256",
        "glossary_path",
        "glossary_sha256",
        "provider",
        "model",
        "generation_parameters",
    ]
    assert list(data["execution"]) == [
        "request_count",
        "checkpoint_reuse_count",
        "attempt_count",
        "input_tokens",
        "output_tokens",
    ]
    assert list(data["translation"]["generation_parameters"]) == [
        "reasoning_effort",
        "temperature",
        "max_output_tokens",
        "store",
    ]
    assert TranslationManifestDTO.from_dict(data).to_dict() == data


@pytest.mark.parametrize(
    ("factory", "schema_version"),
    [
        (_result, "translation.result.v2"),
        (_manifest, "translation.manifest.v2"),
    ],
)
def test_translation_contracts_reject_unknown_versions(factory, schema_version) -> None:
    data = factory().to_dict()
    data["schema_version"] = schema_version

    dto = TranslationResultDTO if factory is _result else TranslationManifestDTO
    with pytest.raises(ValueError, match="unsupported"):
        dto.from_dict(data)


@pytest.mark.parametrize("key", ["source_language", "sentence_translations"])
def test_translation_result_rejects_missing_or_extra_fields(key: str) -> None:
    data = _result().to_dict()
    del data[key]
    with pytest.raises(ValueError, match="must contain exactly"):
        TranslationResultDTO.from_dict(data)

    data = _result().to_dict()
    data["unexpected"] = True
    with pytest.raises(ValueError, match="must contain exactly"):
        TranslationResultDTO.from_dict(data)


def test_nested_contracts_reject_extra_fields() -> None:
    result_data = _result().to_dict()
    result_data["sentence_translations"][0]["source_text"] = "must not leak"
    with pytest.raises(ValueError, match="must contain exactly"):
        TranslationResultDTO.from_dict(result_data)

    manifest_data = _manifest().to_dict()
    manifest_data["translation"]["unexpected"] = True
    with pytest.raises(ValueError, match="must contain exactly"):
        TranslationManifestDTO.from_dict(manifest_data)


def test_generation_parameters_accept_and_freeze_arbitrary_finite_json() -> None:
    original = {
        "adapter_protocol": "translation.codex-cli.v1",
        "structured_output": True,
        "optional": None,
        "limits": {"attempts": 1, "ratio": 0.5},
        "modes": ["exec", {"sandbox": "read-only"}],
    }
    expected = deepcopy(original)

    parameters = TranslationGenerationParametersDTO(original)
    original["limits"]["attempts"] = 2
    original["modes"].append("changed")

    assert parameters.to_dict() == expected
    serialized = parameters.to_dict()
    assert type(serialized) is dict
    assert type(serialized["limits"]) is dict
    assert type(serialized["modes"]) is list
    serialized["limits"]["attempts"] = 3
    assert parameters.to_dict() == expected
    assert TranslationGenerationParametersDTO.from_dict(expected).to_dict() == expected


@pytest.mark.parametrize(
    "parameters",
    [
        {"": "empty key"},
        {1: "non-string key"},
        {"nested": {"": "empty nested key"}},
        {"nested": {1: "non-string nested key"}},
        {"value": b"bytes"},
        {"value": {"set"}},
        {"value": object()},
        {"value": float("nan")},
        {"value": float("inf")},
        {"value": float("-inf")},
    ],
)
def test_generation_parameters_reject_non_json_values(parameters) -> None:
    with pytest.raises(ValueError):
        TranslationGenerationParametersDTO(parameters)


def test_manifest_accepts_codex_generation_parameters_without_openai_fields() -> None:
    data = _manifest().to_dict()
    parameters = {
        "adapter_protocol": "translation.codex-cli.v1",
        "auth_method": "chatgpt",
        "codex_cli_version": "codex-cli 1.2.3",
        "execution_mode": "exec",
        "reasoning_effort": "high",
        "sandbox": "read-only",
        "session_persistence": "ephemeral",
        "structured_output": True,
    }
    data["translation"]["provider"] = "codex-cli-chatgpt"
    data["translation"]["generation_parameters"] = parameters

    assert TranslationManifestDTO.from_dict(data).to_dict() == data


def test_result_rejects_duplicate_ids_and_blank_sentence_text() -> None:
    with pytest.raises(ValueError, match="duplicate IDs"):
        replace(
            _result(),
            sentence_translations=(
                SentenceTranslationDTO("s1", "一。"),
                SentenceTranslationDTO("s1", "二。"),
            ),
        )

    with pytest.raises(ValueError, match="translated_text"):
        SentenceTranslationDTO("s1", "  ")


def test_alignment_validation_requires_exact_section_and_sentence_coverage() -> None:
    alignment = _alignment()

    with pytest.raises(ValueError, match="source sections in order"):
        replace(
            _result(),
            section_title_translations=tuple(
                reversed(_result().section_title_translations)
            ),
        ).validate_against_alignment(alignment)

    with pytest.raises(ValueError, match="source sentences in order"):
        replace(
            _result(),
            sentence_translations=(_result().sentence_translations[0],),
        ).validate_against_alignment(alignment)


def test_alignment_validation_enforces_section_title_nullability() -> None:
    alignment = _alignment()

    with pytest.raises(ValueError, match="non-empty source section"):
        replace(
            _result(),
            section_title_translations=(
                SectionTitleTranslationDTO("sec1", None),
                SectionTitleTranslationDTO("sec2", None),
            ),
        ).validate_against_alignment(alignment)

    with pytest.raises(ValueError, match="empty source section"):
        replace(
            _result(),
            section_title_translations=(
                SectionTitleTranslationDTO("sec1", "第一节"),
                SectionTitleTranslationDTO("sec2", "不应存在"),
            ),
        ).validate_against_alignment(alignment)


def test_alignment_without_sections_requires_no_title_translations() -> None:
    alignment = _alignment(sections=False)
    _result(sections=False).validate_against_alignment(alignment)

    with pytest.raises(ValueError, match="source sections in order"):
        _result().validate_against_alignment(alignment)


@pytest.mark.parametrize(
    "change",
    [
        lambda data: data.update(status="failed"),
        lambda data: data["execution"].update(request_count=-1),
        lambda data: data["execution"].update(input_tokens=True),
        lambda data: data["translation"].update(glossary_path="glossary.json"),
        lambda data: data["output"].update(size_bytes=-1),
        lambda data: data.update(completed_at="not-a-timestamp"),
    ],
)
def test_manifest_rejects_invalid_audit_values(change) -> None:
    data = deepcopy(_manifest().to_dict())
    change(data)

    with pytest.raises(ValueError):
        TranslationManifestDTO.from_dict(data)


def test_manifest_accepts_nullable_usage_and_paired_glossary_evidence() -> None:
    data = _manifest().to_dict()
    data["execution"]["input_tokens"] = None
    data["execution"]["output_tokens"] = None
    data["translation"]["glossary_path"] = "config/translation_glossary.json"
    data["translation"]["glossary_sha256"] = "d" * 64

    assert TranslationManifestDTO.from_dict(data).to_dict() == data


def test_translation_artifacts_have_canonical_filenames() -> None:
    assert (
        canonical_filename(ArtifactType.TRANSLATION_RESULT)
        == "translation_result.json"
    )
    assert (
        canonical_filename(ArtifactType.TRANSLATION_MANIFEST)
        == "translation_manifest.json"
    )
