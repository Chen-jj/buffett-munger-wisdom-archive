"""Monotonic local official-transcript fusion, persistence, and caching."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, replace
from difflib import SequenceMatcher
from functools import lru_cache
from itertools import product
import math
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
from transcription.domain.fusion import (
    ExcludedAsrWord,
    MoneyAmount,
    OfficialSentenceSpan,
    equivalent_fusion_text,
    fusion_candidate_readings,
    fusion_candidate_text,
    is_explicit_fusion_quantity,
    money_spans,
    numeric_clock_equivalent,
    official_surface_text,
    same_official_person,
)
from transcription.domain.fusion_acoustics import AcousticCandidateEvidence
from transcription.domain.sentences import SentenceBoundaryPolicy, is_sentence_terminal

from .alignment import ForcedAlignmentResult
from .audio_asr import (
    AudioVadAsrCacheManifest,
    CacheRecord,
    ExistingTranscriptionArtifactConflict,
    SUCCESSFUL_CACHE_STATUS,
    _cache_key,
)
from .fusion_context import ContextualComparison, contextual_comparison
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
    money_text: str | None = None


@dataclass(frozen=True)
class _FusionBuild:
    words: tuple[TimedWordDTO, ...]
    exclusions: tuple[ExcludedOfficialTokens, ...]
    validations: tuple[LocalAlignmentValidation, ...]
    excluded_asr: tuple[ExcludedAsrWord, ...]


@dataclass(frozen=True)
class _DifferenceWindow:
    start_ms: int
    end_ms: int
    left_id: str | None
    right_id: str | None
    can_extend_left: bool
    can_extend_right: bool


@dataclass(frozen=True)
class _ScoredDifference:
    asr: AcousticCandidateEvidence
    official: AcousticCandidateEvidence
    readings: tuple[str, str]


@dataclass(frozen=True)
class _DifferenceContext:
    left: tuple[AlignedAsrWord, ...]
    right: tuple[AlignedAsrWord, ...]
    start_ms: int
    end_ms: int


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
    asr_amounts = money_spans(tuple(word.text for word in asr))
    official_amounts = money_spans(tuple(token.text for token in official))
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
    return _group_equivalent_money(asr, official, plans, asr_amounts, official_amounts)


def _group_equivalent_money(
    asr: tuple[AlignedAsrWord, ...],
    official: tuple[OfficialTranscriptToken, ...],
    plans: list[_MappingPlan],
    asr_amounts: Sequence[tuple[int, int, MoneyAmount]],
    official_amounts: Sequence[tuple[int, int, MoneyAmount]],
) -> tuple[_MappingPlan, ...]:
    """Use the local plan to locate complete amounts before comparing differences."""
    if not asr_amounts or not official_amounts:
        return tuple(plans)
    asr_positions = {index: position for position, plan in enumerate(plans) for index in plan.asr_indices}
    official_positions = {index: position for position, plan in enumerate(plans) for index in plan.official_indices}
    replacements: dict[int, tuple[int, _MappingPlan]] = {}
    taken_through = 0
    for first_official, last_official, official_amount in official_amounts:
        official_indices = tuple(range(first_official, last_official))
        if not _same_official_context(official, official_indices):
            continue
        match = None
        for first_asr, last_asr, asr_amount in asr_amounts:
            if (asr_amount.currency, asr_amount.value) != (official_amount.currency, official_amount.value):
                continue
            asr_surfaces = tuple(word.text for word in asr[first_asr:last_asr])
            official_surfaces = tuple(token.text for token in official[first_official:last_official])
            if official_amount.currency == "£" and not any("£" in text for text in (*asr_surfaces, *official_surfaces)):
                continue
            # Only an adjacent weak ASR article can supply a numeral article.
            candidate_asr_starts = (first_asr,)
            if (first_asr > 0 and official_amount.numeral_article and asr_surfaces[0].lstrip("-−").startswith(official_amount.currency)
                    and asr[first_asr - 1].text.casefold() == "a"
                    and asr[first_asr - 1].alignment_score is not None
                    and asr[first_asr - 1].alignment_score < 0.20
                    and asr[first_asr - 1].end_ms - asr[first_asr - 1].start_ms <= 120
                    and asr[first_asr].start_ms - asr[first_asr - 1].end_ms <= 1_250):
                candidate_asr_starts = (first_asr - 1, first_asr)
            for candidate_first in candidate_asr_starts:
                asr_indices = tuple(range(candidate_first, last_asr))
                if any(asr[index].timing_source is not AlignmentTimingSource.ACOUSTIC_ALIGNMENT for index in asr_indices):
                    continue
                start = min(asr_positions[candidate_first], official_positions[first_official])
                end = max(asr_positions[last_asr - 1], official_positions[last_official - 1]) + 1
                if start < taken_through:
                    continue
                region = plans[start:end]
                if (tuple(index for plan in region for index in plan.asr_indices) != asr_indices
                        or tuple(index for plan in region for index in plan.official_indices) != official_indices):
                    continue
                shared_neighbor = any(
                    plans[position].match_type in {MatchType.EXACT, MatchType.NORMALIZED_EXACT}
                    and _same_official_context(official, (first_official, *plans[position].official_indices))
                    for position in (start - 1, end) if 0 <= position < len(plans)
                )
                if not shared_neighbor and len(region) != 1:
                    continue
                match = start, end, asr_indices
                break
            if match is not None:
                break
        if match is None:
            continue
        start, end, asr_indices = match
        if len(asr_indices) == len(official_indices) == 1:
            plan = (
                replace(plans[start], money_text=official_amount.text) if end == start + 1 else
                _MappingPlan(MatchType.NORMALIZED_EXACT, asr_indices, official_indices, money_text=official_amount.text)
            )
        else:
            match_type = (
                MatchType.ONE_TO_MANY if len(asr_indices) == 1 else
                MatchType.MANY_TO_ONE if len(official_indices) == 1 else MatchType.MANY_TO_MANY
            )
            plan = _MappingPlan(match_type, asr_indices, official_indices, money_text=official_amount.text)
        replacements[start] = end, plan
        taken_through = end

    merged = []
    position = 0
    while position < len(plans):
        position, plan = replacements.get(position, (position + 1, plans[position]))
        merged.append(plan)
    return tuple(merged)


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
    # Select the maximum-cardinality non-overlapping chain.
    candidates.sort()
    if not candidates:
        return ()
    scores = [1] * len(candidates)
    parents = [-1] * len(candidates)
    coordinates = sorted({position + size for _, position in candidates})
    tree = [-1] * (len(coordinates) + 1)

    def better(left: int, right: int) -> int:
        if left < 0:
            return right
        if right < 0:
            return left
        # Stable earliest candidate wins equal-length ties.
        return min((left, right), key=lambda index: (-scores[index], index))

    active = 0
    for index, (asr_start, official_start) in enumerate(candidates):
        while active < index and candidates[active][0] + size <= asr_start:
            position = bisect_right(coordinates, candidates[active][1] + size)
            while position < len(tree):
                tree[position] = better(tree[position], active)
                position += position & -position
            active += 1
        position = bisect_right(coordinates, official_start)
        parent = -1
        while position:
            parent = better(parent, tree[position])
            position -= position & -position
        parents[index] = parent
        if parent >= 0:
            scores[index] = scores[parent] + 1
    index = min(range(len(candidates)), key=lambda item: (-scores[item], item))
    anchors = []
    while index >= 0:
        anchors.append(_Anchor(*candidates[index], size))
        index = parents[index]
    return tuple(reversed(anchors))


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
    # Equal edge words are not part of the mismatch search budget. Their
    # existing acoustic times remain untouched; they are not n-gram anchors
    # and cannot authorize official-only recovery on their own.
    if asr_count and official_count and asr_count + official_count > matching.max_local_window_words:
        prefix = []
        while asr_start < asr_end and official_start < official_end and (
            normalize_token(asr[asr_start].text, normalization) == official[official_start].normalized
        ):
            kind = MatchType.EXACT if asr[asr_start].text == official[official_start].text else MatchType.NORMALIZED_EXACT
            prefix.append(_MappingPlan(kind, (asr_start,), (official_start,)))
            asr_start += 1
            official_start += 1
        suffix = []
        while asr_start < asr_end and official_start < official_end and (
            normalize_token(asr[asr_end - 1].text, normalization) == official[official_end - 1].normalized
        ):
            asr_end -= 1
            official_end -= 1
            kind = MatchType.EXACT if asr[asr_end].text == official[official_end].text else MatchType.NORMALIZED_EXACT
            suffix.append(_MappingPlan(kind, (asr_end,), (official_end,)))
        if prefix or suffix:
            middle = _align_local_region(asr, official, asr_start, asr_end, official_start, official_end,
                                         normalization, matching, left_anchored=left_anchored,
                                         right_anchored=right_anchored)
            return tuple(prefix) + middle + tuple(reversed(suffix))
    if (
        asr_count
        and official_count
        and asr_count + official_count > matching.max_local_window_words
    ):
        # Refine this region with locally unique n-grams. Each recursive call
        # consumes at least one anchor without allocating a full-transcript matrix.
        local_anchors = _find_monotonic_anchors(
            asr[asr_start:asr_end], official[official_start:official_end],
            normalization, matching,
        )
        if local_anchors:
            refined = []
            asr_cursor, official_cursor = asr_start, official_start
            for index, anchor in enumerate(local_anchors):
                a = asr_start + anchor.asr_start
                o = official_start + anchor.official_start
                refined.extend(_align_local_region(
                    asr, official, asr_cursor, a, official_cursor, o,
                    normalization, matching,
                    left_anchored=left_anchored or index > 0, right_anchored=True,
                ))
                anchor_indices = tuple(range(a, a + anchor.length))
                for offset in range(anchor.length):
                    match_type = (MatchType.EXACT if asr[a + offset].text == official[o + offset].text
                                  else MatchType.NORMALIZED_EXACT)
                    refined.append(_MappingPlan(
                        match_type, (a + offset,), (o + offset,),
                        anchor=True, anchor_asr_indices=anchor_indices,
                    ))
                asr_cursor, official_cursor = a + anchor.length, o + anchor.length
            refined.extend(_align_local_region(
                asr, official, asr_cursor, asr_end, official_cursor, official_end,
                normalization, matching, left_anchored=True, right_anchored=right_anchored,
            ))
            return tuple(refined)
        raise FusionFailure(
            "local mismatch window exceeds configured bound",
            asr_word_ids=tuple(word.id for word in asr[asr_start:asr_end]),
            official_token_ids=tuple(
                token.id for token in official[official_start:official_end]
            ),
        )
    bilateral = left_anchored and right_anchored

    # Preserve all ASR words in one-sided regions without running DP.
    if not official_count:
        return tuple(_MappingPlan(MatchType.ASR_ONLY, (index,), ())
                     for index in range(asr_start, asr_end))
    if not asr_count:
        if not bilateral and official_count > matching.max_official_only_words:
            raise FusionFailure(
                "large unmatched region lacks reliable monotonic bilateral anchors",
                official_token_ids=tuple(token.id for token in official[official_start:official_end]),
            )
        return tuple(_MappingPlan(MatchType.OFFICIAL_ONLY, (), (index,))
                     for index in range(official_start, official_end))

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
                if (
                    asr_units == flattened
                    or numeric_clock_equivalent(asr[asr_index].text, official, official_indices)
                    or equivalent_fusion_text(
                        (asr[asr_index].text,),
                        tuple(official[index].text for index in official_indices),
                    )
                ):
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

            quantity_limit = 8 if is_explicit_fusion_quantity(official[official_index].text) else 0
            for asr_length in range(2, min(max(quantity_limit, matching.max_group_size),
                                           asr_count - relative_asr) + 1):
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
                if flattened == official_units or equivalent_fusion_text(
                    tuple(asr[index].text for index in asr_indices),
                    (official[official_index].text,),
                ):
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
        sum(len(plan.official_indices) for plan in plans
            if plan.match_type is MatchType.OFFICIAL_ONLY) > matching.max_official_only_words
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
    if candidate in matching.allowed_substitutions:
        return True
    official_spelling = official_token.text.casefold().replace("’", "'").strip(".,!?;:—")
    return (
        "'" in official_spelling
        and (candidate[0], official_spelling) in matching.allowed_substitutions
    )


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


def _official_sentence_spans(
    asr: tuple[AlignedAsrWord, ...],
    official: tuple[OfficialTranscriptToken, ...],
    plans: tuple[_MappingPlan, ...],
    excluded_asr: tuple[ExcludedAsrWord, ...],
    matching: MatchingPolicy,
) -> tuple[OfficialSentenceSpan, ...]:
    """Preserve the source associations used by sentence-boundary evidence."""

    policy = SentenceBoundaryPolicy()
    official_surfaces = tuple(token.text for token in official)
    asr_surfaces = tuple(word.text for word in asr)
    provenance = {
        index: plan
        for plan in plans if plan.asr_indices
        for index in plan.official_indices
    }
    mapped_asr = {index for plan in provenance.values() for index in plan.asr_indices}
    excluded_ids = {word.asr_word_id for word in excluded_asr}
    rows: list[OfficialSentenceSpan] = []
    asr_cursor = 0
    official_cursor = 0

    for current in range(len(official)):
        if (
            current + 1 < len(official)
            and _same_official_context(official, (current, current + 1))
            and not is_sentence_terminal(official_surfaces, current, policy)
        ):
            continue
        first, end = official_cursor, current + 1
        official_cursor = end
        evidence = {
            index: provenance[index]
            for index in range(first, end)
            if index in provenance and any(
                asr[source].timing_source is AlignmentTimingSource.ACOUSTIC_ALIGNMENT
                for source in provenance[index].asr_indices
            )
        }
        if not evidence:
            continue
        fully_matched = len(evidence) == end - first
        anchored = any(plan.anchor for plan in evidence.values())
        if not fully_matched and (len(evidence) < 2 or not anchored):
            continue
        first_asr = min(plan.asr_indices[0] for plan in evidence.values())
        last_asr = max(plan.asr_indices[-1] for plan in evidence.values()) + 1
        # Include unmapped ASR wording from the same partial sentence, stopping
        # at other lexical matches and at observed ASR sentence ends.
        if min(evidence) > first:
            floor = max(asr_cursor, first_asr - matching.max_local_window_words)
            while (
                first_asr > floor
                and first_asr - 1 not in mapped_asr
                and not is_sentence_terminal(asr_surfaces, first_asr - 1, policy)
            ):
                first_asr -= 1
        if max(evidence) < end - 1:
            ceiling = min(len(asr), last_asr + matching.max_local_window_words)
            while (
                last_asr < ceiling
                and last_asr not in mapped_asr
                and not is_sentence_terminal(asr_surfaces, last_asr - 1, policy)
            ):
                last_asr += 1
        if first_asr < asr_cursor:
            continue
        asr_ids = tuple(word.id for word in asr[first_asr:last_asr] if word.id not in excluded_ids)
        if asr_ids:
            rows.append(OfficialSentenceSpan(asr_ids, tuple(token.id for token in official[first:end])))
        asr_cursor = last_asr
    return tuple(rows)


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
            "transcript_fusion.v3",
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
            aligned.artifact.words,
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
                aligned.artifact.audio_duration_ms,
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
            official_sentence_spans=_official_sentence_spans(
                aligned.artifact.words, official_tokens, plans, build.excluded_asr, selected_matching,
            ),
            excluded_asr=build.excluded_asr,
        )
        artifact.validate_asr_coverage(aligned.artifact.words)
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
        audio_duration_ms: int,
        *,
        warn_asr_only: bool,
    ) -> _FusionBuild:
        words: list[TimedWordDTO] = []
        exclusions: list[ExcludedOfficialTokens] = []
        validations: list[LocalAlignmentValidation] = []
        excluded_asr: list[ExcludedAsrWord] = []
        adjusted: dict[str, AlignedAsrWord] = {}
        speaker_labels = frozenset(token.speaker_label for token in official if token.speaker_label)
        gap_types = {MatchType.ASR_ONLY, MatchType.OFFICIAL_ONLY}
        plan_index = 0
        while plan_index < len(plans):
            plan = plans[plan_index]
            if plan.match_type not in gap_types:
                word = self._timed_word_from_plan(words, plan, asr, official)
                if len(word.asr_word_ids) == 1 and word.asr_word_ids[0] in adjusted:
                    shared = adjusted[word.asr_word_ids[0]]
                    word = replace(word, start_ms=shared.start_ms, end_ms=shared.end_ms)
                words.append(word)
                self._emit_plan_event(asset_id, word, plan, asr, official, warn_asr_only=warn_asr_only)
                plan_index += 1
                continue

            run_end = plan_index + 1
            while run_end < len(plans) and plans[run_end].match_type in gap_types:
                run_end += 1
            run = plans[plan_index:run_end]
            asr_indices = tuple(index for part in run for index in part.asr_indices)
            official_indices = tuple(index for part in run for index in part.official_indices)
            tokens = tuple(official[index] for index in official_indices)
            original = tuple(asr[index] for index in asr_indices)
            config = official_alignment_config
            window = None
            if self.official_aligner is not None and config is not None and (
                tokens or all(word.alignment_score is None or word.alignment_score < config.min_anchor_alignment_score
                              for word in original)
            ):
                window = self._difference_window(
                    asr, official, plans, plan_index, run_end, asr_indices, official_indices,
                    audio_duration_ms, normalization, matching, config,
                )
                if window is not None and (window.left_id in adjusted or window.right_id in adjusted):
                    left = adjusted.get(window.left_id)
                    right = adjusted.get(window.right_id)
                    window = replace(window, start_ms=left.end_ms if left else window.start_ms,
                                     end_ms=right.start_ms if right else window.end_ms)
            reason = "no bounded same-utterance acoustic window with unique reliable matches"
            context = self._difference_context(
                asr, official, plans, plan_index, run_end, audio_duration_ms, adjusted, words,
            ) if window is not None else None
            if original and tokens:
                replacement = None
                retiming = None
                if window is not None and config is not None and len(original) == len(tokens) == 1 and (
                    plan_index and plans[plan_index - 1].asr_indices == (asr_indices[0] - 1,)
                    and plans[plan_index - 1].official_indices == (official_indices[0] - 1,)
                    and same_official_person(
                        asr[max(0, asr_indices[0] - 5):asr_indices[0] + 1], tokens[0],
                        official[max(0, official_indices[0] - 5):official_indices[0]], speaker_labels,
                    )
                ):
                    replacement = AcousticCandidateEvidence(None, original[0].start_ms, original[0].end_ms)
                    reason = "mapped given name, introduction and official speaker identity establish the same person"
                elif window is not None and config is not None:
                    replacement, reason, retiming = self._compare_difference(
                        asset_id, audio_path, original, tokens, window, context, config,
                    )
                if replacement is not None:
                    if retiming is not None:
                        self._apply_shared_times(asset_id, words, adjusted, context, retiming, asr)
                    split = self._split_sentence_replacement(
                        replacement, original, tokens, len(words) + 1, normalization, config,
                    )
                    if split == ():
                        self._emit(
                            asset_id, EventCode.FUSION_ACOUSTIC_COMPARISON, EventSeverity.WARNING,
                            action="retain_unsplit_sentence_replacement",
                            reason="cross-sentence replacement lacks complete independent token timing",
                            related_ids={"asr_word_ids": ",".join(item.id for item in original),
                                         "official_word_ids": ",".join(item.id for item in tokens)},
                            result_text=official_surface_text(tokens),
                        )
                    replacement_words = split or (TimedWordDTO(
                        id=f"w{len(words) + 1}", text=official_surface_text(tokens),
                        start_ms=replacement.start_ms, end_ms=replacement.end_ms,
                        asr_word_ids=tuple(item.id for item in original),
                        official_token_ids=tuple(item.id for item in tokens),
                        match_type=MatchType.SUBSTITUTION,
                        text_source=TextSource.OFFICIAL_TRANSCRIPT,
                        timing_source=TimingSource.ACOUSTIC_ALIGNMENT,
                    ),)
                    for word in replacement_words:
                        words.append(word)
                        self._emit_mapping(
                            asset_id,
                            (EventCode.FUSION_TEXT_REPLACED if word.asr_word_ids
                             else EventCode.FUSION_OFFICIAL_ONLY_RECOVERED),
                            EventSeverity.INFO, word,
                            source_text=" ".join(item.text for item in original), result_text=word.text,
                            action="replace_in_fixed_acoustic_window", reason=reason,
                        )
                    plan_index = run_end
                    continue
            elif tokens:
                recovered = ()
                retiming = None
                if window is not None and config is not None:
                    recovered, reason, retiming = self._recover_official_only(
                        asset_id, audio_path, tokens, window, context, normalization, config,
                    )
                if retiming is not None:
                    self._apply_shared_times(asset_id, words, adjusted, context, retiming, asr)
                token_ids = tuple(token.id for token in tokens)
                status = LocalValidationStatus.RECOVERED if recovered else LocalValidationStatus.EXCLUDED
                validations.append(LocalAlignmentValidation(
                    token_ids, window.left_id if window else None,
                    window.right_id if window else None, status, reason, recovered,
                ))
                for candidate in recovered:
                    token = official[int(candidate.official_token_id[2:]) - 1]
                    word = TimedWordDTO(
                        id=f"w{len(words) + 1}", text=token.text,
                        start_ms=candidate.start_ms, end_ms=candidate.end_ms,
                        asr_word_ids=(), official_token_ids=(token.id,),
                        match_type=MatchType.OFFICIAL_ONLY,
                        text_source=TextSource.OFFICIAL_TRANSCRIPT,
                        timing_source=TimingSource.ACOUSTIC_ALIGNMENT,
                    )
                    words.append(word)
                    self._emit_mapping(
                        asset_id, EventCode.FUSION_OFFICIAL_ONLY_RECOVERED, EventSeverity.WARNING, word,
                        source_text=None, result_text=word.text, action="recover_official_only_word",
                        reason="local alignment gave this word an independent acoustic span",
                    )
                if not recovered:
                    exclusions.append(self._exclude_official(asset_id, tokens, window, reason))
                plan_index = run_end
                continue

            if tokens:
                exclusions.append(self._exclude_official(asset_id, tokens, window, reason))
            elif context is not None and config is not None:
                omitted = self._omit_asr_only(asset_id, audio_path, original, window, context, config)
                if omitted is not None:
                    self._apply_shared_times(asset_id, words, adjusted, context, omitted, asr)
                    excluded_asr.extend(ExcludedAsrWord(
                        item.id, item.start_ms, item.end_ms,
                        "complete contextual reading supports omission without losing independent speech",
                    ) for item in original)
                    plan_index = run_end
                    continue
            for part in run:
                if part.match_type is not MatchType.ASR_ONLY:
                    continue
                word = self._timed_word_from_plan(words, part, asr, official)
                words.append(word)
                self._emit_plan_event(asset_id, word, part, asr, official, warn_asr_only=warn_asr_only)
            plan_index = run_end

        previous_end = 0
        for word in words:
            if word.start_ms < previous_end or word.end_ms > audio_duration_ms:
                raise FusionFailure(
                    "recovered official word overlaps existing spoken timeline or exceeds audio",
                    asr_word_ids=word.asr_word_ids, official_token_ids=word.official_token_ids,
                )
            previous_end = word.end_ms
        return _FusionBuild(tuple(words), tuple(exclusions), tuple(validations), tuple(excluded_asr))

    @staticmethod
    def _difference_window(
        asr: tuple[AlignedAsrWord, ...],
        official: tuple[OfficialTranscriptToken, ...],
        plans: tuple[_MappingPlan, ...],
        run_start: int,
        run_end: int,
        asr_indices: tuple[int, ...],
        official_indices: tuple[int, ...],
        audio_duration_ms: int,
        normalization: NormalizationPolicy,
        matching: MatchingPolicy,
        config: OfficialAlignmentConfig,
    ) -> _DifferenceWindow | None:
        if len(asr_indices) > matching.max_group_size or len(official_indices) > matching.max_official_only_words:
            return None
        if official_indices and not _same_official_context(official, official_indices):
            return None
        before = plans[run_start - 1] if run_start else None
        after = plans[run_end] if run_end < len(plans) else None
        left = asr[before.asr_indices[-1]] if before else None
        right = asr[after.asr_indices[0]] if after else None
        if not official_indices and (
            before is None or after is None
            or not _same_official_context(official, (before.official_indices[-1], after.official_indices[0]))
        ):
            return None
        if any(word is not None and word.timing_source is not AlignmentTimingSource.ACOUSTIC_ALIGNMENT
               for word in (left, right)):
            return None
        start_ms = left.end_ms if left else 0
        end_ms = right.start_ms if right else audio_duration_ms
        if not 0 <= end_ms - start_ms <= 5_000:
            return None

        context = official_indices[0] if official_indices else before.official_indices[-1]
        evidence: set[int] = set()
        adjacent_context: list[bool] = []
        for position, step in ((run_start - 1, -1), (run_end, 1)):
            adjacent_context.append(
                0 <= position < len(plans) and _same_official_context(
                    official, (context, *plans[position].official_indices)
                )
            )
            for _ in range(matching.max_local_window_words):
                if not 0 <= position < len(plans):
                    break
                plan = plans[position]
                if plan.official_indices and not _same_official_context(
                    official, (context, *plan.official_indices)
                ):
                    break
                for index in plan.asr_indices if plan.official_indices else ():
                    word = asr[index]
                    if word.timing_source is AlignmentTimingSource.ACOUSTIC_ALIGNMENT and (
                        word.alignment_score is not None and word.alignment_score >= config.min_anchor_alignment_score
                    ):
                        evidence.add(index)
                position += step
        if not any(adjacent_context) or len(evidence) < 2:
            return None

        # Use the position of several ordered matches to disambiguate the local
        # repeat, independently of whether each acoustic endpoint scores well.
        ordered = sorted(evidence)
        first, last = ordered[0], ordered[-1]
        offsets = tuple(index - first for index in ordered)
        expected = tuple(normalize_token(asr[index].text, normalization) for index in ordered)
        starts = range(max(0, first - matching.max_local_window_words), min(
            first + matching.max_local_window_words + 1, len(asr) - (last - first)
        ))
        occurrences = sum(
            all(normalize_token(asr[candidate + offset].text, normalization) == target
                for offset, target in zip(offsets, expected, strict=True))
            for candidate in starts
        )
        if occurrences != 1:
            return None
        return _DifferenceWindow(
            start_ms, end_ms, left.id if left else None, right.id if right else None,
            adjacent_context[0], adjacent_context[1],
        )

    @staticmethod
    def _difference_context(
        asr: tuple[AlignedAsrWord, ...],
        official: tuple[OfficialTranscriptToken, ...],
        plans: tuple[_MappingPlan, ...],
        start: int,
        end: int,
        duration_ms: int,
        adjusted: Mapping[str, AlignedAsrWord],
        published: Sequence[TimedWordDTO],
    ) -> _DifferenceContext | None:
        if start == 0 or end == len(plans):
            return None
        left_plan, right_plan = plans[start - 1], plans[end]
        if not left_plan.official_indices or not right_plan.official_indices:
            return None
        context = left_plan.official_indices[-1]
        if not _same_official_context(official, (context, right_plan.official_indices[0])):
            return None

        def shared(position: int, step: int, limit: int) -> list[AlignedAsrWord]:
            result = []
            for _ in range(limit + 2):
                if not 0 <= position < len(plans) or len(result) == limit:
                    break
                plan = plans[position]
                position += step
                if step < 0 and plan.match_type is MatchType.OFFICIAL_ONLY:
                    continue
                if (
                    plan.match_type not in {MatchType.EXACT, MatchType.NORMALIZED_EXACT}
                    or not _same_official_context(official, (context, *plan.official_indices))
                ):
                    break
                word = asr[plan.asr_indices[0]]
                if (
                    word.id in adjusted
                    or word.timing_source is not AlignmentTimingSource.ACOUSTIC_ALIGNMENT
                    or len(fusion_candidate_text(word.text).split()) != 1
                ):
                    break
                if step < 0 and (
                    len(result) >= len(published)
                    or published[-1 - len(result)].asr_word_ids != (word.id,)
                ):
                    break
                result.append(word)
            return result

        left = shared(start - 1, -1, 5)
        right = shared(end, 1, 4)
        if len(right) == 1 and end + 2 < len(plans) and (
            right[0].end_ms - right[0].start_ms > 1_000
            and plans[end + 1].match_type is MatchType.OFFICIAL_ONLY
            and plans[end + 2].match_type is MatchType.OFFICIAL_ONLY
        ):
            # Reserve the unreliable shared cut for the larger adjacent gap.
            return None
        while left and right:
            first_index = int(left[-1].id[2:]) - 1
            last_index = int(right[-1].id[2:]) - 1
            floor = published[-len(left) - 1].end_ms if len(published) > len(left) else 0
            first = max(floor, asr[first_index - 1].end_ms if first_index else 0)
            last = asr[last_index + 1].start_ms if last_index + 1 < len(asr) else duration_ms
            if 0 < last - first <= 5_000:
                return _DifferenceContext(tuple(reversed(left)), tuple(right), first, last)
            if len(left) > 1 and (len(right) <= 2 or len(left) > 2 and (
                left[0].end_ms - first >= last - right[0].start_ms
            )):
                left.pop()
            elif len(right) > 1:
                right.pop()
            else:
                return None
        return None

    def _compare_context(
        self,
        asset_id: AssetId,
        audio_path: str,
        words: tuple[AlignedAsrWord, ...],
        tokens: tuple[OfficialTranscriptToken, ...],
        window: _DifferenceWindow,
        context: _DifferenceContext,
        pairs: tuple[tuple[str, str], ...],
        config: OfficialAlignmentConfig,
    ) -> ContextualComparison | None:
        left, right = context.left, context.right
        bounds = (left, right, context.start_ms, context.end_ms)
        if not words and len(tokens) == 1:
            trials = ((left, right, left[0].start_ms, right[-1].end_ms), bounds)
        elif not words:
            compact_left, compact_right = left[-2:], right[:2]
            trials = ((compact_left, compact_right, compact_left[0].start_ms, compact_right[-1].end_ms), bounds)
        elif not tokens:
            compact_left, compact_right = left[-3:], right[:2]
            trials = ((compact_left, compact_right, compact_left[0].start_ms, compact_right[-1].end_ms), bounds)
        else:
            trials = (bounds,)
        result = None
        for trial_left, trial_right, first, last in dict.fromkeys(trials):
            scored = contextual_comparison(
                self.official_aligner, audio_path, trial_left, trial_right, pairs, first, last, config,
            )
            if scored is not None:
                result = replace(scored, shared=(
                    *left[:-len(trial_left)], *scored.shared, *right[len(trial_right):],
                ))
                break
        self._emit(
            asset_id, EventCode.FUSION_ACOUSTIC_COMPARISON, EventSeverity.INFO,
            action="compare_complete_context", reason=(
                "bounded complete readings agree on contextual word ownership" if result else
                "no independently anchored common cuts from complete contextual readings"
            ),
            related_ids=self._difference_ids(words, tokens, window),
            source_text=result.readings[0] or None if result else pairs[0][0] or None,
            result_text=result.readings[1] or None if result else pairs[0][1] or None,
            start_ms=result.outer_start_ms if result else context.start_ms,
            end_ms=result.outer_end_ms if result else context.end_ms,
            details={
                "original_start_ms": window.start_ms, "original_end_ms": window.end_ms,
                "common_start_ms": result.start_ms if result else None,
                "common_end_ms": result.end_ms if result else None,
                "asr_context_log_likelihood": result.asr_context.ctc_log_likelihood if result else None,
                "official_context_log_likelihood": result.official_context.ctc_log_likelihood if result else None,
            },
        )
        return result

    def _apply_shared_times(
        self,
        asset_id: AssetId,
        published: list[TimedWordDTO],
        adjusted: dict[str, AlignedAsrWord],
        context: _DifferenceContext,
        result: ContextualComparison,
        asr: tuple[AlignedAsrWord, ...],
    ) -> None:
        original_context = (*context.left, *context.right)
        if tuple(item.id for item in result.shared) != tuple(item.id for item in original_context):
            raise FusionFailure("local retiming changed shared word identity")
        previous = context.start_ms
        for position, shared in enumerate(result.shared):
            if position == len(context.left):
                previous = max(previous, result.end_ms)
            if not previous <= shared.start_ms < shared.end_ms <= context.end_ms:
                raise FusionFailure("local retiming overlaps or exceeds shared context")
            if position < len(context.left) and shared.end_ms > result.start_ms:
                raise FusionFailure("local retiming enters the fixed difference window")
            previous = shared.end_ms
        for position, shared in enumerate(result.shared):
            prior = asr[int(shared.id[2:]) - 1]
            if (shared.start_ms, shared.end_ms) == (prior.start_ms, prior.end_ms):
                continue
            adjusted[shared.id] = shared
            if position < len(context.left):
                index = len(published) - len(context.left) + position
                published[index] = replace(published[index], start_ms=shared.start_ms, end_ms=shared.end_ms)
            self._emit(
                asset_id, EventCode.FUSION_ACOUSTIC_COMPARISON, EventSeverity.INFO,
                action="retime_shared_word", reason="shared word independently supported by the bounded context",
                related_ids={"asr_word_id": shared.id}, source_text=shared.text,
                start_ms=shared.start_ms, end_ms=shared.end_ms,
                details={"original_start_ms": prior.start_ms, "original_end_ms": prior.end_ms,
                         "common_start_ms": result.start_ms, "common_end_ms": result.end_ms},
            )

    @staticmethod
    def _split_sentence_replacement(
        replacement: AcousticCandidateEvidence,
        original: tuple[AlignedAsrWord, ...],
        tokens: tuple[OfficialTranscriptToken, ...],
        first_word_number: int,
        normalization: NormalizationPolicy,
        config: OfficialAlignmentConfig,
    ) -> tuple[TimedWordDTO, ...] | None:
        surfaces = tuple(token.text for token in tokens)
        if not any(is_sentence_terminal(surfaces, index, SentenceBoundaryPolicy())
                   for index in range(len(tokens) - 1)):
            return None
        evidence = replacement.word_evidence
        if (len(evidence) != len(tokens) or replacement.start_ms is None
                or replacement.end_ms is None):
            return ()
        previous_end = replacement.start_ms
        for token, word in zip(tokens, evidence, strict=True):
            if (token.normalized != normalize_token(word.text, normalization)
                    or not previous_end <= word.start_ms < word.end_ms <= replacement.end_ms
                    or not math.isfinite(word.score) or not config.min_alignment_score <= word.score <= 1):
                return ()
            previous_end = word.end_ms

        provenance: list[list[str]] = [[] for _ in tokens]
        previous_index = 0
        for source in original:
            def affinity(index: int) -> tuple[int, int, int]:
                word = evidence[index]
                overlap = max(0, min(source.end_ms, word.end_ms) - max(source.start_ms, word.start_ms))
                gap = max(word.start_ms - source.end_ms, source.start_ms - word.end_ms, 0)
                return overlap, -gap, -index

            index = max(range(len(evidence)), key=affinity)
            if index < previous_index:
                return ()
            provenance[index].append(source.id)
            previous_index = index
        # Provenance is accounted once by temporal contribution; word cuts come
        # solely from the chosen candidate, never from the source-token cuts.
        return tuple(TimedWordDTO(
            id=f"w{first_word_number + index}", text=token.text,
            start_ms=word.start_ms, end_ms=word.end_ms,
            asr_word_ids=tuple(source_ids), official_token_ids=(token.id,),
            match_type=MatchType.SUBSTITUTION if source_ids else MatchType.OFFICIAL_ONLY,
            text_source=TextSource.OFFICIAL_TRANSCRIPT,
            timing_source=TimingSource.ACOUSTIC_ALIGNMENT,
        ) for index, (token, word, source_ids) in enumerate(zip(tokens, evidence, provenance, strict=True)))

    def _recover_official_only(
        self,
        asset_id: AssetId,
        audio_path: str,
        tokens: tuple[OfficialTranscriptToken, ...],
        window: _DifferenceWindow,
        context: _DifferenceContext | None,
        normalization: NormalizationPolicy,
        config: OfficialAlignmentConfig,
    ) -> tuple[tuple[OfficialAlignmentCandidate, ...], str, ContextualComparison | None]:
        candidates = ()
        try:
            if window.start_ms < window.end_ms:
                candidates = self.official_aligner.align_official_window(
                    audio_path, tokens, window.start_ms, window.end_ms, config,
                )
        except (RuntimeError, ValueError) as error:
            reason = f"local forced alignment failed: {error}"
        else:
            reason = "local model did not produce evidence for the whole official fragment"

        valid = len(candidates) == len(tokens)
        previous_end = window.start_ms
        for token, candidate in zip(tokens, candidates):
            accepted = (
                candidate.official_token_id == token.id
                and normalize_token(candidate.text, normalization) == token.normalized
                and previous_end <= candidate.start_ms < candidate.end_ms <= window.end_ms
                and candidate.alignment_score >= config.min_alignment_score
            )
            if not accepted:
                if not previous_end <= candidate.start_ms < candidate.end_ms <= window.end_ms:
                    reason = "local alignment is outside anchors or overlaps"
                elif candidate.alignment_score < config.min_alignment_score:
                    reason = "local alignment score is below configured minimum"
                else:
                    reason = "local alignment changed official word identity or text"
            valid = valid and accepted
            previous_end = candidate.end_ms
            self._emit(
                asset_id, EventCode.FUSION_ACOUSTIC_COMPARISON, EventSeverity.INFO,
                action="validate_official_only_word", reason=(
                    "local word passed score and time checks" if accepted else reason
                ),
                related_ids={"official_word_id": token.id}, source_text=token.text,
                start_ms=candidate.start_ms, end_ms=candidate.end_ms,
                details={"word_score": candidate.alignment_score,
                         "window_start_ms": window.start_ms, "window_end_ms": window.end_ms},
            )
        if valid:
            return tuple(candidates), "all words passed independent score and timing checks", None
        if context is None:
            return (), reason, None

        readings = tuple(fusion_candidate_text(token.text) for token in tokens)
        result = self._compare_context(asset_id, audio_path, (), tokens, window, context,
                                       (("", " ".join(readings)),), config)
        if result is None:
            return (), reason, None
        with_fragment = result.official_context.ctc_log_likelihood
        without_fragment = result.asr_context.ctc_log_likelihood
        if with_fragment is None or without_fragment is None:
            return (), "missing comparable likelihoods for the complete official fragment", None
        offset = 0
        projected = []
        previous_end = result.start_ms
        for token, reading in zip(tokens, readings, strict=True):
            count = len(reading.split())
            evidence = result.official_context_difference[offset:offset + count]
            score_floor = config.min_alignment_score if len(tokens) == 1 else 0.08
            if (
                not evidence or len(evidence) != count
                or not previous_end <= evidence[0].start_ms < evidence[-1].end_ms <= result.end_ms
                or min(word.score for word in evidence) < score_floor
            ):
                return (), reason, None
            projected.append(OfficialAlignmentCandidate(
                token.id, token.text, evidence[0].start_ms, evidence[-1].end_ms,
                min(word.score for word in evidence),
            ))
            previous_end = evidence[-1].end_ms
            offset += count
        margin = with_fragment - without_fragment
        if margin < 0 and (len(tokens) > 1 or margin < -0.5) or (
            margin < 4.0 and any(item.alignment_score < config.min_alignment_score for item in projected)
        ):
            return (), "complete contextual comparison did not support the whole official fragment", None
        return tuple(projected), "complete official fragment is independently supported in shared context", result

    def _exclude_official(
        self,
        asset_id: AssetId,
        tokens: tuple[OfficialTranscriptToken, ...],
        window: _DifferenceWindow | None,
        reason: str,
    ) -> ExcludedOfficialTokens:
        left_id = window.left_id if window else None
        right_id = window.right_id if window else None
        for token in tokens:
            self._emit(
                asset_id, EventCode.FUSION_OFFICIAL_ONLY_EXCLUDED, EventSeverity.WARNING,
                action="exclude_unverified_official_word", reason=reason,
                related_ids={"official_word_id": token.id, "left_anchor_id": left_id or "none",
                             "right_anchor_id": right_id or "none"},
                source_text=token.text,
            )
        return ExcludedOfficialTokens(tuple(token.id for token in tokens), reason, left_id, right_id)

    def _compare_difference(
        self,
        asset_id: AssetId,
        audio_path: str,
        words: tuple[AlignedAsrWord, ...],
        tokens: tuple[OfficialTranscriptToken, ...],
        window: _DifferenceWindow,
        context: _DifferenceContext | None,
        config: OfficialAlignmentConfig,
    ) -> tuple[AcousticCandidateEvidence | None, str, ContextualComparison | None]:
        asr_text = " ".join(word.text for word in words)
        official_text = official_surface_text(tokens)
        shared_currency = set(asr_text) & set(official_text) & {"$", "£", "€"}
        original = fusion_candidate_readings(asr_text, implicit_currency=bool(shared_currency))
        incoming = fusion_candidate_readings(official_text, implicit_currency=bool(shared_currency))
        pairs = tuple(product(original, incoming))
        quantity = any(is_explicit_fusion_quantity(text) for text in (asr_text, official_text))
        results = self._score_windows(asset_id, audio_path, words, tokens, pairs, window, config)
        if results and self._asr_refutes_official(results, window, quantity):
            return None, "stable same-window likelihood and distinct ASR words refute the official reading", None
        if results and self._publication_evidence(results[0].official, window, results[0].readings, quantity):
            return results[0].official, "located official reading has valid time and lacks strong ASR refutation", None

        if context is not None and (quantity or (results and results[0].official.start_ms is not None)):
            result = self._compare_context(asset_id, audio_path, words, tokens, window, context, pairs, config)
            if result is not None:
                revised = replace(window, start_ms=result.start_ms, end_ms=result.end_ms,
                                  can_extend_left=False, can_extend_right=False)
                checks = self._score_windows(
                    asset_id, audio_path, words, tokens, (result.readings,), revised, config,
                )
                if checks and self._asr_refutes_official(checks, revised, quantity):
                    return None, "stable likelihood and independent ASR evidence refute the official reading after retiming", None
                if self._publication_evidence(result.official, revised, result.readings, quantity):
                    reason = "official reading is supported between jointly verified shared word cuts"
                    if quantity and any(item.score < 0.20 for item in result.official.word_evidence):
                        reason += "; the weakest amount components leave precision ambiguity"
                    return result.official, reason, result
        return None, "official reading selected by default but reliable independent timing is unavailable", None

    @staticmethod
    def _publication_evidence(
        reading: AcousticCandidateEvidence, window: _DifferenceWindow, readings: tuple[str, str], quantity: bool,
    ) -> bool:
        if not (
            reading.ctc_log_likelihood is not None
            and reading.start_ms is not None and reading.end_ms is not None
            and window.start_ms <= reading.start_ms < reading.end_ms <= window.end_ms
            and reading.mean_character_score >= 0.15 and reading.energy_coverage >= 0.25
        ):
            return False
        if not quantity:
            return True
        indices = TranscriptFusionService._different_word_indices(readings[0], readings[1])
        evidence = reading.word_evidence
        if len(evidence) != len(readings[1].split()):
            return False
        magnitudes = [index for index in indices if evidence[index].text in {
            "thousand", "million", "billion", "trillion",
        }]
        if magnitudes:
            return max(evidence[index].score for index in magnitudes) >= 0.30
        return bool(indices) and all(evidence[index].score >= 0.30 for index in indices)

    @staticmethod
    def _different_word_indices(other: str, selected: str) -> tuple[int, ...]:
        return tuple(index for kind, _, _, start, end in SequenceMatcher(
            None, other.casefold().split(), selected.casefold().split(), autojunk=False,
        ).get_opcodes() if kind != "equal" for index in range(start, end))

    @staticmethod
    def _asr_refutes_official(
        results: tuple[_ScoredDifference, ...], window: _DifferenceWindow, quantity: bool,
    ) -> bool:
        asr = results[0].asr
        readings = results[0].readings
        selected = TranscriptFusionService._different_word_indices(readings[1], readings[0])
        evidence = asr.word_evidence
        floor = 3.0 if quantity else 1.5
        return (
            bool(selected) and len(evidence) == len(readings[0].split())
            and TranscriptFusionService._publication_evidence(asr, window, readings[::-1], quantity)
            and all(evidence[index].score >= 0.28 for index in selected)
            and asr.energy_coverage + 0.10 >= results[0].official.energy_coverage
            and all(item.asr.ctc_log_likelihood is not None and item.official.ctc_log_likelihood is not None
                    and item.asr.ctc_log_likelihood - item.official.ctc_log_likelihood >= floor for item in results)
        )

    def _omit_asr_only(
        self,
        asset_id: AssetId,
        audio_path: str,
        words: tuple[AlignedAsrWord, ...],
        window: _DifferenceWindow,
        context: _DifferenceContext,
        config: OfficialAlignmentConfig,
    ) -> ContextualComparison | None:
        retained = " ".join(fusion_candidate_text(word.text) for word in words)
        result = self._compare_context(asset_id, audio_path, words, (), window, context, ((retained, ""),), config)
        if result is None:
            return None
        with_extra = result.asr_context.ctc_log_likelihood
        without_extra = result.official_context.ctc_log_likelihood
        evidence = result.asr_context_difference
        omit = (
            with_extra is not None and without_extra is not None
            and without_extra - with_extra >= 6.0
            and not result.context_refined_for_official
            and result.asr.ctc_log_likelihood is not None and result.official.ctc_log_likelihood is not None
            and result.official.ctc_log_likelihood - result.asr.ctc_log_likelihood >= 4.0
            and bool(evidence) and all(word.score < 0.12 for word in evidence)
            and result.official_context.mean_character_score >= 0.45
        )
        reason = (
            "complete context supports omission and extra words lack independent speech evidence" if omit
            else "complete context does not justify removing the timed ASR words"
        )
        self._emit(
            asset_id, EventCode.FUSION_ASR_ONLY_EXCLUDED if omit else EventCode.FUSION_ACOUSTIC_COMPARISON,
            EventSeverity.INFO, action="omit_asr_only_words" if omit else "retain_weak_asr_words",
            reason=reason, related_ids=self._difference_ids(words, (), window), source_text=retained,
            start_ms=context.start_ms, end_ms=context.end_ms,
        )
        return result if omit else None

    @staticmethod
    def _difference_ids(
        words: tuple[AlignedAsrWord, ...], tokens: tuple[OfficialTranscriptToken, ...], window: _DifferenceWindow,
    ) -> dict[str, str]:
        return {"asr_word_ids": ",".join(word.id for word in words) or "none",
                "official_word_ids": ",".join(token.id for token in tokens) or "none",
                "left_anchor_id": window.left_id or "none", "right_anchor_id": window.right_id or "none"}

    def _score_windows(
        self,
        asset_id: AssetId,
        audio_path: str,
        words: tuple[AlignedAsrWord, ...],
        tokens: tuple[OfficialTranscriptToken, ...],
        pairs: tuple[tuple[str, str], ...],
        window: _DifferenceWindow,
        config: OfficialAlignmentConfig,
    ) -> tuple[_ScoredDifference, ...]:
        start, end = window.start_ms, window.end_ms
        if start >= end:
            return ()
        windows = [(start, end)]
        if end - start > 120:
            windows.extend(((start + 40, end), (start, end - 40)))
            if window.can_extend_left and start >= 40:
                windows.append((start - 40, end))
            if window.can_extend_right:
                windows.append((start, end + 40))
        originals = tuple(dict.fromkeys(left for left, _ in pairs))
        candidates = tuple(dict.fromkeys(right for _, right in pairs))
        readings = (*originals, *candidates)
        ids = self._difference_ids(words, tokens, window)
        results = []

        def strongest(texts, evidence):
            return max(zip(texts, evidence, strict=True), key=lambda item: (
                item[1].ctc_log_likelihood if item[1].ctc_log_likelihood is not None else float("-inf")
            ))

        for first, last in windows:
            try:
                evidence = self.official_aligner.score_candidates(audio_path, first, last, readings, config)
                asr_text, baseline = strongest(originals, evidence[:len(originals)])
                official_text, official = strongest(candidates, evidence[len(originals):])
            except (RuntimeError, ValueError) as error:
                self._emit(
                    asset_id, EventCode.FUSION_ACOUSTIC_COMPARISON, EventSeverity.INFO,
                    action="score_fixed_window", reason=str(error), related_ids=ids,
                    start_ms=first, end_ms=last, source_text=readings[0] or None, result_text=readings[-1] or None,
                )
                return ()
            results.append(_ScoredDifference(baseline, official, (asr_text, official_text)))
            for action, text, evidence in (
                ("score_asr_reading", asr_text, baseline), ("score_official_reading", official_text, official),
            ):
                self._emit(
                    asset_id, EventCode.FUSION_ACOUSTIC_COMPARISON, EventSeverity.INFO,
                    action=action, reason="CTC likelihood and local path evidence", related_ids=ids,
                    start_ms=first, end_ms=last, source_text=text or None,
                    details={
                        "ctc_log_likelihood": evidence.ctc_log_likelihood,
                        "candidate_start_ms": evidence.start_ms, "candidate_end_ms": evidence.end_ms,
                        "candidate_mean_character_score": evidence.mean_character_score,
                        "candidate_weakest_two_mean": evidence.weakest_two_mean,
                        "candidate_energy_coverage": evidence.energy_coverage,
                        "candidate_longest_weak_character_run": evidence.longest_weak_character_run,
                        "candidate_word_scores": "; ".join(
                            f"{word.text} {word.start_ms}-{word.end_ms} {word.score:.3f}" for word in evidence.word_evidence
                        ),
                    },
                )
        return tuple(results)

    @staticmethod
    def _timed_word_from_plan(
        words: list[TimedWordDTO],
        plan: _MappingPlan,
        asr: tuple[AlignedAsrWord, ...],
        official: tuple[OfficialTranscriptToken, ...],
    ) -> TimedWordDTO:
        asr_words = tuple(asr[index] for index in plan.asr_indices)
        official_words = tuple(official[index] for index in plan.official_indices)
        if plan.match_type is MatchType.ASR_ONLY:
            text = asr_words[0].text
            text_source = TextSource.ASR
        else:
            text = plan.money_text or official_surface_text(official_words)
            text_source = TextSource.OFFICIAL_TRANSCRIPT
        timing_source = (
            TimingSource.MERGED_ACOUSTIC_ALIGNMENT
            if plan.match_type in {MatchType.MANY_TO_ONE, MatchType.MANY_TO_MANY}
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
            MatchType.MANY_TO_MANY: (
                EventCode.FUSION_MANY_TO_MANY_COLLAPSED,
                EventSeverity.INFO,
                "merge_equivalent_money_spans",
                "complete amounts share the same value and currency",
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
            MatchType.MANY_TO_MANY: (
                EventCode.FUSION_MANY_TO_MANY_COLLAPSED,
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
        aligned_words: tuple[AlignedAsrWord, ...],
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
            artifact.validate_asr_coverage(aligned_words)
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
                source_text=source_text,
                result_text=result_text,
                start_ms=start_ms,
                end_ms=end_ms,
                details=details or {},
            )
        )
