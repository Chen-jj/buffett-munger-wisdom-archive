"""Resumable application service for canonical audio, VAD, and raw ASR."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from archive_core.application import build_asset_workspace
from archive_core.domain import AssetId, ArtifactType, canonical_filename
from transcription.domain import (
    AsrConfig,
    ProviderIdentity,
    RawAsrArtifact,
    VadArtifact,
    VadConfig,
    build_vad_chunks,
)

from .observability import (
    EventCode,
    EventSeverity,
    TranscriptionEvent,
    TranscriptionEventSink,
)
from .ports import (
    AsrEngine,
    AudioExtractor,
    ChecksumService,
    MediaProbe,
    TranscriptionArtifactStore,
    VoiceActivityDetector,
)


AUDIO_VAD_ASR_CACHE_SCHEMA = "transcription.audio-vad-asr-cache.v1"
SUCCESSFUL_CACHE_STATUS = "succeeded"
SUCCESSFUL_DOWNLOAD_STATUS = "downloaded"
STAGE_NAME = "audio_vad_asr"


def _require_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _require_int(value: object, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _cache_key(namespace: str, payload: Mapping[str, Any]) -> str:
    serialized = json.dumps(
        {"namespace": namespace, "payload": payload},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AudioExtractionConfig:
    sample_rate_hz: int = 16_000
    channels: int = 1
    sample_format: str = "s16"
    codec: str = "pcm_s16le"

    def __post_init__(self) -> None:
        if (
            self.sample_rate_hz != 16_000
            or self.channels != 1
            or self.sample_format != "s16"
            or self.codec != "pcm_s16le"
        ):
            raise ValueError("canonical audio must be 16 kHz mono signed 16-bit PCM")

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_rate_hz": self.sample_rate_hz,
            "channels": self.channels,
            "sample_format": self.sample_format,
            "codec": self.codec,
        }


@dataclass(frozen=True)
class SourceVideoInput:
    asset_id: AssetId
    path: str
    manifest_asset_id: AssetId
    manifest_status: str
    size_bytes: int
    checksum_algorithm: str
    checksum_value: str
    manifest_valid: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.asset_id, AssetId):
            raise ValueError("asset_id must be an AssetId")
        if not isinstance(self.manifest_asset_id, AssetId):
            raise ValueError("manifest_asset_id must be an AssetId")
        _require_text(self.path, "path")
        _require_text(self.manifest_status, "manifest_status")
        _require_int(self.size_bytes, "size_bytes", minimum=1)
        _require_text(self.checksum_algorithm, "checksum_algorithm")
        _require_text(self.checksum_value, "checksum_value")
        if not isinstance(self.manifest_valid, bool):
            raise ValueError("manifest_valid must be a bool")


@dataclass(frozen=True)
class AudioVadAsrPolicy:
    overwrite: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.overwrite, bool):
            raise ValueError("overwrite must be a bool")


@dataclass(frozen=True)
class CacheRecord:
    path: str
    size_bytes: int
    sha256: str
    cache_key: str
    status: str = SUCCESSFUL_CACHE_STATUS
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.path, "path")
        _require_int(self.size_bytes, "size_bytes", minimum=1)
        _require_text(self.sha256, "sha256")
        _require_text(self.cache_key, "cache_key")
        _require_text(self.status, "status")
        if not isinstance(self.provenance, Mapping):
            raise ValueError("provenance must be a mapping")
        object.__setattr__(self, "provenance", dict(self.provenance))

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "cache_key": self.cache_key,
            "status": self.status,
            "provenance": dict(self.provenance),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CacheRecord":
        return cls(
            path=data.get("path"),
            size_bytes=data.get("size_bytes"),
            sha256=data.get("sha256"),
            cache_key=data.get("cache_key"),
            status=data.get("status"),
            provenance=data.get("provenance", {}),
        )


@dataclass
class AudioVadAsrCacheManifest:
    asset_id: AssetId
    records: dict[str, CacheRecord] = field(default_factory=dict)
    workflow: Mapping[str, Any] | None = None
    schema_version: str = AUDIO_VAD_ASR_CACHE_SCHEMA

    def __post_init__(self) -> None:
        if self.workflow is not None:
            if not isinstance(self.workflow, Mapping):
                raise ValueError("workflow must be an object or null")
            self.workflow = dict(self.workflow)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "schema_version": self.schema_version,
            "asset": {
                "source": self.asset_id.source,
                "group": self.asset_id.group,
                "item": self.asset_id.item,
            },
            "records": {
                name: record.to_dict() for name, record in self.records.items()
            },
        }
        if self.workflow is not None:
            data["workflow"] = dict(self.workflow)
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AudioVadAsrCacheManifest":
        if data.get("schema_version") != AUDIO_VAD_ASR_CACHE_SCHEMA:
            raise ValueError("unsupported audio/VAD/ASR cache manifest schema")
        asset = data.get("asset")
        records = data.get("records", {})
        if not isinstance(asset, Mapping) or not isinstance(records, Mapping):
            raise ValueError("cache manifest asset and records must be objects")
        if not all(
            isinstance(name, str) and isinstance(record, Mapping)
            for name, record in records.items()
        ):
            raise ValueError("cache manifest records must map names to objects")
        workflow = data.get("workflow")
        if workflow is not None and not isinstance(workflow, Mapping):
            raise ValueError("cache manifest workflow must be an object")
        return cls(
            schema_version=data.get("schema_version"),
            asset_id=AssetId(
                source=asset.get("source"),
                group=asset.get("group", ""),
                item=asset.get("item"),
            ),
            records={
                str(name): CacheRecord.from_dict(record)
                for name, record in records.items()
            },
            workflow=dict(workflow) if workflow is not None else None,
        )


@dataclass(frozen=True)
class AudioVadAsrResult:
    audio_path: str
    vad_path: str
    raw_asr_path: str
    manifest_path: str
    audio_sha256: str
    vad: VadArtifact
    raw_asr: RawAsrArtifact
    cache_hits: tuple[str, ...]


class SourceVideoValidationError(RuntimeError):
    pass


class ExistingTranscriptionArtifactConflict(RuntimeError):
    def __init__(self, artifact: str, reason: str) -> None:
        self.artifact = artifact
        self.reason = reason
        super().__init__(f"existing {artifact} cannot be reused: {reason}")


class AudioVadAsrService:
    def __init__(
        self,
        *,
        audio_extractor: AudioExtractor,
        vad_detector: VoiceActivityDetector,
        asr_engine: AsrEngine,
        media_probe: MediaProbe,
        checksum: ChecksumService,
        artifacts: TranscriptionArtifactStore,
        events: TranscriptionEventSink,
        output_root: str = "output",
    ) -> None:
        self.audio_extractor = audio_extractor
        self.vad_detector = vad_detector
        self.asr_engine = asr_engine
        self.media_probe = media_probe
        self.checksum = checksum
        self.artifacts = artifacts
        self.events = events
        self.output_root = output_root

    def execute(
        self,
        source: SourceVideoInput,
        *,
        vad_config: VadConfig,
        asr_config: AsrConfig,
        audio_config: AudioExtractionConfig | None = None,
        policy: AudioVadAsrPolicy | None = None,
    ) -> AudioVadAsrResult:
        selected_audio = audio_config or AudioExtractionConfig()
        selected_vad = vad_config
        selected_asr = asr_config
        selected_policy = policy or AudioVadAsrPolicy()
        self._validate_source_video(source)
        self._emit(
            source.asset_id,
            EventCode.INPUT_VIDEO_VALIDATED,
            action="accept_input",
            reason="download manifest, path, size, and checksum verified",
        )

        duration_ms = self.media_probe.duration_ms(source.path)
        _require_int(duration_ms, "media duration", minimum=1)
        paths = self._paths(source.asset_id)
        manifest = self._load_manifest(paths["manifest"], source.asset_id)
        cache_hits: list[str] = []

        audio_key = _cache_key(
            "audio.v1",
            {
                "video_sha256": source.checksum_value,
                "extractor": self.audio_extractor.identity.to_dict(),
                "config": selected_audio.to_dict(),
            },
        )
        audio_record = self._validated_cache_record(
            manifest,
            "audio",
            paths["audio"],
            audio_key,
        )
        if (
            audio_record is not None
            and audio_record.provenance.get("video_sha256")
            != source.checksum_value
        ):
            audio_record = None
        if audio_record is None:
            self._assert_replace_allowed(
                "audio", paths["audio"], selected_policy.overwrite
            )
            extraction = self.audio_extractor.extract(
                source.path,
                paths["audio"],
                selected_audio,
                overwrite=selected_policy.overwrite,
            )
            audio_record = self._record_artifact(
                path=paths["audio"],
                cache_key=audio_key,
                provenance={
                    "video_sha256": source.checksum_value,
                    "extractor": self.audio_extractor.identity.to_dict(),
                    "config": selected_audio.to_dict(),
                    "command": list(extraction.command),
                    "duration_ms": duration_ms,
                },
            )
            manifest.records["audio"] = audio_record
            self._write_manifest(paths["manifest"], manifest)
            self._emit(
                source.asset_id,
                EventCode.AUDIO_EXTRACTED,
                action="persist_audio",
                reason="canonical PCM audio extracted",
                details={"cache_key": audio_key},
            )
        else:
            cache_hits.append("audio")
            self._emit_cache_hit(source.asset_id, EventCode.AUDIO_CACHE_HIT, audio_key)

        vad_key = _cache_key(
            "vad.v1",
            {
                "audio_sha256": audio_record.sha256,
                "provider": self.vad_detector.identity.to_dict(),
                "config": selected_vad.to_dict(),
            },
        )
        vad_record = self._validated_cache_record(
            manifest,
            "vad",
            paths["vad"],
            vad_key,
        )
        vad: VadArtifact | None = None
        if vad_record is not None:
            try:
                vad = VadArtifact.from_dict(self.artifacts.read_json(paths["vad"]))
            except Exception:
                vad_record = None
            if vad is not None and (
                vad.cache_key != vad_key or vad.audio_sha256 != audio_record.sha256
            ):
                vad = None
                vad_record = None

        if vad_record is None or vad is None:
            self._assert_replace_allowed("vad", paths["vad"], selected_policy.overwrite)
            regions = self.vad_detector.detect(paths["audio"], selected_vad)
            chunks = build_vad_chunks(
                regions, duration_ms=duration_ms, config=selected_vad
            )
            vad = VadArtifact(
                audio_sha256=audio_record.sha256,
                audio_duration_ms=duration_ms,
                provider=self.vad_detector.identity,
                config=selected_vad,
                regions=regions,
                chunks=chunks,
                cache_key=vad_key,
            )
            self.artifacts.write_json(
                paths["vad"], vad.to_dict(), overwrite=selected_policy.overwrite
            )
            vad_record = self._record_artifact(
                path=paths["vad"],
                cache_key=vad_key,
                provenance={
                    "provider": self.vad_detector.identity.to_dict(),
                    "config": selected_vad.to_dict(),
                },
            )
            manifest.records["vad"] = vad_record
            self._write_manifest(paths["manifest"], manifest)
            self._emit(
                source.asset_id,
                EventCode.VAD_COMPLETED,
                action="persist_vad",
                reason="voice activity regions and source mappings recorded",
                details={"region_count": len(vad.regions), "cache_key": vad_key},
            )
        else:
            cache_hits.append("vad")
            self._emit_cache_hit(source.asset_id, EventCode.VAD_CACHE_HIT, vad_key)

        asr_key = _cache_key(
            "raw_asr.v1",
            {
                "audio_sha256": audio_record.sha256,
                "vad_cache_key": vad.cache_key,
                "provider": self.asr_engine.identity.to_dict(),
                "config": selected_asr.to_dict(),
            },
        )
        asr_record = self._validated_cache_record(
            manifest,
            "raw_asr",
            paths["raw_asr"],
            asr_key,
        )
        raw_asr: RawAsrArtifact | None = None
        if asr_record is not None:
            try:
                raw_asr = RawAsrArtifact.from_dict(
                    self.artifacts.read_json(paths["raw_asr"])
                )
            except Exception:
                asr_record = None
            if raw_asr is not None and (
                raw_asr.cache_key != asr_key
                or raw_asr.audio_sha256 != audio_record.sha256
                or raw_asr.vad_cache_key != vad.cache_key
            ):
                raw_asr = None
                asr_record = None

        if asr_record is None or raw_asr is None:
            self._assert_replace_allowed(
                "raw_asr", paths["raw_asr"], selected_policy.overwrite
            )
            segments = self.asr_engine.transcribe(
                paths["audio"], vad, selected_asr
            )
            raw_asr = RawAsrArtifact(
                audio_sha256=audio_record.sha256,
                audio_duration_ms=duration_ms,
                vad_cache_key=vad.cache_key,
                provider=self.asr_engine.identity,
                config=selected_asr,
                segments=segments,
                cache_key=asr_key,
            )
            self.artifacts.write_json(
                paths["raw_asr"],
                raw_asr.to_dict(),
                overwrite=selected_policy.overwrite,
            )
            asr_record = self._record_artifact(
                path=paths["raw_asr"],
                cache_key=asr_key,
                provenance={
                    "provider": self.asr_engine.identity.to_dict(),
                    "config": selected_asr.to_dict(),
                },
            )
            manifest.records["raw_asr"] = asr_record
            self._write_manifest(paths["manifest"], manifest)
            self._emit(
                source.asset_id,
                EventCode.ASR_COMPLETED,
                action="persist_raw_asr",
                reason="English transcribe segments recorded",
                details={
                    "segment_count": len(raw_asr.segments),
                    "cache_key": asr_key,
                    "profile": selected_asr.profile.value,
                },
            )
        else:
            cache_hits.append("raw_asr")
            self._emit_cache_hit(source.asset_id, EventCode.ASR_CACHE_HIT, asr_key)

        self._emit(
            source.asset_id,
            EventCode.STAGE_COMPLETED,
            action="complete_stage",
            reason="audio, VAD, and raw ASR artifacts are verified",
            details={"cache_hits": len(cache_hits)},
        )
        return AudioVadAsrResult(
            audio_path=paths["audio"],
            vad_path=paths["vad"],
            raw_asr_path=paths["raw_asr"],
            manifest_path=paths["manifest"],
            audio_sha256=audio_record.sha256,
            vad=vad,
            raw_asr=raw_asr,
            cache_hits=tuple(cache_hits),
        )

    def _validate_source_video(self, source: SourceVideoInput) -> None:
        expected_path = str(
            build_asset_workspace(source.asset_id, self.output_root)
            / canonical_filename(ArtifactType.SOURCE_VIDEO)
        )
        category: str | None = None
        if not source.manifest_valid:
            category = "manifest_invalid"
        elif source.manifest_asset_id != source.asset_id:
            category = "asset_mismatch"
        elif source.manifest_status != SUCCESSFUL_DOWNLOAD_STATUS:
            category = "status_not_successful"
        elif Path(source.path) != Path(expected_path):
            category = "artifact_path_mismatch"
        elif source.checksum_algorithm != "sha256":
            category = "checksum_algorithm_mismatch"
        elif not self.artifacts.exists(source.path):
            category = "artifact_missing"
        elif self.artifacts.size(source.path) != source.size_bytes:
            category = "size_mismatch"
        elif self.checksum.sha256(source.path) != source.checksum_value:
            category = "checksum_mismatch"
        if category is not None:
            self._emit(
                source.asset_id,
                EventCode.INPUT_VIDEO_REJECTED,
                severity=EventSeverity.ERROR,
                action="reject_input",
                reason=category,
            )
            raise SourceVideoValidationError(category)

    def _paths(self, asset_id: AssetId) -> dict[str, str]:
        workspace = build_asset_workspace(asset_id, self.output_root)
        return {
            "audio": str(workspace / canonical_filename(ArtifactType.SOURCE_AUDIO)),
            "vad": str(workspace / canonical_filename(ArtifactType.VAD)),
            "raw_asr": str(workspace / canonical_filename(ArtifactType.RAW_ASR)),
            "manifest": str(
                workspace / canonical_filename(ArtifactType.TRANSCRIPTION_MANIFEST)
            ),
        }

    def _load_manifest(
        self, path: str, asset_id: AssetId
    ) -> AudioVadAsrCacheManifest:
        if not self.artifacts.exists(path):
            return AudioVadAsrCacheManifest(asset_id=asset_id)
        try:
            manifest = AudioVadAsrCacheManifest.from_dict(
                self.artifacts.read_json(path)
            )
        except Exception as error:
            raise ExistingTranscriptionArtifactConflict(
                "manifest", "manifest_invalid"
            ) from error
        if manifest.asset_id != asset_id:
            raise ExistingTranscriptionArtifactConflict(
                "manifest", "asset_mismatch"
            )
        return manifest

    def _validated_cache_record(
        self,
        manifest: AudioVadAsrCacheManifest,
        name: str,
        path: str,
        cache_key: str,
    ) -> CacheRecord | None:
        record = manifest.records.get(name)
        if record is None:
            return None
        if (
            record.status != SUCCESSFUL_CACHE_STATUS
            or Path(record.path) != Path(path)
            or record.cache_key != cache_key
            or not self.artifacts.exists(path)
            or self.artifacts.size(path) != record.size_bytes
            or self.checksum.sha256(path) != record.sha256
        ):
            return None
        return record

    def _assert_replace_allowed(
        self, artifact: str, path: str, overwrite: bool
    ) -> None:
        if self.artifacts.exists(path) and not overwrite:
            raise ExistingTranscriptionArtifactConflict(
                artifact, "explicit overwrite required"
            )

    def _record_artifact(
        self,
        *,
        path: str,
        cache_key: str,
        provenance: Mapping[str, Any],
    ) -> CacheRecord:
        if not self.artifacts.exists(path):
            raise RuntimeError(f"provider did not create expected artifact: {path}")
        size = self.artifacts.size(path)
        _require_int(size, "artifact size", minimum=1)
        return CacheRecord(
            path=path,
            size_bytes=size,
            sha256=self.checksum.sha256(path),
            cache_key=cache_key,
            provenance=provenance,
        )

    def _write_manifest(
        self, path: str, manifest: AudioVadAsrCacheManifest
    ) -> None:
        self.artifacts.write_json(path, manifest.to_dict(), overwrite=True)

    def _emit_cache_hit(
        self, asset_id: AssetId, code: EventCode, cache_key: str
    ) -> None:
        self._emit(
            asset_id,
            code,
            action="reuse_artifact",
            reason="manifest, cache key, size, and checksum verified",
            details={"cache_key": cache_key},
        )

    def _emit(
        self,
        asset_id: AssetId,
        code: EventCode,
        *,
        action: str,
        reason: str,
        severity: EventSeverity = EventSeverity.INFO,
        details: Mapping[str, str | int | float | bool | None] | None = None,
    ) -> None:
        self.events.emit(
            TranscriptionEvent(
                asset_id=asset_id.value,
                stage=STAGE_NAME,
                code=code,
                severity=severity,
                action=action,
                reason=reason,
                details=details or {},
            )
        )
