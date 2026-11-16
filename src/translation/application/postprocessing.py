"""Persistently bounded content revision and final authority publication."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json

from archive_core.application import build_asset_workspace
from archive_core.domain import ArtifactType, canonical_filename
from archive_core.interfaces.bilingual import (
    ArtifactEvidenceDTO, ChunkTranslationResultDTO, FinalBilingualDraftDTO, StageManifestDTO,
)
from translation.domain import ProviderCall, ProviderError, ProviderResponse, ProviderStatus, RevisionRequest, canonical_json_bytes, canonical_json_sha256
from translation.domain.planning import TERM_MATCH_VERSION, matched_glossary
from translation.domain.postprocessing import (
    Group, POSTPROCESSING_VERSION, REVISION_PROMPT, REVISION_SCHEMA,
    EDITORIAL_WORD_LIMIT, EDITORIAL_CUE_LIMIT, anchored, editorial_batches, final_cues,
    parse_revision, sentence_ids, trial,
)
from .workflow import (
    TranslationArtifactConflict, TranslationCheckpointError, TranslationInputError,
    TranslationProviderFailure, TranslationPublicationError, evidence, load_source_inputs,
    parse_asset, verify_evidence,
)


@dataclass(frozen=True)
class PostprocessingRunResult:
    status: str
    draft_path: str
    report_path: str
    manifest_path: str
    cue_count: int
    warning_count: int
    provider_calls: int
    checkpoint_reuse_count: int


def _group_data(group):
    return {"word_ids":list(group.word_ids),"chinese_text":group.chinese,
            "initial_chunk_ids":list(group.initial_chunk_ids)}


class BilingualPostprocessingWorkflow:
    def __init__(self, *, provider, artifacts, checksum, checkpoints, glossaries, clock,
                 output_root="output", default_glossary_path=None):
        self.provider,self.artifacts,self.checksum=provider,artifacts,checksum
        self.checkpoints,self.glossaries,self.clock=checkpoints,glossaries,clock
        self.output_root=output_root
        self.default_glossary_path=default_glossary_path

    def verify(self, **arguments):
        arguments["overwrite"] = False
        return self.execute(**arguments, _verify=True)

    def execute(self, *, asset_id, transcription_manifest_path, source_chunking_manifest_path,
                translation_manifest_path, glossary_path=None, overwrite=False, _verify=False):
        if not isinstance(overwrite,bool):raise TranslationInputError("overwrite must be boolean")
        workspace=build_asset_workspace(parse_asset(asset_id),self.output_root).absolute()
        alignment,chunks,inputs=load_source_inputs(asset_id,workspace,transcription_manifest_path,
            source_chunking_manifest_path,self.artifacts,self.checksum)
        try:
            if Path(translation_manifest_path)!=workspace/canonical_filename(ArtifactType.TRANSLATION_MANIFEST):
                raise ValueError("translation manifest path is not canonical")
            manifest=StageManifestDTO.from_dict(self.artifacts.read_json(translation_manifest_path))
            if manifest.stage!="translation" or manifest.asset_id!=asset_id or manifest.inputs!=inputs or set(manifest.outputs)!={"translation_result"}:
                raise ValueError("translation chain mismatch")
            item=manifest.outputs["translation_result"]
            verify_evidence(item,self.artifacts,self.checksum,str(workspace/canonical_filename(ArtifactType.TRANSLATION_RESULT)))
            translated=ChunkTranslationResultDTO.from_dict(self.artifacts.read_json(item.path))
            translated.validate_against_inputs(alignment,chunks)
            if translated.source_chunks_sha256!=inputs["source_chunks"].sha256:
                raise ValueError("translation source chunks fingerprint mismatch")
            inputs=dict(inputs,translation_manifest=evidence(translation_manifest_path,self.artifacts,self.checksum),translation_result=item)
            glossary_path=glossary_path or self.default_glossary_path
            resource=self.glossaries.load(glossary_path) if glossary_path else None
            identity={"version":POSTPROCESSING_VERSION,"prompt_sha256":canonical_json_sha256(REVISION_PROMPT),
                "schema":REVISION_SCHEMA,"provider":(self.artifacts.read_json(str(workspace/canonical_filename(ArtifactType.BILINGUAL_POSTPROCESSING_MANIFEST)))["identity"]["provider"] if _verify else self.provider.identity.to_dict()),
                "configuration_sha256":getattr(self.provider,"configuration_sha256",None),
                "source_policy":chunks.to_dict()["policy"],"maximum_content_requests":3,
                "editorial_batch_limits":{"source_words":EDITORIAL_WORD_LIMIT,"initial_cues":EDITORIAL_CUE_LIMIT},
                "glossary_sha256":resource.sha256 if resource else None,
                "term_match_version":TERM_MATCH_VERSION,
                "media":chunks.media.to_dict()}
        except TranslationInputError:raise
        except ProviderError as error:
            raise TranslationProviderFailure(f"revision provider configuration failed ({error.code})") from error
        except Exception as error:raise TranslationInputError("postprocessing inputs/configuration invalid") from error
        paths={"final_bilingual_draft":str(workspace/canonical_filename(ArtifactType.FINAL_BILINGUAL_DRAFT)),
               "report":str(workspace/canonical_filename(ArtifactType.BILINGUAL_POSTPROCESSING_REPORT))}
        final_manifest=str(workspace/canonical_filename(ArtifactType.BILINGUAL_POSTPROCESSING_MANIFEST))
        occupied=[self.artifacts.exists(path) for path in (*paths.values(),final_manifest)]
        if not overwrite and any(occupied):
            if not all(occupied):raise TranslationArtifactConflict("incomplete postprocessing output set")
            try:
                current=StageManifestDTO.from_dict(self.artifacts.read_json(final_manifest))
                draft=FinalBilingualDraftDTO.from_dict(self.artifacts.read_json(paths["final_bilingual_draft"]))
                draft.validate_against_inputs(alignment,chunks,translated)
                if draft.translation_result_sha256 != inputs["translation_result"].sha256:
                    raise ValueError("final draft initial translation fingerprint differs")
                if dict(draft.policy) != dict(chunks.policy,postprocessing_version=POSTPROCESSING_VERSION):
                    raise ValueError("final draft policy differs")
                saved_groups=tuple(Group(cue.word_ids,cue.chinese_text,cue.initial_chunk_ids) for cue in draft.cues)
                if final_cues(saved_groups,alignment,chunks.media,chunks.policy) != draft.cues:
                    raise ValueError("final timing is not the exact authoritative rule projection")
                expected_diagnostics=self._diagnostics(saved_groups,alignment,chunks)
                if canonical_json_sha256(expected_diagnostics) != canonical_json_sha256(draft.diagnostics):
                    raise ValueError("final diagnostics do not match mechanical re-scan")
                outputs={key:evidence(path,self.artifacts,self.checksum) for key,path in paths.items()}
                if current.stage!="bilingual_postprocessing" or current.asset_id!=asset_id or current.inputs!=inputs or current.outputs!=outputs or canonical_json_sha256(current.identity)!=canonical_json_sha256(identity):
                    raise ValueError("postprocessing identity differs")
                report=self.artifacts.read_json(paths["report"])
                if report["status"]!="succeeded" or report["diagnostics"]!=draft.to_dict()["diagnostics"]:
                    raise ValueError("postprocessing report differs")
            except Exception as error:raise TranslationArtifactConflict("postprocessing reuse verification failed") from error
            return PostprocessingRunResult("reused",paths["final_bilingual_draft"],paths["report"],final_manifest,len(draft.cues),len(draft.diagnostics),0,0)
        if _verify:raise TranslationArtifactConflict("verified postprocessing outputs are missing")
        groups=tuple(Group(chunk.word_ids,text.translated_text,(chunk.id,)) for chunk,text in zip(chunks.chunks,translated.chunks,strict=True))
        try:
            trial(groups,alignment,chunks.media,chunks.policy)
            windows=editorial_batches(chunks,alignment)
        except ValueError as error:
            raise TranslationInputError("source timing/grouping is invalid") from error
        calls,reused,window_reports=0,0,[]
        # Right-to-left application preserves the source-index positions of all remaining windows.
        for window in reversed(windows):
            old=groups[window.first:window.last+1]
            window_ids=tuple(wid for group in old for wid in group.word_ids)
            key=canonical_json_sha256({"inputs":{k:v.to_dict() for k,v in inputs.items()},"identity":identity,"window_words":window_ids})
            state={"schema_version":"translation.editorial-ledger.v1","key":key,"attempts":[]}
            if self.checkpoints.exists(key):
                try:
                    state=dict(self.checkpoints.read(key))
                    if set(state)!={"schema_version","key","attempts"} or state["schema_version"]!="translation.editorial-ledger.v1" or state["key"]!=key or not isinstance(state["attempts"],list) or len(state["attempts"])>3:
                        raise ValueError("invalid persistent request ledger")
                except Exception as error:raise TranslationCheckpointError("revision request ledger invalid") from error
            errors=[];adopted=None
            for number,saved in enumerate(state["attempts"]):
                if not isinstance(saved,dict) or set(saved)!={"request","response","accepted","error"} or not isinstance(saved["accepted"],bool):
                    raise TranslationCheckpointError("revision attempt record invalid")
                expected=self._request_payload(groups,window,old,window_ids,alignment,chunks,errors,resource.glossary if resource else None)
                try:
                    matches = canonical_json_sha256(saved["request"]) == canonical_json_sha256(expected)
                except ValueError as error:
                    raise TranslationCheckpointError("invalid persisted revision request") from error
                if not matches:
                    raise TranslationCheckpointError("revision request/permission history differs")
                if saved["response"] is None:
                    if saved["accepted"] or saved["error"] not in (None,"provider_failed","provider_noncompleted","malformed_response"):
                        raise TranslationCheckpointError("revision interrupted request record invalid")
                    errors.append(saved["error"] or "interrupted_request")
                    continue
                proposal,reason=self._evaluate(saved["response"],groups,window,old,alignment,chunks)
                if saved["accepted"]!=(proposal is not None) or saved["error"]!=reason:
                    raise TranslationCheckpointError("revision acceptance/error history differs")
                if proposal is not None:
                    if number!=len(state["attempts"])-1:
                        raise TranslationCheckpointError("requests after accepted revision are invalid")
                    adopted=proposal;reused+=1;break
                errors.append(reason)
            while adopted is None and len(state["attempts"])<3:
                payload=self._request_payload(groups,window,old,window_ids,alignment,chunks,errors,resource.glossary if resource else None)
                record={"request":payload,"response":None,"accepted":False,"error":None}
                state["attempts"].append(record)
                self._save(key,state)  # Charge before the content request; a crash cannot reset its allowance.
                calls+=1
                try:
                    response=self.provider.translate(ProviderCall(REVISION_PROMPT,RevisionRequest(payload),REVISION_SCHEMA,1))
                except ProviderError as error:
                    if error.code == "malformed_response":
                        record["error"] = "malformed_response"
                        self._save(key, state)
                        errors.append(record["error"])
                        continue
                    record["error"]="provider_failed";self._save(key,state)
                    raise TranslationProviderFailure(f"revision provider failed ({error.code}); request allowance retained") from error
                except Exception as error:
                    record["error"]="provider_failed";self._save(key,state)
                    raise TranslationProviderFailure("revision provider failed; request allowance retained") from error
                if not isinstance(response,ProviderResponse) or response.status!=ProviderStatus.COMPLETED:
                    record["error"]="provider_noncompleted";self._save(key,state)
                    raise TranslationProviderFailure("revision provider did not complete; allowance retained")
                # Convert frozen provider mappings/tuples to ordinary JSON values for durable ledger.
                record["response"]=json.loads(canonical_json_bytes(response.output))
                proposal,reason=self._evaluate(response.output,groups,window,old,alignment,chunks)
                record["error"]=reason
                if proposal is not None:
                    record["accepted"]=True;adopted=proposal
                self._save(key,state)
                if record["error"]:errors.append(record["error"])
            if adopted is not None:groups=groups[:window.first]+adopted+groups[window.last+1:]
            window_reports.append({"first_word_id":window_ids[0],"last_word_id":window_ids[-1],
                "request_count":len(state["attempts"]),"adopted":adopted is not None,"errors":errors,
                "retained_initial_draft":adopted is None})
        cues=final_cues(groups,alignment,chunks.media,chunks.policy)
        diagnostics=self._diagnostics(groups,alignment,chunks)
        policy=dict(chunks.to_dict()["policy"],postprocessing_version=POSTPROCESSING_VERSION)
        draft=FinalBilingualDraftDTO(asset_id,inputs["source_alignment"].sha256,inputs["source_chunks"].sha256,
            inputs["translation_result"].sha256,chunks.media,policy,cues,translated.section_titles,diagnostics)
        draft.validate_against_inputs(alignment,chunks,translated)
        report={"schema_version":"translation.postprocessing-report.v3","status":"succeeded",
            "diagnostics":list(diagnostics),"batches":list(reversed(window_reports)),"provider_calls":calls,
            "editorial_generation":"partial_unresolved" if any(not batch["adopted"] for batch in window_reports) else "completed",
            "semantic_review":"not_run"}
        for item in inputs.values():verify_evidence(item,self.artifacts,self.checksum)
        def factory(outputs):
            return StageManifestDTO("bilingual_postprocessing",asset_id,inputs,outputs,identity,
                self.clock.now_utc(),{"provider_calls":calls,"checkpoint_reuse_count":reused}).to_dict()
        try:
            self.artifacts.publish_json_bundle({paths["final_bilingual_draft"]:draft.to_dict(),paths["report"]:report},
                final_manifest,factory,output_names={path:key for key,path in paths.items()},overwrite=overwrite)
        except Exception as error:raise TranslationPublicationError("postprocessing publication failed") from error
        return PostprocessingRunResult("succeeded",paths["final_bilingual_draft"],paths["report"],final_manifest,len(cues),len(diagnostics),calls,reused)

    @staticmethod
    def _request_payload(groups,window,old,window_ids,alignment,chunks,errors,glossary):
        ids=set(window_ids)
        editable_sentence_ids=set(sid for group in old for sid in sentence_ids(group,alignment))
        positions=[i for i,s in enumerate(alignment.sentences) if s.id in editable_sentence_ids]
        section=next((section for section in alignment.sections
                      if int(section.first_sentence_id[1:])<=min(positions)+1
                      and max(positions)+1<=int(section.last_sentence_id[1:])),None)
        context=(alignment.sentences[int(section.first_sentence_id[1:])-1:int(section.last_sentence_id[1:])]
                 if section else alignment.sentences[max(0,min(positions)-3):max(positions)+3])
        payload={"task":"bilingual_editorial_generation",
            "editable_sentences":[s.to_dict() for s in alignment.sentences if s.id in editable_sentence_ids],
            "words":[{"id":w.id,"text":w.text,"start_ms":w.start_ms,"end_ms":w.end_ms}
                     for w in alignment.words if w.id in ids],
            "current_cues":[_group_data(group) for group in old],
            "readonly_context":[{"id":s.id,"text":s.text} for s in context if s.id not in editable_sentence_ids],
            "protected_spans":[span.to_dict() for span in chunks.protected_spans if span.first_word_id in ids or span.last_word_id in ids],
            "analyzed_sentence_ids":[sid for sid in chunks.analyzed_sentence_ids if sid in editable_sentence_ids],
            "annotations":[a.to_dict() for a in alignment.annotations if a.after_word_id in ids],
            "glossary":list(matched_glossary(" ".join(anchored(g,alignment)[2] for g in old),glossary)),
            "policy":chunks.to_dict()["policy"],"media":{"duration_ms":chunks.media.duration_ms,"video_sha256":chunks.media.video_sha256,
                  "frame_evidence":"decoded_pts" if chunks.media.frame_timestamps_us is not None else "unavailable"},
            "trial":[{key:value for key,value in row.items() if key!="group"} for row in trial(groups,alignment,chunks.media,chunks.policy)[window.first:window.last+1]],
            "outer_neighbors":[_group_data(groups[i]) for i in (window.first-1,window.last+1) if 0<=i<len(groups)],
            "previous_errors":list(errors)}
        return payload

    @staticmethod
    def _evaluate(output,groups,window,old,alignment,chunks):
        try:
            proposal=parse_revision(output,old,alignment=alignment,chunks=chunks)
            if proposal is None:return None,"explicit_unresolved"
            after=groups[:window.first]+proposal+groups[window.last+1:]
            trial(after,alignment,chunks.media,chunks.policy)
            return proposal,None
        except (ValueError,TypeError,KeyError) as error:
            return None,str(error)

    @staticmethod
    def _diagnostics(groups,alignment,chunks):
        return tuple({"severity":"warning","code":code,"cue_id":f"c{i}",
            "word_ids":list(row["group"].word_ids),"start_ms":row["start_ms"],"base_end_ms":row["base_end_ms"],"final_end_ms":row["final_end_ms"]}
            for i,row in enumerate(trial(groups,alignment,chunks.media,chunks.policy),1) for code in row["issues"])

    def _save(self,key,state):
        try:self.checkpoints.write(key,state,overwrite=True)
        except Exception as error:raise TranslationCheckpointError("request allowance could not be persisted") from error
