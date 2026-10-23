from __future__ import annotations

from dataclasses import astuple, replace
from fractions import Fraction
import json

import pytest

from archive_core.interfaces import (
    BoundarySource, BoundaryStatus, MatchType, SectionTitleTranslationDTO,
    SentenceTranslationDTO, SourceAlignmentDTO, SourceSectionDTO, SourceSentenceDTO,
    SubtitleCueDTO, SubtitleFragmentDTO, SubtitleMediaDTO, SubtitlePlanDTO,
    TextSource, TimedWordDTO, TimingSource, TranslationResultDTO,
    character_boundaries, normalize_chinese_text, reconstruct_sentence_text,
)
from srt_processing.domain import planner
from srt_processing.domain.planner import (
    D39Cost, PlanningError, analyze_plan as _analyze_plan, plan_subtitles, validate_plan as _validate_plan,
)
from srt_processing.domain.rules import adjust_cue_timing, chinese_half_units, english_characters, rules_identity


SHA = "a" * 64


def segmentation(translation):
    """Explicit offline fake; segmentation quality gets separate span tests."""
    return {item.sentence_id: tuple((index, index + 1) for index in range(len(normalize_chinese_text(item.translated_text))))
            for item in translation.sentence_translations}


def validate_plan(plan, alignment, translation):
    return _validate_plan(plan, alignment, translation, chinese_word_spans=segmentation(translation))


def analyze_plan(plan, alignment, translation):
    return _analyze_plan(plan, alignment, translation, chinese_word_spans=segmentation(translation))


def inputs(texts, chinese, *, duration=600, word_gap=0, sentence_gap=0,
           speakers=None, section_sizes=(), times=None):
    words, sentences = [], []
    current = 100
    for index, sentence_words in enumerate(texts):
        first = len(words)
        for text in sentence_words:
            start, end = times[len(words)] if times is not None else (current, current + duration)
            position = len(words) + 1
            words.append(TimedWordDTO(f"w{position}", text, start, end, (f"a{position}",), (),
                                      MatchType.ASR_ONLY, TextSource.ASR, TimingSource.ACOUSTIC_ALIGNMENT))
            current = end + word_gap
        selected = words[first:]
        sentences.append(SourceSentenceDTO(
            f"s{index + 1}", selected[0].id, selected[-1].id, selected[0].start_ms,
            selected[-1].end_ms, reconstruct_sentence_text(selected),
            None if speakers is None else speakers[index], TextSource.ASR,
            BoundarySource.ASR_PUNCTUATION, BoundaryStatus.INFERRED,
        ))
        current = selected[-1].end_ms + sentence_gap
    sections, next_sentence = [], 1
    for index, size in enumerate(section_sizes):
        sections.append(SourceSectionDTO(f"sec{index + 1}", "Source heading", f"s{next_sentence}",
                                          f"s{next_sentence + size - 1}"))
        next_sentence += size
    alignment = SourceAlignmentDTO("en", words[-1].end_ms + 2000, tuple(words), tuple(sentences), tuple(sections))
    translation = TranslationResultDTO(
        SHA, "en", "zh-Hans", tuple(SectionTitleTranslationDTO(section.id, "不得显示标题") for section in sections),
        tuple(SentenceTranslationDTO(sentence.id, text) for sentence, text in zip(sentences, chinese, strict=True)),
    )
    media = SubtitleMediaDTO(alignment.audio_duration_ms, alignment.audio_duration_ms,
                             alignment.audio_duration_ms, 24, 1, 84)
    return alignment, translation, media


def run(data):
    alignment, translation, media = data
    return plan_subtitles(alignment, translation, source_alignment_sha256=SHA,
                          translation_result_sha256="b" * 64, video_sha256="c" * 64, media=media,
                          chinese_word_spans=segmentation(translation))


def all_merged(data):
    alignment, translation, media = data
    english = reconstruct_sentence_text(alignment.words)
    chinese = "".join(normalize_chinese_text(item.translated_text) for item in translation.sentence_translations)
    timing = adjust_cue_timing(start_ms=alignment.words[0].start_ms, base_end_ms=alignment.words[-1].end_ms,
                               chinese_units=chinese_half_units(chinese), english_count=english_characters(english),
                               usable_duration_ms=media.usable_duration_ms, gap_threshold_ms=84, next_start_ms=None)
    fragments = tuple(SubtitleFragmentDTO(sentence.id, sentence.first_word_id, sentence.last_word_id,
                                          0, len(normalize_chinese_text(item.translated_text)), sentence.speaker_label)
                      for sentence, item in zip(alignment.sentences, translation.sentence_translations, strict=True))
    cue = SubtitleCueDTO("c1", None, alignment.words[0].start_ms, alignment.words[-1].end_ms,
                         timing.end_ms, english, chinese, fragments, timing.timing_adjustment,
                         ("english_sentence", "chinese_sentence"))
    return SubtitlePlanDTO(SHA, "b" * 64, "c" * 64, "en", "zh-Hans", media, rules_identity(), (cue,))


def test_short_sentence_has_one_shared_cue_and_recomputable_report():
    data = inputs([("We", "agree.")], ["\t我们\n同意。 "])
    result = run(data)
    assert result.plan.cues[0].english_text == "We agree."
    assert result.plan.cues[0].chinese_text == "我们 同意。"
    assert result.summary.cue_count == 1
    assert result.plan.cues[0].fragments[0].speaker_label is None
    validate_plan(result.plan, *data[:2])
    assert analyze_plan(result.plan, *data[:2]) == (result.findings, result.summary)
    assert result.summary.average_frame_rate_approximation_count == 1
    assert {item.code for item in result.findings} >= {
        "timing.average_frame_rate_approximation", "timing.word_gap_approximation", "planning.proportional_mapping"}


def test_long_sentence_is_split_with_exact_word_and_character_coverage():
    data = inputs([tuple(["Longword,"] * 10)], ["这是很长的句子，我们完整保留全部文字，不改变任何顺序。"], duration=1300)
    result = run(data)
    assert len(result.plan.cues) >= 2
    assert result.summary.split_sentence_count == 1
    assert all(english_characters(cue.english_text) <= 84
               for cue in result.plan.cues)
    validate_plan(result.plan, *data[:2])
    assert result.plan.cues[-1].fragments[-1].chinese_end_offset == len(data[1].sentence_translations[0].translated_text)


def test_normal_punctuation_is_preferred_and_emergency_is_reported():
    normal = run(inputs([("a" * 30 + ",", "b" * 30 + ",", "c" * 30)], ["甲，乙，丙"])).plan
    assert normal.cues[0].break_methods == ("english_comma", "chinese_comma")
    emergency = run(inputs([("a" * 30, "b" * 30, "c" * 30)], ["甲，乙"]))
    assert emergency.cost.emergency_breaks == 1
    assert any(finding.code == "planning.emergency_break" for finding in emergency.findings)


@pytest.mark.parametrize("speakers", [("B", "B"), (None, None), ("B", None), (None, "B")])
def test_499ms_short_fragment_merge_and_speakers_preserve_original_labels(speakers):
    data = inputs([("Yes.",), ("Indeed.",)], ["是。", "确实。"], duration=400, sentence_gap=499, speakers=speakers)
    result = run(data)
    assert len(result.plan.cues) == 1
    assert tuple(part.speaker_label for part in result.plan.cues[0].fragments) == speakers
    assert result.summary.merged_cue_count == 1


@pytest.mark.parametrize("gap", [500, 501, 800])
def test_500ms_or_longer_source_sentence_pause_forbids_merge(gap):
    data = inputs([("Yes.",), ("Indeed.",)], ["是。", "确实。"], duration=100, sentence_gap=gap)
    assert len(run(data).plan.cues) == 2
    with pytest.raises(PlanningError, match="merge eligibility"):
        validate_plan(all_merged(data), *data[:2])


def test_healthy_sentences_cannot_merge_only_to_reduce_cue_count():
    data = inputs([("Yes.",), ("Indeed.",)], ["是。", "确实。"], duration=1000, sentence_gap=100)
    assert len(run(data).plan.cues) == 2
    with pytest.raises(PlanningError, match="merge eligibility"):
        validate_plan(all_merged(data), *data[:2])


@pytest.mark.parametrize("speakers", [("B", "M"), ("B", None, "M")])
def test_complete_known_speaker_set_cannot_be_bridged_by_null(speakers):
    result = run(inputs([("Yes.",)] * len(speakers), ["是。"] * len(speakers),
                        duration=100, sentence_gap=100, speakers=speakers))
    assert len(result.plan.cues) >= 2
    assert all(len({part.speaker_label for part in cue.fragments if part.speaker_label is not None}) <= 1
               for cue in result.plan.cues)
    assert [part.speaker_label for cue in result.plan.cues for part in cue.fragments] == list(speakers)


def test_section_boundary_is_hard_and_titles_are_not_spoken_text():
    result = run(inputs([("Yes.",), ("Indeed.",)], ["是。", "确实。"], duration=100,
                        sentence_gap=100, section_sizes=(1, 1)))
    assert [cue.section_id for cue in result.plan.cues] == ["sec1", "sec2"]
    assert "标题" not in "".join(cue.chinese_text for cue in result.plan.cues)


def test_merge_qualification_uses_candidate_tail_fragment_not_whole_sentence():
    data = inputs([("a" * 30, "b" * 30, "c" * 30), ("yes",)], ["甲，乙，丙", "丁"],
                  times=[(100, 600), (600, 1100), (1100, 1200), (1300, 2300)])
    result = run(data)
    assert any(len(cue.fragments) == 2 and cue.fragments[0].first_word_id == "w3" for cue in result.plan.cues)


def exhaustive_single_sentence(data, *, greedy=False):
    """Tiny ASCII/Han oracle: enumerate all full paths without production rules.

    Fixtures use Han/punctuation only, so half units are exactly twice the
    substring length. Boundary, timing, layout and v3 costs are recomputed here.
    """
    alignment, translation, media = data
    words = alignment.words
    chinese = translation.sentence_translations[0].translated_text
    total_english = sum(len(word.text) for word in words)
    zero = (0, 0, 0, 0, Fraction(0), 0, Fraction(0), 0, ())

    def edges(i, j):
        for k in range(i + 1, len(words) + 1):
            english = sum(len(word.text) for word in words[i:k])
            base_duration = words[k - 1].end_ms - words[i].start_ms
            if english > 84:
                continue
            if english > 42 and not any(
                sum(len(word.text) for word in words[i:split]) <= 42
                and sum(len(word.text) for word in words[split:k]) <= 42 for split in range(i + 1, k)
            ):
                continue
            for end in range(j + 1, len(chinese) + 1):
                final = k == len(words)
                if final != (end == len(chinese)):
                    continue
                if not final and chinese[end - 1] not in "，、；：。！？":
                    continue
                gap = words[k].start_ms - words[k - 1].end_ms if not final else None
                budget = min(500, media.usable_duration_ms - words[k - 1].end_ms)
                if gap is not None:
                    budget = min(budget, max(0, gap - 84))
                required = max(834, (1000 * (end - j) + 8) // 9)
                gap_extension = gap - 84 if gap is not None and 84 < gap < 500 else 0
                duration = base_duration + min(max(max(0, required - base_duration), gap_extension), budget)
                emergency = not final and not words[k - 1].text.endswith((".", "!", "?", ";", ":", ","))
                en_prefix = sum(len(word.text) for word in words[:k])
                deviation = Fraction(abs(en_prefix * len(chinese) - end * total_english), total_english * len(chinese))
                strong = sum(character in ";；" for character in chinese[j:end - 1])
                rhythm = 1 + Fraction(max(0, (end - j) - 16), 8) ** 2
                score = (strong, 0, int(duration < 834), 0, rhythm, int(emergency), deviation,
                         max(0, 250 - gap) if gap is not None else 0, ((k, end),))
                yield (k, end), score

    def paths(i, j):
        if i == len(words) and j == len(chinese):
            yield zero, ()
            return
        candidates = list(edges(i, j))
        if greedy and candidates:
            candidates = [min(candidates, key=lambda item: item[1])]
        for (k, end), edge in candidates:
            for suffix, cuts in paths(k, end):
                score = tuple(edge[index] + suffix[index] for index in range(8)) + (edge[8] + suffix[8],)
                yield score, ((k, end),) + cuts

    return min(paths(0, 0), default=None)


@pytest.mark.parametrize(("lengths", "duration", "gap", "chinese"), [
    ((20, 20, 20), 100, 0, "甲乙丙丁戊"),
    ((20, 20, 20), 600, 100, "甲乙，丙丁戊"),
    ((10, 25, 15, 20), 450, 300, "甲乙丙，丁戊己庚"),
    ((30, 30), 1, 0, "甲乙丙"),
    ((15, 15, 15, 15), 1800, 499, "甲乙丙丁戊己庚辛"),
    ((21, 22, 10), 2500, 0, "甲乙丙丁戊"),
    ((5, 5, 5, 5), 2000, 0, "甲乙丙丁戊己庚辛"),
    ((30, 30, 30, 30), 600, 0, "甲，乙，丙，丁"),
    ((30, 30, 30, 30, 30), 100, 100, "甲，乙；丙，丁，戊"),
    ((15, 35, 20, 30, 10), 450, 300, "甲乙，丙丁，戊己；庚辛"),
    ((30, 30, 30, 30, 30), 900, 0, "甲乙，丙丁戊"),
])
def test_sparse_dp_matches_independent_exhaustive_full_path_oracle(lengths, duration, gap, chinese):
    data = inputs([tuple(chr(97 + index) * length for index, length in enumerate(lengths))],
                  [chinese], duration=duration, word_gap=gap)
    expected = exhaustive_single_sentence(data)
    if expected is None:
        with pytest.raises(PlanningError, match="no complete"):
            run(data)
        return
    result = run(data)
    assert astuple(result.cost) == expected[0]
    assert result.cost.breakpoints == expected[1]


def test_candidate_enumeration_order_does_not_change_any_plan_bytes(monkeypatch):
    data = inputs([("a" * 20, "b" * 20, "c" * 20, "d" * 20)], ["甲乙，丙丁，戊己庚辛"])
    first = run(data)
    original = planner._candidates
    monkeypatch.setattr(planner, "_candidates", lambda doc, state: reversed(tuple(original(doc, state))))
    second = run(data)
    assert json.dumps(first.plan.to_dict(), ensure_ascii=False) == json.dumps(second.plan.to_dict(), ensure_ascii=False)
    assert first.cost == second.cost
    assert first.findings == second.findings


@pytest.mark.parametrize("position", range(8))
def test_d39_earlier_dimension_cannot_be_reversed_by_any_later_dimension(position):
    good, bad = [0] * 8, [0] * 8
    good[position], bad[position] = 1, 2
    for index in range(position + 1, 8):
        good[index] = 10**12
    assert D39Cost(*good, ((99, 99),)) < D39Cost(*bad, ((1, 1),))


def test_d39_final_tie_break_compares_whole_path_not_only_last_edge():
    left = D39Cost(breakpoints=((1, 2), (4, 5), (6, 7)))
    right = D39Cost(breakpoints=((2, 1), (3, 4), (6, 7)))
    assert left < right
    assert left.plus(D39Cost(breakpoints=((9, 10),))) < right.plus(D39Cost(breakpoints=((9, 10),)))


def test_global_dp_beats_locally_best_edge_on_remaining_short_fragment():
    data = inputs([("a" * 30, "b" * 30, "c" * 30)], ["甲乙丙丁，戊己"],
                  times=[(100, 1100), (1100, 2100), (2100, 2200)])
    best = exhaustive_single_sentence(data)
    greedy = exhaustive_single_sentence(data, greedy=True)
    result = run(data)
    assert best[0] < greedy[0]
    assert best[1] == ((1, 5), (3, 7))
    assert greedy[1] == ((2, 5), (3, 7))
    assert result.cost.breakpoints == best[1]
    assert result.cost.too_short_cues == 0
    assert greedy[0][2] == 1


@pytest.mark.parametrize(("left", "right", "expected"), [
    ("Warren", "Buffett", True), ("10", "million", True), ("10%", "percent", True),
    ("of", "the", True), ("rather", "than", True), ("ordinary", "word", False),
])
def test_local_name_number_and_tight_phrase_table_is_only_a_soft_cost(left, right, expected):
    assert planner._unnatural_cut(left, right) is expected


def test_local_protection_does_not_remove_the_only_legal_path():
    data = inputs([("W" * 30, "B" * 30, "C" * 30)], ["甲，乙"])
    result = run(data)
    assert len(result.plan.cues) == 2
    assert result.cost.unnatural_breaks == 1
    assert "local_rule" in result.plan.cues[0].break_methods
    assert any(item.code == "planning.local_rule_break" for item in result.findings)


@pytest.mark.parametrize(("texts", "chinese", "duration", "message"), [
    ([("a" * 43,)], ["甲"], 600, "indivisible"),
    ([("a" * 30, "b" * 30, "c" * 30)], ["甲"], 600, "no complete"),
])
def test_no_hard_feasible_complete_path_fails_without_text_loss(texts, chinese, duration, message):
    with pytest.raises(PlanningError, match=message) as caught:
        run(inputs(texts, chinese, duration=duration))
    assert caught.value.code == "planning_failed"


def test_high_chinese_and_english_cps_never_prunes_the_only_path():
    result = run(inputs([("a" * 30, "b" * 30, "c" * 30)], ["甲，乙"], duration=1))
    assert len(result.plan.cues) == 2
    assert result.summary.chinese_cps_exceeded_count >= 1
    assert result.summary.english_cps_exceeded_count == 2
    assert any(item.code == "reading.chinese_cps" for item in result.findings)


def test_combining_clusters_and_layout_spaces_keep_exact_source_ranges():
    data = inputs([("a" * 30, "b" * 30, "c" * 30)], ["\t甲，\n e\u0301乙  "])
    result = run(data)
    normalized = normalize_chinese_text(data[1].sentence_translations[0].translated_text)
    pieces = [fragment for cue in result.plan.cues for fragment in cue.fragments]
    assert "".join(normalized[part.chinese_start_offset:part.chinese_end_offset] for part in pieces) == normalized
    assert all(part.chinese_start_offset in character_boundaries(normalized)
               and part.chinese_end_offset in character_boundaries(normalized) for part in pieces)
    assert all(cue.chinese_text == cue.chinese_text.strip(" ") for cue in result.plan.cues)
    assert all(cue.chinese_text for cue in result.plan.cues)


def test_asr_segment_ids_are_not_used_as_sentence_or_cue_boundaries():
    data = inputs([("a" * 20, "b" * 20, "c" * 20)], ["中英语序可能明显不同。"])
    alignment = replace(data[0], words=tuple(replace(word, asr_word_ids=(f"different-segment-{index}",))
                                            for index, word in enumerate(data[0].words)))
    first, second = run(data), run((alignment, *data[1:]))
    assert first.plan == second.plan
    assert all(cue.mapping_method == "monotonic_proportional.v1" for cue in first.plan.cues)


def test_each_crossed_sentence_pause_is_checked_not_only_the_outer_pair():
    data = inputs([("a",), ("b",), ("c",)], ["甲", "乙", "丙"],
                  times=[(100, 200), (300, 400), (900, 1000)])
    result = run(data)
    assert not any(len(cue.fragments) == 3 for cue in result.plan.cues)
    with pytest.raises(PlanningError, match="merge eligibility"):
        validate_plan(all_merged(data), *data[:2])


def test_media_end_and_alignment_fingerprint_are_real_input_gates():
    alignment, translation, media = inputs([("yes",)], ["是"])
    short = SubtitleMediaDTO(200, media.audio_duration_ms, 200, 24, 1, 84)
    with pytest.raises(PlanningError, match="usable media"):
        run((alignment, translation, short))
    with pytest.raises(PlanningError, match="fingerprint"):
        run((alignment, replace(translation, source_alignment_sha256="d" * 64), media))


def test_domain_revalidation_rejects_forged_timing_methods_capacity_or_rules():
    data = inputs([("a" * 30, "b" * 30, "c" * 30)], ["甲，乙"])
    result = run(data)
    first = result.plan.cues[0]
    for bad in (
        replace(result.plan, rules=replace(result.plan.rules, cost_rules_version="unrecognized.v9")),
        replace(result.plan, cues=(replace(first, break_methods=("english_clause", "chinese_clause")), result.plan.cues[1])),
    ):
        with pytest.raises(PlanningError) as caught:
            validate_plan(bad, *data[:2])
        assert caught.value.code == "plan_validation_failed"
    last = result.plan.cues[-1]
    changed = replace(last, end_ms=last.base_end_ms,
                      timing_adjustment=replace(last.timing_adjustment, extension_ms=0, purposes=()))
    with pytest.raises(PlanningError, match="one-pass timing"):
        validate_plan(replace(result.plan, cues=(first, changed)), *data[:2])


def test_revalidation_rejects_oversized_plan_even_if_public_ranges_are_valid():
    data = inputs([("a" * 30, "b" * 30, "c" * 30)], ["甲，乙"])
    forged = all_merged(data)
    forged.validate_against_inputs(*data[:2])
    with pytest.raises(PlanningError, match="capacity"):
        validate_plan(forged, *data[:2])


def test_candidates_include_short_tail_and_complete_following_sentences_never_prefixes():
    data = inputs([("a" * 30, "b" * 25), ("c",), ("d",)],
                  ["甲，乙", "丙", "丁" * 20],
                  times=[(100, 1100), (1100, 1200), (1300, 1400), (1500, 2600)])
    document = planner._document(*data, segmentation(data[1]))
    candidates = tuple(planner._candidates(document, (1, 2)))
    three = [candidate for candidate in candidates if len(candidate.fragments) == 3]
    assert three
    assert all(candidate.fragments[0].first == 1 and candidate.fragments[0].end == 2
               and candidate.fragments[0].chinese_start == 2 for candidate in three)
    assert all(candidate.fragments[1] == planner._Fragment(1, 2, 3, 0, 1) for candidate in three)
    assert all(candidate.fragments[2].first == 3 and candidate.fragments[2].end == 4
               and candidate.fragments[2].chinese_start == 0 and candidate.fragments[2].chinese_end == 20
               for candidate in three)
    validate_plan(run(data).plan, *data[:2])


def test_pause_only_boundary_enumeration_avoids_full_bilingual_character_matrix(monkeypatch):
    data = inputs([("a" * 30, "b" * 30, "c" * 30)], ["甲" * 3000])
    original = planner._make_candidate
    calls = []

    def counted(document, fragments):
        calls.append(fragments)
        return original(document, fragments)

    monkeypatch.setattr(planner, "_make_candidate", counted)
    with pytest.raises(PlanningError, match="no complete"):
        run(data)
    assert len(calls) == 0  # No internal Chinese pauses and English cannot fit whole.


def test_chinese_cps_alone_does_not_qualify_an_otherwise_not_short_merge():
    data = inputs([("yes",), ("indeed",)], ["甲" * 8, "乙" * 8], duration=834, sentence_gap=100)
    forged = all_merged(data)
    with pytest.raises(PlanningError, match="merge eligibility"):
        validate_plan(forged, *data[:2])
    assert len(run(data).plan.cues) == 2


def test_same_total_text_length_does_not_hide_reordered_source_ranges():
    data = inputs([("a" * 30, "b" * 30, "c" * 30)], ["甲，乙"])
    result = run(data)
    first, last = result.plan.cues
    first_fragment, last_fragment = first.fragments[0], last.fragments[0]
    wrong = replace(result.plan, cues=(
        replace(first, chinese_text="乙", fragments=(replace(first_fragment, chinese_start_offset=1, chinese_end_offset=2),)),
        replace(last, chinese_text="甲", fragments=(replace(last_fragment, chinese_start_offset=0, chinese_end_offset=1),)),
    ))
    with pytest.raises(PlanningError, match="exactly once in order"):
        validate_plan(wrong, *data[:2])


@pytest.mark.parametrize(("gap", "method"), [(249, "english_emergency"), (250, "english_pause")])
def test_reasonable_pause_threshold_is_the_versioned_250ms_value(gap, method):
    result = run(inputs([("a" * 30, "b" * 30, "c" * 30)], ["甲，乙"], word_gap=gap))
    assert result.plan.cues[0].break_methods[0] == method


def run_with_spans(data, spans):
    return plan_subtitles(data[0], data[1], source_alignment_sha256=SHA,
                          translation_result_sha256="b" * 64, video_sha256="c" * 64,
                          media=data[2], chinese_word_spans=spans)


def test_chinese_lexical_integrity_precedes_position_and_emergency_objectives():
    data = inputs([("a" * 30, "b" * 30, "c" * 30)], ["甲，乙，丙"])
    result = run_with_spans(data, {"s1": ((0, 2), (2, 5))})
    assert len(result.plan.cues) == 2
    assert result.plan.cues[0].fragments[0].chinese_end_offset == 2
    assert result.cost.unnatural_breaks == 0


def test_dictionary_missegmentation_does_not_delete_the_only_pause_path():
    data = inputs([("a" * 30, "b" * 30, "c" * 30)], ["陌" * 18 + "，" + "生" * 18])
    result = run_with_spans(data, {"s1": ((0, 37),)})
    assert len(result.plan.cues) == 2
    assert result.cost.unnatural_breaks == 1
    assert any(finding.code == "planning.local_rule_break" for finding in result.findings)


def test_two_line_infeasibility_forces_split_even_when_total_is_below_84():
    data = inputs([("a" * 30, "b" * 30, "c" * 20)], ["甲，乙丙"])
    result = run(data)
    assert len(result.plan.cues) == 2
    assert english_characters(reconstruct_sentence_text(data[0].words)) == 80


def test_cross_fragment_latin_join_counts_the_final_text_not_fragment_sum():
    data = inputs([("yes",), ("indeed",)], ["foo-", "bar"], duration=100, sentence_gap=100)
    result = run(data)
    assert len(result.plan.cues) == 1
    assert result.plan.cues[0].chinese_text == "foo-bar"
    assert chinese_half_units(result.plan.cues[0].chinese_text) == 2
    validate_plan(result.plan, *data[:2])


def test_latin_internal_cut_cannot_escape_with_zero_prefix_difference():
    data = inputs([("alpha", "beta")], ["abcdefgh"])
    doc = planner._document(*data, segmentation(data[1]))
    assert planner._make_candidate(doc, (planner._Fragment(0, 0, 1, 0, 4),)) is None
    assert planner._make_candidate(doc, (planner._Fragment(0, 0, 2, 0, 8),)) is not None
    impossible = inputs([("a" * 30, "b" * 30, "c" * 30)], ["abcdefgh"])
    with pytest.raises(PlanningError, match="no complete"):
        run(impossible)


def test_segmentation_evidence_is_required_and_not_replaced_by_character_fallback():
    data = inputs([("ordinary",)], ["普通文本"])
    with pytest.raises(PlanningError, match="segmentation evidence"):
        plan_subtitles(data[0], data[1], source_alignment_sha256=SHA,
                       translation_result_sha256="b" * 64, video_sha256="c" * 64, media=data[2])


def test_switch_count_precedes_tiny_position_deviation_but_not_lexical_quality():
    fewer = D39Cost(rhythm_cost=2, position_deviation=Fraction(1, 10**9))
    more = D39Cost(rhythm_cost=3, position_deviation=Fraction(0))
    assert fewer < more
    assert D39Cost(unnatural_breaks=0, rhythm_cost=4) < D39Cost(unnatural_breaks=1, rhythm_cost=2)


@pytest.mark.parametrize("units", [20, 23])
def test_soft_target_does_not_split_moderate_complete_pause_groups(units):
    # An optional comma is present; stopping at 16 is neither a hard nor the
    # leading optimization target. The count includes that fullwidth comma.
    text = "甲" * 9 + "，" + "乙" * (units - 10)
    result = run(inputs([("first", "second")], [text], duration=2000))
    assert len(result.plan.cues) == 1
    assert result.cost.rhythm_cost == 1 + Fraction(units - 16, 8) ** 2
    length = next(item for item in result.findings if item.code == "reading.chinese_length")
    assert length.observed == {"half_units": 2 * units, "target_half_units": 32}


def test_rhythm_soft_tradeoff_can_prefer_two_complete_longer_groups_not_three():
    text = "甲" * 4 + "，" + "乙" * 11 + "，" + "丙" * 11
    result = run(inputs([("first,", "second,", "third")], [text], duration=2000))
    assert len(text) == 28
    assert [cue.chinese_text for cue in result.plan.cues] == [text[:17], text[17:]]
    assert result.cost.rhythm_cost == Fraction(129, 64)


@pytest.mark.parametrize("duration", [7001, 10001, 25000])
def test_targets_never_create_a_new_duration_or_chinese_hard_cap(duration):
    data = inputs([("word",)], ["甲" * 100], duration=duration)
    result = run(data)
    assert len(result.plan.cues) == 1
    final_duration = duration + (500 if duration < 11112 else 0)
    assert result.plan.cues[0].end_ms - result.plan.cues[0].start_ms == final_duration
    assert {item.code for item in result.findings} >= {"reading.chinese_length", "timing.target_duration"}
    duration_warning = next(item for item in result.findings if item.code == "timing.target_duration")
    assert duration_warning.observed == {"duration_ms": final_duration, "target_duration_ms": 7000}
    assert duration_warning.cue_ids == ("c1",) and duration_warning.sentence_ids == ("s1",)
    validate_plan(result.plan, *data[:2])


def test_exact_targets_do_not_warn_and_cps_never_splits_a_complete_group():
    exact = run(inputs([("word",)], ["甲" * 16], duration=7000))
    assert not {item.code for item in exact.findings} & {"reading.chinese_length", "timing.target_duration"}
    fast = run(inputs([("one,", "two")], ["甲" * 10 + "，" + "乙" * 10], duration=1))
    assert len(fast.plan.cues) == 1
    assert fast.summary.chinese_cps_exceeded_count == 1


def test_semicolon_priority_uses_closed_pause_groups_but_is_not_a_hard_gate():
    text = "甲说“第一；”，然后继续。"
    result = run(inputs([("first,", "second")], [text], duration=1500))
    assert [cue.chinese_text for cue in result.plan.cues] == ["甲说“第一；”，", "然后继续。"]
    assert result.cost.strong_pause_crossings == 0
    one_word = run(inputs([("word",)], [text], duration=1500))
    assert len(one_word.plan.cues) == 1
    warning = next(item for item in one_word.findings if item.code == "planning.strong_pause_retained")
    assert warning.cue_ids == ("c1",) and warning.sentence_ids == ("s1",)
    assert warning.observed == {"semicolon_count": 1}


@pytest.mark.parametrize("text", ["甲" * 100, "含Coca-Cola和See's的完整文字", "甲👩🏽\u200d💻乙"])
def test_no_pause_fallback_cannot_hide_an_impossible_english_layout(text):
    with pytest.raises(PlanningError, match="pause-only.*2x42"):
        run(inputs([("a" * 30, "b" * 30, "c" * 20)], [text]))


def test_full_utterance_function_word_and_punctuated_internal_word_are_not_stranded():
    result = run(inputs([("That", "is", "what", "it", "is", "for.")], ["就是为此。"], duration=200))
    assert result.cost.unnatural_breaks == 0
    assert len(result.plan.cues) == 1
    assert planner._dependent_cut("and") and planner._dependent_cut("the")
    assert not planner._dependent_cut("And,") and not planner._dependent_cut("to.")


def test_short_rescue_can_take_a_complete_nonshort_next_sentence_but_never_its_head():
    data = inputs([("short",), ("complete,", "sentence")], ["短。", "完整，句子。"],
                  times=[(100, 660), (660, 1100), (1100, 1560)])
    document = planner._document(*data, segmentation(data[1]))
    merged = [candidate for candidate in planner._candidates(document, (0, 0)) if len(candidate.fragments) > 1]
    assert merged and all(candidate.fragments[-1] == planner._Fragment(1, 1, 3, 0, 6) for candidate in merged)
    assert planner._make_candidate(document, (planner._Fragment(0, 0, 1, 0, 2),
                                             planner._Fragment(1, 1, 2, 0, 3))) is None
    result = run(data)
    assert len(result.plan.cues) == 1
    assert result.summary.merged_cue_count == 1
    validate_plan(result.plan, *data[:2])


def test_legal_extension_removes_the_need_for_cross_sentence_rescue():
    data = inputs([("first",), ("next",)], ["前。", "后。"],
                  times=[(100, 900), (1200, 2200)])
    result = run(data)
    assert len(result.plan.cues) == 2
    assert result.plan.cues[0].timing_adjustment.extension_ms == 216
    assert result.summary.too_short_count == 0
    with pytest.raises(PlanningError, match="merge eligibility"):
        validate_plan(all_merged(data), *data[:2])


def test_internal_function_word_is_soft_quality_not_an_english_hard_boundary():
    data = inputs([("a" * 42, "because", "b" * 42)], ["甲，乙，丙"])
    result = run(data)
    # 42+7 cannot share either line with the final indivisible 42, so the
    # second cue must start with 'because'; it is not rejected by a word table.
    assert len(result.plan.cues) == 2
    assert result.cost.unnatural_breaks == 0
    assert result.plan.cues[1].english_text.startswith("because ")


def test_semicolon_at_a_source_sentence_end_is_still_crossed_by_a_merged_cue():
    data = inputs([("one",), ("two",)], ["前；", "后。"], duration=100, sentence_gap=0)
    document = planner._document(*data, segmentation(data[1]))
    combined = planner._make_candidate(document, (planner._Fragment(0, 0, 1, 0, 2),
                                                 planner._Fragment(1, 1, 2, 0, 2)))
    assert combined is not None and combined.cost.strong_pause_crossings == 1
