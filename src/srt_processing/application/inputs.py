"""Independent upstream evidence gates for bilingual subtitle planning."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Mapping

from archive_core.application import build_asset_workspace
from archive_core.domain import ArtifactType, AssetId, canonical_filename
from archive_core.interfaces import (
    SourceAlignmentDTO,
    SubtitleArtifactEvidenceDTO,
    SubtitleMediaDTO,
    SubtitleProbeDTO,
    TranslationManifestDTO,
    TranslationResultDTO,
)

from .ports import MediaProbe, MediaProbeResult, SubtitleArtifactStore


TRANSCRIPTION_MANIFEST_SCHEMA = "transcription.audio-vad-asr-cache.v1"
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_INPUT_TYPES = {
    "transcription_manifest": ArtifactType.TRANSCRIPTION_MANIFEST,
    "source_alignment": ArtifactType.SOURCE_ALIGNMENT,
    "translation_manifest": ArtifactType.TRANSLATION_MANIFEST,
    "translation_result": ArtifactType.TRANSLATION_RESULT,
    "video": ArtifactType.SOURCE_VIDEO,
}


class SubtitleInputError(RuntimeError):
    category = "input_invalid"


class SubtitleMediaError(SubtitleInputError):
    category = "media_invalid"


@dataclass(frozen=True)
class ValidatedSubtitleInputs:
    asset: AssetId
    workspace: Path
    alignment: SourceAlignmentDTO
    translation: TranslationResultDTO
    evidence: Mapping[str, SubtitleArtifactEvidenceDTO]
    media: SubtitleMediaDTO
    probe: SubtitleProbeDTO

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence", MappingProxyType(dict(self.evidence)))


def load_subtitle_inputs(
    *,
    asset_id: str,
    transcription_manifest_path: str,
    translation_manifest_path: str,
    artifacts: SubtitleArtifactStore,
    probe: MediaProbe,
    output_root: str = "output",
) -> ValidatedSubtitleInputs:
    """Validate both content chains before allowing the canonical video to be probed."""

    try:
        if not isinstance(asset_id, str) or len(asset_id.split(":")) != 3:
            raise ValueError("asset_id must use source:group:item")
        asset = AssetId(*asset_id.split(":"))
        workspace = build_asset_workspace(asset, output_root)
        paths = {
            key: str(workspace / canonical_filename(kind))
            for key, kind in _INPUT_TYPES.items()
        }
        for name, supplied in (
            ("transcription_manifest", transcription_manifest_path),
            ("translation_manifest", translation_manifest_path),
        ):
            if not isinstance(supplied, str) or Path(supplied) != Path(paths[name]):
                raise ValueError(f"{name} path is not canonical")

        evidence: dict[str, SubtitleArtifactEvidenceDTO] = {}

        def read_json(name: str) -> Mapping[str, Any]:
            data = artifacts.read_bytes(paths[name])
            evidence[name] = SubtitleArtifactEvidenceDTO(
                path=canonical_filename(_INPUT_TYPES[name]),
                size_bytes=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
            )
            parsed = json.loads(data.decode("utf-8"))
            if not isinstance(parsed, Mapping):
                raise ValueError(f"{name} must be a JSON object")
            return parsed

        transcription = read_json("transcription_manifest")
        _keys(transcription, {"schema_version", "asset", "records", "workflow"},
              "transcription manifest")
        if transcription["schema_version"] != TRANSCRIPTION_MANIFEST_SCHEMA:
            raise ValueError("unsupported transcription manifest schema")
        manifest_asset = _keys(transcription["asset"], {"source", "group", "item"},
                               "transcription asset")
        if AssetId(**manifest_asset) != asset:
            raise ValueError("transcription asset identity does not match")
        workflow = _mapping(transcription["workflow"], "transcription workflow")
        if workflow.get("status") != "succeeded":
            raise ValueError("transcription workflow did not succeed")
        records = _mapping(transcription["records"], "transcription records")
        for name, record in records.items():
            if not isinstance(name, str) or not name:
                raise ValueError("transcription record name is invalid")
            _validate_record(record)
        alignment_record = _successful_record(records, "source_alignment", paths["source_alignment"])
        audio_path = str(workspace / canonical_filename(ArtifactType.SOURCE_AUDIO))
        audio_record = _successful_record(records, "audio", audio_path)

        alignment_data = read_json("source_alignment")
        _validate_evidence(evidence["source_alignment"], alignment_record, "source_alignment")
        _strict_alignment_fields(alignment_data)
        alignment = SourceAlignmentDTO.from_dict(alignment_data)
        if not alignment.words or not alignment.sentences:
            raise ValueError("source alignment must contain words and sentences")

        translation_manifest = TranslationManifestDTO.from_dict(read_json("translation_manifest"))
        if translation_manifest.asset_id != asset.value:
            raise ValueError("translation asset identity does not match")
        translation_data = read_json("translation_result")
        _validate_evidence(evidence["translation_result"],
                           translation_manifest.output.to_dict(), "translation_result")
        translation = TranslationResultDTO.from_dict(translation_data)
        translation.validate_against_alignment(alignment)
        alignment_sha256 = evidence["source_alignment"].sha256
        if translation_manifest.input.sha256 != alignment_sha256:
            raise ValueError("translation manifest references a different source alignment")
        if translation.source_alignment_sha256 != alignment_sha256:
            raise ValueError("translation result references a different source alignment")

        evidence["video"] = SubtitleArtifactEvidenceDTO(
            path=canonical_filename(ArtifactType.SOURCE_VIDEO),
            size_bytes=artifacts.size(paths["video"]),
            sha256=artifacts.sha256(paths["video"]),
        )
        recorded_video_sha256 = audio_record["provenance"].get("video_sha256")
        if (not isinstance(recorded_video_sha256, str)
                or _HASH_RE.fullmatch(recorded_video_sha256) is None):
            raise ValueError("audio provenance video checksum is invalid")
        if recorded_video_sha256 != evidence["video"].sha256:
            raise ValueError("video checksum does not match transcription audio provenance")
    except SubtitleInputError:
        raise
    except Exception as error:
        raise SubtitleInputError(str(error)) from error

    try:
        probed = probe.probe(paths["video"])
        if not isinstance(probed, MediaProbeResult):
            raise ValueError("media probe did not return a MediaProbeResult")
        media = SubtitleMediaDTO(
            video_duration_ms=probed.video_duration_ms,
            audio_duration_ms=alignment.audio_duration_ms,
            usable_duration_ms=min(probed.video_duration_ms, alignment.audio_duration_ms),
            fps_numerator=probed.fps_numerator,
            fps_denominator=probed.fps_denominator,
            gap_threshold_ms=(2000 * probed.fps_denominator + probed.fps_numerator - 1)
            // probed.fps_numerator,
        )
        if any(word.end_ms > media.usable_duration_ms for word in alignment.words):
            raise ValueError("source word exceeds usable media duration")
        probe_identity = SubtitleProbeDTO(ffprobe_version=probed.tool_version)
    except Exception as error:
        raise SubtitleMediaError(str(error)) from error

    return ValidatedSubtitleInputs(asset, workspace, alignment, translation, evidence,
                                   media, probe_identity)


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _keys(value: object, expected: set[str], name: str) -> Mapping[str, Any]:
    data = _mapping(value, name)
    if set(data) != expected:
        raise ValueError(f"{name} fields are invalid")
    return data


def _validate_record(value: object) -> None:
    record = _keys(value, {"path", "size_bytes", "sha256", "cache_key", "status", "provenance"},
                   "transcription record")
    for field in ("path", "cache_key", "status"):
        if not isinstance(record[field], str) or not record[field].strip():
            raise ValueError(f"transcription record {field} is invalid")
    if type(record["size_bytes"]) is not int or record["size_bytes"] <= 0:
        raise ValueError("transcription record size is invalid")
    if not isinstance(record["sha256"], str) or _HASH_RE.fullmatch(record["sha256"]) is None:
        raise ValueError("transcription record checksum is invalid")
    _mapping(record["provenance"], "transcription record provenance")


def _successful_record(records: Mapping[str, Any], name: str, path: str) -> Mapping[str, Any]:
    record = _mapping(records.get(name), f"transcription {name} record")
    if record["status"] != "succeeded":
        raise ValueError(f"transcription {name} record did not succeed")
    if Path(record["path"]) != Path(path):
        raise ValueError(f"transcription {name} path is not canonical")
    return record


def _validate_evidence(actual: SubtitleArtifactEvidenceDTO, recorded: Mapping[str, Any], name: str) -> None:
    if actual.size_bytes != recorded["size_bytes"]:
        raise ValueError(f"{name} size does not match manifest")
    if actual.sha256 != recorded["sha256"]:
        raise ValueError(f"{name} checksum does not match manifest")


def _strict_alignment_fields(data: Mapping[str, Any]) -> None:
    _keys(data, {"schema_version", "language", "audio_duration_ms", "words", "sentences", "sections"},
          "source alignment")
    fields = {
        "words": {"id", "text", "start_ms", "end_ms", "asr_word_ids", "official_token_ids",
                  "match_type", "text_source", "timing_source"},
        "sentences": {"id", "first_word_id", "last_word_id", "start_ms", "end_ms", "text",
                      "speaker_label", "text_source", "boundary_source", "boundary_status"},
        "sections": {"id", "title", "first_sentence_id", "last_sentence_id"},
    }
    for name, expected in fields.items():
        if not isinstance(data[name], list):
            raise ValueError(f"source alignment {name} must be an array")
        for item in data[name]:
            _keys(item, expected, f"source alignment {name} item")
