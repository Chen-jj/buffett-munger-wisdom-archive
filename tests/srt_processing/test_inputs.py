from dataclasses import replace
import pytest
from srt_processing.application.inputs import SubtitleInputError, load_subtitle_inputs
from tests.srt_processing.workflow_fakes import WorkflowCase


NAMES = ("transcription_manifest.json", "source_alignment.json", "source_chunks.json", "source_chunking_manifest.json",
         "translation_result.json", "translation_manifest.json", "final_bilingual_draft.json",
         "bilingual_postprocessing_manifest.json", "media_boundary.json", "video.mp4")


def load(case, **overrides):
    args = dict(asset_id=case.asset_id, bilingual_postprocessing_manifest_path=case.command.bilingual_postprocessing_manifest_path,
                artifacts=case.store, output_root=case.root)
    return load_subtitle_inputs(**(args | overrides))


def test_both_chains_are_bound_to_the_exact_parsed_bytes():
    case = WorkflowCase()
    result = load(case)
    assert result.draft == case.draft
    assert {entry.path for entry in result.evidence.values()} == {case.path(name) for name in NAMES}
    for item in result.evidence.values():
        assert (item.sha256, item.size_bytes) == (case.store.sha256(item.path), case.store.size(item.path))


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("change", ["missing", "malformed", "equal_size", "array"])
def test_invalid_inputs_are_never_accepted_by_existence_or_size(name, change):
    case = WorkflowCase()
    path = case.path(name)
    if change == "missing":
        case.store.files.pop(path)
    else:
        case.store.files[path] = {"malformed": b"broken", "equal_size": b"x" * case.store.size(path), "array": b"[]"}[change]
    with pytest.raises(SubtitleInputError):
        load(case)


@pytest.mark.parametrize("field,value", [
    ("asset_id", "other:2000:sample"), ("asset_id", "invalid"),
    ("bilingual_postprocessing_manifest_path", "relative.json"),
    ("bilingual_postprocessing_manifest_path", "/outside/bilingual_postprocessing_manifest.json"),
    ("bilingual_postprocessing_manifest_path", "/archive/cnbc_2000_sample/../cnbc_2000_sample/bilingual_postprocessing_manifest.json"),
])
def test_noncanonical_commands_fail_without_outputs(field, value):
    case = WorkflowCase()
    with pytest.raises(SubtitleInputError):
        load(case, **{field: value})
    assert not any(action in {"stage", "publish"} for action, _ in case.store.operations)


@pytest.mark.parametrize("field,value", [("stage","translation"), ("asset_id","other:asset:id"),
    ("status","failed"), ("schema_version","translation.manifest.v1"), ("inputs",{}), ("outputs",{})])
def test_wrong_stage_envelope_fails_independently(field, value):
    case = WorkflowCase()
    manifest = case.read("bilingual_postprocessing_manifest.json")
    manifest[field] = value
    case.put("bilingual_postprocessing_manifest.json", manifest)
    with pytest.raises(SubtitleInputError):
        load(case)
