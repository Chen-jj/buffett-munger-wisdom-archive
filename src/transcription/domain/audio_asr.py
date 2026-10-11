"""Pure audio, VAD, and raw ASR models for the transcription stage."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence


VAD_SCHEMA_VERSION = "transcription.vad.v1"
RAW_ASR_SCHEMA_VERSION = "transcription.raw-asr.v1"


def _require_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _require_int(value: object, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _require_float(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    return float(value)


def _require_sequence(value: object, name: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{name} must be an array")
    return value


@dataclass(frozen=True)
class ProviderIdentity:
    name: str
    version: str

    def __post_init__(self) -> None:
        _require_text(self.name, "provider name")
        _require_text(self.version, "provider version")

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "version": self.version}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProviderIdentity":
        return cls(name=data.get("name"), version=data.get("version"))


class TranscriptionProfile(str, Enum):
    PRODUCTION = "production"
    DEVELOPMENT = "development"


@dataclass(frozen=True)
class VadConfig:
    model: str
    model_version: str
    onset: float = 0.5
    offset: float = 0.5
    padding_ms: int = 250
    merge_gap_ms: int = 500

    def __post_init__(self) -> None:
        _require_text(self.model, "model")
        _require_text(self.model_version, "model_version")
        onset = _require_float(self.onset, "onset")
        offset = _require_float(self.offset, "offset")
        if not 0 <= onset <= 1 or not 0 <= offset <= 1:
            raise ValueError("onset and offset must be between 0 and 1")
        _require_int(self.padding_ms, "padding_ms")
        _require_int(self.merge_gap_ms, "merge_gap_ms")

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "model_version": self.model_version,
            "onset": float(self.onset),
            "offset": float(self.offset),
            "padding_ms": self.padding_ms,
            "merge_gap_ms": self.merge_gap_ms,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "VadConfig":
        return cls(
            model=data.get("model"),
            model_version=data.get("model_version"),
            onset=data.get("onset"),
            offset=data.get("offset"),
            padding_ms=data.get("padding_ms"),
            merge_gap_ms=data.get("merge_gap_ms"),
        )


@dataclass(frozen=True)
class AsrConfig:
    profile: TranscriptionProfile
    model: str
    device: str
    compute_type: str
    batch_size: int
    beam_size: int
    language: str = "en"
    task: str = "transcribe"

    def __post_init__(self) -> None:
        if not isinstance(self.profile, TranscriptionProfile):
            raise ValueError("profile must be a TranscriptionProfile")
        _require_text(self.model, "model")
        _require_text(self.device, "device")
        _require_text(self.compute_type, "compute_type")
        _require_int(self.batch_size, "batch_size", minimum=1)
        _require_int(self.beam_size, "beam_size", minimum=1)
        if self.language != "en":
            raise ValueError("language must be en")
        if self.task != "transcribe":
            raise ValueError("task must be transcribe")
    @classmethod
    def production(
        cls,
        *,
        model: str,
        device: str,
        compute_type: str,
        batch_size: int = 8,
        beam_size: int = 5,
    ) -> "AsrConfig":
        return cls(
            profile=TranscriptionProfile.PRODUCTION,
            model=model,
            device=device,
            compute_type=compute_type,
            batch_size=batch_size,
            beam_size=beam_size,
        )

    @classmethod
    def development(
        cls,
        *,
        model: str,
        device: str = "cpu",
        compute_type: str = "int8",
        batch_size: int = 1,
        beam_size: int = 1,
    ) -> "AsrConfig":
        return cls(
            profile=TranscriptionProfile.DEVELOPMENT,
            model=model,
            device=device,
            compute_type=compute_type,
            batch_size=batch_size,
            beam_size=beam_size,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile.value,
            "model": self.model,
            "language": self.language,
            "task": self.task,
            "device": self.device,
            "compute_type": self.compute_type,
            "batch_size": self.batch_size,
            "beam_size": self.beam_size,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AsrConfig":
        return cls(
            profile=TranscriptionProfile(data.get("profile")),
            model=data.get("model"),
            language=data.get("language"),
            task=data.get("task"),
            device=data.get("device"),
            compute_type=data.get("compute_type"),
            batch_size=data.get("batch_size"),
            beam_size=data.get("beam_size"),
        )


@dataclass(frozen=True)
class SourceTimeSpan:
    start_ms: int
    end_ms: int

    def __post_init__(self) -> None:
        _require_int(self.start_ms, "start_ms")
        _require_int(self.end_ms, "end_ms")
        if self.end_ms <= self.start_ms:
            raise ValueError("time span must satisfy start_ms < end_ms")

    def to_dict(self) -> dict[str, int]:
        return {"start_ms": self.start_ms, "end_ms": self.end_ms}


@dataclass(frozen=True)
class VadRegion:
    id: str
    start_ms: int
    end_ms: int

    def __post_init__(self) -> None:
        _require_text(self.id, "id")
        if self.position < 1 or self.id != f"vr{self.position}":
            raise ValueError("VAD region id must use vr<one-based position>")
        SourceTimeSpan(self.start_ms, self.end_ms)

    @property
    def position(self) -> int:
        suffix = self.id.removeprefix("vr")
        if not suffix.isdigit() or suffix.startswith("0"):
            return 0
        return int(suffix)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "start_ms": self.start_ms, "end_ms": self.end_ms}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "VadRegion":
        return cls(
            id=data.get("id"),
            start_ms=data.get("start_ms"),
            end_ms=data.get("end_ms"),
        )


@dataclass(frozen=True)
class VadChunkMapping:
    chunk_start_ms: int
    chunk_end_ms: int
    source_start_ms: int
    source_end_ms: int

    def __post_init__(self) -> None:
        chunk = SourceTimeSpan(self.chunk_start_ms, self.chunk_end_ms)
        source = SourceTimeSpan(self.source_start_ms, self.source_end_ms)
        if chunk.end_ms - chunk.start_ms != source.end_ms - source.start_ms:
            raise ValueError("chunk and source mapping durations must be equal")

    def to_dict(self) -> dict[str, int]:
        return {
            "chunk_start_ms": self.chunk_start_ms,
            "chunk_end_ms": self.chunk_end_ms,
            "source_start_ms": self.source_start_ms,
            "source_end_ms": self.source_end_ms,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "VadChunkMapping":
        return cls(
            chunk_start_ms=data.get("chunk_start_ms"),
            chunk_end_ms=data.get("chunk_end_ms"),
            source_start_ms=data.get("source_start_ms"),
            source_end_ms=data.get("source_end_ms"),
        )


@dataclass(frozen=True)
class VadChunk:
    id: str
    mappings: tuple[VadChunkMapping, ...]

    def __post_init__(self) -> None:
        _require_text(self.id, "id")
        suffix = self.id.removeprefix("vc")
        if not suffix.isdigit() or suffix.startswith("0"):
            raise ValueError("VAD chunk id must use vc<one-based position>")
        object.__setattr__(self, "mappings", tuple(self.mappings))
        if not self.mappings:
            raise ValueError("VAD chunk must contain at least one mapping")
        previous_chunk_end = 0
        previous_source_end = 0
        for mapping in self.mappings:
            if not isinstance(mapping, VadChunkMapping):
                raise ValueError("mappings must contain VadChunkMapping values")
            if mapping.chunk_start_ms != previous_chunk_end:
                raise ValueError("chunk mappings must continuously cover chunk time")
            if mapping.source_start_ms < previous_source_end:
                raise ValueError("chunk source mappings must be monotonic")
            previous_chunk_end = mapping.chunk_end_ms
            previous_source_end = mapping.source_end_ms

    @property
    def duration_ms(self) -> int:
        return self.mappings[-1].chunk_end_ms

    def map_range_to_source(
        self, start_ms: int, end_ms: int
    ) -> tuple[SourceTimeSpan, ...]:
        requested = SourceTimeSpan(start_ms, end_ms)
        if requested.end_ms > self.duration_ms:
            raise ValueError("chunk range exceeds chunk duration")
        spans: list[SourceTimeSpan] = []
        for mapping in self.mappings:
            overlap_start = max(requested.start_ms, mapping.chunk_start_ms)
            overlap_end = min(requested.end_ms, mapping.chunk_end_ms)
            if overlap_start >= overlap_end:
                continue
            source_start = mapping.source_start_ms + (
                overlap_start - mapping.chunk_start_ms
            )
            source_end = mapping.source_start_ms + (
                overlap_end - mapping.chunk_start_ms
            )
            spans.append(SourceTimeSpan(source_start, source_end))
        if sum(span.end_ms - span.start_ms for span in spans) != end_ms - start_ms:
            raise ValueError("chunk range is not fully mapped to source time")
        return tuple(spans)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "duration_ms": self.duration_ms,
            "mappings": [mapping.to_dict() for mapping in self.mappings],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "VadChunk":
        mappings = _require_sequence(data.get("mappings", []), "mappings")
        return cls(
            id=data.get("id"),
            mappings=tuple(VadChunkMapping.from_dict(item) for item in mappings),
        )


def build_vad_chunks(
    regions: Sequence[VadRegion], *, duration_ms: int, config: VadConfig
) -> tuple[VadChunk, ...]:
    """Pad, de-overlap, and concatenate nearby speech regions with exact mappings."""

    _require_int(duration_ms, "duration_ms", minimum=1)
    if not isinstance(config, VadConfig):
        raise ValueError("config must be a VadConfig")
    normalized_regions = tuple(regions)
    padded: list[SourceTimeSpan] = []
    previous_end = 0
    for position, region in enumerate(normalized_regions, start=1):
        if not isinstance(region, VadRegion) or region.id != f"vr{position}":
            raise ValueError("VAD regions must be vr1..vrN in source order")
        if region.start_ms < previous_end or region.end_ms > duration_ms:
            raise ValueError("VAD regions must be monotonic and within audio duration")
        previous_end = region.end_ms
        candidate = SourceTimeSpan(
            max(0, region.start_ms - config.padding_ms),
            min(duration_ms, region.end_ms + config.padding_ms),
        )
        if padded and candidate.start_ms <= padded[-1].end_ms:
            padded[-1] = SourceTimeSpan(
                padded[-1].start_ms, max(padded[-1].end_ms, candidate.end_ms)
            )
        else:
            padded.append(candidate)

    if not padded:
        return ()

    chunk_groups: list[list[SourceTimeSpan]] = [[padded[0]]]
    for span in padded[1:]:
        if span.start_ms - chunk_groups[-1][-1].end_ms <= config.merge_gap_ms:
            chunk_groups[-1].append(span)
        else:
            chunk_groups.append([span])

    chunks: list[VadChunk] = []
    for chunk_position, group in enumerate(chunk_groups, start=1):
        chunk_offset = 0
        mappings: list[VadChunkMapping] = []
        for span in group:
            source_duration = span.end_ms - span.start_ms
            mappings.append(
                VadChunkMapping(
                    chunk_start_ms=chunk_offset,
                    chunk_end_ms=chunk_offset + source_duration,
                    source_start_ms=span.start_ms,
                    source_end_ms=span.end_ms,
                )
            )
            chunk_offset += source_duration
        chunks.append(VadChunk(id=f"vc{chunk_position}", mappings=tuple(mappings)))
    return tuple(chunks)


@dataclass(frozen=True)
class VadArtifact:
    audio_sha256: str
    audio_duration_ms: int
    provider: ProviderIdentity
    config: VadConfig
    regions: tuple[VadRegion, ...]
    chunks: tuple[VadChunk, ...]
    cache_key: str
    schema_version: str = VAD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != VAD_SCHEMA_VERSION:
            raise ValueError(f"unsupported VAD schema: {self.schema_version}")
        _require_text(self.audio_sha256, "audio_sha256")
        _require_int(self.audio_duration_ms, "audio_duration_ms", minimum=1)
        _require_text(self.cache_key, "cache_key")
        if not isinstance(self.provider, ProviderIdentity):
            raise ValueError("provider must be a ProviderIdentity")
        if not isinstance(self.config, VadConfig):
            raise ValueError("config must be a VadConfig")
        object.__setattr__(self, "regions", tuple(self.regions))
        object.__setattr__(self, "chunks", tuple(self.chunks))
        expected_chunks = build_vad_chunks(
            self.regions, duration_ms=self.audio_duration_ms, config=self.config
        )
        if self.chunks != expected_chunks:
            raise ValueError("VAD chunks must match the configured region mapping")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "audio_sha256": self.audio_sha256,
            "audio_duration_ms": self.audio_duration_ms,
            "provider": self.provider.to_dict(),
            "config": self.config.to_dict(),
            "regions": [region.to_dict() for region in self.regions],
            "chunks": [chunk.to_dict() for chunk in self.chunks],
            "cache_key": self.cache_key,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "VadArtifact":
        if data.get("schema_version") != VAD_SCHEMA_VERSION:
            raise ValueError(f"unsupported VAD schema: {data.get('schema_version')}")
        regions = _require_sequence(data.get("regions", []), "regions")
        chunks = _require_sequence(data.get("chunks", []), "chunks")
        return cls(
            schema_version=data.get("schema_version"),
            audio_sha256=data.get("audio_sha256"),
            audio_duration_ms=data.get("audio_duration_ms"),
            provider=ProviderIdentity.from_dict(data.get("provider", {})),
            config=VadConfig.from_dict(data.get("config", {})),
            regions=tuple(VadRegion.from_dict(item) for item in regions),
            chunks=tuple(VadChunk.from_dict(item) for item in chunks),
            cache_key=data.get("cache_key"),
        )


@dataclass(frozen=True)
class RawAsrSegment:
    id: str
    text: str
    start_ms: int
    end_ms: int

    def __post_init__(self) -> None:
        _require_text(self.id, "id")
        suffix = self.id.removeprefix("seg")
        if not suffix.isdigit() or suffix.startswith("0"):
            raise ValueError("raw ASR segment id must use seg<one-based position>")
        _require_text(self.text, "text")
        SourceTimeSpan(self.start_ms, self.end_ms)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RawAsrSegment":
        return cls(
            id=data.get("id"),
            text=data.get("text"),
            start_ms=data.get("start_ms"),
            end_ms=data.get("end_ms"),
        )


@dataclass(frozen=True)
class RawAsrArtifact:
    audio_sha256: str
    audio_duration_ms: int
    vad_cache_key: str
    provider: ProviderIdentity
    config: AsrConfig
    segments: tuple[RawAsrSegment, ...]
    cache_key: str
    schema_version: str = RAW_ASR_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RAW_ASR_SCHEMA_VERSION:
            raise ValueError(f"unsupported raw ASR schema: {self.schema_version}")
        _require_text(self.audio_sha256, "audio_sha256")
        _require_int(self.audio_duration_ms, "audio_duration_ms", minimum=1)
        _require_text(self.vad_cache_key, "vad_cache_key")
        _require_text(self.cache_key, "cache_key")
        if not isinstance(self.provider, ProviderIdentity):
            raise ValueError("provider must be a ProviderIdentity")
        if not isinstance(self.config, AsrConfig):
            raise ValueError("config must be an AsrConfig")
        object.__setattr__(self, "segments", tuple(self.segments))
        previous_end = 0
        for position, segment in enumerate(self.segments, start=1):
            if not isinstance(segment, RawAsrSegment) or segment.id != f"seg{position}":
                raise ValueError("raw ASR segments must be seg1..segN in time order")
            if segment.start_ms < previous_end:
                raise ValueError("raw ASR segments must not overlap or move backward")
            if segment.end_ms > self.audio_duration_ms:
                raise ValueError("raw ASR segment exceeds audio duration")
            previous_end = segment.end_ms

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "audio_sha256": self.audio_sha256,
            "audio_duration_ms": self.audio_duration_ms,
            "vad_cache_key": self.vad_cache_key,
            "language": self.config.language,
            "task": self.config.task,
            "profile": self.config.profile.value,
            "provider": self.provider.to_dict(),
            "config": self.config.to_dict(),
            "segments": [segment.to_dict() for segment in self.segments],
            "cache_key": self.cache_key,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RawAsrArtifact":
        if data.get("schema_version") != RAW_ASR_SCHEMA_VERSION:
            raise ValueError(f"unsupported raw ASR schema: {data.get('schema_version')}")
        segments = _require_sequence(data.get("segments", []), "segments")
        return cls(
            schema_version=data.get("schema_version"),
            audio_sha256=data.get("audio_sha256"),
            audio_duration_ms=data.get("audio_duration_ms"),
            vad_cache_key=data.get("vad_cache_key"),
            provider=ProviderIdentity.from_dict(data.get("provider", {})),
            config=AsrConfig.from_dict(data.get("config", {})),
            segments=tuple(RawAsrSegment.from_dict(item) for item in segments),
            cache_key=data.get("cache_key"),
        )
