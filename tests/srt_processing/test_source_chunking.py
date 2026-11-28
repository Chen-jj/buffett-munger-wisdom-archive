from dataclasses import replace
from types import SimpleNamespace as NS

import pytest

from archive_core.interfaces.transcription import (
    SourceAlignmentDTO, SourceSentenceDTO, SourceSectionDTO, TimedWordDTO,
    MatchType, TextSource, TimingSource, BoundarySource, BoundaryStatus,
    reconstruct_sentence_text,
)
from archive_core.interfaces.bilingual import MediaBoundaryDTO, ProtectedSpanDTO
from srt_processing.domain.chunking import (
    build_source_chunks, SyntaxAnalysis, SyntaxBoundary, SyntaxSpan,
    evaluate_partition, _split_sentence, _PartitionScorer, _ordinary_grade,
)
from srt_processing.infrastructure.stanza_chunking import analyze_stanza_sentence


class Analyzer:
    identity = {"engine": "fake-syntax"}

    def __init__(self, protections=(), scores=None):
        self.calls = []
        self.protections, self.scores = protections, scores

    def analyze(self, words):
        self.calls.append(words)
        scores = self.scores if self.scores is not None else tuple((n, 3) for n in range(1, len(words)))
        tags = {0: "clause.independent", 1: "punctuation", 2: "phrase.preposition", 3: "ordinary"}
        return SyntaxAnalysis(tuple(SyntaxBoundary(n, (tags[value] if isinstance(value, int) else value,)) for n, value in scores), self.protections)


def alignment(specs, *, sections=(), speakers=None):
    words, sentences = [], []
    for number, (tokens, times) in enumerate(specs, 1):
        first = len(words)
        for token, (start, end) in zip(tokens, times):
            index = len(words) + 1
            words.append(TimedWordDTO(f"w{index}", token, start, end, (f"aw{index}",), (),
                                      MatchType.ASR_ONLY, TextSource.ASR, TimingSource.ACOUSTIC_ALIGNMENT))
        part = words[first:]
        sentences.append(SourceSentenceDTO(f"s{number}", part[0].id, part[-1].id, part[0].start_ms,
                                            part[-1].end_ms, reconstruct_sentence_text(part),
                                            (speakers or [None] * len(specs))[number - 1], TextSource.ASR,
                                            BoundarySource.FUSED_PUNCTUATION, BoundaryStatus.VERIFIED))
    return SourceAlignmentDTO("en", max(word.end_ms for word in words) + 1000, tuple(words), tuple(sentences), sections)


def build(source, analyzer=None, *, frames=tuple(range(0, 30000000, 40000)), protections=()):
    return build_source_chunks(asset_id="synthetic:test:source", alignment=source,
                               source_alignment_sha256="a" * 64,
                               media=MediaBoundaryDTO("b" * 64, source.audio_duration_ms, None if frames is None else tuple(value for value in frames if value < source.audio_duration_ms * 1000)),
                               analyzer=analyzer or Analyzer(), confirmed_protections=protections)


@pytest.mark.parametrize("length", [83, 84, 85])
def test_capacity_boundary_uses_all_codepoints(length):
    analyzer = Analyzer()
    plan = build(alignment([(["a" * length], [(0, 2000)])]), analyzer)
    assert len(analyzer.calls) == (length > 84)
    assert len(plan.chunks) == 1
    assert ("english.capacity" in plan.chunks[0].issues) == (length > 84)


@pytest.mark.parametrize("end", [7000, 7001])
def test_duration_alone_triggers_model(end):
    analyzer = Analyzer()
    plan = build(alignment([(["yes"], [(0, end)])]), analyzer)
    assert len(analyzer.calls) == (end > 7000)
    assert plan.chunks[0].base_end_ms == end


def test_cps_only_never_calls_model_or_splits_and_spaces_count():
    analyzer = Analyzer()
    plan = build(alignment([(["x" * 19, "y" * 20], [(0, 400), (400, 1000)])]), analyzer)
    assert not analyzer.calls and len(plan.chunks) == 1
    assert len(plan.chunks[0].english_text) == 40
    assert plan.chunks[0].issues == ("reading.english_cps",)


def test_split_uses_complete_sentence_and_exact_timing_and_protections():
    source = alignment([(["longword"] * 10, [(n * 500, n * 500 + 450) for n in range(10)])])
    protection = ProtectedSpanDTO("w3", "w5", "confirmed-name")
    analyzer = Analyzer((protection,))
    plan = build(source, analyzer)
    assert len(analyzer.calls) == 1 and analyzer.calls[0] == source.words
    assert all(len(chunk.english_text) <= 84 for chunk in plan.chunks)
    assert tuple(word for chunk in plan.chunks for word in chunk.word_ids) == tuple(word.id for word in source.words)
    assert not {"w3", "w4"} & {chunk.word_ids[-1] for chunk in plan.chunks[:-1]}
    assert all(chunk.start_ms == source.words[int(chunk.word_ids[0][1:])-1].start_ms for chunk in plan.chunks)


def test_protection_too_long_preserves_whole_sentence_with_warning():
    source = alignment([(["longword"] * 10, [(n * 500, n * 500 + 450) for n in range(10)])])
    plan = build(source, Analyzer((ProtectedSpanDTO("w1", "w10", "name"),)))
    assert len(plan.chunks) == 1 and "english.capacity" in plan.chunks[0].issues


def test_sample_s47_considers_canonical_commas_in_complete_sentence_analysis():
    expected = (
        "One of the most interesting things about the stretch is that,",
        "during pretty much the whole period,",
        "the company has owned marketable securities in excess of its net worth.",
    )
    # Relative canonical word anchors from the CNBC sample; no integration fixture needed.
    times = ((0, 60), (100, 140), (160, 240), (280, 420), (480, 920), (960, 1221),
             (1261, 1501), (1541, 1661), (1701, 2101), (2161, 2262), (2302, 2502),
             (2582, 2862), (2922, 3122), (3162, 3342), (3382, 3482), (3523, 3743),
             (3783, 4243), (5084, 5204), (5244, 5684), (5724, 5944), (6085, 6365),
             (7065, 7606), (7686, 8346), (9467, 9567), (9688, 10068), (10128, 10188),
             (10228, 10648), (10908, 11089), (11129, 11509))
    analyzer = Analyzer()
    plan = build(alignment([(" ".join(expected).split(), times)]), analyzer)
    assert len(analyzer.calls) == 1 and plan.analyzed_sentence_ids == ("s1",)
    assert tuple(word_id for chunk in plan.chunks for word_id in chunk.word_ids) == tuple(f"w{n}" for n in range(1, 30))
    assert all(len(chunk.english_text) <= 84 for chunk in plan.chunks)
    source_words = alignment([(" ".join(expected).split(), times)]).words
    positions = {word.id: word for word in source_words}
    assert all(chunk.start_ms == positions[chunk.word_ids[0]].start_ms
               and chunk.base_end_ms == positions[chunk.word_ids[-1]].end_ms for chunk in plan.chunks)


def test_sample_s9_fits_84_and_keeps_complete_sentence_without_artificial_short_cue():
    text = "I hope your question isn't going to be whether we can continue that, but go ahead."
    times = ((0, 40), (60, 180), (220, 340), (360, 720), (780, 960), (980, 1140),
             (1180, 1220), (1260, 1360), (1381, 1541), (1581, 1661), (1681, 1801),
             (1841, 2281), (2301, 2521), (2561, 2681), (2921, 2961), (2981, 3121))
    analyzer = Analyzer()
    plan = build(alignment([(text.split(), times)]), analyzer)
    assert not analyzer.calls
    assert [c.english_text for c in plan.chunks] == [text]
    assert "timing.minimum_duration" not in plan.chunks[0].issues
    assert (plan.chunks[0].start_ms, plan.chunks[0].base_end_ms) == (0, 3121)


@pytest.mark.parametrize("text,duration", [
    ("They will have bad years from time to time.", 2161),
    ("That doesn't bother us as long as the math is in our favor.", 2621),
    ("That doesn't mean we don't do it inadvertently and make mistakes, because we do.", 3282),
], ids=["s43", "s65", "s73-at-capacity"])
def test_sample_sentences_within_capacity_and_duration_do_not_cut(text, duration):
    tokens = text.split()
    times = [(i * duration // len(tokens), (i + 1) * duration // len(tokens)) for i in range(len(tokens))]
    analyzer = Analyzer()
    plan = build(alignment([(tokens, times)]), analyzer)
    assert not analyzer.calls
    assert [chunk.english_text for chunk in plan.chunks] == [text]
    assert plan.chunks[0].issues == (("reading.english_cps",) if len(text) * 1000 > 20 * duration else ())


def test_comma_grouping_skips_a_cut_that_would_create_an_avoidable_short_fragment():
    tokens = ["a" * 24 + ",", "b" * 27 + ",", "c" * 30 + "."]
    analyzer = Analyzer()
    plan = build(alignment([(tokens, [(0, 400), (440, 1550), (1600, 3000)])]), analyzer)
    assert len(analyzer.calls) == 1
    assert [chunk.word_ids for chunk in plan.chunks] == [("w1", "w2"), ("w3",)]


def test_duration_trigger_analyzes_complete_sentence_even_with_comma():
    analyzer = Analyzer()
    plan = build(alignment([(["First,", "second."], [(0, 3900), (4100, 8000)])]), analyzer)
    assert len(analyzer.calls) == 1
    assert [chunk.english_text for chunk in plan.chunks] == ["First,", "second."]


def test_inadequate_comma_plan_is_not_committed_before_complete_syntax_analysis():
    source = alignment([(["head,", "x" * 43, "y" * 43], [(0, 1000), (1100, 2100), (2200, 3200)])])
    analyzer = Analyzer()
    plan = build(source, analyzer)
    assert analyzer.calls == [source.words]
    assert [c.word_ids for c in plan.chunks] == [("w1", "w2"), ("w3",)]


@pytest.mark.parametrize("numeric", [("1,000",), ("1,", "000")])
def test_numeric_comma_is_not_a_cut_in_either_pass(numeric):
    tokens = ["a" * 42, *numeric, "z" * 40]
    source = alignment([(tokens, [(n * 1100, n * 1100 + 1000) for n in range(len(tokens))])])
    # Prefer the numeric-comma boundary if it were allowed by syntax fallback.
    analyzer = Analyzer(scores=((2, 0),) if len(numeric) == 1 else ((2, 0), (len(tokens) - 1, 1)))
    plan = build(source, analyzer)
    assert analyzer.calls == [source.words] and plan.analyzed_sentence_ids == ("s1",)
    assert plan.chunks[0].word_ids == tuple(w.id for w in source.words[:-1])
    if len(numeric) == 2:
        assert plan.protected_spans == (ProtectedSpanDTO("w2", "w3", "canonical.numeric-comma.v1"),)


def test_confirmed_span_blocks_a_comma_and_syntax_receives_complete_sentence():
    tokens = ["a" * 42 + ",", "b" * 27, "c" * 27]
    source = alignment([(tokens, [(n * 1100, n * 1100 + 1000) for n in range(len(tokens))])])
    protection = ProtectedSpanDTO("w1", "w2", "confirmed")
    analyzer = Analyzer(scores=((1, 0), (2, 2)))
    plan = build(source, analyzer, protections=(protection,))
    assert analyzer.calls == [source.words]
    assert plan.protected_spans == (protection,)
    assert [chunk.word_ids for chunk in plan.chunks] == [("w1", "w2"), ("w3",)]


def test_syntax_prefers_a_complete_partition_without_an_avoidable_short_chunk():
    tokens = ["if", "a" * 41, "b" * 19, "z" * 21]
    source = alignment([(tokens, [(0, 100), (120, 1520), (1560, 2760), (2800, 3920)])])
    plan = build(source, Analyzer(scores=((1, 0), (2, 2))))
    assert len(plan.chunks) == 2
    assert all(chunk.base_end_ms - chunk.start_ms >= 834 for chunk in plan.chunks)


@pytest.mark.parametrize("scores,first_chunk", [
    (((1, 2), (2, 2)), ("w1", "w2")),
    (((1, 0), (2, 2)), ("w1",)),
])
def test_syntax_prefers_a_larger_source_gap_only_when_other_scores_tie(scores, first_chunk):
    source = alignment([(["a" * 30] * 3, [(0, 2000), (2010, 4010), (4430, 6430)])])
    plan = build(source, Analyzer(scores=scores))
    assert plan.chunks[0].word_ids == first_chunk


@pytest.mark.parametrize("mode", ["repair", "protected", "missing-pts", "not-both-tight", "capacity", "cps"])
def test_typed_dp_never_replaces_better_structural_boundaries_for_framegap_alone(mode):
    tokens = ["a" * (50 if mode == "capacity" else 35), "b" * 35, "c" * 35, "d" * 35]
    start = 200 if mode == "cps" else 0
    second_start = 1880 if mode == "not-both-tight" else 1840
    source = alignment([(tokens, [(start, 1800), (second_start, 3640), (4040, 5840), (5880, 7680)])])
    protected = (ProtectedSpanDTO("w2", "w3", "confirmed-name"),) if mode == "protected" else ()
    analyzer = Analyzer(scores=((1, 0), (2, "subject.predicate"), (3, 0)))
    frames = None if mode == "missing-pts" else tuple(range(0, 9000000, 40000))
    plan = build(source, analyzer, frames=frames, protections=protected)
    assert analyzer.calls == [source.words]
    assert [chunk.word_ids for chunk in plan.chunks] == [("w1",), ("w2", "w3"), ("w4",)]
    assert tuple(word_id for chunk in plan.chunks for word_id in chunk.word_ids) == tuple(w.id for w in source.words)
    assert all(len(chunk.english_text) <= 84 for chunk in plan.chunks)
    if mode == "repair":
        assert any("timing.short_frame_gap" in chunk.issues for chunk in plan.chunks)


@pytest.mark.parametrize("gap,merged", [(499, True), (500, False), (501, False)])
def test_cross_sentence_gap_strict_limit(gap, merged):
    plan = build(alignment([(["Yes."], [(0, 400)]), (["Fine."], [(400 + gap, 1000 + gap)])]))
    assert len(plan.chunks) == (1 if merged else 2)
    if merged:
        assert plan.chunks[0].sentence_ids == ("s1", "s2")


@pytest.mark.parametrize("specs", [
    [(["x" * 78 + ",", "fine."], [(0, 4000), (4200, 5400)]), (["Yes."], [(5420, 5820)])],
    [(["Indeed."], [(0, 1000)]), (["fine,", "x" * 80], [(1020, 1320), (1350, 5450)])],
], ids=["previous-sentence-tail", "next-sentence-prefix"])
def test_short_rescue_does_not_merge_only_part_of_a_different_sentence(specs):
    plan = build(alignment(specs))
    assert len(plan.chunks) == 3
    assert all(len(chunk.sentence_ids) == 1 for chunk in plan.chunks)
    assert sum("timing.minimum_duration" in chunk.issues for chunk in plan.chunks) == 1


@pytest.mark.parametrize("end,merged", [(833, False), (834, True)])
def test_merge_minimum_duration_requires_full_intermediate_result(end, merged):
    plan = build(alignment([(["a"], [(0, 300)]), (["b"], [(300, end)])]))
    assert len(plan.chunks) == (1 if merged else 2)


def test_three_short_blocks_not_searched_as_single_rescue():
    plan = build(alignment([(["a"], [(0, 300)]), (["b"], [(300, 600)]), (["c"], [(600, 900)])]))
    assert len(plan.chunks) == 3


def test_merge_rejects_cps_and_tries_other_neighbor():
    source = alignment([(["x" * 21], [(0, 1000)]), (["y"], [(1010, 1110)]), (["z"], [(1200, 2200)])])
    plan = build(source)
    assert [chunk.word_ids for chunk in plan.chunks] == [("w1",), ("w2", "w3")]


def test_merge_same_objective_tie_uses_stable_cut_offsets_and_advances():
    source = alignment([(["a"], [(0, 1000)]), (["b"], [(1100, 1200)]), (["c"], [(1300, 2300)])])
    plan = build(source)
    assert [chunk.word_ids for chunk in plan.chunks] == [("w1",), ("w2", "w3")]


def test_known_speakers_cannot_be_bridged_by_unknown():
    source = alignment([(["a"], [(0, 1000)]), (["b"], [(1100, 1200)]), (["c"], [(1300, 2300)])], speakers=["A", None, "B"])
    plan = build(source)
    assert not any(len(chunk.word_ids) == 3 for chunk in plan.chunks)


def test_sections_never_merge():
    sections = (SourceSectionDTO("sec1", "one", "s1", "s1"), SourceSectionDTO("sec2", "two", "s2", "s2"))
    plan = build(alignment([(["Yes."], [(0, 400)]), (["Fine."], [(500, 1200)])], sections=sections))
    assert len(plan.chunks) == 2


def test_budget_is_readonly_caps_extension_and_uses_actual_frames():
    source = alignment([(["One."], [(0, 1000)]), (["Two."], [(1600, 2600)])])
    plan = build(source)
    assert plan.chunks[0].budget.extension_ms == 500
    assert plan.chunks[0].budget.base_units == 9
    assert plan.chunks[0].budget.maximum_units == 13
    assert plan.chunks[0].base_end_ms == 1000
    assert build(source, frames=None).chunks[0].budget.extension_ms == 0
    assert "timing.frame_gap_unverified" in build(source, frames=None).chunks[0].issues


def test_syntax_failures_are_not_converted_to_punctuation_fallback():
    class Broken(Analyzer):
        def analyze(self, words):
            raise ValueError("model failed")
    with pytest.raises(ValueError, match="model failed"):
        build(alignment([(["x" * 85], [(0, 2000)])]), Broken())


def tree(label, *children):
    return NS(label=label, children=list(children))


def test_stanza_scores_keep_a_verb_and_pp_together_before_coordinated_vps():
    tagged = [("The", "DT"), ("Earth", "NNP"), ("revolves", "VBZ"), ("around", "IN"),
              ("the", "DT"), ("sun", "NN"), ("and", "CC"), ("circles", "VBZ"), ("stars", "NNS")]
    source = alignment([([text for text, _ in tagged], [(n * 400, n * 400 + 350) for n in range(9)])])
    offset = 0
    tokens = []
    for text, tag in tagged:
        end = offset + len(text)
        tokens.append(NS(text=text, start_char=offset, end_char=end, words=[NS(text=text, xpos=tag)]))
        offset = end + 1
    the, earth, revolves, around, article, sun, and_, circles, stars = (
        tree(tag, tree(text)) for text, tag in tagged
    )
    parse = tree("ROOT", tree("S", tree("NP", the, earth), tree("VP",
        tree("VP", revolves, tree("PP", around, tree("NP", article, sun))), and_,
        tree("VP", circles, tree("NP", stars)),
    )))
    result = analyze_stanza_sentence(source.words, NS(sentences=[NS(tokens=tokens, constituency=parse)]))
    relations = {boundary.offset: boundary.relations for boundary in result.boundaries}
    assert "clause.coordinate" in relations[6]
    assert "subject.predicate" in relations[2]
    assert "phrase.preposition" in relations[3]
    assert "connector.after" in relations[7]
    assert ProtectedSpanDTO("w4", "w6", "stanza.preposition-object-core.v2") in result.protected_spans
    assert not any(span.first_word_id == "w3" for span in result.protected_spans)  # A soft ranking, not a hard span.


def test_exact_token_mapping_handles_contraction_without_word_internal_boundary():
    source = alignment([(["I", "don't", "know."], [(0, 400), (400, 800), (800, 1500)])])
    tokens = [NS(text="I", start_char=0, end_char=1, words=[NS(text="I", xpos="PRP")]),
              NS(text="don't", start_char=2, end_char=7, words=[NS(text="do", xpos="VBP"), NS(text="n't", xpos="RB")]),
              NS(text="know", start_char=8, end_char=12, words=[NS(text="know", xpos="VB")]),
              NS(text=".", start_char=12, end_char=13, words=[NS(text=".", xpos=".")])]
    parse = tree("ROOT", tree("S", *[tree(tag, tree(value)) for value, tag in [("I", "PRP"), ("do", "VBP"), ("n't", "RB"), ("know", "VB"), (".", ".")]]))
    document = NS(sentences=[NS(tokens=tokens, constituency=parse)])
    result = analyze_stanza_sentence(source.words, document)
    assert {boundary.offset for boundary in result.boundaries} == {1, 2}
    assert ProtectedSpanDTO("w2", "w3", "stanza.auxiliary-negation-verb.v2") in result.protected_spans
    tokens[1].end_char = 6
    with pytest.raises(ValueError, match="spans"):
        analyze_stanza_sentence(source.words, document)


def test_asr_provider_ids_do_not_become_cue_or_sentence_boundaries():
    source = alignment([(["If", "prices", "rise."], [(0, 500), (500, 1000), (1000, 2000)])])
    replaced = replace(source, words=tuple(replace(word, asr_word_ids=(f"other{index}",)) for index, word in enumerate(source.words, 1)))
    assert build(source).chunks == build(replaced).chunks


def typed(words, relations=None, spans=(), protections=()):
    return SyntaxAnalysis(tuple(SyntaxBoundary(n, (relations or {}).get(n, ("clause.independent",)))
                                for n in range(1, len(words))), protections, spans)


def test_strong_dependency_cannot_be_redeemed_by_fewer_cues_or_a_larger_gap():
    source = alignment([(["a" * 30] * 4, [(0, 2000), (2020, 4020), (6020, 8020), (8040, 10040)])])
    analysis = typed(source.words, {2: ("predicate.complement", "punctuation")})
    media = MediaBoundaryDTO("b" * 64, source.audio_duration_ms, tuple(range(0, source.audio_duration_ms * 1000, 40000)))
    parts = _split_sentence(source.words, analysis, (), stanza_media=media)
    assert tuple(len(part) for part in parts) == (1, 2, 1)
    assert evaluate_partition(source.words, parts, analysis, media)[0] == 0
    bad = (source.words[:2], source.words[2:])
    assert evaluate_partition(source.words, bad, analysis, media)[0] == 1


def test_one_boundary_with_multiple_structural_labels_is_charged_once():
    source = alignment([(["one", "two"], [(0, 1000), (3000, 4000)])])
    analysis = typed(source.words, {1: ("predicate.complement", "noun.infinitive", "clause.relative",
                                       "evidence.relative.no-comma", "punctuation")})
    score = evaluate_partition(source.words, (source.words[:1], source.words[1:]), analysis)
    assert score[:2] == (1, 0)
    assert score[4:7] == (0, 0, 0)
    assert score[10] == 0  # Neither punctuation nor a long gap buys back the dependency.


def test_cue_mixing_a_dependent_tail_and_new_statement_is_worse_than_three_cues():
    source = alignment([(["word"] * 6, [(n * 1000, (n + 1) * 1000) for n in range(6)])])
    analysis = typed(source.words, spans=(SyntaxSpan(0, 2, "statement"), SyntaxSpan(2, 4, "adverbial"),
                                        SyntaxSpan(4, 6, "statement")))
    mixed = (source.words[:2], source.words[2:])
    complete = (source.words[:2], source.words[2:4], source.words[4:])
    assert evaluate_partition(source.words, complete, analysis) < evaluate_partition(source.words, mixed, analysis)
    assert evaluate_partition(source.words, mixed, analysis)[0] == 1


def test_two_complete_short_statements_in_one_cue_are_not_mixed_fragments():
    source = alignment([(["Yes.", "Fine."], [(0, 1000), (1100, 2100)])])
    analysis = typed(source.words, spans=(SyntaxSpan(0, 1, "statement"), SyntaxSpan(1, 2, "statement")))
    assert evaluate_partition(source.words, (source.words,), analysis)[:2] == (0, 0)


@pytest.mark.parametrize("duration,high,short,deficit", [(100, 1, 1, 734), (249, 1, 1, 585),
                                                        (250, 0, 1, 584), (833, 0, 1, 1), (834, 0, 0, 0)])
def test_flash_shortness_and_deficit_have_explicit_separate_boundaries(duration, high, short, deficit):
    source = alignment([(["Yes."], [(0, duration)])])
    score = evaluate_partition(source.words, (source.words,), typed(source.words))
    assert (score[0], score[2], score[3]) == (high, short, deficit)
    plan = build(source)
    assert len(plan.chunks) == 1 and plan.chunks[0].base_end_ms == duration


def test_micro_gap_differences_in_same_actual_frame_band_do_not_decide():
    scores = []
    for gap in (160, 200):
        source = alignment([(["One.", "Two."], [(0, 1000), (1000 + gap, 2000 + gap)])])
        media = MediaBoundaryDTO("b" * 64, source.audio_duration_ms,
                                 tuple(range(0, source.audio_duration_ms * 1000, 40000)))
        scores.append(evaluate_partition(source.words, (source.words[:1], source.words[1:]), typed(source.words), media))
    assert scores[0] == scores[1]
    assert scores[0][10] == -1


def test_pause_reward_uses_real_frames_not_ms_and_never_rewards_an_unverified_gap():
    source = alignment([(["One.", "Two."], [(0, 1000), (1200, 2200)])])
    analysis = typed(source.words)
    irregular = MediaBoundaryDTO("b" * 64, source.audio_duration_ms, (0, 1000000, 1100000, 1200000))
    parts = (source.words[:1], source.words[1:])
    assert evaluate_partition(source.words, parts, analysis, irregular)[10] == 0
    assert evaluate_partition(source.words, parts, analysis, MediaBoundaryDTO("b" * 64, source.audio_duration_ms, None))[10] == 0


def test_relative_pause_mad_needs_eight_samples_nonzero_spread_and_is_capped():
    gaps = (0, 0, 1, 1, 2, 2, 3, 8)
    times, start = [], 0
    for gap in (*gaps, 0):
        times.append((start, start + 1000))
        start += 1000 + gap * 40
    source = alignment([(["word"] * len(times), times)])
    media = MediaBoundaryDTO("b" * 64, source.audio_duration_ms,
                             tuple(range(0, source.audio_duration_ms * 1000, 40000)))
    scorer = _PartitionScorer(source.words, typed(source.words), media)
    fixed = _PartitionScorer(source.words, typed(source.words), media, use_relative_gap=False)
    assert scorer.relative_mad > 0
    assert scorer.pause_reward(8, 0) == 2 and fixed.pause_reward(8, 0) == 1
    assert scorer.pause_reward(8, 2) == 0
    short = _PartitionScorer(source.words[:8], typed(source.words[:8]), media)
    assert short.relative_center is None
    equal = alignment([(["word"] * 9, [(n * 1000, (n + 1) * 1000) for n in range(9)])])
    constant = _PartitionScorer(equal.words, typed(equal.words), media)
    assert constant.relative_mad == 0
    assert constant.pause_reward(1, 0) == 0


def test_short_rescue_compares_external_neighbors_in_the_same_global_objective():
    source = alignment([(["aaaaaaa"], [(0, 1000)]), (["b"], [(1020, 1120)]),
                        (["ccc"], [(1140, 2140)])])
    plan = build(source)
    assert [chunk.word_ids for chunk in plan.chunks] == [("w1",), ("w2", "w3")]


def test_malformed_or_duplicate_typed_boundary_fails_instead_of_silently_scoring_it():
    source = alignment([(["longword"] * 11, [(n * 1000, n * 1000 + 900) for n in range(11)])])
    for boundaries in (((1, 0),), (SyntaxBoundary(1, ("ordinary",)), SyntaxBoundary(1, ("punctuation",)))):
        with pytest.raises(ValueError, match="typed canonical"):
            _split_sentence(source.words, SyntaxAnalysis(boundaries, ()), ())


def exhaustive_oracle(words, *, strong=(), forbidden=(), grades=None, reading=True, rhythm=True):
    """Independent small-input specification: enumerate every partition, not DP costs."""
    from itertools import product

    choices = []
    for cuts_mask in product((False, True), repeat=len(words) - 1):
        cuts = tuple(n for n, cut in enumerate(cuts_mask, 1) if cut) + (len(words),)
        if any(cut in forbidden for cut in cuts[:-1]):
            continue
        previous, lengths, durations = 0, [], []
        for cut in cuts:
            lengths.append(len(" ".join(word.text for word in words[previous:cut])))
            durations.append(words[cut - 1].end_ms - words[previous].start_ms)
            previous = cut
        if any(length > 84 for length in lengths) or any(duration > 7000 for duration in durations):
            continue
        excess = [max(0, length * 1000 - 20 * duration) if reading else 0
                  for length, duration in zip(lengths, durations)]
        ordinary = [(grades or {}).get(cut, 0) for cut in cuts[:-1] if cut not in strong]
        score = (sum(cut in strong for cut in cuts[:-1]) + sum(duration < 250 for duration in durations),
                 0, sum(duration < 834 for duration in durations),
                 sum(max(0, 834 - duration) for duration in durations),
                 sum(grade == 3 for grade in ordinary), sum(grade == 2 for grade in ordinary),
                 sum(grade == 1 for grade in ordinary), sum(value > 0 for value in excess), sum(excess), len(cuts), 0,
                 sum(abs(a - b) for a, b in zip(lengths, lengths[1:])) if rhythm else 0,
                 sum(length * length for length in lengths), cuts)
        choices.append((score, cuts))
    return min(choices)


@pytest.mark.parametrize("reading,rhythm", [(True, True), (True, False), (False, True), (False, False)])
def test_second_order_dp_matches_independent_exhaustive_oracle(reading, rhythm):
    import random

    randomizer = random.Random(1213)
    for _ in range(20):
        lengths = [randomizer.randrange(12, 40) for _ in range(8)]
        source = alignment([(["x" * n for n in lengths], [(n * 1000, n * 1000 + 900) for n in range(8)])])
        analysis = typed(source.words, {1: ("punctuation",), 2: ("predicate.complement",),
                                         4: ("ordinary",), 5: ("clause.interrogative",), 6: ("phrase.preposition",)},
                         protections=(ProtectedSpanDTO("w3", "w4", "confirmed-name"),))
        parts = _split_sentence(source.words, analysis, (), use_gap=False,
                                use_reading=reading, use_rhythm=rhythm)
        oracle, cuts = exhaustive_oracle(source.words, strong=(2,), forbidden=(3,), grades={1: 1, 4: 2, 6: 2},
                                        reading=reading, rhythm=rhythm)
        assert evaluate_partition(source.words, parts, analysis, use_gap=False,
                                  use_reading=reading, use_rhythm=rhythm) == oracle
        assert tuple(sum(len(part) for part in parts[:n]) for n in range(1, len(parts) + 1)) == cuts


def test_rhythm_counterexample_requires_the_previous_cue_in_dp_state():
    lengths = [24, 18, 28, 16, 29, 27, 14, 29]
    source = alignment([(["x" * n for n in lengths], [(n * 1000, n * 1000 + 900) for n in range(8)])])
    analysis = typed(source.words)
    parts = _split_sentence(source.words, analysis, (), use_gap=False, use_reading=False)
    score, cuts = exhaustive_oracle(source.words, reading=False)
    assert cuts == (3, 6, 8) and tuple(len(part) for part in parts) == (3, 3, 2)
    assert evaluate_partition(source.words, parts, analysis, use_gap=False, use_reading=False) == score
    # Collapsing the suffix to a single best(first) path loses this alternative:
    # suffix-internal balance favors (2,3,3), but its incoming transition is worse.
    first_order_trap = (source.words[:2], source.words[2:5], source.words[5:])
    wrong = evaluate_partition(source.words, first_order_trap, analysis, use_gap=False, use_reading=False)
    assert score[11] == 32 < wrong[11] == 35


def test_three_frame_gap_is_neutral_even_when_relative_mad_z_is_high():
    gaps = (0, 0, 0, 0, 1, 1, 1, 3)
    times, start = [], 0
    for gap in (*gaps, 0):
        times.append((start, start + 1000))
        start += 1000 + gap * 40
    source = alignment([(["word"] * len(times), times)])
    media = MediaBoundaryDTO("b" * 64, source.audio_duration_ms,
                             tuple(range(0, source.audio_duration_ms * 1000, 40000)))
    scorer = _PartitionScorer(source.words, typed(source.words), media)
    from math import log1p
    assert (log1p(3) - scorer.relative_center) / scorer.relative_mad >= 2
    assert scorer.pause_reward(8, 0) == 0


def test_whole_partition_rescue_retains_each_original_sentences_relative_gap_context():
    specs, start = [], 0
    for gaps in ((0, 0, 1, 1, 2, 2, 3, 8), (30, 40, 50, 60, 70, 80, 90, 100)):
        times = []
        for gap in (*gaps, 5):
            times.append((start, start + 1000))
            start += 1000 + gap * 40
        specs.append((["word"] * 9, times))
    source = alignment(specs)
    media = MediaBoundaryDTO("b" * 64, source.audio_duration_ms,
                             tuple(range(0, source.audio_duration_ms * 1000, 40000)))
    global_scorer = _PartitionScorer(source.words, typed(source.words), media, sentence_ranges=((0, 9), (9, 18)))
    for offset in (0, 9):
        words = source.words[offset:offset + 9]
        local = _PartitionScorer(words, typed(words), media)
        for boundary in range(1, 9):
            assert global_scorer.pause_reward(offset + boundary, 0) == local.pause_reward(boundary, 0)
    assert 9 not in global_scorer.relative_stats  # Cross-sentence gaps only use the fixed frame band.


def test_long_soft_dependency_remains_a_legal_candidate_when_capacity_requires_it():
    source = alignment([(["x" * 50] * 3, [(n * 2000, n * 2000 + 1800) for n in range(3)])])
    analysis = typed(source.words, {1: ("noun.infinitive",),
                                     2: ("clause.relative", "evidence.relative.no-comma")})
    parts = _split_sentence(source.words, analysis, ())
    assert tuple(len(part) for part in parts) == (1, 1, 1)
    assert evaluate_partition(source.words, parts, analysis)[0] == 2


def test_new_statement_prefix_and_subject_predicate_at_same_cut_are_one_event():
    source = alignment([(["word"] * 4, [(n * 1000, (n + 1) * 1000) for n in range(4)])])
    analysis = typed(source.words, {3: ("subject.predicate",)},
                         spans=(SyntaxSpan(0, 2, "statement"), SyntaxSpan(2, 4, "statement")))
    parts = (source.words[:3], source.words[3:])
    score = evaluate_partition(source.words, parts, analysis)
    assert score[:2] == (1, 0)
    scorer = _PartitionScorer(source.words, analysis, None)
    assert scorer.cost(0, 3)[0] == 0  # No fee on the left cue's end.
    assert scorer.cost(3, 4, 0)[0] == 1  # Both labels belong to the cut at 3.


def test_mixed_middle_cue_causes_two_independent_cut_events_not_one_cue_maximum():
    source = alignment([(["word"] * 6, [(n * 1000, (n + 1) * 1000) for n in range(6)])])
    analysis = typed(source.words, {1: ("subject.predicate",), 5: ("predicate.complement",)},
                         spans=(SyntaxSpan(0, 2, "statement"), SyntaxSpan(2, 4, "statement"),
                                SyntaxSpan(4, 6, "statement")))
    parts = (source.words[:1], source.words[1:5], source.words[5:])
    assert evaluate_partition(source.words, parts, analysis)[:2] == (2, 0)
    scorer = _PartitionScorer(source.words, analysis, None)
    assert scorer.cost(1, 5, 0)[0] == 1
    assert scorer.cost(5, 6, 1)[0] == 1


def test_flash_and_structural_cut_are_independent_events_even_on_one_cue():
    source = alignment([(["word", "Yes."], [(0, 1000), (1000, 1100)])])
    analysis = typed(source.words, {1: ("subject.predicate",)})
    assert evaluate_partition(source.words, (source.words[:1], source.words[1:]), analysis)[0] == 2


def cut_interaction_oracle(words, statements, strong=(), general=(), *, grades=None, reading=True, rhythm=True):
    """Independent cut-based specification with left/right cue interaction."""
    from itertools import product

    choices = []
    for bits in product((False, True), repeat=len(words) - 1):
        cuts = (0,) + tuple(n for n, bit in enumerate(bits, 1) if bit) + (len(words),)
        lengths = [len(" ".join(word.text for word in words[a:b])) for a, b in zip(cuts, cuts[1:])]
        durations = [words[b - 1].end_ms - words[a].start_ms for a, b in zip(cuts, cuts[1:])]
        if any(length > 84 for length in lengths) or any(duration > 7000 for duration in durations):
            continue
        levels = []
        for previous, cut, following in zip(cuts, cuts[1:], cuts[2:]):
            left_head = any(previous < start < cut < end for start, end in statements)
            right_tail = (any(start < cut < end for start, end in statements)
                          and any(cut < start < following for start, end in statements))
            levels.append(2 if cut in strong or left_head or right_tail else (1 if cut in general else 0))
        excess = [max(0, length * 1000 - 20 * duration) if reading else 0
                  for length, duration in zip(lengths, durations)]
        ordinary = [(grades or {}).get(cut, 0) for cut, level in zip(cuts[1:-1], levels) if not level]
        score = (sum(level == 2 for level in levels) + sum(duration < 250 for duration in durations),
                 sum(level == 1 for level in levels), sum(duration < 834 for duration in durations),
                 sum(max(0, 834 - duration) for duration in durations),
                 sum(grade == 3 for grade in ordinary), sum(grade == 2 for grade in ordinary),
                 sum(grade == 1 for grade in ordinary), sum(value > 0 for value in excess), sum(excess), len(lengths), 0,
                 sum(abs(a - b) for a, b in zip(lengths, lengths[1:])) if rhythm else 0,
                 sum(length * length for length in lengths), cuts[1:])
        choices.append((score, cuts))
    return min(choices)


@pytest.mark.parametrize("reading,rhythm", [(True, True), (True, False), (False, True), (False, False)])
@pytest.mark.parametrize("general_relation", [
    "noun.clause", "attachment.nominal-of", "attachment.coordination", "attachment.scope",
    "attachment.frequency", "attachment.temporal", "attachment.adjectival",
])
def test_second_order_dp_matches_cut_interaction_oracle_without_global_dedup_sets(reading, rhythm, general_relation):
    import random

    randomizer = random.Random(1413)
    statements = ((0, 2), (2, 5), (5, 8))
    for _ in range(15):
        lengths = [randomizer.randrange(9, 35) for _ in range(8)]
        source = alignment([(["x" * n for n in lengths], [(n * 1000, n * 1000 + 900) for n in range(8)])])
        analysis = typed(source.words, {1: ("punctuation",), 3: ("subject.predicate",), 4: ("ordinary",),
                                         6: (general_relation,), 7: ("phrase.preposition",)},
                         spans=tuple(SyntaxSpan(first, last, "statement") for first, last in statements))
        oracle, cuts = cut_interaction_oracle(source.words, statements, strong=(3,), general=(6,),
                                               grades={1: 1, 4: 2, 7: 2}, reading=reading, rhythm=rhythm)
        parts = _split_sentence(source.words, analysis, (), use_gap=False,
                                use_reading=reading, use_rhythm=rhythm)
        assert evaluate_partition(source.words, parts, analysis, use_gap=False,
                                  use_reading=reading, use_rhythm=rhythm) == oracle
        assert tuple(sum(len(part) for part in parts[:n]) for n in range(len(parts) + 1)) == cuts


def test_quantity_attachment_is_general_structure_not_washed_away_by_punctuation():
    source = alignment([(["five,", "ten"], [(0, 1000), (1200, 2200)])])
    analysis = typed(source.words, {1: ("attachment.quantity", "evidence.quantity.enumeration", "punctuation")})
    parts = (source.words[:1], source.words[1:])
    score = evaluate_partition(source.words, parts, analysis)
    assert score[:2] == (0, 1)
    assert score[4:7] == (0, 0, 0)
    assert _PartitionScorer(source.words, analysis, None).pause_reward(1, 1) == 0


def test_long_quantity_attachment_is_soft_and_not_an_entire_list_hard_protection():
    source = alignment([(["x" * 50] * 3, [(n * 2000, n * 2000 + 1800) for n in range(3)])])
    analysis = typed(source.words, {1: ("attachment.quantity",), 2: ("attachment.quantity",)})
    parts = _split_sentence(source.words, analysis, ())
    assert tuple(len(part) for part in parts) == (1, 1, 1)
    assert evaluate_partition(source.words, parts, analysis)[:2] == (0, 2)


@pytest.mark.parametrize("marker", ["so", "And", "therefore", "as a result"])
def test_owned_marker_span_allows_a_later_split_but_marker_cannot_be_left_behind(marker):
    tokens = marker.split() + "the company will expand, and its patient shareholders will benefit over many years.".split()
    times, start = [], 0
    for n in range(len(tokens)):
        duration = 1000 if n == 0 else 400
        times.append((start, start + duration))
        start += duration
    source = alignment([(tokens, times)])
    marker_end, split = len(marker.split()), len(marker.split()) + 4
    analysis = typed(source.words, {marker_end: ("connector.after",), split: ("clause.coordinate",)},
                         spans=(SyntaxSpan(0, len(tokens), "statement"),))
    legitimate = (source.words[:split], source.words[split:])
    stranded_marker = (source.words[:marker_end], source.words[marker_end:])
    assert evaluate_partition(source.words, legitimate, analysis)[0] == 0
    assert evaluate_partition(source.words, stranded_marker, analysis)[0] == 1


@pytest.mark.parametrize("cuts", [(6,), (1,)])
def test_owned_connector_does_not_hide_true_old_statement_head_or_tail_mixing(cuts):
    source = alignment([(["word"] * 10, [(n * 1000, (n + 1) * 1000) for n in range(10)])])
    # The second statement includes its marker at 2, but must not swallow the old statement.
    analysis = typed(source.words, spans=(SyntaxSpan(0, 2, "statement"), SyntaxSpan(2, 10, "statement")))
    edges = (0,) + cuts + (len(source.words),)
    parts = tuple(source.words[first:last] for first, last in zip(edges, edges[1:]))
    assert evaluate_partition(source.words, parts, analysis)[0] == 1


def test_s16_shape_owned_and_allows_future_assuming_without_a_false_mixing_charge():
    tokens = "And there are going to be lots of years in the future assuming I live long enough, we will have plenty of down years.".split()
    source = alignment([(tokens, [(n * 400, (n + 1) * 400) for n in range(len(tokens))])])
    assuming, we = tokens.index("assuming"), tokens.index("we")
    analysis = typed(source.words, {1: ("connector.after",), assuming: ("clause.adverbial",)},
                         spans=(SyntaxSpan(0, we, "statement"), SyntaxSpan(assuming, we, "adverbial")))
    good = (source.words[:assuming], source.words[assuming:])
    bad = (source.words[:1], source.words[1:assuming], source.words[assuming:])
    assert evaluate_partition(source.words, good, analysis)[0] == 0
    assert evaluate_partition(source.words, bad, analysis)[0] == 1


def test_unknown_boundaries_are_ordinary_two_not_an_observed_weak_relation():
    assert _ordinary_grade(("ordinary",)) == 2
    assert _ordinary_grade(("unrecognised.evidence",)) == 2
    assert _ordinary_grade(("phrase.preposition",)) == 2
    assert _ordinary_grade(("punctuation",)) == 1
    assert _ordinary_grade(("clause.independent",)) == 0
    # A known dependency remains in its independent structural tier, not this grade.
    source = alignment([(["one", "two"], [(0, 1000), (1000, 2000)])])
    analysis = typed(source.words, {1: ("subject.predicate", "punctuation")})
    assert evaluate_partition(source.words, (source.words[:1], source.words[1:]), analysis)[:2] == (1, 0)


def test_better_ordinary_syntax_can_win_over_lower_cps_burden_without_disabling_cps():
    from srt_processing.domain.chunking_policy import SCORE_FIELDS

    source = alignment([(["x" * 30] * 3, [(0, 2000), (2010, 3010), (3430, 5430)])])
    analysis = typed(source.words, {1: ("phrase.preposition",), 2: ("punctuation",)})
    syntax_good = (source.words[:2], source.words[2:])
    cps_good = (source.words[:1], source.words[1:])
    syntax_score = evaluate_partition(source.words, syntax_good, analysis, use_gap=False)
    cps_score = evaluate_partition(source.words, cps_good, analysis, use_gap=False)
    assert dict(zip(SCORE_FIELDS, syntax_score))["cps_exceed_cue_count"] == 1
    assert dict(zip(SCORE_FIELDS, cps_score))["cps_exceed_cue_count"] == 0
    assert syntax_score < cps_score
    assert _split_sentence(source.words, analysis, (), use_gap=False) == syntax_good


def test_cps_is_still_a_tiebreaker_when_the_syntax_tiers_are_equal():
    source = alignment([(["x" * 30] * 3, [(0, 2000), (2010, 3010), (3430, 5430)])])
    analysis = typed(source.words, {1: ("phrase.preposition",), 2: ("phrase.preposition",)})
    assert _split_sentence(source.words, analysis, (), use_gap=False) == (source.words[:1], source.words[1:])


def test_one_ordinary_unknown_cut_need_not_lose_to_three_prepositional_fragments():
    from srt_processing.domain.chunking_policy import SCORE_FIELDS

    source = alignment([(["x" * 30] * 4, [(n * 2000, (n + 1) * 2000) for n in range(4)])])
    analysis = typed(source.words, {1: ("phrase.preposition",), 2: ("ordinary",), 3: ("phrase.preposition",)})
    coherent = (source.words[:2], source.words[2:])
    fragments = tuple((word,) for word in source.words)
    score = evaluate_partition(source.words, coherent, analysis, use_gap=False)
    assert dict(zip(SCORE_FIELDS, score))["ordinary_grade3_count"] == 0
    assert dict(zip(SCORE_FIELDS, score))["ordinary_grade2_count"] == 1
    assert score < evaluate_partition(source.words, fragments, analysis, use_gap=False)
    assert _split_sentence(source.words, analysis, (), use_gap=False) == coherent


def test_interrogative_entry_is_low_and_uses_the_unchanged_ordered_fields():
    from srt_processing.domain.chunking_policy import SCORE_FIELDS, chunking_policy

    source = alignment([(["Question,", "would"], [(0, 1000), (1160, 2160)])])
    media = MediaBoundaryDTO("b" * 64, source.audio_duration_ms,
                             tuple(range(0, source.audio_duration_ms * 1000, 40000)))
    analysis = typed(source.words, {1: ("clause.interrogative", "punctuation")})
    score = evaluate_partition(source.words, (source.words[:1], source.words[1:]), analysis, media)
    named = dict(zip(SCORE_FIELDS, score))
    assert (named["high_impact_events"], named["ordinary_structure_events"],
            named["ordinary_grade1_count"], named["ordinary_grade2_count"]) == (0, 0, 0, 0)
    assert named["negative_pause_reward"] == -1
    assert chunking_policy()["score_fields"] == list(SCORE_FIELDS)
    assert SCORE_FIELDS.index("ordinary_grade1_count") < SCORE_FIELDS.index("cps_exceed_cue_count")


def test_interrogative_good_label_does_not_wash_away_a_true_strong_dependency():
    source = alignment([(["would", "you"], [(0, 1000), (1160, 2160)])])
    analysis = typed(source.words, {1: ("clause.interrogative", "subject.predicate", "punctuation")})
    assert evaluate_partition(source.words, (source.words[:1], source.words[1:]), analysis)[:2] == (1, 0)


def test_uncertain_noun_clause_stays_general_even_with_punctuation_and_good_label():
    source = alignment([(["claim,", "they"], [(0, 1000), (1160, 2160)])])
    analysis = typed(source.words, {1: ("noun.clause", "clause.interrogative", "punctuation")})
    assert evaluate_partition(source.words, (source.words[:1], source.words[1:]), analysis)[:2] == (0, 1)


def test_noun_clause_attachment_is_soft_when_capacity_requires_a_split():
    source = alignment([(["x" * 50] * 3, [(n * 2000, n * 2000 + 1800) for n in range(3)])])
    analysis = typed(source.words, {1: ("noun.clause",), 2: ("clause.interrogative",)})
    parts = _split_sentence(source.words, analysis, ())
    assert tuple(len(part) for part in parts) == (1, 1, 1)
    assert evaluate_partition(source.words, parts, analysis)[:2] == (0, 1)


def test_nominal_of_is_one_general_event_not_an_extra_preposition_or_punctuation_fee():
    source = alignment([(["rate", "of"], [(0, 1000), (1160, 2160)])])
    analysis = typed(source.words, {1: ("attachment.nominal-of", "phrase.preposition", "punctuation")})
    score = evaluate_partition(source.words, (source.words[:1], source.words[1:]), analysis)
    assert score[:2] == (0, 1)
    assert score[4:7] == (0, 0, 0)


def test_unannotated_verbal_or_other_preposition_boundary_is_not_a_nominal_attachment():
    source = alignment([(["think", "of"], [(0, 1000), (1160, 2160)])])
    analysis = typed(source.words, {1: ("phrase.preposition",)})
    score = evaluate_partition(source.words, (source.words[:1], source.words[1:]), analysis)
    assert score[:2] == (0, 0)
    assert score[4:7] == (0, 1, 0)


def test_long_nominal_of_attachment_is_still_a_legal_soft_cut_when_capacity_requires_it():
    source = alignment([(["x" * 50] * 3, [(n * 2000, n * 2000 + 1800) for n in range(3)])])
    analysis = typed(source.words, {1: ("attachment.nominal-of",), 2: ("attachment.nominal-of",)})
    parts = _split_sentence(source.words, analysis, ())
    assert tuple(len(part) for part in parts) == (1, 1, 1)
    assert evaluate_partition(source.words, parts, analysis)[:2] == (0, 2)
    assert tuple(word.id for part in parts for word in part) == tuple(word.id for word in source.words)


@pytest.mark.parametrize("relation", [
    "attachment.coordination", "attachment.scope", "attachment.frequency", "attachment.temporal",
    "attachment.adjectival",
])
def test_local_unit_attachment_is_one_general_event_and_never_overrides_strong_evidence(relation):
    source = alignment([(["left", "right"], [(0, 1000), (1160, 2160)])])
    analysis = typed(source.words, {1: (relation, "punctuation", "clause.independent")})
    parts = (source.words[:1], source.words[1:])
    score = evaluate_partition(source.words, parts, analysis)
    assert score[:2] == (0, 1)
    assert score[4:7] == (0, 0, 0)
    strong = typed(source.words, {1: (relation, "subject.predicate", "punctuation")})
    assert evaluate_partition(source.words, parts, strong)[:2] == (1, 0)


@pytest.mark.parametrize("relation", [
    "attachment.coordination", "attachment.scope", "attachment.frequency", "attachment.temporal",
    "attachment.adjectival",
])
def test_local_soft_attachment_does_not_become_a_long_hard_protection(relation):
    source = alignment([(["x" * 50] * 3, [(n * 2000, n * 2000 + 1800) for n in range(3)])])
    analysis = typed(source.words, {1: (relation,), 2: (relation,)})
    parts = _split_sentence(source.words, analysis, ())
    assert tuple(len(part) for part in parts) == (1, 1, 1)
    assert evaluate_partition(source.words, parts, analysis)[:2] == (0, 2)
    assert tuple(word.id for part in parts for word in part) == tuple(word.id for word in source.words)


@pytest.mark.parametrize("tokens", [("those", "times"), ("Times", "report"), ("from", "London"),
                                    ("income", "overseas"), ("actually,", "all"), ("related", "to"), ("proud", "of")])
def test_unannotated_words_do_not_invent_local_attachment_relations(tokens):
    source = alignment([(tokens, [(0, 1000), (1160, 2160)])])
    analysis = typed(source.words, {1: ("ordinary",)})
    assert evaluate_partition(source.words, (source.words[:1], source.words[1:]), analysis)[:2] == (0, 0)
