"""Current chunk result and stage provenance contracts, without an old parser."""

from copy import deepcopy
from dataclasses import replace

import pytest

from archive_core.domain import ArtifactType, canonical_filename
from archive_core.interfaces import SectionTitleTranslationDTO, SourceSectionDTO
from archive_core.interfaces.bilingual import ArtifactEvidenceDTO, ChunkTranslationDTO, ChunkTranslationResultDTO, StageManifestDTO
from tests.translation.chunk_support import source
from translation.domain import ProviderIdentity


SOURCE_SHA256 = "a" * 64
PROMPT_SHA256 = "b" * 64
RESULT_SHA256 = "c" * 64


def _source(*, sections=True):
    alignment, chunks = source(2)
    if sections:
        alignment = replace(alignment, sections=(SourceSectionDTO("sec1", "Opening", "s1", "s1"),
                                                SourceSectionDTO("sec2", "", "s2", "s2")))
    return alignment, chunks


def _result(*, sections=True):
    _, chunks = _source(sections=sections)
    return ChunkTranslationResultDTO(chunks.asset_id, SOURCE_SHA256, "d" * 64,
        (ChunkTranslationDTO("k1", "第一句。"), ChunkTranslationDTO("k2", "第二句。")),
        (SectionTitleTranslationDTO("sec1", "开场"),) if sections else ())


def _manifest():
    result = _result()
    return StageManifestDTO("translation", result.asset_id,
        {"source_alignment": ArtifactEvidenceDTO("/workspace/source_alignment.json", 100, SOURCE_SHA256),
         "source_chunks": ArtifactEvidenceDTO("/workspace/source_chunks.json", 120, "d" * 64)},
        {"translation_result": ArtifactEvidenceDTO("/workspace/translation_result.json", 210, RESULT_SHA256)},
        {"prompt_version":"translation.contextual-chunks.zh-hans.v1", "prompt_sha256": PROMPT_SHA256,
         "glossary_path":None,"glossary_sha256":None,
         "provider":{"provider":"openai-responses","model":"gpt-5.6-sol","generation_parameters":{
             "reasoning_effort":"high","temperature":None,"max_output_tokens":128000,"store":False}}},
        "2026-11-06T00:00:00Z", {"request_count":2,"checkpoint_reuse_count":0,"provider_calls":2,
          "input_tokens":20,"output_tokens":10,"unknown_usage_count":0})


def test_translation_result_round_trips_with_deterministic_field_order():
    result = _result()
    data = result.to_dict()
    assert list(data) == ["asset_id","source_alignment_sha256","source_chunks_sha256","chunks","section_titles","schema_version"]
    assert list(data["section_titles"][0]) == ["section_id","translated_title"]
    assert list(data["chunks"][0]) == ["id","translated_text"]
    assert ChunkTranslationResultDTO.from_dict(data).to_dict() == data
    result.validate_against_inputs(*_source())


def test_translation_manifest_round_trips_with_deterministic_field_order():
    data = _manifest().to_dict()
    assert list(data) == ["stage","asset_id","inputs","outputs","identity","completed_at","execution","status","schema_version"]
    assert list(data["identity"]["provider"]["generation_parameters"]) == ["reasoning_effort","temperature","max_output_tokens","store"]
    assert list(data["execution"]) == ["request_count","checkpoint_reuse_count","provider_calls","input_tokens","output_tokens","unknown_usage_count"]
    assert StageManifestDTO.from_dict(data).to_dict() == data


@pytest.mark.parametrize("factory,schema_version",[(_result,"translation.result.v2"),(_manifest,"translation.manifest.v2"),
                                                     (_result,"translation.result.v1"),(_manifest,"translation.manifest.v1")])
def test_translation_contracts_reject_unknown_versions(factory,schema_version):
    data=factory().to_dict()
    data["schema_version"]=schema_version
    dto=ChunkTranslationResultDTO if factory is _result else StageManifestDTO
    with pytest.raises(ValueError,match="unsupported"):
        dto.from_dict(data)


@pytest.mark.parametrize("key",["source_chunks_sha256","chunks"])
def test_translation_result_rejects_missing_or_extra_fields(key):
    data=_result().to_dict()
    del data[key]
    with pytest.raises(ValueError,match="missing or unknown"):
        ChunkTranslationResultDTO.from_dict(data)
    with pytest.raises(ValueError,match="missing or unknown"):
        ChunkTranslationResultDTO.from_dict(dict(_result().to_dict(),unexpected=True))


def test_nested_contracts_reject_extra_fields():
    result=_result().to_dict()
    result["chunks"][0]["source_text"]="must not leak"
    with pytest.raises(ValueError,match="missing or unknown"):
        ChunkTranslationResultDTO.from_dict(result)
    manifest=_manifest().to_dict()
    manifest["outputs"]["translation_result"]["unexpected"]=True
    with pytest.raises(ValueError,match="missing or unknown"):
        StageManifestDTO.from_dict(manifest)


def test_generation_parameters_accept_and_freeze_arbitrary_finite_json():
    original={"adapter_protocol":"translation.codex-cli.v1","structured_output":True,"optional":None,
        "limits":{"attempts":1,"ratio":0.5},"modes":["exec",{"sandbox":"read-only"}]}
    expected=deepcopy(original)
    identity=ProviderIdentity("codex-cli-chatgpt","gpt-5.6-sol",original)
    original["limits"]["attempts"]=2
    original["modes"].append("changed")
    serialized=identity.to_dict()["generation_parameters"]
    assert serialized==expected and type(serialized) is dict
    assert type(serialized["limits"]) is dict and type(serialized["modes"]) is list
    serialized["limits"]["attempts"]=3
    assert identity.to_dict()["generation_parameters"]==expected
    data=_manifest().to_dict()
    data["identity"]["provider"]=identity.to_dict()
    assert StageManifestDTO.from_dict(data).to_dict()==data


@pytest.mark.parametrize("parameters",[
    {"":"empty key"},{1:"non-string key"},{"nested":{"":"empty nested key"}},
    {"nested":{1:"non-string nested key"}},{"value":b"bytes"},{"value":{"set"}},
    {"value":object()},{"value":float("nan")},{"value":float("inf")},{"value":float("-inf")},
])
def test_generation_parameters_reject_non_json_values(parameters):
    with pytest.raises(ValueError):
        ProviderIdentity("codex-cli-chatgpt","gpt-5.6-sol",parameters)


def test_manifest_accepts_codex_generation_parameters_without_openai_fields():
    data=_manifest().to_dict()
    data["identity"]["provider"]={"provider":"codex-cli-chatgpt","model":"gpt-5.6-sol",
        "generation_parameters":{"adapter_protocol":"translation.codex-cli.v1","auth_method":"chatgpt",
        "codex_cli_version":"codex-cli 1.2.3","execution_mode":"exec","reasoning_effort":"high",
        "sandbox":"read-only","session_persistence":"ephemeral","structured_output":True}}
    assert StageManifestDTO.from_dict(data).to_dict()==data


def test_result_rejects_duplicate_ids_and_blank_chunk_text():
    with pytest.raises(ValueError,match="duplicate chunk"):
        replace(_result(),chunks=(ChunkTranslationDTO("k1","一。"),ChunkTranslationDTO("k1","二。")))
    with pytest.raises(ValueError,match="translated_text"):
        ChunkTranslationDTO("k1"," ")


def test_alignment_validation_requires_exact_section_and_chunk_coverage():
    alignment,chunks=_source()
    alignment=replace(alignment,sections=(alignment.sections[0],replace(alignment.sections[1],title="Second")))
    with pytest.raises(ValueError,match="non-empty source titles in order"):
        replace(_result(),section_titles=(SectionTitleTranslationDTO("sec2","第二节"),
            SectionTitleTranslationDTO("sec1","第一节"))).validate_against_inputs(alignment,chunks)
    with pytest.raises(ValueError,match="every chunk in order"):
        replace(_result(),chunks=(_result().chunks[0],)).validate_against_inputs(*_source())


def test_alignment_validation_enforces_section_title_nullability():
    with pytest.raises(ValueError,match="translated"):
        replace(_result(),section_titles=(SectionTitleTranslationDTO("sec1",None),))
    with pytest.raises(ValueError,match="non-empty source titles"):
        replace(_result(),section_titles=(SectionTitleTranslationDTO("sec1","第一节"),
            SectionTitleTranslationDTO("sec2","不应存在"))).validate_against_inputs(*_source())


def test_alignment_without_sections_requires_no_title_translations():
    _result(sections=False).validate_against_inputs(*_source(sections=False))
    with pytest.raises(ValueError,match="non-empty source titles"):
        _result().validate_against_inputs(*_source(sections=False))


@pytest.mark.parametrize("change",[
    lambda data:data.update(status="failed"),
    lambda data:data["execution"].update(request_count=-1),
    lambda data:data["execution"].update(input_tokens=True),
    lambda data:data["outputs"]["translation_result"].update(sha256="invalid"),
    lambda data:data["outputs"]["translation_result"].update(size_bytes=-1),
    lambda data:data.update(completed_at="not-a-timestamp"),
])
def test_manifest_rejects_invalid_audit_values(change):
    data=_manifest().to_dict()
    change(data)
    with pytest.raises(ValueError):
        StageManifestDTO.from_dict(data)


def test_manifest_accepts_explicit_unknown_usage_and_paired_glossary_evidence():
    data=_manifest().to_dict()
    data["execution"].update(input_tokens=0,output_tokens=0,unknown_usage_count=2)
    data["identity"].update(glossary_path="/workspace/glossary.json",glossary_sha256="e"*64)
    assert StageManifestDTO.from_dict(data).to_dict()==data


def test_translation_artifacts_have_canonical_filenames():
    assert canonical_filename(ArtifactType.TRANSLATION_RESULT)=="translation_result.json"
    assert canonical_filename(ArtifactType.TRANSLATION_MANIFEST)=="translation_manifest.json"
