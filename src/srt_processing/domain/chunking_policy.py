"""The single English source chunking policy (ADR-0013)."""

ENGLISH_MAX_CHARACTERS = 84
ENGLISH_CPS_LIMIT = 20
MIN_CHUNK_DURATION_MS = 834
MAX_CHUNK_DURATION_MS = 7000
CROSS_SENTENCE_MERGE_GAP_LIMIT_MS = 500
MAX_EXTENSION_MS = 500
CHINESE_CPS_LIMIT = 9
CHINESE_LINE_TARGET_UNITS = 16
FLASH_DURATION_MS = 250
GAP_NEUTRAL_MAX_FRAMES = 3
GAP_WEAK_MAX_FRAMES = 8
GAP_RELATIVE_MIN_SAMPLES = 8
GAP_RELATIVE_WEAK_Z = 2
GAP_RELATIVE_STRONG_Z = 3
SCORE_FIELDS = (
    "high_impact_events", "ordinary_structure_events", "short_cue_count", "shortfall_ms",
    "ordinary_grade3_count", "ordinary_grade2_count", "ordinary_grade1_count",
    "cps_exceed_cue_count", "cps_excess_burden", "cue_count", "negative_pause_reward",
    "adjacent_character_rhythm", "squared_character_load",
)


def chunking_policy() -> dict[str, object]:
    return {
        "version": "english-typed-cue-dp.v8",
        "english_counting": "unicode-codepoints-with-spaces.v1",
        "chinese_counting": "unicode14-latin-word.v2",
        "english_max_characters": ENGLISH_MAX_CHARACTERS,
        "english_cps_limit": ENGLISH_CPS_LIMIT,
        "minimum_duration_ms": MIN_CHUNK_DURATION_MS,
        "maximum_duration_ms": MAX_CHUNK_DURATION_MS,
        "cross_sentence_merge_gap_limit_ms": CROSS_SENTENCE_MERGE_GAP_LIMIT_MS,
        "maximum_extension_ms": MAX_EXTENSION_MS,
        "chinese_cps_limit": CHINESE_CPS_LIMIT,
        "chinese_line_target_units": CHINESE_LINE_TARGET_UNITS,
        "boundary_ranking": "typed-cut-anchor-local-units-adjectival-short-syntax-ordinary2-cps-count-pause-rhythm-headroom-offset.v8",
        "score_fields": list(SCORE_FIELDS),
        "ordinary_default_grade": 2,
        "flash_duration_ms": FLASH_DURATION_MS,
        "gap_ranking": {"neutral_max_frames": GAP_NEUTRAL_MAX_FRAMES, "weak_max_frames": GAP_WEAK_MAX_FRAMES,
                        "relative_minimum_samples": GAP_RELATIVE_MIN_SAMPLES, "relative_z": [GAP_RELATIVE_WEAK_Z, GAP_RELATIVE_STRONG_Z],
                        "relative_statistic": "log1p-frame-median-mad-unscaled.v1", "maximum_boundary_reward": 2},
        "rhythm_ranking": "second-order-previous-span-absolute-character-difference.v2",
        "short_merge_order": "cross-sentence-complete-only;same-objective-strict-improvement;advance-past-result.v3",
    }
