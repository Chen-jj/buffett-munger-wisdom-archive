"""Read-only gates for every explicit upstream evidence link, not upstream algorithms."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Mapping

from archive_core.application import build_asset_workspace
from archive_core.domain import ArtifactType, AssetId, canonical_filename
from archive_core.interfaces import (
    RenderArtifactEvidenceDTO, RenderMediaDTO, SourceAlignmentDTO, StructuredTranscriptDTO,
    SrtProcessingManifestDTO, SrtProcessingReportDTO, SubtitlePlanDTO,
    TranslationManifestDTO, TranslationResultDTO, is_combining_mark, is_layout_whitespace,
)

from .ports import MediaProbe, RenderingArtifactStore


class RenderingInputError(ValueError):
    category = "input_invalid"


@dataclass(frozen=True)
class FileFingerprint:
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class ValidatedRenderInputs:
    asset: AssetId
    workspace: Path
    source_plan: SubtitlePlanDTO
    srt_manifest: SrtProcessingManifestDTO
    srt_report: SrtProcessingReportDTO
    alignment: SourceAlignmentDTO
    translation: TranslationResultDTO
    evidence: Mapping[str, RenderArtifactEvidenceDTO]
    media: RenderMediaDTO
    fingerprints: Mapping[str, FileFingerprint]

    def __post_init__(self) -> None:
        for name in ("evidence", "fingerprints"):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))

    def verify_unchanged(self, artifacts: RenderingArtifactStore) -> None:
        for path, expected in self.fingerprints.items():
            if fingerprint(artifacts, path) != expected:
                raise RenderingInputError("Upstream evidence changed during rendering.")


def canonical_path(value: str) -> str:
    if not isinstance(value, str) or not value or ".." in Path(value).parts or any(ord(c) < 32 for c in value):
        raise ValueError("path must be traversal-free and contain no controls")
    # Deliberately lexical: resolving final symlinks would reject the read-only v3 inputs.
    return os.path.abspath(value)


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def parse_json(data: bytes) -> Mapping[str, Any]:
    def reject_constant(value: str) -> None:
        raise ValueError("non-finite JSON number")
    def finite_float(value: str) -> float:
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("non-finite JSON number")
        return number
    result = json.loads(data.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=reject_constant, parse_float=finite_float)
    if not isinstance(result, dict):
        raise ValueError("JSON document must be an object")
    return result


def fingerprint(store: RenderingArtifactStore, path: str) -> FileFingerprint:
    size, digest = store.size(path), store.sha256(path)
    if type(size) is not int or size <= 0 or not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ValueError("file evidence must be nonempty with a SHA-256")
    return FileFingerprint(size, digest)


def _keys(value: object, fields: tuple[str, ...]) -> Mapping[str, Any]:
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError("upstream envelope has unexpected fields")
    return value


def _dto(dtype: type, data: Mapping[str, Any]):
    value = dtype.from_dict(data)
    if value.to_dict() != data:
        raise ValueError("public DTO has unrecognized or noncanonical fields")
    return value


def validate_english_budget(text: str, parameters: Mapping[str, Any]) -> None:
    """Frozen visible-unit count and greedy word packing; no SRT projection or DP."""
    def units(word: str) -> int:
        return sum(not is_layout_whitespace(char) and not is_combining_mark(char)
                   and char != "\u200d" and not 0x1F3FB <= ord(char) <= 0x1F3FF for char in word)
    words, start = [], 0
    for pos, char in enumerate(text):
        if is_layout_whitespace(char):
            if start < pos:
                words.append(text[start:pos])
            start = pos + 1
    if start < len(text):
        words.append(text[start:])
    capacity = parameters.get("english_line_capacity", parameters["english_capacity"])
    maximum = parameters.get("english_max_lines", 1)
    line, lines = 0, 1
    for word in words:
        count = units(word)
        if count > capacity:
            raise ValueError("English word exceeds the upstream line budget")
        if line + count > capacity:
            lines += 1
            line = 0
        line += count
    if lines > maximum:
        raise ValueError("English text cannot pack into the upstream word-line budget")


def load_render_inputs(*, asset_id: str, srt_processing_manifest_path: str,
                       artifacts: RenderingArtifactStore, probe: MediaProbe,
                       output_root: str) -> ValidatedRenderInputs:
    try:
        if not isinstance(asset_id, str) or len(asset_id.split(":")) != 3:
            raise ValueError("asset_id must use source:group:item")
        asset = AssetId(*asset_id.split(":"))
        workspace = build_asset_workspace(asset, canonical_path(output_root))
        path = lambda kind: str(workspace / canonical_filename(kind))
        manifest_path = path(ArtifactType.SRT_PROCESSING_MANIFEST)
        if canonical_path(srt_processing_manifest_path) != manifest_path:
            raise ValueError("SRT manifest path is not canonical")
        snapshots: dict[str, FileFingerprint] = {}

        def check(file_path: str, expected=None) -> FileFingerprint:
            actual = fingerprint(artifacts, file_path)
            if expected is not None and (actual.size_bytes != expected.size_bytes or actual.sha256 != expected.sha256):
                raise ValueError("file evidence does not match upstream manifest")
            if file_path in snapshots and snapshots[file_path] != actual:
                raise ValueError("input changed during validation")
            snapshots[file_path] = actual
            return actual

        def read(file_path: str) -> Mapping[str, Any]:
            data = artifacts.read_bytes(file_path)
            actual = FileFingerprint(len(data), hashlib.sha256(data).hexdigest())
            check(file_path)
            if actual != snapshots[file_path]:
                raise ValueError("input changed during read")
            return parse_json(data)

        manifest = _dto(SrtProcessingManifestDTO, read(manifest_path))
        if manifest.asset_id != asset_id:
            raise ValueError("SRT asset identity differs")
        for evidence in (*manifest.inputs.values(), *manifest.outputs.values()):
            check(str(workspace / evidence.path), evidence)
        source = _dto(SubtitlePlanDTO, read(path(ArtifactType.SUBTITLE_PLAN)))
        alignment = _dto(SourceAlignmentDTO, read(path(ArtifactType.SOURCE_ALIGNMENT)))
        translation = _dto(TranslationResultDTO, read(path(ArtifactType.TRANSLATION_RESULT)))
        translation_manifest = _dto(TranslationManifestDTO, read(path(ArtifactType.TRANSLATION_MANIFEST)))
        srt_report = _dto(SrtProcessingReportDTO, read(path(ArtifactType.SRT_PROCESSING_REPORT)))
        translation.validate_against_alignment(alignment)
        source.validate_against_inputs(alignment, translation)
        manifest.validate_against_plan(source)
        if translation_manifest.asset_id != asset_id or translation_manifest.input.sha256 != source.source_alignment_sha256:
            raise ValueError("translation manifest source identity differs")
        result = snapshots[path(ArtifactType.TRANSLATION_RESULT)]
        if (translation_manifest.output.size_bytes, translation_manifest.output.sha256) != (result.size_bytes, result.sha256):
            raise ValueError("translation output evidence differs")
        if (srt_report.asset_id != asset_id or srt_report.status != "succeeded"
                or srt_report.summary != manifest.summary):
            raise ValueError("SRT report is not the matching success report")
        for cue in source.cues:
            validate_english_budget(cue.english_text, manifest.profile.parameters)

        transcription = read(path(ArtifactType.TRANSCRIPTION_MANIFEST))
        _keys(transcription, ("schema_version", "asset", "records", "workflow"))
        if transcription["schema_version"] != "transcription.audio-vad-asr-cache.v1" or transcription["asset"] != {"source": asset.source, "group": asset.group, "item": asset.item}:
            raise ValueError("transcription manifest identity differs")
        workflow = _keys(transcription["workflow"], ("status", "stage_order", "completed_stages", "cache_hits", "inputs", "qa_policy", "summary"))
        stages = ["audio_vad_asr", "forced_alignment", "official_transcript_fusion", "sentence_boundaries"]
        if workflow["status"] != "succeeded" or workflow["stage_order"] != stages or workflow["completed_stages"] != stages:
            raise ValueError("transcription workflow did not completely succeed")
        kinds = {"audio": ArtifactType.SOURCE_AUDIO, "vad": ArtifactType.VAD,
                 "raw_asr": ArtifactType.RAW_ASR, "aligned_asr": ArtifactType.ALIGNED_ASR,
                 "transcript_fusion": ArtifactType.TRANSCRIPT_FUSION, "source_alignment": ArtifactType.SOURCE_ALIGNMENT,
                 "transcription_log": ArtifactType.TRANSCRIPTION_LOG, "transcription_report": ArtifactType.TRANSCRIPTION_REPORT}
        records = _keys(transcription["records"], tuple(kinds))
        if (not isinstance(workflow["cache_hits"], list) or len(set(workflow["cache_hits"])) != len(workflow["cache_hits"])
                or any(name not in kinds for name in workflow["cache_hits"])):
            raise ValueError("invalid transcription cache hits")
        for name, kind in kinds.items():
            record = _keys(records[name], ("path", "size_bytes", "sha256", "cache_key", "status", "provenance"))
            if (record["status"] != "succeeded" or canonical_path(record["path"]) != path(kind)
                    or not isinstance(record["cache_key"], str) or re.fullmatch(r"[0-9a-f]{64}", record["cache_key"]) is None
                    or not isinstance(record["provenance"], dict) or type(record["size_bytes"]) is not int):
                raise ValueError("invalid transcription record")
            actual = check(path(kind))
            if actual != FileFingerprint(record["size_bytes"], record["sha256"]):
                raise ValueError("transcription record evidence differs")
        duration = alignment.audio_duration_ms
        audio_provenance = records["audio"]["provenance"]
        if type(audio_provenance.get("duration_ms")) is not int or audio_provenance["duration_ms"] != duration or audio_provenance.get("video_sha256") != source.video_sha256:
            raise ValueError("audio provenance differs from source")
        envelopes = {
            "vad": ("transcription.vad.v1", ("schema_version", "audio_sha256", "audio_duration_ms", "provider", "config", "regions", "chunks", "cache_key")),
            "raw_asr": ("transcription.raw-asr.v1", ("schema_version", "audio_sha256", "audio_duration_ms", "vad_cache_key", "language", "task", "profile", "provider", "config", "segments", "cache_key")),
            "aligned_asr": ("transcription.aligned-asr.v1", ("schema_version", "language", "audio_sha256", "raw_asr_sha256", "audio_duration_ms", "provider", "config", "words", "cache_key")),
            "transcript_fusion": ("transcription.transcript-fusion.v1", ("schema_version", "audio_duration_ms", "aligned_asr_sha256", "chapters_sha256", "mode", "normalization", "matching", "official_aligner", "official_alignment_config", "official_tokens", "ignored_content", "words", "excluded_official", "local_validations", "cache_key")),
        }
        cached = {}
        for name, (schema, fields) in envelopes.items():
            data = _keys(read(path(kinds[name])), fields)
            if (data["schema_version"] != schema or data["cache_key"] != records[name]["cache_key"]
                    or type(data["audio_duration_ms"]) is not int or data["audio_duration_ms"] != duration):
                raise ValueError("transcription cache envelope differs")
            if name != "transcript_fusion":
                if data["audio_sha256"] != records["audio"]["sha256"] or data["provider"] != records[name]["provenance"].get("provider") or data["config"] != records[name]["provenance"].get("config"):
                    raise ValueError("transcription cache audio/provider provenance differs")
            cached[name] = data
        if cached["raw_asr"]["vad_cache_key"] != records["vad"]["cache_key"] or cached["aligned_asr"]["raw_asr_sha256"] != records["raw_asr"]["sha256"]:
            raise ValueError("ASR cache links differ")
        fusion = cached["transcript_fusion"]
        if (fusion["aligned_asr_sha256"] != records["aligned_asr"]["sha256"]
                or records["transcript_fusion"]["provenance"].get("aligned_asr_sha256") != fusion["aligned_asr_sha256"]
                or records["source_alignment"]["provenance"].get("sentence_input_sha256") != records["transcript_fusion"]["sha256"]):
            raise ValueError("fusion/alignment provenance differs")
        transcription_inputs = _keys(workflow["inputs"], ("chapters_sha256", "download_manifest_path"))
        chapters_sha = transcription_inputs["chapters_sha256"]
        if (fusion["chapters_sha256"] != chapters_sha or records["transcript_fusion"]["provenance"].get("chapters_sha256") != chapters_sha
                or records["source_alignment"]["provenance"].get("chapter_input_sha256") != chapters_sha):
            raise ValueError("chapter provenance differs")
        if chapters_sha is not None:
            _dto(StructuredTranscriptDTO, read(path(ArtifactType.CHAPTERS)))
            if snapshots[path(ArtifactType.CHAPTERS)].sha256 != chapters_sha:
                raise ValueError("chapter fingerprint differs")
        report = _keys(read(path(ArtifactType.TRANSCRIPTION_REPORT)), ("schema_version", "asset_id", "status", "counts", "findings", "qa"))
        if (report["schema_version"] != "transcription.report.v1" or report["asset_id"] != asset_id or report["status"] != "succeeded"
                or report["counts"] != workflow["summary"] or not isinstance(report["counts"], dict)
                or any(type(count) is not int or count < 0 for count in report["counts"].values()) or report["counts"].get("error") != 0
                or not isinstance(report["findings"], list) or any(not isinstance(item, dict) or item.get("severity") == "ERROR" for item in report["findings"])):
            raise ValueError("transcription report did not match successful workflow")
        qa = report["qa"]
        if not isinstance(qa, list) or not qa or any(_keys(item, ("name", "passed", "detail"))["passed"] is not True for item in qa):
            raise ValueError("transcription report QA failed")
        policy = _keys(workflow["qa_policy"], ("version", "max_interpolated_word_ratio", "require_non_empty_alignment"))
        if (policy["version"] != "transcription-qa.v1" or policy["require_non_empty_alignment"] is not True
                or type(policy["max_interpolated_word_ratio"]) not in (int, float) or not 0 <= policy["max_interpolated_word_ratio"] <= 1
                or not alignment.words or report["counts"].get("aligned") != len(alignment.words)
                or report["counts"].get("interpolated", len(alignment.words) + 1) > len(alignment.words) * policy["max_interpolated_word_ratio"]):
            raise ValueError("transcription QA summary differs")
        download_path = transcription_inputs["download_manifest_path"]
        if download_path is not None:
            download_path = canonical_path(download_path)
            if Path(download_path).name != "download_manifest.json":
                raise ValueError("download manifest filename differs")
            download = _keys(read(download_path), ("schema_version", "asset", "media", "artifact", "download"))
            artifact = _keys(download["artifact"], ("path", "size_bytes", "checksum"))
            checksum = _keys(artifact["checksum"], ("algorithm", "value"))
            original_video = str(Path(download_path).parent / canonical_filename(ArtifactType.SOURCE_VIDEO))
            if (download["schema_version"] != "media-download.manifest.1" or download["asset"] != transcription["asset"]
                    or not isinstance(download["download"], dict) or download["download"].get("status") not in ("downloaded", "reused")
                    or canonical_path(artifact["path"]) != original_video or checksum["algorithm"] != "sha256"
                    or type(artifact["size_bytes"]) is not int):
                raise ValueError("download identity differs")
            if check(original_video) != FileFingerprint(artifact["size_bytes"], checksum["value"]) or snapshots[original_video] != snapshots[path(ArtifactType.SOURCE_VIDEO)]:
                raise ValueError("download source video differs")
        media = probe.probe(path(ArtifactType.SOURCE_VIDEO))
        if not isinstance(media, RenderMediaDTO):
            raise ValueError("probe did not return public media DTO")
        video = media.video
        if (source.media.video_duration_ms != media.duration_us // 1000 or source.media.audio_duration_ms != duration
                or Fraction(source.media.fps_numerator, source.media.fps_denominator) != Fraction(video.fps_numerator, video.fps_denominator)
                or max(cue.end_ms for cue in source.cues) * 1000 > video.duration_us):
            raise ValueError("actual source media differs from subtitle media")
        direct = {}
        for name, kind in (("srt_processing_manifest", ArtifactType.SRT_PROCESSING_MANIFEST), ("subtitle_plan", ArtifactType.SUBTITLE_PLAN), ("video", ArtifactType.SOURCE_VIDEO)):
            fp = snapshots[path(kind)]
            direct[name] = RenderArtifactEvidenceDTO(canonical_filename(kind), fp.size_bytes, fp.sha256)
        result = ValidatedRenderInputs(asset, workspace, source, manifest, srt_report, alignment,
                                       translation, direct, media, snapshots)
        result.verify_unchanged(artifacts)
        return result
    except RenderingInputError:
        raise
    except Exception as error:
        raise RenderingInputError(str(error)) from error
