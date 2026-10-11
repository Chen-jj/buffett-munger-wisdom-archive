"""Forced-alignment validation, interpolation, persistence, and caching."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from archive_core.application import build_asset_workspace
from archive_core.domain import AssetId, ArtifactType, canonical_filename
from transcription.domain import (
    AlignedAsrArtifact,
    AlignedAsrWord,
    AlignmentCandidate,
    AlignmentTimingSource,
    ForcedAlignmentConfig,
    RawAsrArtifact,
    RawAsrToken,
    build_raw_asr_tokens,
)

from .audio_asr import (
    AudioVadAsrCacheManifest,
    AudioVadAsrResult,
    CacheRecord,
    ExistingTranscriptionArtifactConflict,
    SUCCESSFUL_CACHE_STATUS,
    _cache_key,
)
from .observability import (
    EventCode,
    EventSeverity,
    TranscriptionEvent,
    TranscriptionEventSink,
)
from .ports import ChecksumService, ForcedAligner, TranscriptionArtifactStore


ALIGNMENT_STAGE_NAME = "forced_alignment"


@dataclass(frozen=True)
class ForcedAlignmentPolicy:
    overwrite: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.overwrite, bool):
            raise ValueError("overwrite must be a bool")


@dataclass(frozen=True)
class ForcedAlignmentResult:
    path: str
    manifest_path: str
    artifact: AlignedAsrArtifact
    cache_hit: bool


class AlignmentInputValidationError(RuntimeError):
    pass


class AlignmentFailure(RuntimeError):
    def __init__(
        self,
        category: str,
        reason: str,
        *,
        raw_word_id: str | None = None,
        segment_id: str | None = None,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> None:
        self.category = category
        self.reason = reason
        self.raw_word_id = raw_word_id
        self.segment_id = segment_id
        self.start_ms = start_ms
        self.end_ms = end_ms
        super().__init__(f"forced alignment failed ({category}): {reason}")


def resolve_alignment_candidates(
    raw_asr: RawAsrArtifact,
    tokens: Sequence[RawAsrToken],
    candidates: Sequence[AlignmentCandidate],
    config: ForcedAlignmentConfig,
) -> tuple[AlignedAsrWord, ...]:
    """Validate full token coverage and interpolate only safe anchored gaps."""

    expected_tokens = tuple(tokens)
    supplied = tuple(candidates)
    if len(supplied) != len(expected_tokens):
        raise AlignmentFailure(
            "coverage",
            f"expected {len(expected_tokens)} candidates, received {len(supplied)}",
        )
    segments = {segment.id: segment for segment in raw_asr.segments}
    for token, candidate in zip(expected_tokens, supplied):
        if (
            candidate.raw_word_id != token.id
            or candidate.segment_id != token.segment_id
        ):
            raise AlignmentFailure(
                "coverage",
                "candidate does not preserve raw word and segment identity",
                raw_word_id=token.id,
                segment_id=token.segment_id,
            )
        if _normalized_surface(candidate.text) != _normalized_surface(token.text):
            raise AlignmentFailure(
                "text_mismatch",
                "candidate surface text does not match raw ASR token",
                raw_word_id=token.id,
                segment_id=token.segment_id,
            )
        if candidate.start_ms is not None:
            segment = segments[token.segment_id]
            if (
                candidate.start_ms < segment.start_ms
                or candidate.end_ms is None
                or candidate.end_ms > segment.end_ms
            ):
                raise AlignmentFailure(
                    "out_of_bounds",
                    "acoustic word lies outside its raw ASR segment",
                    raw_word_id=token.id,
                    segment_id=token.segment_id,
                    start_ms=candidate.start_ms,
                    end_ms=candidate.end_ms,
                )

    words: list[AlignedAsrWord | None] = [None] * len(expected_tokens)
    index = 0
    while index < len(supplied):
        candidate = supplied[index]
        token = expected_tokens[index]
        if candidate.start_ms is not None:
            words[index] = AlignedAsrWord(
                id=f"aw{index + 1}",
                raw_word_id=token.id,
                segment_id=token.segment_id,
                text=token.text,
                start_ms=candidate.start_ms,
                end_ms=candidate.end_ms,
                alignment_score=float(candidate.alignment_score),
                timing_source=AlignmentTimingSource.ACOUSTIC_ALIGNMENT,
            )
            index += 1
            continue

        run_start = index
        while index < len(supplied) and supplied[index].start_ms is None:
            index += 1
        run_end = index
        _interpolate_run(
            words,
            expected_tokens,
            supplied,
            run_start,
            run_end,
            config,
        )

    resolved = tuple(word for word in words if word is not None)
    if len(resolved) != len(expected_tokens):
        raise AlignmentFailure("coverage", "one or more raw words were not resolved")
    previous: AlignedAsrWord | None = None
    for word in resolved:
        if previous is not None and word.start_ms < previous.end_ms:
            raise AlignmentFailure(
                "overlap",
                f"{word.id} overlaps {previous.id}",
                raw_word_id=word.raw_word_id,
                segment_id=word.segment_id,
                start_ms=word.start_ms,
                end_ms=word.end_ms,
            )
        previous = word
    return resolved


def _interpolate_run(
    words: list[AlignedAsrWord | None],
    tokens: tuple[RawAsrToken, ...],
    candidates: tuple[AlignmentCandidate, ...],
    run_start: int,
    run_end: int,
    config: ForcedAlignmentConfig,
) -> None:
    run_length = run_end - run_start
    policy = config.interpolation
    first_token = tokens[run_start]
    if run_length > policy.max_consecutive_words:
        raise AlignmentFailure(
            "unrecoverable",
            "unaligned run exceeds interpolation word limit",
            raw_word_id=first_token.id,
            segment_id=first_token.segment_id,
        )
    if run_start == 0 or run_end >= len(candidates):
        raise AlignmentFailure(
            "unrecoverable",
            "unaligned run lacks reliable anchors on both sides",
            raw_word_id=first_token.id,
            segment_id=first_token.segment_id,
        )
    left = candidates[run_start - 1]
    right = candidates[run_end]
    if left.end_ms is None or right.start_ms is None:
        raise AlignmentFailure(
            "unrecoverable",
            "unaligned run lacks timed anchors",
            raw_word_id=first_token.id,
            segment_id=first_token.segment_id,
        )
    minimum_anchor_score = float(policy.min_anchor_alignment_score)
    if (
        left.alignment_score is None
        or right.alignment_score is None
        or float(left.alignment_score) < minimum_anchor_score
        or float(right.alignment_score) < minimum_anchor_score
    ):
        raise AlignmentFailure(
            "unrecoverable",
            "unaligned run lacks reliable acoustic anchors",
            raw_word_id=first_token.id,
            segment_id=first_token.segment_id,
        )
    if any(
        token.segment_id != first_token.segment_id
        for token in tokens[run_start:run_end]
    ) or left.segment_id != first_token.segment_id or right.segment_id != first_token.segment_id:
        raise AlignmentFailure(
            "unrecoverable",
            "interpolation cannot cross raw ASR segment boundaries",
            raw_word_id=first_token.id,
            segment_id=first_token.segment_id,
        )
    for candidate in candidates[run_start:run_end]:
        if candidate.unaligned_reason not in policy.allowed_reasons:
            raise AlignmentFailure(
                "unrecoverable",
                f"unaligned reason is not explainable: {candidate.unaligned_reason}",
                raw_word_id=candidate.raw_word_id,
                segment_id=candidate.segment_id,
            )
    available_ms = right.start_ms - left.end_ms
    if available_ms <= 0:
        raise AlignmentFailure(
            "overlap",
            "interpolation anchors overlap or are reversed",
            raw_word_id=first_token.id,
            segment_id=first_token.segment_id,
            start_ms=left.end_ms,
            end_ms=right.start_ms,
        )
    if available_ms > policy.max_window_ms:
        raise AlignmentFailure(
            "unrecoverable",
            "interpolation window exceeds configured maximum",
            raw_word_id=first_token.id,
            segment_id=first_token.segment_id,
        )
    if available_ms < run_length * policy.min_word_duration_ms:
        raise AlignmentFailure(
            "unrecoverable",
            "interpolation window is too short for missing words",
            raw_word_id=first_token.id,
            segment_id=first_token.segment_id,
        )

    base_width, remainder = divmod(available_ms, run_length)
    cursor = left.end_ms
    left_anchor_id = f"aw{run_start}"
    right_anchor_id = f"aw{run_end + 1}"
    for offset, position in enumerate(range(run_start, run_end)):
        width = base_width + (1 if offset < remainder else 0)
        token = tokens[position]
        words[position] = AlignedAsrWord(
            id=f"aw{position + 1}",
            raw_word_id=token.id,
            segment_id=token.segment_id,
            text=token.text,
            start_ms=cursor,
            end_ms=cursor + width,
            alignment_score=None,
            timing_source=AlignmentTimingSource.INTERPOLATED,
            left_anchor_id=left_anchor_id,
            right_anchor_id=right_anchor_id,
        )
        cursor += width


def _normalized_surface(text: str) -> str:
    return " ".join(text.split())


class ForcedAlignmentService:
    def __init__(
        self,
        *,
        aligner: ForcedAligner,
        checksum: ChecksumService,
        artifacts: TranscriptionArtifactStore,
        events: TranscriptionEventSink,
        output_root: str = "output",
    ) -> None:
        self.aligner = aligner
        self.checksum = checksum
        self.artifacts = artifacts
        self.events = events
        self.output_root = output_root

    def execute(
        self,
        upstream: AudioVadAsrResult,
        *,
        config: ForcedAlignmentConfig,
        policy: ForcedAlignmentPolicy | None = None,
    ) -> ForcedAlignmentResult:
        selected_policy = policy or ForcedAlignmentPolicy()
        asset_id, manifest = self._validate_upstream(upstream)
        raw_record = manifest.records["raw_asr"]
        aligned_path = str(
            build_asset_workspace(asset_id, self.output_root)
            / canonical_filename(ArtifactType.ALIGNED_ASR)
        )
        cache_key = _cache_key(
            "aligned_asr.v1",
            {
                "raw_asr_sha256": raw_record.sha256,
                "provider": self.aligner.identity.to_dict(),
                "config": config.to_dict(),
            },
        )
        cached = self._validated_cache_record(
            manifest, aligned_path, cache_key, raw_record.sha256
        )
        if cached is not None:
            interpolated_count = sum(
                word.timing_source is AlignmentTimingSource.INTERPOLATED
                for word in cached.words
            )
            self._emit(
                asset_id,
                EventCode.ALIGNMENT_CACHE_HIT,
                EventSeverity.INFO,
                action="reuse_artifact",
                reason="aligned ASR manifest, cache key, size, and checksum verified",
                details={
                    "cache_key": cache_key,
                    "aligned_count": len(cached.words) - interpolated_count,
                    "interpolated_count": interpolated_count,
                },
            )
            return ForcedAlignmentResult(
                path=aligned_path,
                manifest_path=upstream.manifest_path,
                artifact=cached,
                cache_hit=True,
            )
        if self.artifacts.exists(aligned_path) and not selected_policy.overwrite:
            raise ExistingTranscriptionArtifactConflict(
                "aligned_asr", "explicit overwrite required"
            )

        tokens = build_raw_asr_tokens(upstream.raw_asr)
        candidates = self.aligner.align(
            upstream.audio_path, upstream.raw_asr, tokens, config
        )
        for token, candidate in zip(tokens, candidates):
            if candidate.start_ms is None:
                self._emit(
                    asset_id,
                    EventCode.ALIGNMENT_WORD_UNALIGNED,
                    EventSeverity.DEBUG,
                    action="evaluate_interpolation",
                    reason=candidate.unaligned_reason or "missing word timing",
                    related_ids={
                        "raw_word_id": token.id,
                        "segment_id": token.segment_id,
                    },
                    source_text=token.text,
                )
        try:
            words = resolve_alignment_candidates(
                upstream.raw_asr, tokens, candidates, config
            )
        except AlignmentFailure as error:
            self._emit_failure(asset_id, error)
            raise

        for word in words:
            if word.timing_source is AlignmentTimingSource.INTERPOLATED:
                self._emit(
                    asset_id,
                    EventCode.ALIGNMENT_WORD_INTERPOLATED,
                    EventSeverity.WARNING,
                    action="interpolate_word_timing",
                    reason="small explainable gap with reliable bilateral anchors",
                    related_ids={
                        "aligned_word_id": word.id,
                        "raw_word_id": word.raw_word_id,
                        "segment_id": word.segment_id,
                    },
                    source_text=word.text,
                    start_ms=word.start_ms,
                    end_ms=word.end_ms,
                )
            else:
                self._emit(
                    asset_id,
                    EventCode.ALIGNMENT_WORD_ALIGNED,
                    EventSeverity.DEBUG,
                    action="keep_acoustic_timing",
                    reason="forced alignment returned a valid acoustic anchor",
                    related_ids={
                        "aligned_word_id": word.id,
                        "raw_word_id": word.raw_word_id,
                        "segment_id": word.segment_id,
                    },
                    source_text=word.text,
                    start_ms=word.start_ms,
                    end_ms=word.end_ms,
                )

        artifact = AlignedAsrArtifact(
            audio_sha256=upstream.audio_sha256,
            raw_asr_sha256=raw_record.sha256,
            audio_duration_ms=upstream.raw_asr.audio_duration_ms,
            provider=self.aligner.identity,
            config=config,
            words=words,
            cache_key=cache_key,
        )
        self.artifacts.write_json(
            aligned_path,
            artifact.to_dict(),
            overwrite=selected_policy.overwrite,
        )
        aligned_record = CacheRecord(
            path=aligned_path,
            size_bytes=self.artifacts.size(aligned_path),
            sha256=self.checksum.sha256(aligned_path),
            cache_key=cache_key,
            provenance={
                "provider": self.aligner.identity.to_dict(),
                "config": config.to_dict(),
            },
        )
        manifest.records["aligned_asr"] = aligned_record
        self.artifacts.write_json(
            upstream.manifest_path, manifest.to_dict(), overwrite=True
        )
        self._emit(
            asset_id,
            EventCode.ALIGNMENT_COMPLETED,
            EventSeverity.INFO,
            action="persist_aligned_asr",
            reason="all raw ASR words have validated word-level timing",
            details={
                "word_count": len(words),
                "cache_key": cache_key,
            },
        )
        return ForcedAlignmentResult(
            path=aligned_path,
            manifest_path=upstream.manifest_path,
            artifact=artifact,
            cache_hit=False,
        )

    def _validate_upstream(
        self, upstream: AudioVadAsrResult
    ) -> tuple[AssetId, AudioVadAsrCacheManifest]:
        expected_audio_name = canonical_filename(ArtifactType.SOURCE_AUDIO)
        expected_raw_name = canonical_filename(ArtifactType.RAW_ASR)
        if Path(upstream.audio_path).name != expected_audio_name:
            raise AlignmentInputValidationError("audio path is not canonical")
        if Path(upstream.raw_asr_path).name != expected_raw_name:
            raise AlignmentInputValidationError("raw ASR path is not canonical")
        if not self.artifacts.exists(upstream.manifest_path):
            raise AlignmentInputValidationError("transcription manifest is missing")
        try:
            manifest = AudioVadAsrCacheManifest.from_dict(
                self.artifacts.read_json(upstream.manifest_path)
            )
        except Exception as error:
            raise AlignmentInputValidationError(
                "transcription manifest is invalid"
            ) from error
        asset_id = manifest.asset_id
        workspace = build_asset_workspace(asset_id, self.output_root)
        expected_paths = {
            "audio": str(workspace / expected_audio_name),
            "raw_asr": str(workspace / expected_raw_name),
            "manifest": str(
                workspace / canonical_filename(ArtifactType.TRANSCRIPTION_MANIFEST)
            ),
        }
        if (
            Path(upstream.audio_path) != Path(expected_paths["audio"])
            or Path(upstream.raw_asr_path) != Path(expected_paths["raw_asr"])
            or Path(upstream.manifest_path) != Path(expected_paths["manifest"])
        ):
            raise AlignmentInputValidationError("upstream paths are not canonical")
        for name, path in (
            ("audio", upstream.audio_path),
            ("raw_asr", upstream.raw_asr_path),
        ):
            record = manifest.records.get(name)
            if record is None or record.status != SUCCESSFUL_CACHE_STATUS:
                raise AlignmentInputValidationError(
                    f"successful upstream {name} record is missing"
                )
            if (
                Path(record.path) != Path(path)
                or not self.artifacts.exists(path)
                or self.artifacts.size(path) != record.size_bytes
                or self.checksum.sha256(path) != record.sha256
            ):
                raise AlignmentInputValidationError(
                    f"upstream {name} checksum or metadata is invalid"
                )
        try:
            persisted_raw = RawAsrArtifact.from_dict(
                self.artifacts.read_json(upstream.raw_asr_path)
            )
        except Exception as error:
            raise AlignmentInputValidationError("raw ASR artifact is invalid") from error
        if persisted_raw != upstream.raw_asr:
            raise AlignmentInputValidationError(
                "raw ASR input does not match persisted artifact"
            )
        if manifest.records["raw_asr"].cache_key != persisted_raw.cache_key:
            raise AlignmentInputValidationError(
                "raw ASR manifest cache key does not match persisted artifact"
            )
        if (
            upstream.audio_sha256 != manifest.records["audio"].sha256
            or upstream.raw_asr.audio_sha256 != upstream.audio_sha256
        ):
            raise AlignmentInputValidationError("audio checksum chain is invalid")
        return asset_id, manifest

    def _validated_cache_record(
        self,
        manifest: AudioVadAsrCacheManifest,
        path: str,
        cache_key: str,
        raw_asr_sha256: str,
    ) -> AlignedAsrArtifact | None:
        record = manifest.records.get("aligned_asr")
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
        try:
            artifact = AlignedAsrArtifact.from_dict(self.artifacts.read_json(path))
        except Exception:
            return None
        if (
            artifact.cache_key != cache_key
            or artifact.raw_asr_sha256 != raw_asr_sha256
        ):
            return None
        return artifact

    def _emit_failure(self, asset_id: AssetId, error: AlignmentFailure) -> None:
        code = (
            EventCode.ALIGNMENT_WORD_OVERLAP
            if error.category == "overlap"
            else EventCode.ALIGNMENT_WORD_UNRECOVERABLE
        )
        related_ids = {}
        if error.raw_word_id is not None:
            related_ids["raw_word_id"] = error.raw_word_id
        if error.segment_id is not None:
            related_ids["segment_id"] = error.segment_id
        time_range = {}
        if (
            error.start_ms is not None
            and error.end_ms is not None
            and error.end_ms > error.start_ms
        ):
            time_range = {"start_ms": error.start_ms, "end_ms": error.end_ms}
        self._emit(
            asset_id,
            code,
            EventSeverity.ERROR,
            action="reject_alignment",
            reason=error.reason,
            related_ids=related_ids,
            **time_range,
        )

    def _emit(
        self,
        asset_id: AssetId,
        code: EventCode,
        severity: EventSeverity,
        *,
        action: str,
        reason: str,
        related_ids: Mapping[str, str] | None = None,
        source_text: str | None = None,
        start_ms: int | None = None,
        end_ms: int | None = None,
        details: Mapping[str, str | int | float | bool | None] | None = None,
    ) -> None:
        self.events.emit(
            TranscriptionEvent(
                asset_id=asset_id.value,
                stage=ALIGNMENT_STAGE_NAME,
                code=code,
                severity=severity,
                action=action,
                reason=reason,
                related_ids=related_ids or {},
                source_text=source_text,
                start_ms=start_ms,
                end_ms=end_ms,
                details=details or {},
            )
        )
