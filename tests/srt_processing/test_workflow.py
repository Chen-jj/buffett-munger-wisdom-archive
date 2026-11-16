from pathlib import Path
import pytest
from tests.srt_processing.workflow_fakes import WorkflowCase


def test_generation_prepares_and_qa_checks_all_outputs_before_manifest_last():
    case = WorkflowCase()
    result = case.run()
    assert result.status == "succeeded", result
    writes = [(action, Path(path).name) for action, path in case.store.operations if action in {"stage", "publish"}]
    assert writes[:4] == [("stage", name) for name in case.output_names[:-1]]
    assert writes[-1] == ("publish", "srt_processing_manifest.json")
    assert all(case.store.files[path] == data for path, data in case.upstream.items())
    assert case.clock.calls == 1


def test_reuse_verifies_complete_evidence_without_clock_or_writes():
    case = WorkflowCase()
    assert case.run().status == "succeeded"
    before = dict(case.store.files)
    case.store.operations.clear()
    assert case.run().status == "reused"
    assert case.store.files == before and case.clock.calls == 1
    assert not [item for item in case.store.operations if item[0] in {"stage", "publish"}]


@pytest.mark.parametrize("name", WorkflowCase.output_names)
@pytest.mark.parametrize("change", ["missing", "corrupt"])
def test_partial_or_corrupt_formal_set_is_read_only_conflict(name, change):
    case = WorkflowCase()
    assert case.run().status == "succeeded"
    path = case.path(name)
    if change == "missing":
        case.store.files.pop(path)
    else:
        case.store.files[path] = b"broken"
    before = dict(case.store.files)
    assert case.run().status == "failed"
    assert case.store.files == before and case.clock.calls == 1


@pytest.mark.parametrize("key,name", [("english_srt","english.srt"), ("bilingual_srt","bilingual.srt"), ("report","srt_processing_report.json")])
def test_resigning_does_not_hide_projection_or_report_damage(key, name):
    case = WorkflowCase()
    assert case.run().status == "succeeded"
    case.put(name, b"false formally signed output")
    case.resign_output(key, name)
    assert case.run().error_category == "artifact_conflict"


@pytest.mark.parametrize("action", ["stage", "publish"])
@pytest.mark.parametrize("name", WorkflowCase.output_names)
def test_each_fault_never_publishes_success_manifest(action, name):
    case = WorkflowCase()
    case.store.fail = lambda actual, path: actual == action and Path(path).name == name
    assert case.run().status == "failed"
    assert case.path("srt_processing_manifest.json") not in case.store.files
    assert all(case.store.files[path] == data for path, data in case.upstream.items())


@pytest.mark.parametrize("change", ["text", "time", "drop"])
def test_codec_roundtrip_mismatch_prevents_all_publication(change):
    case = WorkflowCase()
    def mutate(rows):
        if change == "text": rows[0][-1] = "wrong"
        if change == "time": rows[0][2] -= 1
        if change == "drop": rows.pop()
        return rows
    case.codec.mutate = mutate
    assert case.run().status == "failed"
    assert case.store.files == case.upstream


def test_explicit_overwrite_regenerates_only_exports():
    case = WorkflowCase()
    assert case.run().status == "succeeded"
    case.put("english.srt", b"stale")
    assert case.run().status == "failed"
    assert case.run(overwrite=True).status == "succeeded"
    assert all(case.store.files[path] == data for path, data in case.upstream.items())


@pytest.mark.parametrize("value", [1, None, "true", []])
def test_overwrite_requires_actual_boolean(value):
    case = WorkflowCase()
    assert case.run(overwrite=value).error_category == "input_invalid"
    assert case.store.files == case.upstream


@pytest.mark.parametrize("key", ["english_srt","chinese_srt","bilingual_srt","report"])
@pytest.mark.parametrize("field,value", [("path","/archive/cnbc_2000_sample/other"), ("size_bytes",1), ("sha256","f"*64)])
def test_every_output_evidence_dimension_is_verified(key, field, value):
    case = WorkflowCase()
    assert case.run().status == "succeeded"
    manifest = case.read("srt_processing_manifest.json")
    manifest["outputs"][key][field] = value
    case.put("srt_processing_manifest.json", manifest)
    before = dict(case.store.files)
    assert case.run().error_category == "artifact_conflict"
    assert case.store.files == before


@pytest.mark.parametrize("key", ["transcription_manifest","source_alignment","source_chunks","source_chunking_manifest",
                                "translation_result","translation_manifest","final_bilingual_draft","bilingual_postprocessing_manifest","media_boundary","video"])
@pytest.mark.parametrize("field,value", [("path","/archive/cnbc_2000_sample/other"), ("size_bytes",1), ("sha256","f"*64)])
def test_every_input_evidence_dimension_binds_reuse(key, field, value):
    case = WorkflowCase()
    assert case.run().status == "succeeded"
    manifest = case.read("srt_processing_manifest.json")
    manifest["inputs"][key][field] = value
    case.put("srt_processing_manifest.json", manifest)
    before = dict(case.store.files)
    assert case.run().error_category == "artifact_conflict"
    assert case.store.files == before


@pytest.mark.parametrize("name", WorkflowCase.output_names)
def test_each_staged_read_failure_never_publishes_success_manifest(name):
    case = WorkflowCase()
    case.store.fail = lambda action, path: action == "read" and path == case.path(name) + ".stage"
    assert case.run().status == "failed"
    assert case.path("srt_processing_manifest.json") not in case.store.files


def test_failed_explicit_overwrite_leaves_old_manifest_but_mixed_set_is_rejected():
    case = WorkflowCase()
    assert case.run().status == "succeeded"
    old_manifest = case.store.files[case.path("srt_processing_manifest.json")]
    case.codec.identity = {"engine":"changed-codec","serialization":"changed.v2"}
    case.store.fail = lambda action, path: action == "publish" and path == case.path("srt_processing_manifest.json")
    assert case.run(overwrite=True).status == "failed"
    assert case.store.files[case.path("srt_processing_manifest.json")] == old_manifest
    assert case.run().error_category == "artifact_conflict"
