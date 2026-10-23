"""Sparse deterministic bilingual DP and source-preserving subtitle QA."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import re
from typing import Mapping

from archive_core.interfaces import (
    SourceAlignmentDTO, TranslationResultDTO, SubtitleCueDTO, SubtitleFindingDTO,
    SubtitleFragmentDTO, SubtitleMediaDTO, SubtitlePlanDTO, SubtitleSummaryDTO,
    normalize_chinese_text, reconstruct_sentence_text,
)

from .rules import (
    PROFILE, TimingResult, adjust_cue_timing, chinese_half_units,
    english_characters, rules_identity, wrap_english_text,
)
from .boundaries import chinese_boundaries, chinese_semicolon_boundaries


class PlanningError(ValueError):
    def __init__(self, message: str, code: str = "planning_failed") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, order=True)
class D39Cost:
    strong_pause_crossings: int = 0
    unnatural_breaks: int = 0
    too_short_cues: int = 0
    merged_boundaries: int = 0
    rhythm_cost: Fraction = Fraction(0)
    emergency_breaks: int = 0
    position_deviation: Fraction = Fraction(0)
    gap_penalty: int = 0
    breakpoints: tuple[tuple[int, int], ...] = ()

    def plus(self, other: D39Cost) -> D39Cost:
        return D39Cost(
            self.strong_pause_crossings + other.strong_pause_crossings,
            self.unnatural_breaks + other.unnatural_breaks,
            self.too_short_cues + other.too_short_cues,
            self.merged_boundaries + other.merged_boundaries,
            self.rhythm_cost + other.rhythm_cost,
            self.emergency_breaks + other.emergency_breaks,
            self.position_deviation + other.position_deviation,
            self.gap_penalty + other.gap_penalty,
            self.breakpoints + other.breakpoints,
        )


@dataclass(frozen=True)
class PlanningResult:
    plan: SubtitlePlanDTO
    findings: tuple[SubtitleFindingDTO, ...]
    summary: SubtitleSummaryDTO
    cost: D39Cost


@dataclass(frozen=True)
class _Sentence:
    id: str
    first: int
    end: int
    speaker: str | None
    section: str | None
    chinese: str
    chinese_prefix: tuple[int, ...]
    boundaries: tuple[int, ...]
    lexical_cuts: frozenset[int]
    semicolons: tuple[int, ...]


@dataclass(frozen=True)
class _Document:
    alignment: SourceAlignmentDTO
    sentences: tuple[_Sentence, ...]
    word_sentence: tuple[int, ...]
    english_prefix: tuple[int, ...]
    media: SubtitleMediaDTO


@dataclass(frozen=True)
class _Fragment:
    sentence: int
    first: int
    end: int
    chinese_start: int
    chinese_end: int


@dataclass(frozen=True)
class _Candidate:
    fragments: tuple[_Fragment, ...]
    timing: TimingResult
    methods: tuple[str, ...]
    cost: D39Cost

@dataclass(frozen=True)
class _Label:
    cost: D39Cost
    previous: _Label | None
    candidate: _Candidate | None


def _document(alignment: SourceAlignmentDTO, translation: TranslationResultDTO,
              media: SubtitleMediaDTO, chinese_word_spans: Mapping[str, tuple[tuple[int, int], ...]]) -> _Document:
    if not isinstance(alignment, SourceAlignmentDTO) or not isinstance(translation, TranslationResultDTO):
        raise ValueError("planner inputs must be public alignment and translation DTOs")
    translation.validate_against_alignment(alignment)
    if not alignment.words or not alignment.sentences:
        raise ValueError("subtitle inputs must contain source words and sentences")
    if not isinstance(media, SubtitleMediaDTO) or media.audio_duration_ms != alignment.audio_duration_ms:
        raise ValueError("media must describe the source audio duration")
    if alignment.words[-1].end_ms > media.usable_duration_ms:
        raise ValueError("source words exceed usable media")
    sections = {}
    for section in alignment.sections:
        for index in range(int(section.first_sentence_id[1:]), int(section.last_sentence_id[1:]) + 1):
            sections[f"s{index}"] = section.id
    chinese = {item.sentence_id: normalize_chinese_text(item.translated_text)
               for item in translation.sentence_translations}
    if not isinstance(chinese_word_spans, Mapping) or set(chinese_word_spans) != set(chinese):
        raise ValueError("Chinese segmentation evidence must cover exactly the source sentences")
    sentences = []
    word_sentence = []
    for index, sentence in enumerate(alignment.sentences):
        text = chinese[sentence.id]
        if not text:
            raise ValueError("normalized Chinese sentence must not be empty")
        # Whole-prefix counts are only positional evidence, not additive capacity
        # allocation. Latin token interiors cannot become cue boundaries.
        prefix = tuple(chinese_half_units(text[:end]) for end in range(len(text) + 1))
        boundaries = chinese_boundaries(text, chinese_word_spans[sentence.id])
        first, end = int(sentence.first_word_id[1:]) - 1, int(sentence.last_word_id[1:])
        sentences.append(_Sentence(sentence.id, first, end, sentence.speaker_label,
                                   sections.get(sentence.id), text, prefix, boundaries.allowed,
                                   boundaries.lexical_cuts, chinese_semicolon_boundaries(text)))
        word_sentence.extend([index] * (end - first))
    english_prefix = [0]
    for word in alignment.words:
        count = english_characters(word.text)
        if count > PROFILE.parameters["english_line_capacity"]:
            raise ValueError("an indivisible source word exceeds English capacity")
        english_prefix.append(english_prefix[-1] + count)
    return _Document(alignment, tuple(sentences), tuple(word_sentence), tuple(english_prefix), media)


# Heuristics only: no syntax/semantic claims and no hard rejection at these cuts.
_TIGHT_PAIRS = frozenset({("of", "the"), ("in", "the"), ("to", "the"), ("as", "a"),
                          ("such", "as"), ("not", "only"), ("rather", "than")})
_UNITS = frozenset({"percent", "percentage", "dollars", "dollar", "million", "billion",
                    "trillion", "years", "year", "months", "month", "kg", "km", "ms"})
_NUMBER = re.compile(r"^[+-]?[0-9]+(?:[,.][0-9]+)*%?$")
_DEPENDENT_ENDINGS = frozenset({"and", "or", "but", "because", "if", "although", "while",
                               "the", "a", "an", "of", "to", "for", "with", "from", "by"})


def _word_token(text: str) -> str:
    return text.strip(" \"'“”‘’()[]{}.,;:!?")


def _unnatural_cut(left: str, right: str) -> bool:
    left, right = _word_token(left), _word_token(right)
    names = bool(left and right and "A" <= left[0] <= "Z" and "A" <= right[0] <= "Z")
    number_unit = bool(_NUMBER.fullmatch(left) and (right.lower() in _UNITS or right == "%"))
    return names or number_unit or (left.lower(), right.lower()) in _TIGHT_PAIRS


def _dependent_cut(left: str) -> bool:
    # Only internal, unpunctuated cuts use this heuristic. Complete utterances
    # ending in e.g. "to." are not made unnatural by a function-word table.
    return left == _word_token(left) and left.lower() in _DEPENDENT_ENDINGS


def _break_methods(doc: _Document, end_word: int, chinese_end: int) -> tuple[str, ...]:
    sentence = doc.sentences[doc.word_sentence[end_word - 1]]
    if end_word == sentence.end:
        return "english_sentence", "chinese_sentence"
    words = doc.alignment.words
    english = words[end_word - 1].text.rstrip(" \"'”’)]}")
    if english.endswith((".", "!", "?")):
        english_method = "english_sentence"
    elif english.endswith((";", ":")):
        english_method = "english_clause"
    elif english.endswith((",", "—", "–", "--")):
        english_method = "english_comma"
    elif words[end_word].start_ms - words[end_word - 1].end_ms >= PROFILE.parameters["pause_boundary_ms"]:
        english_method = "english_pause"
    else:
        english_method = "english_emergency"
    chinese = sentence.chinese[:chinese_end].rstrip(" \"'”’」』）)]}")
    if chinese.endswith(("。", "！", "？", ".", "!", "?")):
        chinese_method = "chinese_sentence"
    elif chinese.endswith(("；", "：", ";", ":")):
        chinese_method = "chinese_clause"
    elif chinese.endswith(("，", "、", ",", "—", "–", "--")):
        chinese_method = "chinese_comma"
    else:
        chinese_method = "chinese_emergency"
    methods = (english_method, chinese_method)
    if (_unnatural_cut(words[end_word - 1].text, words[end_word].text)
            or _dependent_cut(words[end_word - 1].text)):
        methods += ("local_rule",)
    elif chinese_end in sentence.lexical_cuts:
        methods += ("local_rule",)
    return methods


def _merge_eligible(doc: _Document, fragments: tuple[_Fragment, ...]) -> bool:
    if len(fragments) == 1:
        return True
    sentences = [doc.sentences[fragment.sentence] for fragment in fragments]
    if len({sentence.section for sentence in sentences}) != 1:
        return False
    if len({sentence.speaker for sentence in sentences if sentence.speaker is not None}) > 1:
        return False
    words = doc.alignment.words
    for left, right in zip(sentences, sentences[1:]):
        if words[right.first].start_ms - words[left.end - 1].end_ms >= PROFILE.parameters["cross_sentence_gap_upper_ms"]:
            return False
    # Never steal the next sentence's opening: every later source sentence and
    # translation must be consumed in full, not just an attractive short prefix.
    for fragment, sentence in zip(fragments[1:], sentences[1:], strict=True):
        if (fragment.first != sentence.first or fragment.end != sentence.end
                or fragment.chinese_start != 0 or fragment.chinese_end != len(sentence.chinese)):
            return False
    first = fragments[0]
    if words[first.end - 1].end_ms - words[first.first].start_ms >= PROFILE.parameters["minimum_duration_ms"]:
        return False
    isolated = adjust_cue_timing(
        start_ms=words[first.first].start_ms, base_end_ms=words[first.end - 1].end_ms,
        chinese_units=chinese_half_units(sentences[0].chinese[first.chinese_start:first.chinese_end].strip(" ")),
        english_count=doc.english_prefix[first.end] - doc.english_prefix[first.first],
        usable_duration_ms=doc.media.usable_duration_ms, gap_threshold_ms=doc.media.gap_threshold_ms,
        next_start_ms=words[first.end].start_ms,
    )
    return isolated.too_short


def _make_candidate(doc: _Document, fragments: tuple[_Fragment, ...]) -> _Candidate | None:
    first, last = fragments[0], fragments[-1]
    english_count = doc.english_prefix[last.end] - doc.english_prefix[first.first]
    chinese_text = "".join(doc.sentences[part.sentence].chinese[part.chinese_start:part.chinese_end].strip(" ")
                           for part in fragments)
    units = chinese_half_units(chinese_text)
    if (english_count > PROFILE.parameters["english_capacity"]
            or not _merge_eligible(doc, fragments)):
        return None
    for part in fragments:
        if (part.chinese_start not in doc.sentences[part.sentence].boundaries
                or part.chinese_end not in doc.sentences[part.sentence].boundaries):
            return None
        if not doc.sentences[part.sentence].chinese[part.chinese_start:part.chinese_end].strip(" "):
            return None
    try:
        wrap_english_text(reconstruct_sentence_text(doc.alignment.words[first.first:last.end]))
    except ValueError:
        return None
    words = doc.alignment.words
    start, base_end = words[first.first].start_ms, words[last.end - 1].end_ms
    timing = adjust_cue_timing(
        start_ms=start, base_end_ms=base_end, chinese_units=units, english_count=english_count,
        usable_duration_ms=doc.media.usable_duration_ms, gap_threshold_ms=doc.media.gap_threshold_ms,
        next_start_ms=words[last.end].start_ms if last.end < len(words) else None,
    )
    methods = _break_methods(doc, last.end, last.chinese_end)
    sentence = doc.sentences[last.sentence]
    en_total = doc.english_prefix[sentence.end] - doc.english_prefix[sentence.first]
    en_prefix = doc.english_prefix[last.end] - doc.english_prefix[sentence.first]
    zh_total = sentence.chinese_prefix[-1]
    zh_prefix = sentence.chinese_prefix[last.chinese_end]
    deviation = (Fraction(abs(en_prefix * zh_total - zh_prefix * en_total), en_total * zh_total)
                 if en_total and zh_total else Fraction(0))
    target = PROFILE.parameters["chinese_target_half_units"]
    cost = D39Cost(
        strong_pause_crossings=sum(part.chinese_start < boundary <= part.chinese_end
                                   and (part != last or boundary < part.chinese_end)
                                   for part in fragments for boundary in doc.sentences[part.sentence].semicolons),
        unnatural_breaks=(int(last.end < sentence.end and
                              (_unnatural_cut(words[last.end - 1].text, words[last.end].text)
                               or _dependent_cut(words[last.end - 1].text)))
                          + int(last.chinese_end in sentence.lexical_cuts)),
        too_short_cues=int(timing.too_short), merged_boundaries=len(fragments) - 1,
        rhythm_cost=1 + Fraction(2 * max(0, units - target), target) ** 2,
        emergency_breaks=int(methods[0] in {"english_emergency", "english_pause"}),
        position_deviation=deviation,
        gap_penalty=(max(0, PROFILE.parameters["pause_boundary_ms"] -
                         (words[last.end].start_ms - words[last.end - 1].end_ms))
                     if last.end < sentence.end else 0),
        breakpoints=((last.end, last.chinese_end),),
    )
    return _Candidate(fragments, timing, methods, cost)


def _candidates(doc: _Document, state: tuple[int, int]):
    """Enumerate all hard-feasible edges; no CPS or proportional-window pruning."""
    first_word, chinese_start = state
    first_sentence = doc.word_sentence[first_word]
    words = doc.alignment.words
    for end_word in range(first_word + 1, len(words) + 1):
        if doc.english_prefix[end_word] - doc.english_prefix[first_word] > PROFILE.parameters["english_capacity"]:
            break  # Further extension cannot reduce the English count.
        try:
            wrap_english_text(reconstruct_sentence_text(words[first_word:end_word]))
        except ValueError:
            break  # Appending words cannot restore an impossible two-line prefix.
        last_sentence = doc.word_sentence[end_word - 1]
        sentences = doc.sentences[first_sentence:last_sentence + 1]
        if len({sentence.section for sentence in sentences}) > 1:
            break
        if len({sentence.speaker for sentence in sentences if sentence.speaker is not None}) > 1:
            break
        if any(words[right.first].start_ms - words[left.end - 1].end_ms >= PROFILE.parameters["cross_sentence_gap_upper_ms"]
               for left, right in zip(sentences, sentences[1:])):
            break
        last = doc.sentences[last_sentence]
        ends = (len(last.chinese),) if end_word == last.end else last.boundaries[1:-1]
        for chinese_end in ends:
            if first_sentence == last_sentence and chinese_end <= chinese_start:
                continue
            fragments = tuple(
                _Fragment(index, max(first_word, sentence.first), min(end_word, sentence.end),
                          chinese_start if index == first_sentence else 0,
                          chinese_end if index == last_sentence else len(sentence.chinese))
                for index, sentence in enumerate(doc.sentences[first_sentence:last_sentence + 1], first_sentence)
            )
            candidate = _make_candidate(doc, fragments)
            if candidate is not None:
                yield candidate


def _next_state(doc: _Document, candidate: _Candidate) -> tuple[int, int]:
    last = candidate.fragments[-1]
    return last.end, 0 if last.end == doc.sentences[last.sentence].end else last.chinese_end


def _solve(doc: _Document) -> tuple[tuple[_Candidate, ...], D39Cost]:
    # Only reachable state dictionaries, never a full-document bilingual matrix.
    levels: dict[int, dict[int, _Label]] = {0: {0: _Label(D39Cost(), None, None)}}
    for first_word in range(len(doc.alignment.words)):
        for chinese_start, prefix in sorted(levels.pop(first_word, {}).items()):
            for candidate in _candidates(doc, (first_word, chinese_start)):
                end_word, chinese_end = _next_state(doc, candidate)
                cost = prefix.cost.plus(candidate.cost)
                destination = levels.setdefault(end_word, {})
                existing = destination.get(chinese_end)
                if existing is None or cost < existing.cost:
                    destination[chinese_end] = _Label(cost, prefix, candidate)
    final = levels.get(len(doc.alignment.words), {}).get(0)
    if final is None:
        raise PlanningError("no complete hard-feasible bilingual cue path: Chinese pause-only boundaries and English 2x42 layout cannot cover the inputs")
    selected = []
    label = final
    while label.candidate is not None:
        selected.append(label.candidate)
        label = label.previous
    return tuple(reversed(selected)), final.cost


def _cue(doc: _Document, candidate: _Candidate, position: int) -> SubtitleCueDTO:
    first, last = candidate.fragments[0], candidate.fragments[-1]
    words = doc.alignment.words
    fragments = tuple(SubtitleFragmentDTO(
        doc.sentences[part.sentence].id, words[part.first].id, words[part.end - 1].id,
        part.chinese_start, part.chinese_end, doc.sentences[part.sentence].speaker,
    ) for part in candidate.fragments)
    chinese = "".join(doc.sentences[part.sentence].chinese[part.chinese_start:part.chinese_end].strip(" ")
                      for part in candidate.fragments)
    # Materialization deliberately calls the same time function as edge evaluation.
    timing = adjust_cue_timing(
        start_ms=words[first.first].start_ms, base_end_ms=words[last.end - 1].end_ms,
        chinese_units=chinese_half_units(chinese),
        english_count=doc.english_prefix[last.end] - doc.english_prefix[first.first],
        usable_duration_ms=doc.media.usable_duration_ms, gap_threshold_ms=doc.media.gap_threshold_ms,
        next_start_ms=words[last.end].start_ms if last.end < len(words) else None,
    )
    if timing != candidate.timing:
        raise PlanningError("estimated and materialized timing differ")
    return SubtitleCueDTO(
        id=f"c{position}", section_id=doc.sentences[first.sentence].section,
        start_ms=words[first.first].start_ms, base_end_ms=words[last.end - 1].end_ms,
        end_ms=timing.end_ms, english_text=reconstruct_sentence_text(words[first.first:last.end]),
        chinese_text=chinese, fragments=fragments, timing_adjustment=timing.timing_adjustment,
        break_methods=candidate.methods,
    )


def _validated_candidates(plan: SubtitlePlanDTO, alignment: SourceAlignmentDTO,
                          translation: TranslationResultDTO,
                          chinese_word_spans: Mapping[str, tuple[tuple[int, int], ...]]) -> tuple[_Candidate, ...]:
    if not isinstance(plan, SubtitlePlanDTO):
        raise ValueError("plan must be a SubtitlePlanDTO")
    if plan.rules != rules_identity():
        raise ValueError("plan does not use the current fixed profile and rule identity")
    plan.validate_against_inputs(alignment, translation)
    doc = _document(alignment, translation, plan.media, chinese_word_spans)
    sentence_positions = {sentence.id: index for index, sentence in enumerate(doc.sentences)}
    candidates = []
    for position, cue in enumerate(plan.cues, 1):
        fragments = tuple(_Fragment(
            sentence_positions[part.sentence_id], int(part.first_word_id[1:]) - 1,
            int(part.last_word_id[1:]), part.chinese_start_offset, part.chinese_end_offset,
        ) for part in cue.fragments)
        candidate = _make_candidate(doc, fragments)
        if candidate is None:
            raise ValueError("cue violates English capacity, Chinese pause boundaries or original merge eligibility")
        if _cue(doc, candidate, position) != cue:
            raise ValueError("cue differs from reconstructed text, break methods or one-pass timing")
        candidates.append(candidate)
    return tuple(candidates)


def validate_plan(plan: SubtitlePlanDTO, alignment: SourceAlignmentDTO,
                  translation: TranslationResultDTO, *,
                  chinese_word_spans: Mapping[str, tuple[tuple[int, int], ...]] | None = None) -> None:
    """Recheck hard QA and exact methods/timing, not global DP optimality."""
    try:
        _validated_candidates(plan, alignment, translation, chinese_word_spans)
    except ValueError as error:
        raise PlanningError(str(error), "plan_validation_failed") from error


def analyze_plan(plan: SubtitlePlanDTO, alignment: SourceAlignmentDTO,
                 translation: TranslationResultDTO, *,
                 chinese_word_spans: Mapping[str, tuple[tuple[int, int], ...]] | None = None,
                 ) -> tuple[tuple[SubtitleFindingDTO, ...], SubtitleSummaryDTO]:
    """Recompute a successful report solely from validated source and plan."""
    try:
        candidates = _validated_candidates(plan, alignment, translation, chinese_word_spans)
    except ValueError as error:
        raise PlanningError(str(error), "plan_validation_failed") from error
    findings = [
        SubtitleFindingDTO("timing.average_frame_rate_approximation", "warning",
                           "Two-frame spacing uses average FPS, not individual frame timestamps.",
                           observed={"fps_numerator": plan.media.fps_numerator,
                                     "fps_denominator": plan.media.fps_denominator,
                                     "gap_threshold_ms": plan.media.gap_threshold_ms}),
        SubtitleFindingDTO("timing.word_gap_approximation", "warning",
                           "Available word gaps are not verified silence; no VAD is performed."),
        SubtitleFindingDTO("planning.proportional_mapping", "warning",
                           "Monotonic text positions are heuristic, not semantic alignment."),
    ]
    counts = {"too_short_count": 0, "chinese_cps_exceeded_count": 0,
              "english_cps_exceeded_count": 0, "unclosed_gap_count": 0, "extended_cue_count": 0}
    sentence_cues: dict[str, int] = {}
    for cue, candidate in zip(plan.cues, candidates, strict=True):
        for fragment in cue.fragments:
            sentence_cues[fragment.sentence_id] = sentence_cues.get(fragment.sentence_id, 0) + 1
        timing = candidate.timing
        observations = {"duration_ms": cue.end_ms - cue.start_ms,
                        "chinese_half_units": chinese_half_units(cue.chinese_text),
                        "english_characters": english_characters(cue.english_text),
                        "original_gap_ms": cue.timing_adjustment.original_gap_ms,
                        "extension_ms": cue.timing_adjustment.extension_ms}
        flags = (
            (timing.too_short, "too_short_count", "timing.minimum_duration", "Final display remains below 834ms."),
            (timing.chinese_cps_excess > 0, "chinese_cps_exceeded_count", "reading.chinese_cps", "Chinese CPS exceeds the soft target of 9."),
            (timing.english_cps_excess > 0, "english_cps_exceeded_count", "reading.english_cps", "English CPS exceeds the reporting reference of 17."),
            (timing.unclosed_gap, "unclosed_gap_count", "timing.short_gap_unclosed", "The original short gap could not close to two frames."),
            (timing.timing_adjustment.extension_ms > 0, "extended_cue_count", "timing.end_extended", "Cue end uses limited word-gap extension."),
        )
        for enabled, count, code, message in flags:
            if not enabled:
                continue
            counts[count] += 1
            findings.append(SubtitleFindingDTO(
                code, "info" if code == "timing.end_extended" else "warning", message,
                cue_ids=(cue.id,), sentence_ids=tuple(part.sentence_id for part in cue.fragments),
                word_ids=(cue.fragments[0].first_word_id,) if cue.fragments[0].first_word_id == cue.fragments[-1].last_word_id
                else (cue.fragments[0].first_word_id, cue.fragments[-1].last_word_id),
                original_start_ms=cue.start_ms, original_end_ms=cue.base_end_ms,
                final_start_ms=cue.start_ms, final_end_ms=cue.end_ms, observed=observations,
            ))
        target_warnings = (
            (observations["chinese_half_units"] > PROFILE.parameters["chinese_target_half_units"],
             "reading.chinese_length", "Chinese text exceeds the soft length target.",
             {"half_units": observations["chinese_half_units"],
              "target_half_units": PROFILE.parameters["chinese_target_half_units"]}),
            (observations["duration_ms"] > PROFILE.parameters["target_duration_ms"],
             "timing.target_duration", "Display duration exceeds the reporting target.",
             {"duration_ms": observations["duration_ms"],
              "target_duration_ms": PROFILE.parameters["target_duration_ms"]}),
            (candidate.cost.strong_pause_crossings > 0,
             "planning.strong_pause_retained", "An internal Chinese semicolon was retained in one cue.",
             {"semicolon_count": candidate.cost.strong_pause_crossings}),
        )
        for enabled, code, message, observed in target_warnings:
            if enabled:
                findings.append(SubtitleFindingDTO(
                    code, "warning", message, cue_ids=(cue.id,),
                    sentence_ids=tuple(part.sentence_id for part in cue.fragments),
                    original_start_ms=cue.start_ms, original_end_ms=cue.base_end_ms,
                    final_start_ms=cue.start_ms, final_end_ms=cue.end_ms, observed=observed,
                ))
        if candidate.cost.emergency_breaks:
            findings.append(SubtitleFindingDTO("planning.emergency_break", "warning",
                                               "An English word boundary without punctuation was used.", cue_ids=(cue.id,),
                                               observed={"methods": list(cue.break_methods)}))
        if candidate.cost.unnatural_breaks:
            findings.append(SubtitleFindingDTO("planning.local_rule_break", "warning",
                                               "A Chinese lexical span, name, number/unit or tight phrase was crossed.",
                                               cue_ids=(cue.id,)))
    summary = SubtitleSummaryDTO(
        cue_count=len(plan.cues), merged_cue_count=sum(len(cue.fragments) > 1 for cue in plan.cues),
        split_sentence_count=sum(count > 1 for count in sentence_cues.values()),
        average_frame_rate_approximation_count=1, **counts,
    )
    return tuple(findings), summary


def plan_subtitles(
    alignment: SourceAlignmentDTO, translation: TranslationResultDTO, *,
    source_alignment_sha256: str, translation_result_sha256: str, video_sha256: str,
    media: SubtitleMediaDTO,
    chinese_word_spans: Mapping[str, tuple[tuple[int, int], ...]] | None = None,
) -> PlanningResult:
    try:
        if translation.source_alignment_sha256 != source_alignment_sha256:
            raise ValueError("translation must reference this alignment fingerprint")
        document = _document(alignment, translation, media, chinese_word_spans)
        candidates, cost = _solve(document)
        plan = SubtitlePlanDTO(
            source_alignment_sha256, translation_result_sha256, video_sha256, "en", "zh-Hans",
            media, rules_identity(), tuple(_cue(document, candidate, position)
                                           for position, candidate in enumerate(candidates, 1)),
        )
        findings, summary = analyze_plan(plan, alignment, translation, chinese_word_spans=chinese_word_spans)
        return PlanningResult(plan, findings, summary, cost)
    except PlanningError:
        raise
    except ValueError as error:
        raise PlanningError(str(error)) from error
