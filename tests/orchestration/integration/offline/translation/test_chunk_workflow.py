"""Current workflow with real local evidence/checkpoint/store and fake provider."""

import json
import pytest
from translation.domain import ProviderIdentity
from tests.orchestration.integration.offline.translation.workflow_support import prepared, snapshot


def test_real_store_publishes_chunks_and_reuses_without_calls_or_writes(tmp_path):
    handler,command,provider,workspace=prepared(tmp_path)
    first=handler.handle(command)
    assert first.status=="succeeded" and first.request_count==first.attempt_count==1
    before=snapshot(workspace)
    second=handler.handle(command)
    assert second.status=="reused" and second.attempt_count==0
    assert len(provider.calls)==1 and snapshot(workspace)==before
    result=json.loads((workspace/"translation_result.json").read_bytes())
    assert result["schema_version"]=="translation.chunks.v1"
    assert [r["id"] for r in result["chunks"]]==["k1","k2","k3"]


def test_failed_second_batch_resumes_verified_first_batch_without_title_retranslation(tmp_path):
    handler,command,provider,workspace=prepared(tmp_path,51)
    provider.fail_at=2
    assert handler.handle(command).status=="failed"
    assert not (workspace/"translation_result.json").exists()
    provider.fail_at=None
    outcome=handler.handle(command)
    assert outcome.status=="succeeded" and outcome.checkpoint_reuse_count==1 and outcome.attempt_count==1
    assert len(provider.calls)==3
    assert [c.request.translate_title for c in provider.calls]==[True,False,False]


@pytest.mark.parametrize("name",["source_alignment.json","source_chunks.json","source_chunking_report.json","video.mp4"])
def test_damaged_upstream_fails_before_provider(tmp_path,name):
    handler,command,provider,workspace=prepared(tmp_path)
    (workspace/name).write_bytes(b"changed")
    assert handler.handle(command).error_category=="input_invalid"
    assert not provider.calls


def test_orphan_formal_file_conflicts_and_never_calls_provider(tmp_path):
    handler,command,provider,workspace=prepared(tmp_path)
    (workspace/"translation_result.json").write_bytes(b"orphan")
    before=snapshot(workspace)
    assert handler.handle(command).error_category=="artifact_conflict"
    assert snapshot(workspace)==before and not provider.calls


def test_changed_provider_identity_invalidates_reuse_without_overwrite(tmp_path):
    handler,command,provider,workspace=prepared(tmp_path)
    assert handler.handle(command).status=="succeeded"
    before=snapshot(workspace)
    provider.identity=ProviderIdentity("fake","changed",{})
    assert handler.handle(command).error_category=="artifact_conflict"
    assert len(provider.calls)==1 and snapshot(workspace)==before


def test_source_change_during_provider_call_blocks_publication(tmp_path):
    handler,command,provider,workspace=prepared(tmp_path)
    original=provider.translate
    def change(call):
        result=original(call)
        (workspace/"source_alignment.json").write_bytes(b"changed")
        return result
    provider.translate=change
    assert handler.handle(command).error_category=="input_invalid"
    assert not (workspace/"translation_manifest.json").exists()


def test_manifest_glossary_pair_change_conflicts_with_validated_execution_identity(tmp_path):
    handler, command, provider, workspace = prepared(tmp_path)
    assert handler.handle(command).status == "succeeded"
    path = workspace / "translation_manifest.json"
    data = json.loads(path.read_bytes())
    data["identity"]["glossary_sha256"] = None
    assert data["identity"]["glossary_path"]
    path.write_text(json.dumps(data), encoding="utf-8")
    assert handler.verify(command).error_category == "artifact_conflict"
    assert len(provider.calls) == 1


def test_actual_partial_install_never_reuses_previous_success_manifest(tmp_path, monkeypatch):
    from dataclasses import replace
    from pathlib import Path
    from translation.domain import ProviderResponse, ProviderStatus
    handler, command, provider, workspace = prepared(tmp_path)
    assert handler.handle(command).status == "succeeded"
    manifest = workspace / "translation_manifest.json"
    result = workspace / "translation_result.json"
    old_manifest, old_result = manifest.read_bytes(), result.read_bytes()
    original_translate = provider.translate
    def updated(call):
        response = original_translate(call)
        body = {"section": dict(response.output["section"]), "items": [dict(item) for item in response.output["items"]]}
        body["items"][0]["translated_text"] = "新版译文"
        return ProviderResponse(ProviderStatus.COMPLETED, body, 1)
    provider.identity=ProviderIdentity("fake","new-content",{})
    monkeypatch.setattr(provider, "translate", updated)
    original_replace = Path.replace
    def fail_manifest(source, target):
        if Path(target) == manifest:
            raise OSError("manifest publication interruption")
        return original_replace(source, target)
    monkeypatch.setattr(Path, "replace", fail_manifest)
    assert handler.handle(replace(command, overwrite=True)).error_category == "publication_failed"
    assert result.read_bytes() != old_result and manifest.read_bytes() == old_manifest
    assert list(workspace.glob(".translation_manifest.json.*.tmp"))
    calls = len(provider.calls)
    assert handler.verify(command).error_category == "artifact_conflict"
    assert len(provider.calls) == calls


def test_explicit_output_overwrite_reuses_verified_current_batch_after_interruption(tmp_path):
    from dataclasses import replace
    handler,command,provider,workspace=prepared(tmp_path,51)
    provider.fail_at=2
    assert handler.handle(command).status=="failed" and len(provider.calls)==2
    assert not (workspace/"translation_result.json").exists()
    provider.fail_at=None
    result=handler.handle(replace(command,overwrite=True))
    assert result.status=="succeeded" and result.checkpoint_reuse_count==1 and result.attempt_count==1
    assert len(provider.calls)==3
    assert [call.request.translate_title for call in provider.calls]==[True,False,False]


def test_explicit_overwrite_never_reuses_checkpoint_from_different_provider_identity(tmp_path):
    from dataclasses import replace
    handler,command,provider,workspace=prepared(tmp_path)
    assert handler.handle(command).status=="succeeded"
    provider.identity=ProviderIdentity("fake","different-generation",{})
    result=handler.handle(replace(command,overwrite=True))
    assert result.status=="succeeded" and result.checkpoint_reuse_count==0 and result.attempt_count==1
    assert len(provider.calls)==2
