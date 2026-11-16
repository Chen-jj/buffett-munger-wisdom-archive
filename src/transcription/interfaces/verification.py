"""Read-only canonical transcription evidence verification for pipeline planning."""

from pathlib import Path

from archive_core.application import build_asset_workspace
from archive_core.domain import ArtifactType, canonical_filename
from archive_core.interfaces import SourceAlignmentDTO
from infrastructure.infrastructure.artifacts import evidence, read_json, verify_evidence
from archive_core.interfaces.bilingual import ArtifactEvidenceDTO


def verify_transcription(command, *, output_root="output"):
    from transcription.application.audio_asr import AudioVadAsrCacheManifest
    from transcription.application.observability import TranscriptionReport

    workspace = build_asset_workspace(command.asset_id, Path(output_root).resolve())
    manifest_path = workspace / "transcription_manifest.json"
    manifest = AudioVadAsrCacheManifest.from_dict(read_json(manifest_path))
    if manifest.asset_id != command.asset_id or manifest.workflow is None or manifest.workflow.get("status") != "succeeded":
        raise ValueError("transcription is not a completed matching workflow")
    required = {"audio", "vad", "raw_asr", "aligned_asr", "source_alignment", "transcription_log", "transcription_report"}
    if command.chapters_sha256 is not None:
        required.add("transcript_fusion")
    if not required <= set(manifest.records):
        raise ValueError("transcription cache records incomplete")
    names = {"audio": ArtifactType.SOURCE_AUDIO, "vad": ArtifactType.VAD, "raw_asr": ArtifactType.RAW_ASR,
             "aligned_asr": ArtifactType.ALIGNED_ASR, "transcript_fusion": ArtifactType.TRANSCRIPT_FUSION,
             "source_alignment": ArtifactType.SOURCE_ALIGNMENT, "transcription_log": ArtifactType.TRANSCRIPTION_LOG,
             "transcription_report": ArtifactType.TRANSCRIPTION_REPORT}
    for name, record in manifest.records.items():
        if name not in names or record.status != "succeeded":
            raise ValueError("unknown or unsuccessful transcription record")
        verify_evidence(ArtifactEvidenceDTO(record.path, record.size_bytes, record.sha256), workspace / canonical_filename(names[name]))
        if name not in {"audio", "transcription_log"}:
            read_json(record.path)
    report = TranscriptionReport.from_dict(read_json(workspace / "transcription_report.json"))
    if report.asset_id != command.asset_id.value or report.status.value != "succeeded" or dict(report.counts) != manifest.workflow.get("summary"):
        raise ValueError("transcription report does not match successful workflow")
    if manifest.workflow.get("inputs") != {"download_manifest_path": command.download_manifest_path, "chapters_sha256": command.chapters_sha256}:
        raise ValueError("transcription request evidence changed")
    alignment = SourceAlignmentDTO.from_dict(read_json(workspace / "source_alignment.json"))
    video = evidence(workspace / "video.mp4")
    download = read_json(command.download_manifest_path)
    if download["artifact"]["checksum"]["value"] != video.sha256 or download["artifact"]["size_bytes"] != video.size_bytes:
        raise ValueError("transcription source video changed")
    provenance = manifest.records["audio"].provenance
    if provenance.get("video_sha256") != video.sha256:
        raise ValueError("transcription audio source chain changed")
    if command.chapters_sha256 is not None and evidence(workspace / "chapters.json").sha256 != command.chapters_sha256:
        raise ValueError("transcription chapter evidence changed")
    return alignment
