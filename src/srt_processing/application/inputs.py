"""Read-only validation of the single current final-draft provenance chain."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Mapping

from archive_core.application import build_asset_workspace
from archive_core.domain import AssetId, ArtifactType, canonical_filename
from archive_core.interfaces.bilingual import (
    ArtifactEvidenceDTO, ChunkTranslationResultDTO, FinalBilingualDraftDTO,
    MediaBoundaryDTO, SourceChunkPlanDTO, StageManifestDTO,
)
from archive_core.interfaces.transcription import SourceAlignmentDTO
from .ports import SubtitleArtifactStore


class SubtitleInputError(ValueError):
    category = "input_invalid"


@dataclass(frozen=True)
class ValidatedSubtitleInputs:
    workspace: Path
    draft: FinalBilingualDraftDTO
    alignment: SourceAlignmentDTO
    chunks: SourceChunkPlanDTO
    translation: ChunkTranslationResultDTO
    evidence: Mapping[str, ArtifactEvidenceDTO]


def load_subtitle_inputs(*, asset_id: str, bilingual_postprocessing_manifest_path: str,
                         artifacts: SubtitleArtifactStore, output_root: str) -> ValidatedSubtitleInputs:
    try:
        workspace = build_asset_workspace(AssetId(*asset_id.split(":")), output_root).resolve()
        kinds = {
            "transcription_manifest": ArtifactType.TRANSCRIPTION_MANIFEST,
            "source_alignment": ArtifactType.SOURCE_ALIGNMENT,
            "source_chunks": ArtifactType.SOURCE_CHUNKS,
            "source_chunking_manifest": ArtifactType.SOURCE_CHUNKING_MANIFEST,
            "translation_result": ArtifactType.TRANSLATION_RESULT,
            "translation_manifest": ArtifactType.TRANSLATION_MANIFEST,
            "final_bilingual_draft": ArtifactType.FINAL_BILINGUAL_DRAFT,
            "bilingual_postprocessing_manifest": ArtifactType.BILINGUAL_POSTPROCESSING_MANIFEST,
            "media_boundary": ArtifactType.MEDIA_BOUNDARY,
            "video": ArtifactType.SOURCE_VIDEO,
        }
        paths = {name: str(workspace / canonical_filename(kind)) for name, kind in kinds.items()}
        if bilingual_postprocessing_manifest_path != paths["bilingual_postprocessing_manifest"]:
            raise ValueError("postprocessing manifest path is not absolute canonical path")
        evidence = {}
        parsed = {}
        for name, path in paths.items():
            evidence[name] = ArtifactEvidenceDTO(path, artifacts.size(path), artifacts.sha256(path))
            if name != "video":
                raw = artifacts.read_bytes(path)
                if (len(raw), hashlib.sha256(raw).hexdigest()) != (evidence[name].size_bytes, evidence[name].sha256):
                    raise ValueError("input changed during read")
                parsed[name] = json.loads(raw)
        for name, stage in (("source_chunking_manifest", "source_chunking"),
                            ("translation_manifest", "translation"),
                            ("bilingual_postprocessing_manifest", "bilingual_postprocessing")):
            manifest = StageManifestDTO.from_dict(parsed[name])
            if manifest.asset_id != asset_id or manifest.stage != stage:
                raise ValueError("stage manifest asset/stage mismatch")
            for recorded in (*manifest.inputs.values(), *manifest.outputs.values()):
                target = Path(recorded.path)
                if target.parent != workspace or target.resolve() != target:
                    raise ValueError("stage evidence escapes workspace")
                if artifacts.size(recorded.path) != recorded.size_bytes or artifacts.sha256(recorded.path) != recorded.sha256:
                    raise ValueError("stage evidence mismatch")
            required_output = {"source_chunking": "source_chunks", "translation": "translation_result",
                               "bilingual_postprocessing": "final_bilingual_draft"}[stage]
            if manifest.outputs.get(required_output) != evidence[required_output]:
                raise ValueError("stage manifest does not bind its canonical result")
            for upstream in {"source_chunking": ("source_alignment",),
                             "translation": ("source_alignment", "source_chunks"),
                             "bilingual_postprocessing": ("source_alignment", "source_chunks", "translation_result")}[stage]:
                if manifest.inputs.get(upstream) != evidence[upstream]:
                    raise ValueError("stage missing upstream source binding")
        transcription = parsed["transcription_manifest"]
        if (transcription.get("schema_version") != "transcription.audio-vad-asr-cache.v1"
                or transcription.get("asset") != dict(zip(("source", "group", "item"), asset_id.split(":")))
                or transcription.get("workflow", {}).get("status") != "succeeded"):
            raise ValueError("invalid transcription success identity")
        record = transcription["records"]["source_alignment"]
        if (Path(record["path"]).resolve() != Path(paths["source_alignment"]) or record["status"] != "succeeded"
                or (record["size_bytes"], record["sha256"]) != (evidence["source_alignment"].size_bytes, evidence["source_alignment"].sha256)
                or transcription["records"]["audio"]["provenance"]["video_sha256"] != evidence["video"].sha256):
            raise ValueError("transcription source evidence differs")
        alignment = SourceAlignmentDTO.from_dict(parsed["source_alignment"])
        chunks = SourceChunkPlanDTO.from_dict(parsed["source_chunks"])
        translation = ChunkTranslationResultDTO.from_dict(parsed["translation_result"])
        draft = FinalBilingualDraftDTO.from_dict(parsed["final_bilingual_draft"])
        media = MediaBoundaryDTO.from_dict(parsed["media_boundary"])
        draft.validate_against_inputs(alignment, chunks, translation)
        if (draft.asset_id != asset_id or draft.source_alignment_sha256 != evidence["source_alignment"].sha256
                or draft.source_chunks_sha256 != evidence["source_chunks"].sha256
                or draft.translation_result_sha256 != evidence["translation_result"].sha256
                or media != draft.media or media != chunks.media or media.video_sha256 != evidence["video"].sha256):
            raise ValueError("final draft source fingerprint/media mismatch")
        return ValidatedSubtitleInputs(workspace, draft, alignment, chunks, translation, evidence)
    except Exception as error:
        raise SubtitleInputError(str(error)) from error
