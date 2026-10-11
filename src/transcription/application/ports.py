"""Provider-neutral ports for audio extraction, VAD, ASR, and persistence."""

from __future__ import annotations

from typing import Any, Callable, Mapping, Protocol

from transcription.domain import (
    AlignedAsrWord,
    AlignmentCandidate,
    AsrConfig,
    ForcedAlignmentConfig,
    OfficialAlignmentCandidate,
    OfficialAlignmentConfig,
    OfficialTranscriptToken,
    ProviderIdentity,
    RawAsrArtifact,
    RawAsrToken,
    RawAsrSegment,
    SentenceBoundaryPolicy,
    VadArtifact,
    VadConfig,
    VadRegion,
)


class AudioExtractionConfigLike(Protocol):
    def to_dict(self) -> dict[str, Any]:
        """Return result-affecting canonical audio parameters."""


class AudioExtractionResultLike(Protocol):
    command: tuple[str, ...]


class AudioExtractor(Protocol):
    @property
    def identity(self) -> ProviderIdentity:
        """Return the exact executable identity used by the cache key."""

    def extract(
        self,
        video_path: str,
        output_path: str,
        config: AudioExtractionConfigLike,
        *,
        overwrite: bool,
    ) -> AudioExtractionResultLike:
        """Create canonical audio at output_path."""


class VoiceActivityDetector(Protocol):
    @property
    def identity(self) -> ProviderIdentity:
        """Return the VAD provider and version."""

    def detect(
        self, audio_path: str, config: VadConfig
    ) -> tuple[VadRegion, ...]:
        """Return source-timeline speech regions."""


class AsrEngine(Protocol):
    @property
    def identity(self) -> ProviderIdentity:
        """Return the ASR provider and version."""

    def transcribe(
        self, audio_path: str, vad: VadArtifact, config: AsrConfig
    ) -> tuple[RawAsrSegment, ...]:
        """Return coarse ASR segments on the original audio timeline."""


class ForcedAligner(Protocol):
    @property
    def identity(self) -> ProviderIdentity:
        """Return the forced-alignment provider and version."""

    def align(
        self,
        audio_path: str,
        raw_asr: RawAsrArtifact,
        tokens: tuple[RawAsrToken, ...],
        config: ForcedAlignmentConfig,
    ) -> tuple[AlignmentCandidate, ...]:
        """Return exactly one timed or explicitly unaligned candidate per token."""


class OfficialTranscriptAligner(Protocol):
    @property
    def identity(self) -> ProviderIdentity:
        """Return the local official-token alignment provider and version."""

    def align_official(
        self,
        audio_path: str,
        tokens: tuple[OfficialTranscriptToken, ...],
        left_anchor: AlignedAsrWord,
        right_anchor: AlignedAsrWord,
        config: OfficialAlignmentConfig,
    ) -> tuple[OfficialAlignmentCandidate, ...]:
        """Acoustically validate official-only tokens inside two anchors."""


class SentenceBoundaryDetector(Protocol):
    @property
    def identity(self) -> ProviderIdentity:
        """Return the local detector identity used by the sentence cache key."""

    def detect(
        self,
        words: tuple[str, ...],
        policy: SentenceBoundaryPolicy,
    ) -> tuple[int, ...]:
        """Return zero-based word indices after which a sentence may end."""


class MediaProbe(Protocol):
    def duration_ms(self, media_path: str) -> int:
        """Return media duration as a positive integer millisecond value."""


class ChecksumService(Protocol):
    def sha256(self, path: str) -> str:
        """Return the local file SHA-256 checksum."""


class TranscriptionArtifactStore(Protocol):
    def exists(self, path: str) -> bool:
        """Return whether path exists."""

    def size(self, path: str) -> int:
        """Return file size in bytes."""

    def read_json(self, path: str) -> Mapping[str, Any]:
        """Read one JSON object."""

    def write_json(
        self, path: str, data: Mapping[str, Any], *, overwrite: bool
    ) -> str:
        """Atomically write one JSON object and return its path."""

    def write_text(self, path: str, text: str, *, overwrite: bool) -> str:
        """Atomically write one text artifact and return its path."""

    def publish_json_pair(
        self,
        canonical_path: str,
        canonical_data: Mapping[str, Any],
        manifest_path: str,
        manifest_factory: Callable[[int, str], Mapping[str, Any]],
        *,
        overwrite: bool,
    ) -> tuple[int, str]:
        """Publish a canonical JSON artifact and its manifest as one transaction."""
