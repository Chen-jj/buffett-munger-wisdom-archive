"""Current source analysis never uses jieba or falls back to another parser."""
from srt_processing.infrastructure.stanza_chunking import STANZA_VERSION
from srt_processing.domain.chunking_policy import chunking_policy


def test_selected_syntax_library_and_counting_policy_are_versioned():
    assert STANZA_VERSION == "1.11.0"
    policy = chunking_policy()
    assert policy["version"] == "english-typed-cue-dp.v8"
    assert policy["boundary_ranking"] == (
        "typed-cut-anchor-local-units-adjectival-short-syntax-ordinary2-cps-count-pause-rhythm-headroom-offset.v8"
    )
    assert policy["english_max_characters"] == 84
    assert policy["english_counting"] == "unicode-codepoints-with-spaces.v1"


def test_actual_ordered_score_fields_are_bound_to_the_single_policy_identity():
    from srt_processing.domain.chunking_policy import SCORE_FIELDS

    expected = (
        "high_impact_events", "ordinary_structure_events", "short_cue_count", "shortfall_ms",
        "ordinary_grade3_count", "ordinary_grade2_count", "ordinary_grade1_count",
        "cps_exceed_cue_count", "cps_excess_burden", "cue_count", "negative_pause_reward",
        "adjacent_character_rhythm", "squared_character_load",
    )
    assert SCORE_FIELDS == expected
    assert chunking_policy()["score_fields"] == list(expected)
    assert chunking_policy()["ordinary_default_grade"] == 2
