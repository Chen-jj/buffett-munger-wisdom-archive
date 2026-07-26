"""Artifact naming contracts shared by pipeline modules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .identifiers import AssetId, SessionId


class ArtifactType(str, Enum):
    TRANSCRIPT = "transcript"
    CHAPTERS = "chapters"
    SOURCE_META = "source_meta"
    SOURCE_VIDEO = "source_video"
    SOURCE_AUDIO = "source_audio"
    ENGLISH_SRT = "english_srt"
    CHINESE_SRT = "chinese_srt"
    RENDERED_VIDEO = "rendered_video"
    MANIFEST = "manifest"
    PROVENANCE = "provenance"


CANONICAL_FILENAMES: dict[ArtifactType, str] = {
    ArtifactType.TRANSCRIPT: "transcript.txt",
    ArtifactType.CHAPTERS: "chapters.json",
    ArtifactType.SOURCE_META: "meta.json",
    ArtifactType.SOURCE_VIDEO: "video.mp4",
    ArtifactType.SOURCE_AUDIO: "audio.wav",
    ArtifactType.ENGLISH_SRT: "english.srt",
    ArtifactType.CHINESE_SRT: "chinese.srt",
    ArtifactType.RENDERED_VIDEO: "video_中文字幕.mp4",
    ArtifactType.MANIFEST: "manifest.json",
    ArtifactType.PROVENANCE: "provenance.json",
}


def canonical_filename(artifact_type: ArtifactType) -> str:
    return CANONICAL_FILENAMES[artifact_type]


def canonical_artifact_path(
    asset_or_session_id: AssetId | SessionId, artifact_type: ArtifactType
) -> str:
    if isinstance(asset_or_session_id, SessionId):
        workspace_path = asset_or_session_id.workspace_path
    else:
        parts = [
            asset_or_session_id.source,
            asset_or_session_id.group,
            asset_or_session_id.item,
        ]
        workspace_path = "_".join(part for part in parts if part)
    return f"{workspace_path}/{canonical_filename(artifact_type)}"


@dataclass(frozen=True)
class ArtifactRef:
    """Reference to one artifact path under a session workspace."""

    asset_id: AssetId
    artifact_type: ArtifactType
    relative_path: str

    def __post_init__(self) -> None:
        if self.relative_path.startswith("/") or ".." in self.relative_path.split("/"):
            raise ValueError("relative_path must stay within the archive workspace")

    @classmethod
    def canonical(
        cls, asset_id: AssetId, artifact_type: ArtifactType
    ) -> "ArtifactRef":
        return cls(
            asset_id=asset_id,
            artifact_type=artifact_type,
            relative_path=canonical_artifact_path(asset_id, artifact_type),
        )


@dataclass(frozen=True)
class TimeRange:
    start_seconds: float
    end_seconds: float

    def __post_init__(self) -> None:
        if self.start_seconds < 0:
            raise ValueError("start_seconds must be non-negative")
        if self.end_seconds < self.start_seconds:
            raise ValueError("end_seconds must be greater than or equal to start_seconds")
