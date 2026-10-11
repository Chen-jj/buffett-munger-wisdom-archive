"""Monotonic local official-transcript fusion, persistence, and caching."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Mapping, Sequence

from archive_core.application import build_asset_workspace
from archive_core.domain import AssetId, ArtifactType, canonical_filename
from archive_core.interfaces import (
    MatchType,
    StructuredTranscriptDTO,
    TextSource,
    TimedWordDTO,
    TimingSource,
)
from transcription.domain import (
    AlignedAsrArtifact,
    AlignedAsrWord,
    AlignmentTimingSource,
    ExcludedOfficialTokens,
    FusionMode,
    IgnoredOfficialContent,
    LocalAlignmentValidation,
    LocalValidationStatus,
    MatchingPolicy,
    NormalizationPolicy,
    OfficialAlignmentCandidate,
    OfficialAlignmentConfig,
    OfficialTranscriptToken,
    TranscriptFusionArtifact,
    aligned_timing_source,
    build_official_tokens,
    normalize_token,
)

from .alignment import ForcedAlignmentResult
from .audio_asr import (
    AudioVadAsrCacheManifest,
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
from .ports import (
    ChecksumService,
    OfficialTranscriptAligner,
    TranscriptionArtifactStore,
)


FUSION_STAGE_NAME = "official_transcript_fusion"


@dataclass(frozen=True)
class OfficialTranscriptInput:
    path: str
    sha256: str
    transcript: StructuredTranscriptDTO

    def __post_init__(self) -> None:
        if not isinstance(self.path, str) or not self.path.strip():
            raise ValueError("path must be a non-empty string")
        if not isinstance(self.sha256, str) or not self.sha256.strip():
            raise ValueError("sha256 must be a non-empty string")
        if not isinstance(self.transcript, StructuredTranscriptDTO):
            raise ValueError("transcript must be a StructuredTranscriptDTO")


@dataclass(frozen=True)
class TranscriptFusionPolicy:
    overwrite: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.overwrite, bool):
            raise ValueError("overwrite must be a bool")


@dataclass(frozen=True)
class TranscriptFusionResult:
    path: str | None
    manifest_path: str
    words: tuple[TimedWordDTO, ...]
    artifact: TranscriptFusionArtifact | None
    used_official: bool
    cache_hit: bool


class FusionInputValidationError(RuntimeError):
    pass


class FusionFailure(RuntimeError):
    def __init__(
        self,
        reason: str,
        *,
        asr_word_ids: tuple[str, ...] = (),
        official_token_ids: tuple[str, ...] = (),
    ) -> None:
        self.reason = reason
        self.asr_word_ids = asr_word_ids
        self.official_token_ids = official_token_ids
        super().__init__(f"official transcript fusion failed: {reason}")


@dataclass(frozen=True)
class _Anchor:
    asr_start: int
    official_start: int
    length: int


@dataclass(frozen=True)
class _MappingPlan:
    match_type: MatchType
    asr_indices: tuple[int, ...]
    official_indices: tuple[int, ...]
    anchor: bool = False
    anchor_asr_indices: tuple[int, ...] = ()


@dataclass(frozen=True)
class _FusionBuild:
    words: tuple[TimedWordDTO, ...]
    exclusions: tuple[ExcludedOfficialTokens, ...]
    validations: tuple[LocalAlignmentValidation, ...]


def identity_fusion_words(
    aligned_asr: AlignedAsrArtifact,
) -> tuple[TimedWordDTO, ...]:
    """Project aligned words unchanged when no official transcript exists."""

    return tuple(
        TimedWordDTO(
            id=f"w{position}",
            text=word.text,
            start_ms=word.start_ms,
            end_ms=word.end_ms,
            asr_word_ids=(word.id,),
            official_token_ids=(),
            match_type=MatchType.ASR_ONLY,
            text_source=TextSource.ASR,
            timing_source=aligned_timing_source(word.timing_source),
        )
        for position, word in enumerate(aligned_asr.words, start=1)
    )


def plan_transcript_fusion(
    aligned_words: Sequence[AlignedAsrWord],
    official_tokens: Sequence[OfficialTranscriptToken],
    *,
    normalization: NormalizationPolicy,
    matching: MatchingPolicy,
) -> tuple[_MappingPlan, ...]:
    """Find monotonic n-gram anchors, then align only bounded local windows."""

    asr = tuple(aligned_words)
    official = tuple(official_tokens)
    anchors = _find_monotonic_anchors(asr, official, normalization, matching)
    plans: list[_MappingPlan] = []
    asr_cursor = 0
    official_cursor = 0
    for anchor_index, anchor in enumerate(anchors):
        plans.extend(
            _align_local_region(
                asr,
                official,
                asr_cursor,
                anchor.asr_start,
                official_cursor,
                anchor.official_start,
                normalization,
                matching,
                left_anchored=anchor_index > 0,
                right_anchored=True,
            )
        )
        for offset in range(anchor.length):
            asr_index = anchor.asr_start + offset
            official_index = anchor.official_start + offset
            anchor_asr_indices = tuple(
                range(anchor.asr_start, anchor.asr_start + anchor.length)
            )
            match_type = (
                MatchType.EXACT
                if asr[asr_index].text == official[official_index].text
                else MatchType.NORMALIZED_EXACT
            )
            plans.append(
                _MappingPlan(
                    match_type,
                    (asr_index,),
                    (official_index,),
                    anchor=True,
                    anchor_asr_indices=anchor_asr_indices,
                )
            )
        asr_cursor = anchor.asr_start + anchor.length
        official_cursor = anchor.official_start + anchor.length
    plans.extend(
        _align_local_region(
            asr,
            official,
            asr_cursor,
            len(asr),
            official_cursor,
            len(official),
            normalization,
            matching,
            left_anchored=bool(anchors),
            right_anchored=False,
        )
    )
    return tuple(plans)


def _find_monotonic_anchors(
    asr: tuple[AlignedAsrWord, ...],
    official: tuple[OfficialTranscriptToken, ...],
    normalization: NormalizationPolicy,
    matching: MatchingPolicy,
) -> tuple[_Anchor, ...]:
    size = matching.anchor_ngram_size
    if len(asr) < size or len(official) < size:
        return ()
    asr_norm = tuple(normalize_token(word.text, normalization) for word in asr)
    official_norm = tuple(token.normalized for token in official)
    asr_grams: dict[tuple[tuple[str, ...], ...], list[int]] = {}
    official_grams: dict[tuple[tuple[str, ...], ...], list[int]] = {}
    for position in range(len(asr_norm) - size + 1):
        asr_grams.setdefault(asr_norm[position : position + size], []).append(position)
    for position in range(len(official_norm) - size + 1):
        official_grams.setdefault(
            official_norm[position : position + size], []
        ).append(position)
    candidates = [
        (asr_positions[0], official_grams[gram][0])
        for gram, asr_positions in asr_grams.items()
        if len(asr_positions) == 1
        and gram in official_grams
        and len(official_grams[gram]) == 1
    ]
    anchors: list[_Anchor] = []
    next_asr = 0
    next_official = 0
    for asr_start, official_start in sorted(candidates):
        if asr_start < next_asr or official_start < next_official:
            continue
        anchors.append(_Anchor(asr_start, official_start, size))
        next_asr = asr_start + size
        next_official = official_start + size
    return tuple(anchors)


def _align_local_region(
    asr: tuple[AlignedAsrWord, ...],
    official: tuple[OfficialTranscriptToken, ...],
    asr_start: int,
    asr_end: int,
    official_start: int,
    official_end: int,
    normalization: NormalizationPolicy,
    matching: MatchingPolicy,
    *,
    left_anchored: bool,
    right_anchored: bool,
) -> tuple[_MappingPlan, ...]:
    asr_count = asr_end - asr_start
    official_count = official_end - official_start
    if (
        asr_count
        and official_count
        and asr_count + official_count > matching.max_local_window_words
    ):
        raise FusionFailure(
            "local mismatch window exceeds configured bound",
            asr_word_ids=tuple(word.id for word in asr[asr_start:asr_end]),
            official_token_ids=tuple(
                token.id for token in official[official_start:official_end]
            ),
        )
    bilateral = left_anchored and right_anchored

    @lru_cache(maxsize=None)
    def solve(
        relative_asr: int, relative_official: int
    ) -> tuple[int, tuple[_MappingPlan, ...]]:
        if relative_asr == asr_count and relative_official == official_count:
            return 0, ()
        choices: list[tuple[int, int, tuple[_MappingPlan, ...]]] = []

        def add_choice(
            cost: int,
            priority: int,
            plan: _MappingPlan,
            next_asr: int,
            next_official: int,
        ) -> None:
            remaining_cost, remaining = solve(next_asr, next_official)
            choices.append((cost + remaining_cost, priority, (plan,) + remaining))

        if relative_asr < asr_count and relative_official < official_count:
            asr_index = asr_start + relative_asr
            official_index = official_start + relative_official
            asr_units = normalize_token(asr[asr_index].text, normalization)
            official_units = official[official_index].normalized
            if asr_units == official_units:
                match_type = (
                    MatchType.EXACT
                    if asr[asr_index].text == official[official_index].text
                    else MatchType.NORMALIZED_EXACT
                )
                add_choice(
                    0 if match_type is MatchType.EXACT else 1,
                    0,
                    _MappingPlan(match_type, (asr_index,), (official_index,)),
                    relative_asr + 1,
                    relative_official + 1,
                )
            elif bilateral and _substitution_is_explicitly_allowed(
                asr[asr_index],
                official[official_index],
                normalization,
                matching,
            ):
                add_choice(
                    20,
                    3,
                    _MappingPlan(
                        MatchType.SUBSTITUTION,
                        (asr_index,),
                        (official_index,),
                    ),
                    relative_asr + 1,
                    relative_official + 1,
                )

            for official_length in range(
                2,
                min(matching.max_group_size, official_count - relative_official) + 1,
            ):
                official_indices = tuple(
                    range(official_index, official_index + official_length)
                )
                if not _same_official_context(official, official_indices):
                    continue
                flattened = tuple(
                    unit
                    for index in official_indices
                    for unit in official[index].normalized
                )
                if asr_units == flattened:
                    add_choice(
                        2,
                        1,
                        _MappingPlan(
                            MatchType.ONE_TO_MANY,
                            (asr_index,),
                            official_indices,
                        ),
                        relative_asr + 1,
                        relative_official + official_length,
                    )

            for asr_length in range(
                2,
                min(matching.max_group_size, asr_count - relative_asr) + 1,
            ):
                asr_indices = tuple(range(asr_index, asr_index + asr_length))
                if any(
                    asr[index].timing_source
                    is not AlignmentTimingSource.ACOUSTIC_ALIGNMENT
                    for index in asr_indices
                ):
                    continue
                flattened = tuple(
                    unit
                    for index in asr_indices
                    for unit in normalize_token(asr[index].text, normalization)
                )
                if flattened == official_units:
                    add_choice(
                        2,
                        2,
                        _MappingPlan(
                            MatchType.MANY_TO_ONE,
                            asr_indices,
                            (official_index,),
                        ),
                        relative_asr + asr_length,
                        relative_official + 1,
                    )

        if relative_asr < asr_count:
            asr_index = asr_start + relative_asr
            add_choice(
                30,
                4,
                _MappingPlan(MatchType.ASR_ONLY, (asr_index,), ()),
                relative_asr + 1,
                relative_official,
            )
        if relative_official < official_count:
            official_index = official_start + relative_official
            add_choice(
                30,
                5,
                _MappingPlan(MatchType.OFFICIAL_ONLY, (), (official_index,)),
                relative_asr,
                relative_official + 1,
            )
        best = min(
            choices, key=lambda choice: (choice[0], choice[1], len(choice[2]))
        )
        return best[0], best[2]

    _, plans = solve(0, 0)
    unmatched = sum(
        len(plan.asr_indices) + len(plan.official_indices)
        for plan in plans
        if plan.match_type in {MatchType.ASR_ONLY, MatchType.OFFICIAL_ONLY}
    )
    has_official_gap = any(
        plan.match_type is MatchType.OFFICIAL_ONLY for plan in plans
    )
    has_asr_gap = any(plan.match_type is MatchType.ASR_ONLY for plan in plans)
    if not bilateral and has_official_gap and (
        official_count > matching.max_official_only_words
        or (
            has_asr_gap
            and unmatched > matching.max_unanchored_conflict_words
        )
    ):
        raise FusionFailure(
            "large unmatched region lacks reliable monotonic bilateral anchors",
            asr_word_ids=tuple(word.id for word in asr[asr_start:asr_end]),
            official_token_ids=tuple(
                token.id for token in official[official_start:official_end]
            ),
        )
    return plans


def _substitution_is_explicitly_allowed(
    asr_word: AlignedAsrWord,
    official_token: OfficialTranscriptToken,
    normalization: NormalizationPolicy,
    matching: MatchingPolicy,
) -> bool:
    candidate = (
        " ".join(normalize_token(asr_word.text, normalization)),
        " ".join(official_token.normalized),
    )
    return candidate in matching.allowed_substitutions


def _same_official_context(
    official: tuple[OfficialTranscriptToken, ...], indices: tuple[int, ...]
) -> bool:
    contexts = {
        (
            official[index].chapter_index,
            official[index].chapter_number,
            official[index].paragraph_index,
            official[index].speaker_label,
        )
        for index in indices
    }
    return len(contexts) == 1


class TranscriptFusionService:
    def __init__(
        self,
        *,
        checksum: ChecksumService,
        artifacts: TranscriptionArtifactStore,
        events: TranscriptionEventSink,
        official_aligner: OfficialTranscriptAligner | None = None,
        output_root: str = "output",
    ) -> None:
        self.checksum = checksum
        self.artifacts = artifacts
        self.events = events
        self.official_aligner = official_aligner
        self.output_root = output_root

    def execute(
        self,
        aligned: ForcedAlignmentResult,
        *,
        official: OfficialTranscriptInput | None,
        normalization: NormalizationPolicy | None = None,
        matching: MatchingPolicy | None = None,
        official_alignment_config: OfficialAlignmentConfig | None = None,
        policy: TranscriptFusionPolicy | None = None,
    ) -> TranscriptFusionResult:
        selected_normalization = normalization or NormalizationPolicy()
        selected_matching = matching or MatchingPolicy()
        selected_policy = policy or TranscriptFusionPolicy()
        asset_id, manifest, aligned_record, audio_path = self._validate_alignment(
            aligned
        )
        workspace = build_asset_workspace(asset_id, self.output_root)
        chapters_path = str(
            workspace / canonical_filename(ArtifactType.CHAPTERS)
        )
        if official is None:
            if self.artifacts.exists(chapters_path):
                raise FusionInputValidationError(
                    "canonical chapters.json exists but no official input was supplied"
                )
            words = identity_fusion_words(aligned.artifact)
            self._emit(
                asset_id,
                EventCode.FUSION_NO_OFFICIAL,
                EventSeverity.INFO,
                action="use_aligned_asr_identity",
                reason="no canonical official transcript exists",
                details={"word_count": len(words)},
            )
            return TranscriptFusionResult(
                path=None,
                manifest_path=aligned.manifest_path,
                words=words,
                artifact=None,
                used_official=False,
                cache_hit=False,
            )

        if (self.official_aligner is None) != (official_alignment_config is None):
            raise ValueError(
                "official aligner and official alignment config must appear together"
            )

        chapters_sha256 = self._validate_official(
            official, chapters_path
        )
        fusion_path = str(
            workspace / canonical_filename(ArtifactType.TRANSCRIPT_FUSION)
        )
        cache_key = _cache_key(
            "transcript_fusion.v1",
            {
                "aligned_asr_sha256": aligned_record.sha256,
                "chapters_sha256": chapters_sha256,
                "normalization": selected_normalization.to_dict(),
                "matching": selected_matching.to_dict(),
                "official_aligner": (
                    self.official_aligner.identity.to_dict()
                    if self.official_aligner is not None
                    else None
                ),
                "official_alignment_config": (
                    official_alignment_config.to_dict()
                    if official_alignment_config is not None
                    else None
                ),
            },
        )
        cached = self._validated_cache(
            manifest,
            fusion_path,
            cache_key,
            aligned_record.sha256,
            chapters_sha256,
        )
        if cached is not None:
            self._emit_cached_summary(asset_id, aligned.artifact, cached)
            self._emit(
                asset_id,
                EventCode.FUSION_CACHE_HIT,
                EventSeverity.INFO,
                action="reuse_artifact",
                reason="fusion manifest, cache key, size, and checksum verified",
                details={"cache_key": cache_key},
            )
            return TranscriptFusionResult(
                path=fusion_path,
                manifest_path=aligned.manifest_path,
                words=cached.words,
                artifact=cached,
                used_official=True,
                cache_hit=True,
            )
        if self.artifacts.exists(fusion_path) and not selected_policy.overwrite:
            raise ExistingTranscriptionArtifactConflict(
                "transcript_fusion", "explicit overwrite required"
            )

        official_tokens, ignored_content = build_official_tokens(
            official.transcript, selected_normalization
        )
        try:
            plans = plan_transcript_fusion(
                aligned.artifact.words,
                official_tokens,
                normalization=selected_normalization,
                matching=selected_matching,
            )
            build = self._build_fusion(
                asset_id,
                audio_path,
                aligned.artifact.words,
                official_tokens,
                plans,
                selected_normalization,
                selected_matching,
                official_alignment_config,
                warn_asr_only=bool(official_tokens),
            )
        except FusionFailure as error:
            self._emit(
                asset_id,
                EventCode.FUSION_REGION_UNMATCHED,
                EventSeverity.ERROR,
                action="reject_fusion",
                reason=error.reason,
                related_ids={
                    "asr_word_ids": ",".join(error.asr_word_ids) or "none",
                    "official_word_ids": ",".join(error.official_token_ids)
                    or "none",
                },
            )
            raise

        artifact = TranscriptFusionArtifact(
            audio_duration_ms=aligned.artifact.audio_duration_ms,
            aligned_asr_sha256=aligned_record.sha256,
            chapters_sha256=chapters_sha256,
            mode=FusionMode.OFFICIAL,
            normalization=selected_normalization,
            matching=selected_matching,
            official_aligner=(
                self.official_aligner.identity
                if self.official_aligner is not None
                else None
            ),
            official_alignment_config=official_alignment_config,
            official_tokens=official_tokens,
            ignored_content=ignored_content,
            words=build.words,
            excluded_official=build.exclusions,
            local_validations=build.validations,
            cache_key=cache_key,
        )
        self.artifacts.write_json(
            fusion_path,
            artifact.to_dict(),
            overwrite=selected_policy.overwrite,
        )
        record = CacheRecord(
            path=fusion_path,
            size_bytes=self.artifacts.size(fusion_path),
            sha256=self.checksum.sha256(fusion_path),
            cache_key=cache_key,
            provenance={
                "aligned_asr_sha256": aligned_record.sha256,
                "chapters_sha256": chapters_sha256,
                "normalization": selected_normalization.to_dict(),
                "matching": selected_matching.to_dict(),
                "official_aligner": (
                    self.official_aligner.identity.to_dict()
                    if self.official_aligner is not None
                    else None
                ),
                "official_alignment_config": (
                    official_alignment_config.to_dict()
                    if official_alignment_config is not None
                    else None
                ),
            },
        )
        manifest.records["transcript_fusion"] = record
        self.artifacts.write_json(
            aligned.manifest_path, manifest.to_dict(), overwrite=True
        )
        self._emit(
            asset_id,
            EventCode.FUSION_COMPLETED,
            EventSeverity.INFO,
            action="persist_transcript_fusion",
            reason="official transcript mappings and exclusions were validated",
            details={
                "word_count": len(artifact.words),
                "official_word_count": len(official_tokens),
                "excluded_official_count": sum(
                    len(item.official_token_ids)
                    for item in artifact.excluded_official
                ),
                "cache_key": cache_key,
            },
        )
        return TranscriptFusionResult(
            path=fusion_path,
            manifest_path=aligned.manifest_path,
            words=artifact.words,
            artifact=artifact,
            used_official=True,
            cache_hit=False,
        )

    def _build_fusion(
        self,
        asset_id: AssetId,
        audio_path: str,
        asr: tuple[AlignedAsrWord, ...],
        official: tuple[OfficialTranscriptToken, ...],
        plans: tuple[_MappingPlan, ...],
        normalization: NormalizationPolicy,
        matching: MatchingPolicy,
        official_alignment_config: OfficialAlignmentConfig | None,
        *,
        warn_asr_only: bool,
    ) -> _FusionBuild:
        words: list[TimedWordDTO] = []
        exclusions: list[ExcludedOfficialTokens] = []
        validations: list[LocalAlignmentValidation] = []
        plan_index = 0
        while plan_index < len(plans):
            plan = plans[plan_index]
            if plan.match_type is MatchType.OFFICIAL_ONLY:
                run_end = plan_index + 1
                while (
                    run_end < len(plans)
                    and plans[run_end].match_type is MatchType.OFFICIAL_ONLY
                ):
                    run_end += 1
                token_indices = tuple(
                    index
                    for run_plan in plans[plan_index:run_end]
                    for index in run_plan.official_indices
                )
                recovered, exclusion, validation = self._recover_official_only(
                    asset_id,
                    audio_path,
                    asr,
                    official,
                    plans,
                    plan_index,
                    run_end,
                    token_indices,
                    normalization,
                    matching,
                    official_alignment_config,
                )
                for candidate in recovered:
                    token = official[int(candidate.official_token_id[2:]) - 1]
                    word = TimedWordDTO(
                        id=f"w{len(words) + 1}",
                        text=token.text,
                        start_ms=candidate.start_ms,
                        end_ms=candidate.end_ms,
                        asr_word_ids=(),
                        official_token_ids=(token.id,),
                        match_type=MatchType.OFFICIAL_ONLY,
                        text_source=TextSource.OFFICIAL_TRANSCRIPT,
                        timing_source=TimingSource.ACOUSTIC_ALIGNMENT,
                    )
                    words.append(word)
                    self._emit_mapping(
                        asset_id,
                        EventCode.FUSION_OFFICIAL_ONLY_RECOVERED,
                        EventSeverity.WARNING,
                        word,
                        source_text=None,
                        result_text=word.text,
                        action="recover_official_only_word",
                        reason=(
                            "local forced alignment succeeded between reliable anchors"
                        ),
                        additional_related_ids={
                            "left_anchor_id": validation.left_anchor_id or "none",
                            "right_anchor_id": validation.right_anchor_id or "none",
                        },
                    )
                if exclusion is not None:
                    exclusions.append(exclusion)
                    for token_index in token_indices:
                        token = official[token_index]
                        self._emit(
                            asset_id,
                            EventCode.FUSION_OFFICIAL_ONLY_EXCLUDED,
                            EventSeverity.WARNING,
                            action="exclude_unverified_official_word",
                            reason=exclusion.reason,
                            related_ids={
                                "official_word_id": token.id,
                                "left_anchor_id": exclusion.left_anchor_id or "none",
                                "right_anchor_id": exclusion.right_anchor_id or "none",
                            },
                            source_text=token.text,
                        )
                validations.append(validation)
                plan_index = run_end
                continue

            word = self._timed_word_from_plan(words, plan, asr, official)
            words.append(word)
            self._emit_plan_event(
                asset_id,
                word,
                plan,
                asr,
                official,
                warn_asr_only=warn_asr_only,
            )
            plan_index += 1

        previous_end = 0
        for word in words:
            if word.start_ms < previous_end:
                raise FusionFailure(
                    "recovered official word overlaps existing spoken timeline",
                    asr_word_ids=word.asr_word_ids,
                    official_token_ids=word.official_token_ids,
                )
            previous_end = word.end_ms
        return _FusionBuild(tuple(words), tuple(exclusions), tuple(validations))

    def _recover_official_only(
        self,
        asset_id: AssetId,
        audio_path: str,
        asr: tuple[AlignedAsrWord, ...],
        official: tuple[OfficialTranscriptToken, ...],
        plans: tuple[_MappingPlan, ...],
        run_start: int,
        run_end: int,
        token_indices: tuple[int, ...],
        normalization: NormalizationPolicy,
        matching: MatchingPolicy,
        config: OfficialAlignmentConfig | None,
    ) -> tuple[
        tuple[OfficialAlignmentCandidate, ...],
        ExcludedOfficialTokens | None,
        LocalAlignmentValidation,
    ]:
        tokens = tuple(official[index] for index in token_indices)
        token_ids = tuple(token.id for token in tokens)
        left_plan = self._nearest_anchor_plan(plans, run_start - 1, step=-1)
        right_plan = self._nearest_anchor_plan(plans, run_end, step=1)
        minimum_anchor_score = (
            float(config.min_anchor_alignment_score)
            if config is not None
            else None
        )
        left = self._reliable_rightmost_anchor(
            left_plan, asr, minimum_anchor_score
        )
        right = self._reliable_leftmost_anchor(
            right_plan, asr, minimum_anchor_score
        )
        left_boundary = self._nearest_asr_word(
            plans, asr, run_start - 1, step=-1, take_rightmost=True
        )
        right_boundary = self._nearest_asr_word(
            plans, asr, run_end, step=1, take_rightmost=False
        )
        left_id = left.id if left is not None else None
        right_id = right.id if right is not None else None
        reason: str | None = None
        if len(tokens) > matching.max_official_only_words:
            reason = "official-only run exceeds local acoustic validation limit"
        elif not _same_official_context(official, token_indices):
            reason = "official-only run crosses chapter, paragraph, or speaker boundary"
        elif not self._same_speaker_as_anchors(
            tokens, left_plan, right_plan, official
        ):
            reason = "official-only run crosses a speaker boundary"
        elif left is None or right is None:
            reason = "official-only run lacks reliable acoustic anchors on both sides"
        elif left.end_ms >= right.start_ms:
            reason = "official-only anchor window has no available time"
        elif self.official_aligner is None or config is None:
            reason = "no local official transcript aligner is configured"
        if reason is None:
            try:
                candidates = self.official_aligner.align_official(
                    audio_path, tokens, left, right, config
                )
                self._validate_local_candidates(
                    tokens,
                    candidates,
                    left_boundary or left,
                    right_boundary or right,
                    normalization,
                    config,
                )
            except Exception as error:
                reason = f"local forced alignment failed: {error}"
            else:
                validation = LocalAlignmentValidation(
                    token_ids,
                    left_id,
                    right_id,
                    LocalValidationStatus.RECOVERED,
                    "all official-only words passed local acoustic validation",
                    tuple(candidates),
                )
                return tuple(candidates), None, validation
        exclusion = ExcludedOfficialTokens(token_ids, reason, left_id, right_id)
        validation = LocalAlignmentValidation(
            token_ids,
            left_id,
            right_id,
            LocalValidationStatus.EXCLUDED,
            reason,
        )
        return (), exclusion, validation

    @staticmethod
    def _nearest_anchor_plan(
        plans: tuple[_MappingPlan, ...], start: int, *, step: int
    ) -> _MappingPlan | None:
        index = start
        while 0 <= index < len(plans):
            if plans[index].anchor:
                return plans[index]
            index += step
        return None

    @staticmethod
    def _nearest_asr_word(
        plans: tuple[_MappingPlan, ...],
        asr: tuple[AlignedAsrWord, ...],
        start: int,
        *,
        step: int,
        take_rightmost: bool,
    ) -> AlignedAsrWord | None:
        index = start
        while 0 <= index < len(plans):
            asr_indices = plans[index].asr_indices
            if asr_indices:
                selected = asr_indices[-1] if take_rightmost else asr_indices[0]
                return asr[selected]
            index += step
        return None

    @staticmethod
    def _same_speaker_as_anchors(
        tokens: tuple[OfficialTranscriptToken, ...],
        left_plan: _MappingPlan | None,
        right_plan: _MappingPlan | None,
        official: tuple[OfficialTranscriptToken, ...],
    ) -> bool:
        if (
            left_plan is None
            or right_plan is None
            or not left_plan.official_indices
            or not right_plan.official_indices
        ):
            return True
        speakers = {token.speaker_label for token in tokens}
        speakers.add(official[left_plan.official_indices[-1]].speaker_label)
        speakers.add(official[right_plan.official_indices[0]].speaker_label)
        return len(speakers) == 1

    @staticmethod
    def _reliable_rightmost_anchor(
        plan: _MappingPlan | None,
        asr: tuple[AlignedAsrWord, ...],
        minimum_score: float | None,
    ) -> AlignedAsrWord | None:
        if plan is None or not plan.anchor or not plan.asr_indices:
            return None
        words = tuple(asr[index] for index in plan.anchor_asr_indices)
        if any(
            word.timing_source is not AlignmentTimingSource.ACOUSTIC_ALIGNMENT
            for word in words
        ):
            return None
        if minimum_score is not None and any(
            word.alignment_score is None
            or float(word.alignment_score) < minimum_score
            for word in words
        ):
            return None
        return asr[plan.asr_indices[-1]]

    @staticmethod
    def _reliable_leftmost_anchor(
        plan: _MappingPlan | None,
        asr: tuple[AlignedAsrWord, ...],
        minimum_score: float | None,
    ) -> AlignedAsrWord | None:
        if plan is None or not plan.anchor or not plan.asr_indices:
            return None
        words = tuple(asr[index] for index in plan.anchor_asr_indices)
        if any(
            word.timing_source is not AlignmentTimingSource.ACOUSTIC_ALIGNMENT
            for word in words
        ):
            return None
        if minimum_score is not None and any(
            word.alignment_score is None
            or float(word.alignment_score) < minimum_score
            for word in words
        ):
            return None
        return asr[plan.asr_indices[0]]

    @staticmethod
    def _validate_local_candidates(
        tokens: tuple[OfficialTranscriptToken, ...],
        candidates: Sequence[OfficialAlignmentCandidate],
        left: AlignedAsrWord,
        right: AlignedAsrWord,
        normalization: NormalizationPolicy,
        config: OfficialAlignmentConfig,
    ) -> None:
        supplied = tuple(candidates)
        if len(supplied) != len(tokens):
            raise ValueError("local alignment did not preserve official word coverage")
        previous_end = left.end_ms
        for token, candidate in zip(tokens, supplied):
            if (
                candidate.official_token_id != token.id
                or normalize_token(candidate.text, normalization) != token.normalized
            ):
                raise ValueError(
                    "local alignment changed official word identity or text"
                )
            if (
                candidate.start_ms < previous_end
                or candidate.end_ms > right.start_ms
            ):
                raise ValueError("local alignment is outside anchors or overlaps")
            if float(candidate.alignment_score) < float(config.min_alignment_score):
                raise ValueError("local alignment score is below configured minimum")
            previous_end = candidate.end_ms

    @staticmethod
    def _timed_word_from_plan(
        words: list[TimedWordDTO],
        plan: _MappingPlan,
        asr: tuple[AlignedAsrWord, ...],
        official: tuple[OfficialTranscriptToken, ...],
    ) -> TimedWordDTO:
        asr_words = tuple(asr[index] for index in plan.asr_indices)
        official_words = tuple(official[index] for index in plan.official_indices)
        if plan.match_type is MatchType.ONE_TO_MANY:
            text = asr_words[0].text
            text_source = TextSource.ASR
        elif plan.match_type is MatchType.ASR_ONLY:
            text = asr_words[0].text
            text_source = TextSource.ASR
        else:
            text = official_words[0].text
            text_source = TextSource.OFFICIAL_TRANSCRIPT
        timing_source = (
            TimingSource.MERGED_ACOUSTIC_ALIGNMENT
            if plan.match_type is MatchType.MANY_TO_ONE
            else aligned_timing_source(asr_words[0].timing_source)
        )
        return TimedWordDTO(
            id=f"w{len(words) + 1}",
            text=text,
            start_ms=asr_words[0].start_ms,
            end_ms=asr_words[-1].end_ms,
            asr_word_ids=tuple(word.id for word in asr_words),
            official_token_ids=tuple(token.id for token in official_words),
            match_type=plan.match_type,
            text_source=text_source,
            timing_source=timing_source,
        )

    def _emit_plan_event(
        self,
        asset_id: AssetId,
        word: TimedWordDTO,
        plan: _MappingPlan,
        asr: tuple[AlignedAsrWord, ...],
        official: tuple[OfficialTranscriptToken, ...],
        *,
        warn_asr_only: bool,
    ) -> None:
        source_text = " ".join(asr[index].text for index in plan.asr_indices)
        result_text = word.text
        event = {
            MatchType.EXACT: (
                EventCode.FUSION_EXACT_MATCHED,
                EventSeverity.DEBUG,
                "keep_exact_official_surface",
                "ASR and official surfaces match exactly",
            ),
            MatchType.NORMALIZED_EXACT: (
                EventCode.FUSION_SURFACE_ADJUSTED,
                EventSeverity.INFO,
                "apply_official_surface",
                "ASR and official text match after versioned normalization",
            ),
            MatchType.SUBSTITUTION: (
                EventCode.FUSION_TEXT_REPLACED,
                EventSeverity.INFO,
                "replace_asr_surface",
                "bounded bilateral anchors support official spelling",
            ),
            MatchType.ONE_TO_MANY: (
                EventCode.FUSION_ONE_TO_MANY_COLLAPSED,
                EventSeverity.INFO,
                "collapse_official_words",
                "normalized lexical units prove one-to-many equivalence",
            ),
            MatchType.MANY_TO_ONE: (
                EventCode.FUSION_MANY_TO_ONE_COLLAPSED,
                EventSeverity.INFO,
                "merge_asr_words",
                "normalized lexical units prove many-to-one equivalence",
            ),
            MatchType.ASR_ONLY: (
                EventCode.FUSION_ASR_ONLY_RETAINED,
                EventSeverity.WARNING if warn_asr_only else EventSeverity.DEBUG,
                "retain_acoustically_aligned_asr_word",
                "official transcript has no mapped spoken token",
            ),
        }[plan.match_type]
        self._emit_mapping(
            asset_id,
            event[0],
            event[1],
            word,
            source_text=source_text,
            result_text=result_text,
            action=event[2],
            reason=event[3],
        )

    def _emit_cached_summary(
        self,
        asset_id: AssetId,
        aligned: AlignedAsrArtifact,
        artifact: TranscriptFusionArtifact,
    ) -> None:
        asr_by_id = {word.id: word for word in aligned.words}
        official_by_id = {token.id: token for token in artifact.official_tokens}
        warn_asr_only = bool(artifact.official_tokens)
        event_by_match = {
            MatchType.EXACT: (
                EventCode.FUSION_EXACT_MATCHED,
                EventSeverity.DEBUG,
            ),
            MatchType.NORMALIZED_EXACT: (
                EventCode.FUSION_SURFACE_ADJUSTED,
                EventSeverity.INFO,
            ),
            MatchType.SUBSTITUTION: (
                EventCode.FUSION_TEXT_REPLACED,
                EventSeverity.INFO,
            ),
            MatchType.ONE_TO_MANY: (
                EventCode.FUSION_ONE_TO_MANY_COLLAPSED,
                EventSeverity.INFO,
            ),
            MatchType.MANY_TO_ONE: (
                EventCode.FUSION_MANY_TO_ONE_COLLAPSED,
                EventSeverity.INFO,
            ),
            MatchType.ASR_ONLY: (
                EventCode.FUSION_ASR_ONLY_RETAINED,
                EventSeverity.WARNING if warn_asr_only else EventSeverity.DEBUG,
            ),
            MatchType.OFFICIAL_ONLY: (
                EventCode.FUSION_OFFICIAL_ONLY_RECOVERED,
                EventSeverity.WARNING,
            ),
        }
        for word in artifact.words:
            code, severity = event_by_match[word.match_type]
            source_text = " ".join(
                asr_by_id[word_id].text for word_id in word.asr_word_ids
            ) or None
            self._emit_mapping(
                asset_id,
                code,
                severity,
                word,
                source_text=source_text,
                result_text=word.text,
                action="summarize_cached_mapping",
                reason="validated cached fusion mapping",
            )
        for exclusion in artifact.excluded_official:
            for token_id in exclusion.official_token_ids:
                token = official_by_id[token_id]
                self._emit(
                    asset_id,
                    EventCode.FUSION_OFFICIAL_ONLY_EXCLUDED,
                    EventSeverity.WARNING,
                    action="summarize_cached_exclusion",
                    reason=exclusion.reason,
                    related_ids={
                        "official_word_id": token.id,
                        "left_anchor_id": exclusion.left_anchor_id or "none",
                        "right_anchor_id": exclusion.right_anchor_id or "none",
                    },
                    source_text=token.text,
                )

    def _emit_mapping(
        self,
        asset_id: AssetId,
        code: EventCode,
        severity: EventSeverity,
        word: TimedWordDTO,
        *,
        source_text: str | None,
        result_text: str,
        action: str,
        reason: str,
        additional_related_ids: Mapping[str, str] | None = None,
    ) -> None:
        related = {"timed_word_id": word.id}
        if word.asr_word_ids:
            related["asr_word_ids"] = ",".join(word.asr_word_ids)
        if word.official_token_ids:
            related["official_word_ids"] = ",".join(word.official_token_ids)
        related.update(additional_related_ids or {})
        self._emit(
            asset_id,
            code,
            severity,
            action=action,
            reason=reason,
            related_ids=related,
            source_text=source_text,
            result_text=result_text,
            start_ms=word.start_ms,
            end_ms=word.end_ms,
        )

    def _validate_alignment(
        self, aligned: ForcedAlignmentResult
    ) -> tuple[AssetId, AudioVadAsrCacheManifest, CacheRecord, str]:
        try:
            manifest = AudioVadAsrCacheManifest.from_dict(
                self.artifacts.read_json(aligned.manifest_path)
            )
        except Exception as error:
            raise FusionInputValidationError(
                "transcription manifest is missing or invalid"
            ) from error
        asset_id = manifest.asset_id
        workspace = build_asset_workspace(asset_id, self.output_root)
        expected_aligned = str(
            workspace / canonical_filename(ArtifactType.ALIGNED_ASR)
        )
        expected_manifest = str(
            workspace / canonical_filename(ArtifactType.TRANSCRIPTION_MANIFEST)
        )
        audio_path = str(workspace / canonical_filename(ArtifactType.SOURCE_AUDIO))
        if (
            Path(aligned.path) != Path(expected_aligned)
            or Path(aligned.manifest_path) != Path(expected_manifest)
        ):
            raise FusionInputValidationError("alignment paths are not canonical")
        aligned_record = manifest.records.get("aligned_asr")
        audio_record = manifest.records.get("audio")
        for name, record, path in (
            ("aligned_asr", aligned_record, aligned.path),
            ("audio", audio_record, audio_path),
        ):
            if record is None or record.status != SUCCESSFUL_CACHE_STATUS:
                raise FusionInputValidationError(
                    f"successful {name} manifest record is missing"
                )
            if (
                Path(record.path) != Path(path)
                or not self.artifacts.exists(path)
                or self.artifacts.size(path) != record.size_bytes
                or self.checksum.sha256(path) != record.sha256
            ):
                raise FusionInputValidationError(
                    f"{name} manifest metadata or checksum is invalid"
                )
        try:
            persisted = AlignedAsrArtifact.from_dict(
                self.artifacts.read_json(aligned.path)
            )
        except Exception as error:
            raise FusionInputValidationError(
                "aligned ASR artifact is invalid"
            ) from error
        if persisted != aligned.artifact:
            raise FusionInputValidationError(
                "aligned ASR input does not match persisted artifact"
            )
        if (
            aligned_record.cache_key != persisted.cache_key
            or persisted.audio_sha256 != audio_record.sha256
        ):
            raise FusionInputValidationError("aligned ASR checksum chain is invalid")
        return asset_id, manifest, aligned_record, audio_path

    def _validate_official(
        self,
        official: OfficialTranscriptInput,
        expected_path: str,
    ) -> str:
        if Path(official.path) != Path(expected_path):
            raise FusionInputValidationError("chapters path is not canonical")
        if (
            not self.artifacts.exists(official.path)
            or self.checksum.sha256(official.path) != official.sha256
        ):
            raise FusionInputValidationError("chapters checksum is invalid")
        try:
            persisted = StructuredTranscriptDTO.from_dict(
                self.artifacts.read_json(official.path)
            )
        except Exception as error:
            raise FusionInputValidationError("chapters artifact is invalid") from error
        if persisted != official.transcript:
            raise FusionInputValidationError(
                "official transcript input does not match chapters artifact"
            )
        return official.sha256

    def _validated_cache(
        self,
        manifest: AudioVadAsrCacheManifest,
        path: str,
        cache_key: str,
        aligned_sha256: str,
        chapters_sha256: str,
    ) -> TranscriptFusionArtifact | None:
        record = manifest.records.get("transcript_fusion")
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
            artifact = TranscriptFusionArtifact.from_dict(
                self.artifacts.read_json(path)
            )
        except Exception:
            return None
        if (
            artifact.cache_key != cache_key
            or artifact.aligned_asr_sha256 != aligned_sha256
            or artifact.chapters_sha256 != chapters_sha256
        ):
            return None
        return artifact

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
        result_text: str | None = None,
        start_ms: int | None = None,
        end_ms: int | None = None,
        details: Mapping[str, str | int | float | bool | None] | None = None,
    ) -> None:
        self.events.emit(
            TranscriptionEvent(
                asset_id=asset_id.value,
                stage=FUSION_STAGE_NAME,
                code=code,
                severity=severity,
                action=action,
                reason=reason,
                related_ids=related_ids or {},
                source_text=_event_excerpt(source_text),
                result_text=_event_excerpt(result_text),
                start_ms=start_ms,
                end_ms=end_ms,
                details=details or {},
            )
        )


def _event_excerpt(value: str | None) -> str | None:
    if value is None or len(value) <= 500:
        return value
    return f"{value[:497]}..."
