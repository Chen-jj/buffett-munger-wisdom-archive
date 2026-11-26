"""Re-establish shared word times before scoring a bounded fusion difference."""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
import unicodedata

from transcription.domain import AlignedAsrWord, AlignmentTimingSource, OfficialAlignmentConfig
from transcription.domain.fusion import fusion_candidate_text
from transcription.domain.fusion_acoustics import AcousticCandidateEvidence, AcousticWordEvidence

from .ports import OfficialTranscriptAligner


_MAX_WINDOW_MS = 5_000
_MAX_CONTEXT_WORDS = 10
_MAX_READINGS_PER_SIDE = 16
_CUT_JITTER_MS = 40
_MIN_RETIMED_WORD_SCORE = 0.08
_MIN_CONTEXT_GUIDE_ADVANTAGE = 8.0


@dataclass(frozen=True)
class ContextualComparison:
    outer_start_ms: int
    outer_end_ms: int
    start_ms: int
    end_ms: int
    readings: tuple[str, str]
    shared: tuple[AlignedAsrWord, ...]
    asr: AcousticCandidateEvidence
    official: AcousticCandidateEvidence
    asr_context: AcousticCandidateEvidence
    official_context: AcousticCandidateEvidence
    asr_context_difference: tuple[AcousticWordEvidence, ...]
    official_context_difference: tuple[AcousticWordEvidence, ...]
    context_refined_for_official: bool


def _lexemes(reading: str) -> tuple[str, ...]:
    text = unicodedata.normalize("NFKC", reading).casefold().replace("’", "'")
    parts = (
        "".join(character for character in chunk if character.isalnum() or character in "'-").strip("'-")
        for chunk in text.split()
    )
    return tuple(part for part in parts if part)


def _valid_path(
    evidence: AcousticCandidateEvidence, reading: str, start_ms: int, end_ms: int,
) -> bool:
    likelihood = evidence.ctc_log_likelihood
    if likelihood is None or not math.isfinite(likelihood):
        return False
    words = evidence.word_evidence
    if tuple(word.text for word in words) != _lexemes(reading):
        return False
    previous_end = start_ms
    for word in words:
        if not previous_end <= word.start_ms < word.end_ms <= end_ms or not 0 <= word.score <= 1:
            return False
        previous_end = word.end_ms
    return True


def _common_words(
    evidence: AcousticCandidateEvidence, left_count: int, right_count: int,
) -> tuple[AcousticWordEvidence, ...]:
    return evidence.word_evidence[:left_count] + evidence.word_evidence[-right_count:]


def _intersection(words: tuple[AcousticWordEvidence, ...]) -> AcousticWordEvidence | None:
    start = max(word.start_ms for word in words)
    end = min(word.end_ms for word in words)
    if start >= end:
        return None
    return AcousticWordEvidence(words[0].text, start, end, min(word.score for word in words))


def contextual_comparison(
    aligner: OfficialTranscriptAligner,
    audio_path: str,
    left: tuple[AlignedAsrWord, ...],
    right: tuple[AlignedAsrWord, ...],
    reading_pairs: tuple[tuple[str, str], ...],
    start_ms: int,
    end_ms: int,
    config: OfficialAlignmentConfig,
) -> ContextualComparison | None:
    """Compare complete readings and return fixed cuts for an atomic local edit.

    The caller supplies consecutive common words from a single turn and bounds
    that exclude untouched words. Returned times are proposals to commit only
    with a compatible, independently supported edit inside the fixed cuts.
    """
    flanks = left + right
    if (not left or not right or len(flanks) > _MAX_CONTEXT_WORDS or not reading_pairs
            or not 0 <= start_ms < end_ms <= start_ms + _MAX_WINDOW_MS):
        return None
    if any(word.timing_source is not AlignmentTimingSource.ACOUSTIC_ALIGNMENT for word in flanks):
        return None
    if (flanks[0].start_ms < start_ms or flanks[-1].end_ms > end_ms
            or any(first.end_ms > second.start_ms for first, second in zip(flanks, flanks[1:]))):
        return None
    flank_readings = tuple(fusion_candidate_text(word.text) for word in flanks)
    if any(len(_lexemes(reading)) != 1 for reading in flank_readings):
        return None
    prefix = " ".join(flank_readings[:len(left)])
    suffix = " ".join(flank_readings[len(left):])

    def surrounding(reading: str) -> str:
        return " ".join(part for part in (prefix, reading, suffix) if part)

    original, revised = (tuple(dict.fromkeys(side)) for side in zip(*reading_pairs, strict=True))
    if max(len(original), len(revised)) > _MAX_READINGS_PER_SIDE:
        return None
    complete = tuple(dict.fromkeys(map(surrounding, original + revised)))
    try:
        paths = dict(zip(complete, aligner.score_candidates(audio_path, start_ms, end_ms, complete, config), strict=True))
    except (RuntimeError, ValueError):
        return None

    def best_reading(options: tuple[str, ...]) -> str | None:
        return max(
            (reading for reading in options if _valid_path(paths[surrounding(reading)], surrounding(reading), start_ms, end_ms)),
            key=lambda reading: paths[surrounding(reading)].ctc_log_likelihood,
            default=None,
        )

    original_reading = best_reading(original)
    revised_reading = best_reading(revised)
    if original_reading is None or revised_reading is None:
        return None
    readings = original_reading, revised_reading
    broad = tuple(map(surrounding, readings))
    asr_path, official_path = (paths[reading] for reading in broad)
    asr_flanks = _common_words(asr_path, len(left), len(right))
    official_flanks = _common_words(official_path, len(left), len(right))
    agreed = tuple(_intersection(pair) for pair in zip(asr_flanks, official_flanks, strict=True))

    # A path with a weak or displaced interior common word cannot determine
    # the cuts on its own. Anchor both exterior words, then require stable
    # evidence for the proposed whole utterance under two perturbed outer cuts.
    guided = any(word is None for word in agreed)
    if guided:
        if (agreed[0] is None or agreed[-1] is None or end_ms - start_ms <= 2 * _CUT_JITTER_MS
                or min(agreed[0].score, agreed[-1].score) < config.min_alignment_score
                or official_path.ctc_log_likelihood - asr_path.ctc_log_likelihood < _MIN_CONTEXT_GUIDE_ADVANTAGE):
            return None
        stable = [official_flanks]
        for first, last in ((start_ms + _CUT_JITTER_MS, end_ms), (start_ms, end_ms - _CUT_JITTER_MS)):
            try:
                asr_trial, official_trial = aligner.score_candidates(audio_path, first, last, broad, config)
            except (RuntimeError, ValueError):
                return None
            if (not _valid_path(asr_trial, broad[0], first, last)
                    or not _valid_path(official_trial, broad[1], first, last)
                    or official_trial.ctc_log_likelihood - asr_trial.ctc_log_likelihood < _MIN_CONTEXT_GUIDE_ADVANTAGE):
                return None
            stable.append(_common_words(official_trial, len(left), len(right)))
        agreed = tuple(
            agreed[index] or _intersection(evidence)
            for index, evidence in enumerate(zip(*stable, strict=True))
        )
    shared = []
    for index, (word, path) in enumerate(zip(flanks, agreed, strict=True)):
        if path is None:
            return None
        if path.score >= _MIN_RETIMED_WORD_SCORE:
            shared.append(replace(word, start_ms=path.start_ms, end_ms=path.end_ms, alignment_score=path.score))
            continue
        if (index in {len(left) - 1, len(left)}
                or max(word.start_ms, path.start_ms) >= min(word.end_ms, path.end_ms)):
            return None
        # Weak evidence away from a cut can support the surrounding search
        # without replacing an existing, compatible timing.
        shared.append(word)
    if any(first.end_ms > second.start_ms for first, second in zip(shared, shared[1:])):
        return None
    fixed_start = shared[len(left) - 1].end_ms
    fixed_end = shared[len(left)].start_ms
    if fixed_start >= fixed_end:
        return None
    try:
        asr_inner, official_inner = aligner.score_candidates(audio_path, fixed_start, fixed_end, readings, config)
    except (RuntimeError, ValueError):
        return None
    if not _valid_path(asr_inner, readings[0], fixed_start, fixed_end):
        asr_inner = AcousticCandidateEvidence(None)
    if not _valid_path(official_inner, readings[1], fixed_start, fixed_end):
        official_inner = AcousticCandidateEvidence(None)
    return ContextualComparison(
        start_ms, end_ms, fixed_start, fixed_end, readings, tuple(shared), asr_inner, official_inner,
        asr_path, official_path, asr_path.word_evidence[len(left):-len(right)],
        official_path.word_evidence[len(left):-len(right)], guided,
    )
