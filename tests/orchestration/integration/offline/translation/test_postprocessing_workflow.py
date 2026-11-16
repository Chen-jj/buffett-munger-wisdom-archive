"""Durable request budgets, warning publication and real local final authority."""

import json

import pytest

from tests.orchestration.integration.offline.translation.workflow_support import prepared, snapshot, Clock
from translation.domain import ProviderIdentity, ProviderResponse, ProviderStatus, PermanentProviderError
from translation.interfaces import BilingualPostprocessingCommand, build_bilingual_postprocessing_handler


class RevisionProvider:
    identity=ProviderIdentity("fake-revision","fixed",{})
    def __init__(self,mode="valid"):self.calls=[];self.mode=mode
    def translate(self,call):
        self.calls.append(call)
        if self.mode=="fail":raise PermanentProviderError("private",code="configuration")
        if self.mode=="invalid":return ProviderResponse(ProviderStatus.COMPLETED,{"english":"not allowed"},1)
        if self.mode=="unresolved":return ProviderResponse(ProviderStatus.COMPLETED,{"status":"unresolved","cues":[]},1)
        payload=call.request.to_dict()
        result={"status":"proposed","cues":[{"first_word_id":row["word_ids"][0],"last_word_id":row["word_ids"][-1],
            "translated_text":"译"}
            for row in payload["current_cues"]]}
        return ProviderResponse(ProviderStatus.COMPLETED,result,1)


def setup(tmp_path,mode="valid",count=3):
    handler,command,initial,workspace=prepared(tmp_path,count)
    assert handler.handle(command).status=="succeeded"
    provider=RevisionProvider(mode)
    post=build_bilingual_postprocessing_handler(output_root=handler.workflow.output_root,provider=provider,clock=Clock())
    postcommand=BilingualPostprocessingCommand(command.asset_id,command.transcription_manifest_path,
        command.source_chunking_manifest_path,str(workspace/"translation_manifest.json"))
    return post,postcommand,provider,workspace


def test_final_authority_uses_program_english_times_and_reuses_zero_requests(tmp_path):
    handler,command,provider,workspace=setup(tmp_path)
    result=handler.handle(command)
    assert result.status=="succeeded" and result.provider_calls==1
    draft=json.loads((workspace/"final_bilingual_draft.json").read_bytes())
    assert [c["chinese_text"] for c in draft["cues"]]==["译"]*3
    assert [c["english_text"] for c in draft["cues"]]==["Word1.","Word2.","Word3."]
    assert all(c["start_ms"]==i*1100 and c["final_end_ms"]==i*1100+1000 for i,c in enumerate(draft["cues"]))
    assert all(call.max_attempts==1 for call in provider.calls)
    report=json.loads((workspace/"bilingual_postprocessing_report.json").read_bytes())
    assert report["editorial_generation"]=="completed" and report["semantic_review"]=="not_run"
    assert len(report["batches"])==1 and report["batches"][0]["adopted"]
    before=snapshot(workspace)
    assert handler.handle(command).status=="reused"
    assert len(provider.calls)==1 and snapshot(workspace)==before


@pytest.mark.parametrize("mode",["invalid","unresolved"])
def test_three_requests_per_window_exhaust_then_publish_warning_without_reset(tmp_path,mode):
    handler,command,provider,workspace=setup(tmp_path,mode,count=1)
    result=handler.handle(command)
    assert result.status=="succeeded" and result.provider_calls==3 and result.warning_count>0
    report=json.loads((workspace/"bilingual_postprocessing_report.json").read_bytes())
    assert report["batches"][0]["request_count"]==3 and not report["batches"][0]["adopted"]
    assert report["batches"][0]["retained_initial_draft"]
    assert report["editorial_generation"]=="partial_unresolved" and report["semantic_review"]=="not_run"
    assert [call.request.to_dict()["task"] for call in provider.calls]==["bilingual_editorial_generation"]*3
    assert handler.handle(command).status=="reused" and len(provider.calls)==3


def test_reading_metrics_are_truthfully_reported_not_retried_or_used_as_semantic_quality(tmp_path):
    handler,command,provider,workspace=setup(tmp_path,count=1)
    def long_faithful_candidate(call):
        provider.calls.append(call)
        return ProviderResponse(ProviderStatus.COMPLETED,{"status":"proposed","cues":[{
            "first_word_id":"w1","last_word_id":"w1","translated_text":"未删减的完整译文"*10}]},1)
    provider.translate=long_faithful_candidate
    result=handler.handle(command)
    assert result.status=="succeeded" and result.provider_calls==1 and result.warning_count>0
    report=json.loads((workspace/"bilingual_postprocessing_report.json").read_bytes())
    assert report["editorial_generation"]=="completed" and report["semantic_review"]=="not_run"
    assert {"chinese_cps","chinese_length"}<={row["code"] for row in report["diagnostics"]}
    assert handler.handle(command).status=="reused" and len(provider.calls)==1


def test_interruption_or_provider_failure_consumes_persistent_allowance(tmp_path):
    handler,command,provider,workspace=setup(tmp_path,"fail",count=1)
    first=handler.handle(command)
    assert first.status=="failed" and first.error_category=="provider_failed"
    assert not (workspace/"final_bilingual_draft.json").exists()
    provider.mode="invalid"
    result=handler.handle(command)
    assert result.status=="succeeded" and result.provider_calls==2 and len(provider.calls)==3
    report=json.loads((workspace/"bilingual_postprocessing_report.json").read_bytes())
    assert report["batches"][0]["request_count"]==3


def test_verify_is_zero_provider_identity_process_checkpoint_and_writes(tmp_path):
    handler,command,provider,workspace=setup(tmp_path,count=1)
    assert handler.handle(command).status=="succeeded"
    class Forbidden:
        @property
        def identity(self):pytest.fail("provider identity/preflight on verify")
        def translate(self,call):pytest.fail("content request on verify")
    handler.workflow.provider=Forbidden()
    before=snapshot(workspace)
    assert handler.verify(command).status=="reused"
    assert snapshot(workspace)==before


@pytest.mark.parametrize("field",["request","accepted","error"])
def test_replayed_request_ledger_cannot_self_authorize_permissions_or_acceptance(tmp_path,field):
    handler,command,provider,workspace=setup(tmp_path,"fail",count=1)
    assert handler.handle(command).status=="failed"
    store=handler.workflow.checkpoints
    path=next(p for p in store.directory.glob("*.json")
              if json.loads(p.read_bytes())["schema_version"]=="translation.editorial-ledger.v1")
    state=json.loads(path.read_bytes())
    if field=="request":state["attempts"][0]["request"]["task"]="other"
    elif field=="accepted":state["attempts"][0]["accepted"]=True
    else:state["attempts"][0]["error"]="made_up"
    path.write_text(json.dumps(state))
    provider.mode="valid"
    result=handler.handle(command)
    assert result.status=="failed" and result.error_category=="checkpoint_invalid"
    assert len(provider.calls)==1


def test_revision_request_uses_window_summaries_not_all_media_frame_pts(tmp_path):
    handler,command,provider,workspace=setup(tmp_path,count=1)
    assert handler.handle(command).status=="succeeded"
    payload=provider.calls[0].request.to_dict()
    assert "frame_timestamps_us" not in payload["media"]
    assert "trial" in payload and "outer_neighbors" in payload
    assert set(payload["words"][0])=={"id","text","start_ms","end_ms"}
    assert payload["task"]=="bilingual_editorial_generation"
    assert "mode" not in payload and "target_word_ranges" not in payload


def test_list_status_is_format_retry_without_permission_escalation(tmp_path):
    handler,command,provider,workspace=setup(tmp_path,count=1)
    def malformed(call):
        provider.calls.append(call)
        return ProviderResponse(ProviderStatus.COMPLETED,{"status":[],"cues":[]},1)
    provider.translate=malformed
    result=handler.handle(command)
    assert result.status=="succeeded" and len(provider.calls)==3
    assert [call.request.to_dict()["task"] for call in provider.calls]==["bilingual_editorial_generation"]*3


def test_resume_after_format_rejection_and_provider_failure_replays_original_request_history(tmp_path):
    handler,command,provider,workspace=setup(tmp_path,count=1)
    original=provider.translate
    def reject_then_fail(call):
        provider.calls.append(call)
        if len(provider.calls)==1:
            raise PermanentProviderError("unparseable adapter output",code="malformed_response")
        raise PermanentProviderError("backend failed",code="configuration")
    provider.translate=reject_then_fail
    failed=handler.handle(command)
    assert failed.error_category=="provider_failed" and len(provider.calls)==2
    provider.translate=original
    resumed=handler.handle(command)
    assert resumed.status=="succeeded" and resumed.provider_calls==1
    assert [call.request.to_dict()["task"] for call in provider.calls]==["bilingual_editorial_generation"]*3
    assert [call.request.to_dict()["previous_errors"] for call in provider.calls]==[
        [],["malformed_response"],["malformed_response","provider_failed"],
    ]


def test_valid_revision_replayed_after_failed_publication_without_another_content_request(tmp_path,monkeypatch):
    handler,command,provider,workspace=setup(tmp_path,count=1)
    store=handler.workflow.artifacts
    original=store.publish_json_bundle
    def fail(*args,**kwargs):
        raise OSError("injected publication failure")
    monkeypatch.setattr(store,"publish_json_bundle",fail)
    assert handler.handle(command).error_category=="publication_failed"
    assert len(provider.calls)==1
    monkeypatch.setattr(store,"publish_json_bundle",original)
    result=handler.handle(command)
    assert result.status=="succeeded" and result.provider_calls==0 and result.checkpoint_reuse_count==1
    assert len(provider.calls)==1


def test_complete_editorial_batch_does_not_premerge_original_initial_cues(tmp_path):
    handler,command,provider,workspace=setup(tmp_path,count=3)
    assert handler.handle(command).status=="succeeded"
    assert len(provider.calls)==1
    assert [cue["word_ids"] for cue in provider.calls[0].request.to_dict()["current_cues"]]==[["w1"],["w2"],["w3"]]


def test_unresolved_draft_can_be_replayed_after_publication_failure_without_reset(tmp_path,monkeypatch):
    handler,command,provider,workspace=setup(tmp_path,"unresolved",count=1)
    store=handler.workflow.artifacts
    original=store.publish_json_bundle
    monkeypatch.setattr(store,"publish_json_bundle",lambda *args,**kwargs:(_ for _ in ()).throw(OSError("injected")))
    assert handler.handle(command).error_category=="publication_failed"
    assert len(provider.calls)==3
    monkeypatch.setattr(store,"publish_json_bundle",original)
    result=handler.handle(command)
    assert result.status=="succeeded" and result.provider_calls==0 and len(provider.calls)==3
    report=json.loads((workspace/"bilingual_postprocessing_report.json").read_bytes())
    assert report["editorial_generation"]=="partial_unresolved" and report["batches"][0]["retained_initial_draft"]
