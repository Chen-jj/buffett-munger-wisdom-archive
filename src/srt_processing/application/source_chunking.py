"""Source chunking evidence gates, deterministic reuse, and manifest-last publication."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from archive_core.application import build_asset_workspace
from archive_core.domain import AssetId, ArtifactType, canonical_filename
from archive_core.interfaces.bilingual import (
    ArtifactEvidenceDTO, MediaBoundaryDTO, SourceChunkPlanDTO, StageManifestDTO,
)
from archive_core.interfaces.transcription import SourceAlignmentDTO
from srt_processing.domain.chunking import ConstituencyAnalyzer, build_source_chunks, chunk_issues, reading_budget
from srt_processing.domain.chunking_policy import chunking_policy
from .ports import Clock, SubtitleArtifactStore


def metadata_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


class SourceChunkingWorkflow:
    def __init__(self, *, artifacts: SubtitleArtifactStore, analyzer: ConstituencyAnalyzer,
                 clock: Clock, output_root: str):
        self.artifacts, self.analyzer, self.clock = artifacts, analyzer, clock
        self.output_root = output_root

    def run(self, command):
        if type(command.overwrite) is not bool:
            raise ValueError("overwrite must be boolean")
        workspace = build_asset_workspace(AssetId(*command.asset_id.split(":")), self.output_root).resolve()
        paths = {key: str(workspace / canonical_filename(kind)) for key, kind in {
            "transcription_manifest": ArtifactType.TRANSCRIPTION_MANIFEST,
            "source_alignment": ArtifactType.SOURCE_ALIGNMENT, "video": ArtifactType.SOURCE_VIDEO,
            "media_boundary": ArtifactType.MEDIA_BOUNDARY, "source_chunks": ArtifactType.SOURCE_CHUNKS,
            "report": ArtifactType.SOURCE_CHUNKING_REPORT, "manifest": ArtifactType.SOURCE_CHUNKING_MANIFEST,
        }.items()}
        if (command.transcription_manifest_path != paths["transcription_manifest"]
                or command.media_boundary_path != paths["media_boundary"]):
            raise ValueError("chunking inputs must use absolute canonical paths")
        evidence = {}

        def read(name):
            data = self.artifacts.read_bytes(paths[name])
            evidence[name] = ArtifactEvidenceDTO(paths[name], len(data), hashlib.sha256(data).hexdigest())
            return json.loads(data)

        transcription = read("transcription_manifest")
        if (transcription.get("schema_version") != "transcription.audio-vad-asr-cache.v1"
                or transcription.get("asset") != dict(zip(("source", "group", "item"), command.asset_id.split(":")))
                or transcription.get("workflow", {}).get("status") != "succeeded"):
            raise ValueError("invalid transcription manifest identity/status")
        alignment = SourceAlignmentDTO.from_dict(read("source_alignment"))
        media = MediaBoundaryDTO.from_dict(read("media_boundary"))
        record = transcription["records"]["source_alignment"]
        if (record["status"] != "succeeded" or Path(record["path"]).resolve() != Path(paths["source_alignment"])
                or record["size_bytes"] != evidence["source_alignment"].size_bytes
                or record["sha256"] != evidence["source_alignment"].sha256):
            raise ValueError("alignment does not match successful transcription record")
        evidence["video"] = ArtifactEvidenceDTO(paths["video"], self.artifacts.size(paths["video"]), self.artifacts.sha256(paths["video"]))
        if (media.video_sha256 != evidence["video"].sha256
                or transcription["records"]["audio"]["provenance"]["video_sha256"] != media.video_sha256):
            raise ValueError("media/transcription source chain mismatch")
        identity = {"policy": chunking_policy(), "analyzer": dict(self.analyzer.identity),
                    "confirmed_protections": [span.to_dict() for span in command.confirmed_protections]}
        output_names = ("source_chunks", "report", "manifest")
        existing = [self.artifacts.exists(paths[name]) for name in output_names]
        if any(existing) and not command.overwrite:
            if not all(existing):
                raise FileExistsError("partial source chunking output set")
            manifest = StageManifestDTO.from_dict(json.loads(self.artifacts.read_bytes(paths["manifest"])))
            if (manifest.stage != "source_chunking" or manifest.asset_id != command.asset_id
                    or manifest.inputs != evidence or metadata_bytes(manifest.to_dict()["identity"]) != metadata_bytes(identity)
                    or set(manifest.outputs) != {"source_chunks", "report"}):
                raise FileExistsError("source chunking identity conflict")
            for name, recorded in manifest.outputs.items():
                if (recorded.path != paths[name] or self.artifacts.size(paths[name]) != recorded.size_bytes
                        or self.artifacts.sha256(paths[name]) != recorded.sha256):
                    raise FileExistsError("source chunking output evidence conflict")
            plan = SourceChunkPlanDTO.from_dict(json.loads(self.artifacts.read_bytes(paths["source_chunks"])))
            plan.validate_against_alignment(alignment)
            if (plan.asset_id != command.asset_id or plan.source_alignment_sha256 != evidence["source_alignment"].sha256 or plan.media != media
                    or metadata_bytes(plan.to_dict()["policy"]) != metadata_bytes(identity["policy"])
                    or metadata_bytes(plan.to_dict()["analyzer"]) != metadata_bytes(identity["analyzer"])):
                raise FileExistsError("source chunking plan identity conflict")
            report = json.loads(self.artifacts.read_bytes(paths["report"]))
            if report != chunking_report(plan):
                raise FileExistsError("source chunking report conflict")
            return "reused", paths, plan, 0
        plan = build_source_chunks(asset_id=command.asset_id, alignment=alignment,
                                   source_alignment_sha256=evidence["source_alignment"].sha256,
                                   media=media, analyzer=self.analyzer,
                                   confirmed_protections=command.confirmed_protections)
        payloads = {"source_chunks": metadata_bytes(plan.to_dict()), "report": metadata_bytes(chunking_report(plan))}
        staged = {}
        for name, data in payloads.items():
            staged[name] = self.artifacts.stage_bytes(paths[name], data)
            if self.artifacts.read_bytes(staged[name]) != data:
                raise ValueError("staged source chunking bytes changed")
        SourceChunkPlanDTO.from_dict(json.loads(self.artifacts.read_bytes(staged["source_chunks"]))).validate_against_alignment(alignment)
        outputs = {name: ArtifactEvidenceDTO(paths[name], len(data), hashlib.sha256(data).hexdigest())
                   for name, data in payloads.items()}
        manifest = StageManifestDTO(stage="source_chunking", asset_id=command.asset_id, inputs=evidence,
                                    outputs=outputs, identity=identity, completed_at=self.clock.now_utc(),
                                    execution={"analyzer_calls": len(plan.analyzed_sentence_ids), "writes": 3})
        for item in evidence.values():
            if self.artifacts.size(item.path) != item.size_bytes or self.artifacts.sha256(item.path) != item.sha256:
                raise ValueError("source chunking input changed before publication")
        for name in payloads:
            self.artifacts.publish(staged[name], paths[name], overwrite=command.overwrite)
        data = metadata_bytes(manifest.to_dict())
        staged_manifest = self.artifacts.stage_bytes(paths["manifest"], data)
        if self.artifacts.read_bytes(staged_manifest) != data:
            raise ValueError("staged source chunking manifest bytes changed")
        self.artifacts.publish(staged_manifest, paths["manifest"], overwrite=command.overwrite)
        return "succeeded", paths, plan, len(plan.analyzed_sentence_ids)


def chunking_report(plan: SourceChunkPlanDTO) -> dict:
    findings = []
    for position, chunk in enumerate(plan.chunks):
        duration = chunk.base_end_ms - chunk.start_ms
        next_start = plan.chunks[position + 1].start_ms if position + 1 < len(plan.chunks) else None
        budget, gap_issues = reading_budget(plan.media, chunk.start_ms, chunk.base_end_ms, next_start)
        expected = chunk_issues(chunk.english_text, duration) + gap_issues
        if chunk.issues != expected or chunk.budget != budget:
            raise ValueError("chunking issues or budget do not match measured metrics")
        for issue in chunk.issues:
            findings.append({"severity": "warning", "code": issue, "chunk_id": chunk.id,
                             "characters": len(chunk.english_text), "duration_ms": duration})
    return {"schema_version": "subtitle.source-chunking-report.v1", "status": "succeeded",
            "chunk_count": len(plan.chunks), "analyzed_sentence_ids": list(plan.analyzed_sentence_ids),
            "findings": findings, "warning_count": len(findings), "semantic_review": "not_run"}
