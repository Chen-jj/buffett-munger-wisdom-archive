"""Shared context must have one validated timing for both competing readings."""

from dataclasses import replace

from transcription.application.fusion_context import contextual_comparison
from transcription.domain import AlignedAsrWord, AlignmentTimingSource, OfficialAlignmentConfig
from transcription.domain.fusion_acoustics import AcousticCandidateEvidence, AcousticWordEvidence


def _aligned(index, text, start_ms, end_ms):
    return AlignedAsrWord(
        f"aw{index}", f"rw{index}", "seg1", text, start_ms, end_ms, 0.50,
        AlignmentTimingSource.ACOUSTIC_ALIGNMENT,
    )


def _path(likelihood, *words):
    return AcousticCandidateEvidence(
        likelihood, word_evidence=tuple(AcousticWordEvidence(*word) for word in words),
    )


class _Scorer:
    def __init__(self, paths):
        self.paths = paths
        self.calls = []

    def score_candidates(self, audio_path, start_ms, end_ms, readings, config):
        self.calls.append((start_ms, end_ms, readings))
        return tuple(self.paths[(start_ms, end_ms, reading)] for reading in readings)


_CONFIG = OfficialAlignmentConfig("local-model", "snapshot", "cpu")


def test_shared_context_intersects_candidate_paths_before_fixed_window_rescore():
    left = (_aligned(1, "put", 100, 400),)
    right = (_aligned(3, "or", 550, 750),)
    score = _Scorer({
        (0, 1000, "put a million or"): _path(-30,
            ("put", 100, 200, 0.90), ("a", 250, 300, 0.80),
            ("million", 320, 460, 0.30), ("or", 650, 820, 0.60)),
        (0, 1000, "put one million or"): _path(None),
        (0, 1000, "put a billion or"): _path(-10,
            ("put", 100, 200, 0.90), ("a", 250, 300, 0.80),
            ("billion", 320, 610, 0.98), ("or", 710, 820, 0.88)),
        (200, 710, "a million"): _path(-31,
            ("a", 250, 300, 0.80), ("million", 320, 460, 0.30)),
        (200, 710, "a billion"): _path(-9,
            ("a", 250, 300, 0.80), ("billion", 320, 610, 0.98)),
    })

    result = contextual_comparison(score, "audio", left, right, (
        ("a million", "a billion"), ("one million", "a billion"),
    ), 0, 1000, _CONFIG)

    assert result is not None and not result.context_refined_for_official
    assert score.calls == [
        (0, 1000, ("put a million or", "put one million or", "put a billion or")),
        (200, 710, ("a million", "a billion")),
    ]
    assert (result.start_ms, result.end_ms, result.official.ctc_log_likelihood) == (200, 710, -9)
    assert [(word.id, word.start_ms, word.end_ms) for word in result.shared] == [
        ("aw1", 100, 200), ("aw3", 710, 820),
    ]
    assert left[0].end_ms == 400 and right[0].start_ms == 550


def test_stable_full_reading_can_retime_one_disputed_interior_common_word():
    left = (_aligned(1, "business", 100, 200), _aligned(2, "that", 245, 550))
    right = (_aligned(3, "looks", 800, 900),)
    baseline = _path(-40, ("business", 95, 210, 0.85), ("that", 600, 680, 0.80), ("looks", 810, 900, 0.90))
    official = _path(-15, ("business", 95, 210, 0.86), ("that", 265, 350, 0.20),
        ("does", 415, 475, 0.87), ("not", 505, 585, 0.78), ("have", 605, 700, 0.88), ("looks", 810, 900, 0.96))
    paths = {
        (start, end, reading): path
        for start, end in ((0, 1000), (40, 1000), (0, 960))
        for reading, path in (
            ("business that looks", baseline),
            ("business that does not have looks", official),
        )
    }
    paths[350, 810, ""] = _path(-55)
    paths[350, 810, "does not have"] = _path(-8, *(
        (word.text, word.start_ms, word.end_ms, word.score) for word in official.word_evidence[2:5]
    ))
    scorer = _Scorer(paths)

    result = contextual_comparison(scorer, "audio", left, right, (("", "does not have"),), 0, 1000, _CONFIG)

    assert result is not None and result.context_refined_for_official
    assert result.shared[1].end_ms == 350 and result.shared[1].text == "that"
    assert result.official_context_difference == official.word_evidence[2:5]
    assert result.asr_context_difference == ()
    assert scorer.calls[-1] == (350, 810, ("", "does not have"))

    paths[40, 1000, "business that does not have looks"] = replace(official, ctc_log_likelihood=-41)
    scorer.calls.clear()
    assert contextual_comparison(scorer, "audio", left, right, (("", "does not have"),), 0, 1000, _CONFIG) is None
    assert len(scorer.calls) == 2


def test_refuses_missing_outer_anchor_or_window_over_budget():
    left = (_aligned(1, "that", 245, 550),)
    right = (_aligned(2, "looks", 800, 900),)
    score = _Scorer({
        (0, 1000, "that looks"): _path(-40, ("that", 600, 680, 0.80), ("looks", 810, 900, 0.90)),
        (0, 1000, "that does looks"): _path(-15,
            ("that", 265, 350, 0.21), ("does", 415, 475, 0.87), ("looks", 810, 900, 0.96)),
    })
    assert contextual_comparison(score, "audio", left, right, (("", "does"),), 0, 5001, _CONFIG) is None
    assert not score.calls
    assert contextual_comparison(score, "audio", left, right, (("", "does"),), 0, 1000, _CONFIG) is None
    assert len(score.calls) == 1
