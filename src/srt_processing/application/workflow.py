"""Validate and project the authoritative final draft; never replan or retime."""

from dataclasses import dataclass
import hashlib
import json

from archive_core.domain import ArtifactType, canonical_filename
from archive_core.interfaces.subtitles import SrtExportReportDTO
from archive_core.interfaces.bilingual import ArtifactEvidenceDTO, StageManifestDTO
from archive_core.interfaces.bilingual_timing import chinese_half_units, empty_frame_count
from .inputs import load_subtitle_inputs, SubtitleInputError
from .ports import SrtCue
from srt_processing.domain.chunking_policy import (ENGLISH_MAX_CHARACTERS, ENGLISH_CPS_LIMIT, CHINESE_CPS_LIMIT, CHINESE_LINE_TARGET_UNITS, MIN_CHUNK_DURATION_MS, MAX_CHUNK_DURATION_MS)
from .source_chunking import metadata_bytes


class SrtProcessingWorkflowError(RuntimeError):
    category = "srt_processing_failed"


@dataclass(frozen=True)
class SrtProcessingRunResult:
    status: str
    plan_path: str
    manifest_path: str
    report_path: str
    english_srt_path: str
    chinese_srt_path: str
    bilingual_srt_path: str
    cue_count: int
    warning_count: int
    writes: int


def export_report(draft):
    findings = []
    def warning(code, cue, observed):
        findings.append({"code": code, "severity": "warning", "cue_id": cue.id,
                         "start_ms": cue.start_ms, "end_ms": cue.end_ms, "observed": observed})
    for position, cue in enumerate(draft.cues):
        duration = cue.end_ms - cue.start_ms
        units = chinese_half_units(cue.chinese_text)
        if len(cue.english_text) > ENGLISH_MAX_CHARACTERS:
            warning("english.capacity", cue, {"characters": len(cue.english_text), "limit": ENGLISH_MAX_CHARACTERS})
        if len(cue.english_text) * 1000 > duration * ENGLISH_CPS_LIMIT:
            warning("reading.english_cps", cue, {"characters": len(cue.english_text), "duration_ms": duration, "limit": ENGLISH_CPS_LIMIT})
        if units * 1000 > duration * (2 * CHINESE_CPS_LIMIT):
            warning("reading.chinese_cps", cue, {"half_units": units, "duration_ms": duration, "limit": CHINESE_CPS_LIMIT})
        if units > 2 * CHINESE_LINE_TARGET_UNITS:
            warning("reading.chinese_length", cue, {"half_units": units, "target_half_units": 2 * CHINESE_LINE_TARGET_UNITS})
        if duration < MIN_CHUNK_DURATION_MS or duration > MAX_CHUNK_DURATION_MS:
            warning("timing.display_duration", cue, {"duration_ms": duration, "minimum_ms": MIN_CHUNK_DURATION_MS, "maximum_ms": MAX_CHUNK_DURATION_MS})
        if position + 1 < len(draft.cues):
            count = empty_frame_count(draft.media, cue.end_ms, draft.cues[position + 1].start_ms)
            if count is None or count < 2:
                warning("timing.frame_gap_unverified" if count is None else "timing.short_frame_gap", cue,
                        {"empty_frames": count, "minimum": 2})
    data = {"schema_version": "subtitle.export-report.v1", "asset_id": draft.asset_id,
            "status": "succeeded", "findings": findings,
            "summary": {"cue_count": len(draft.cues), "warning_count": len(findings)},
            "semantic_review": "not_run"}
    result = SrtExportReportDTO.from_dict(data)
    result.validate_against_draft(draft)
    return result.to_dict()


class SrtProcessingWorkflow:
    def __init__(self, *, artifacts, codec, clock, output_root="output"):
        self.artifacts, self.codec, self.clock, self.output_root = artifacts, codec, clock, output_root

    def execute(self, *, asset_id, bilingual_postprocessing_manifest_path, overwrite=False):
        if type(overwrite) is not bool:
            raise SubtitleInputError("overwrite must be boolean")
        inputs = load_subtitle_inputs(asset_id=asset_id,
                                     bilingual_postprocessing_manifest_path=bilingual_postprocessing_manifest_path,
                                     artifacts=self.artifacts, output_root=self.output_root)
        paths = {name: str(inputs.workspace / canonical_filename(kind)) for name, kind in {
            "english_srt": ArtifactType.ENGLISH_SRT, "chinese_srt": ArtifactType.CHINESE_SRT,
            "bilingual_srt": ArtifactType.BILINGUAL_SRT, "report": ArtifactType.SRT_PROCESSING_REPORT,
            "manifest": ArtifactType.SRT_PROCESSING_MANIFEST,
        }.items()}
        report = export_report(inputs.draft)
        payloads = {}
        for name in ("english", "chinese", "bilingual"):
            data = self.codec.encode(inputs.draft, name)
            expected = tuple(
                SrtCue(position, cue.start_ms, cue.end_ms,
                       cue.english_text if name == "english" else cue.chinese_text if name == "chinese"
                       else cue.chinese_text + "\n" + cue.english_text)
                for position, cue in enumerate(inputs.draft.cues, 1)
            )
            if self.codec.decode(data) != expected:
                raise SrtProcessingWorkflowError("codec did not preserve authoritative text and timing")
            payloads[name + "_srt"] = data
        payloads["report"] = metadata_bytes(report)
        identity = {"codec": dict(self.codec.identity), "projection": "authoritative-logical-lines.v1"}
        occupied = [self.artifacts.exists(path) for path in paths.values()]
        status, writes = "succeeded", 5
        if any(occupied) and not overwrite:
            if not all(occupied):
                raise FileExistsError("partial SRT output set")
            manifest = StageManifestDTO.from_dict(json.loads(self.artifacts.read_bytes(paths["manifest"])))
            if (manifest.stage != "srt_export" or manifest.asset_id != asset_id or manifest.inputs != inputs.evidence
                    or metadata_bytes(manifest.to_dict()["identity"]) != metadata_bytes(identity)
                    or set(manifest.outputs) != set(payloads)):
                raise FileExistsError("SRT manifest identity conflict")
            for name, data in payloads.items():
                recorded = manifest.outputs[name]
                if (self.artifacts.read_bytes(paths[name]) != data or recorded.path != paths[name]
                        or (recorded.size_bytes, recorded.sha256) != (len(data), hashlib.sha256(data).hexdigest())):
                    raise FileExistsError("SRT projection/report evidence differs")
            status, writes = "reused", 0
        else:
            staged = {name: self.artifacts.stage_bytes(paths[name], data) for name, data in payloads.items()}
            for name, data in payloads.items():
                if self.artifacts.read_bytes(staged[name]) != data:
                    raise ValueError("staged SRT bytes changed")
                if name != "report":
                    self.codec.decode(data)
            # TOCTOU: the validated content chain must remain unchanged before publication.
            for evidence in inputs.evidence.values():
                if self.artifacts.size(evidence.path) != evidence.size_bytes or self.artifacts.sha256(evidence.path) != evidence.sha256:
                    raise SubtitleInputError("input changed during export")
            outputs = {name: ArtifactEvidenceDTO(paths[name], len(data), hashlib.sha256(data).hexdigest()) for name, data in payloads.items()}
            manifest = StageManifestDTO(stage="srt_export", asset_id=asset_id, inputs=inputs.evidence,
                                        outputs=outputs, identity=identity, completed_at=self.clock.now_utc(), execution={"writes": writes})
            for name in payloads:
                self.artifacts.publish(staged[name], paths[name], overwrite=overwrite)
            manifest_bytes = metadata_bytes(manifest.to_dict())
            staged_manifest = self.artifacts.stage_bytes(paths["manifest"], manifest_bytes)
            if self.artifacts.read_bytes(staged_manifest) != manifest_bytes:
                raise ValueError("staged SRT manifest bytes changed")
            self.artifacts.publish(staged_manifest, paths["manifest"], overwrite=overwrite)
        return SrtProcessingRunResult(status, inputs.evidence["final_bilingual_draft"].path, paths["manifest"], paths["report"],
                                      paths["english_srt"], paths["chinese_srt"], paths["bilingual_srt"], len(inputs.draft.cues),
                                      report["summary"]["warning_count"], writes)
