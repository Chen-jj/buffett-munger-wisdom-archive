"""Deterministic two-pass source grouping, without translation or time changes."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from math import log1p
from statistics import median
from typing import Mapping, Protocol

from archive_core.interfaces.transcription import SourceAlignmentDTO, TimedWordDTO, reconstruct_sentence_text
from archive_core.interfaces.bilingual import (
    MediaBoundaryDTO, ProtectedSpanDTO, ReadingBudgetDTO, SourceChunkDTO, SourceChunkPlanDTO,
)

from archive_core.interfaces.bilingual_timing import empty_frame_count, maximum_extension_ms

from .chunking_policy import (
    CHINESE_CPS_LIMIT, CHINESE_LINE_TARGET_UNITS, CROSS_SENTENCE_MERGE_GAP_LIMIT_MS,
    ENGLISH_CPS_LIMIT, ENGLISH_MAX_CHARACTERS, MAX_CHUNK_DURATION_MS,
    MAX_EXTENSION_MS, MIN_CHUNK_DURATION_MS, FLASH_DURATION_MS,
    GAP_NEUTRAL_MAX_FRAMES, GAP_WEAK_MAX_FRAMES, GAP_RELATIVE_MIN_SAMPLES,
    GAP_RELATIVE_WEAK_Z, GAP_RELATIVE_STRONG_Z, SCORE_FIELDS, chunking_policy,
)


@dataclass(frozen=True)
class SyntaxBoundary:
    """All observed relations at one canonical word-boundary offset."""

    offset: int
    relations: tuple[str, ...]


@dataclass(frozen=True)
class SyntaxSpan:
    """A typed half-open canonical word range, relative to the complete sentence."""

    first: int
    last: int
    kind: str


@dataclass(frozen=True)
class SyntaxAnalysis:
    """Typed structure, never a parser confidence or a pre-summed boundary cost."""

    boundaries: tuple[SyntaxBoundary, ...]
    protected_spans: tuple[ProtectedSpanDTO, ...]
    spans: tuple[SyntaxSpan, ...] = ()


class ConstituencyAnalyzer(Protocol):
    @property
    def identity(self) -> Mapping[str, object]: ...

    def analyze(self, words: tuple[TimedWordDTO, ...]) -> SyntaxAnalysis: ...


def chunk_issues(text: str, duration: int) -> tuple[str, ...]:
    issues = []
    if len(text) > ENGLISH_MAX_CHARACTERS:
        issues.append("english.capacity")
    if duration > MAX_CHUNK_DURATION_MS:
        issues.append("timing.maximum_duration")
    if duration < MIN_CHUNK_DURATION_MS:
        issues.append("timing.minimum_duration")
    if len(text) * 1000 > ENGLISH_CPS_LIMIT * duration:
        issues.append("reading.english_cps")
    return tuple(issues)


def reading_budget(media, start_ms, base_end_ms, next_start_ms):
    duration = base_end_ms - start_ms
    extension = maximum_extension_ms(media, start_ms, base_end_ms, next_start_ms)
    budget = ReadingBudgetDTO(
        base_units=CHINESE_CPS_LIMIT * duration // 1000,
        maximum_units=CHINESE_CPS_LIMIT * (duration + extension) // 1000,
        extension_ms=extension, chinese_line_target_units=CHINESE_LINE_TARGET_UNITS,
    )
    issues = ()
    if next_start_ms is not None:
        count = empty_frame_count(media, base_end_ms, next_start_ms)
        if count is None:
            issues = ("timing.frame_gap_unverified",)
        elif count < 2:
            issues = ("timing.short_frame_gap",)
    return budget, issues


_STRONG_RELATIONS = frozenset({
    "subject.predicate", "predicate.complement", "noun.infinitive", "connector.after",
})
_GOOD_RELATIONS = frozenset({"clause.independent", "clause.coordinate", "clause.adverbial", "clause.interrogative"})
_DEPENDENT_SPANS = frozenset({"relative", "adverbial", "infinitive", "complement"})
_SCORE_FIELDS = len(SCORE_FIELDS)


def _structural_level(relations):
    if (_STRONG_RELATIONS.intersection(relations)
            or ("clause.relative" in relations and "evidence.relative.no-comma" in relations)):
        return 2
    if ("clause.relative" in relations
            or {"attachment.adverbial", "attachment.quantity", "attachment.nominal-of",
                "attachment.coordination", "attachment.scope", "attachment.frequency",
                "attachment.temporal", "attachment.adjectival", "noun.clause"}.intersection(relations)):
        return 1
    return 0


def _ordinary_grade(relations):
    if _structural_level(relations):
        return 0  # This event is already charged once at its highest structural level.
    if _GOOD_RELATIONS.intersection(relations):
        return 0
    if "punctuation" in relations:
        return 1
    return 2


def _canonical_punctuation(words):
    boundaries, protected = [], []
    for offset, (left, right) in enumerate(zip(words, words[1:]), 1):
        if left.text.endswith(",") and left.text[-2:-1].isdecimal() and right.text[0].isdecimal():
            protected.append(ProtectedSpanDTO(left.id, right.id, "canonical.numeric-comma.v1"))
        elif left.text.endswith((",", ";", ":", ".", "?", "!")):
            boundaries.append(SyntaxBoundary(offset, ("punctuation",)))
    return SyntaxAnalysis(tuple(boundaries), tuple(protected))


class _PartitionScorer:
    """Additive cue/boundary cost with an explicit previous-cue rhythm state."""

    def __init__(self, words, analysis, media, confirmed=(), *, use_gap=True,
                 use_relative_gap=True, use_reading=True, use_rhythm=True, sentence_ranges=None):
        self.words, self.media = words, media
        self._metrics = {}
        self.use_gap, self.use_relative_gap = use_gap, use_relative_gap
        self.use_reading, self.use_rhythm = use_reading, use_rhythm
        positions = {word.id: n for n, word in enumerate(words)}
        self.forbidden = set()
        for span in analysis.protected_spans + confirmed:
            if span.first_word_id in positions and span.last_word_id in positions:
                first, last = positions[span.first_word_id], positions[span.last_word_id]
                if last < first:
                    raise ValueError("reversed syntax protection")
                self.forbidden.update(range(first + 1, last + 1))
        self.relations = {n: {"ordinary"} for n in range(1, len(words))}
        seen = set()
        for boundary in analysis.boundaries:
            if (not isinstance(boundary, SyntaxBoundary) or type(boundary.offset) is not int
                    or not 0 < boundary.offset < len(words) or boundary.offset in seen
                    or not isinstance(boundary.relations, tuple) or not boundary.relations
                    or any(not isinstance(item, str) or not item for item in boundary.relations)):
                raise ValueError("syntax must contain unique typed canonical word boundaries")
            seen.add(boundary.offset)
            self.relations[boundary.offset].update(boundary.relations)
        for span in analysis.spans:
            if (not isinstance(span, SyntaxSpan) or type(span.first) is not int or type(span.last) is not int
                    or not 0 <= span.first < span.last <= len(words)
                    or span.kind not in {"statement", *_DEPENDENT_SPANS}):
                raise ValueError("syntax span must identify a typed canonical word range")
        self.spans = analysis.spans
        statements = tuple(span for span in analysis.spans if span.kind == "statement")
        # Coordinated child statements, rather than their umbrella S, are the units.
        self.statements = tuple(span for span in statements if not any(
            span.first <= child.first and child.last <= span.last and child != span
            for child in statements
        ))
        self.frames = {}
        if media is not None:
            self.frames = {n: empty_frame_count(media, words[n - 1].end_ms, words[n].start_ms)
                           for n in range(1, len(words))}
        ranges = sentence_ranges if sentence_ranges is not None else ((0, len(words)),)
        self.relative_stats = {}
        self.relative_center, self.relative_mad = None, 0
        for first, last in ranges:
            samples = [log1p(self.frames[n]) for n in range(first + 1, last)
                       if self.frames.get(n) is not None]
            center = median(samples) if len(samples) >= GAP_RELATIVE_MIN_SAMPLES else None
            mad = median(abs(sample - center) for sample in samples) if center is not None else 0
            self.relative_stats.update((n, (center, mad)) for n in range(first + 1, last))
            if len(ranges) == 1:
                self.relative_center, self.relative_mad = center, mad

    def metrics(self, first, last):
        if (first, last) not in self._metrics:
            part = self.words[first:last]
            self._metrics[first, last] = len(reconstruct_sentence_text(part)), part[-1].end_ms - part[0].start_ms
        return self._metrics[first, last]

    def legal(self, first, last):
        characters, duration = self.metrics(first, last)
        return (first not in self.forbidden and last not in self.forbidden
                and characters <= ENGLISH_MAX_CHARACTERS and 0 < duration <= MAX_CHUNK_DURATION_MS)

    def cue_level(self, first, last, previous_first=None):
        if not first:
            return 0  # The source start is not a cut introduced by this partition.
        level = _structural_level(self.relations[first])
        left_head = previous_first is not None and any(
            previous_first < span.first < first < span.last for span in self.statements
        )
        later_statement = any(first < span.first < last for span in self.statements)
        starts_in_tail = any(span.first < first < span.last for span in self.statements)
        dependent_tail = any(span.kind in _DEPENDENT_SPANS and span.first <= first < span.last
                             for span in self.spans)
        if left_head or (later_statement and (starts_in_tail or dependent_tail)):
            level = 2
        # All manifestations of the cut at `first` are charged on its right cue.
        return level

    def pause_reward(self, first, level):
        if not self.use_gap or not first or level:
            return 0
        relations = self.relations[first]
        if not (_GOOD_RELATIONS.intersection(relations)
                or "punctuation" in relations or "phrase.preposition" in relations):
            return 0
        frames = self.frames.get(first)
        if frames is None or frames <= GAP_NEUTRAL_MAX_FRAMES:
            return 0
        fixed = 1 if frames <= GAP_WEAK_MAX_FRAMES else 2
        relative = 0
        center, mad = self.relative_stats.get(first, (None, 0))
        if self.use_relative_gap and mad:
            z = (log1p(frames) - center) / mad
            relative = 2 if z >= GAP_RELATIVE_STRONG_Z else (1 if z >= GAP_RELATIVE_WEAK_Z else 0)
        return min(2, fixed + relative)

    def cost(self, first, last, previous_first=None):
        characters, duration = self.metrics(first, last)
        level = self.cue_level(first, last, previous_first)
        grade = _ordinary_grade(self.relations[first]) if first and not level else 0
        cps_excess = max(0, characters * 1000 - ENGLISH_CPS_LIMIT * duration) if self.use_reading else 0
        previous_characters = self.metrics(previous_first, first)[0] if previous_first is not None else None
        rhythm = abs(characters - previous_characters) if self.use_rhythm and previous_characters is not None else 0
        return (int(level == 2) + int(duration < FLASH_DURATION_MS), int(level == 1),
                int(duration < MIN_CHUNK_DURATION_MS), max(0, MIN_CHUNK_DURATION_MS - duration),
                int(grade == 3), int(grade == 2), int(grade == 1), int(cps_excess > 0), cps_excess,
                1, -self.pause_reward(first, level), rhythm, characters * characters)

    def score(self, parts):
        total, cuts, first, previous_first = [0] * _SCORE_FIELDS, [], 0, None
        for part in parts:
            last = first + len(part)
            if not part or tuple(word.id for word in part) != tuple(word.id for word in self.words[first:last]):
                raise ValueError("partition must preserve continuous canonical source coverage")
            total = [a + b for a, b in zip(total, self.cost(first, last, previous_first))]
            previous_first = first
            cuts.append(last)
            first = last
        if first != len(self.words):
            raise ValueError("partition must cover all canonical words")
        return (*total, tuple(cuts))


def evaluate_partition(words, parts, analysis, media=None, *, use_gap=True, use_relative_gap=True,
                       use_reading=True, use_rhythm=True):
    """Pure diagnostic score; options isolate requested ablations, not legacy algorithms."""
    return _PartitionScorer(words, analysis, media, use_gap=use_gap, use_relative_gap=use_relative_gap,
                            use_reading=use_reading, use_rhythm=use_rhythm).score(parts)


def _split_sentence(words, analysis, confirmed, *, stanza_media=None, use_gap=True,
                    use_relative_gap=True, use_reading=True, use_rhythm=True):
    scorer = _PartitionScorer(words, analysis, stanza_media, confirmed, use_gap=use_gap,
                              use_relative_gap=use_relative_gap, use_reading=use_reading,
                              use_rhythm=use_rhythm)

    @lru_cache(maxsize=None)
    def best(first, previous_first):
        if first == len(words):
            return (0,) * _SCORE_FIELDS + ((),), ()
        choices = []
        for last in range(first + 1, len(words) + 1):
            characters, duration = scorer.metrics(first, last)
            if characters > ENGLISH_MAX_CHARACTERS or duration > MAX_CHUNK_DURATION_MS:
                break  # Both are monotone along canonical source words.
            if not scorer.legal(first, last):
                continue
            suffix = best(last, first)
            if suffix is None:
                continue
            suffix_score, suffix_parts = suffix
            local = scorer.cost(first, last, previous_first)
            score = tuple(a + b for a, b in zip(local, suffix_score[:-1])) + ((last,) + suffix_score[-1],)
            choices.append((score, (words[first:last],) + suffix_parts))
        return min(choices, key=lambda item: item[0]) if choices else None

    result = best(0, None)
    return result[1] if result else None


def build_source_chunks(
    *, asset_id: str, alignment: SourceAlignmentDTO, source_alignment_sha256: str,
    media: MediaBoundaryDTO, analyzer: ConstituencyAnalyzer,
    confirmed_protections: tuple[ProtectedSpanDTO, ...] = (),
) -> SourceChunkPlanDTO:
    """Cut only for capacity or duration, using one complete-sentence typed DP."""
    if not alignment.words:
        raise ValueError("source chunking needs at least one source word")
    if alignment.words[-1].end_ms > media.duration_ms:
        raise ValueError("source word extends beyond usable video")
    words = alignment.words
    index = {word.id: position for position, word in enumerate(words)}
    source_sentences = {sentence.id: sentence for sentence in alignment.sentences}
    sentence_for_word = {}
    section_for_sentence = {}
    for section in alignment.sections:
        first, last = int(section.first_sentence_id[1:]), int(section.last_sentence_id[1:])
        for number in range(first, last + 1):
            section_for_sentence[f"s{number}"] = section.id
    speaker_for_sentence = {sentence.id: sentence.speaker_label for sentence in alignment.sentences}
    spans = list(confirmed_protections)
    for protection in confirmed_protections:
        if (protection.first_word_id not in index or protection.last_word_id not in index
                or index[protection.first_word_id] > index[protection.last_word_id]):
            raise ValueError("confirmed protection must identify ordered source words")
    analyzed = []
    global_boundaries, global_spans = {}, []
    groups = []
    for sentence in alignment.sentences:
        part = words[index[sentence.first_word_id]:index[sentence.last_word_id] + 1]
        for word in part:
            sentence_for_word[word.id] = sentence.id
        punctuation = _canonical_punctuation(part)
        spans.extend(punctuation.protected_spans)
        sentence_offset = index[part[0].id]
        if sentence_offset:
            global_boundaries.setdefault(sentence_offset, set()).add("clause.independent")
        if (len(reconstruct_sentence_text(part)) > ENGLISH_MAX_CHARACTERS
                or part[-1].end_ms - part[0].start_ms > MAX_CHUNK_DURATION_MS):
            raw = analyzer.analyze(part)
            _PartitionScorer(part, raw, None)  # Validate before combining canonical evidence.
            combined = {boundary.offset: set(boundary.relations) for boundary in raw.boundaries}
            for boundary in punctuation.boundaries:
                combined.setdefault(boundary.offset, set()).update(boundary.relations)
            analysis = SyntaxAnalysis(tuple(SyntaxBoundary(n, tuple(sorted(relations)))
                                            for n, relations in sorted(combined.items())),
                                      raw.protected_spans + punctuation.protected_spans, raw.spans)
            spans.extend(raw.protected_spans)
            analyzed.append(sentence.id)
            groups.extend(_split_sentence(part, analysis, confirmed_protections, stanza_media=media) or (part,))
            for boundary in analysis.boundaries:
                global_boundaries.setdefault(sentence_offset + boundary.offset, set()).update(boundary.relations)
            global_spans.extend(SyntaxSpan(sentence_offset + span.first, sentence_offset + span.last, span.kind)
                                for span in analysis.spans)
            if not any(span.kind == "statement" for span in analysis.spans):
                global_spans.append(SyntaxSpan(sentence_offset, sentence_offset + len(part), "statement"))
        else:
            groups.append(part)
            global_spans.append(SyntaxSpan(sentence_offset, sentence_offset + len(part), "statement"))

    global_analysis = SyntaxAnalysis(tuple(SyntaxBoundary(n, tuple(sorted(relations)))
                                          for n, relations in sorted(global_boundaries.items())),
                                    tuple(dict.fromkeys(spans)), tuple(global_spans))
    sentence_ranges = tuple((index[sentence.first_word_id], index[sentence.last_word_id] + 1)
                            for sentence in alignment.sentences)
    rescue_scorer = _PartitionScorer(words, global_analysis, media, sentence_ranges=sentence_ranges)

    def sentences(group):
        return tuple(dict.fromkeys(sentence_for_word[word.id] for word in group))

    def merge_allowed(left, right):
        combined = left + right
        ids = sentences(combined)
        if len(ids) > 1 and (combined[0].id != source_sentences[ids[0]].first_word_id
                             or combined[-1].id != source_sentences[ids[-1]].last_word_id):
            # A local duration rescue must not attach a different sentence's fragment.
            return False
        if len({section_for_sentence.get(sid) for sid in ids}) > 1:
            return False
        if len({speaker_for_sentence[sid] for sid in ids if speaker_for_sentence[sid] is not None}) > 1:
            return False
        for sid_left, sid_right in zip(ids, ids[1:]):
            a, b = source_sentences[sid_left], source_sentences[sid_right]
            gap = b.start_ms - a.end_ms
            if not 0 <= gap < CROSS_SENTENCE_MERGE_GAP_LIMIT_MS:
                return False
        return not chunk_issues(reconstruct_sentence_text(combined), combined[-1].end_ms - combined[0].start_ms)

    current = 0
    while current < len(groups):
        part = groups[current]
        if part[-1].end_ms - part[0].start_ms < MIN_CHUNK_DURATION_MS:
            options = []
            for neighbor in (current - 1, current + 1):
                if not 0 <= neighbor < len(groups):
                    continue
                first, last = sorted((current, neighbor))
                left, right = groups[first], groups[last]
                if merge_allowed(left, right):
                    candidate = tuple(groups[:first] + [left + right] + groups[last + 1:])
                    score = rescue_scorer.score(candidate)
                    if score < rescue_scorer.score(groups):
                        options.append((score, first, last, left + right))
            if options:
                _, first, last, combined = min(options, key=lambda option: option[0])
                groups[first:last + 1] = [combined]
                current = first + 1
                continue
        current += 1

    chunks = []
    for position, part in enumerate(groups):
        text = reconstruct_sentence_text(part)
        duration = part[-1].end_ms - part[0].start_ms
        next_start = groups[position + 1][0].start_ms if position + 1 < len(groups) else None
        budget, gap_issues = reading_budget(media, part[0].start_ms, part[-1].end_ms, next_start)
        issues = chunk_issues(text, duration) + gap_issues
        chunks.append(SourceChunkDTO(
            id=f"k{position + 1}", word_ids=tuple(word.id for word in part),
            sentence_ids=sentences(part), english_text=text,
            start_ms=part[0].start_ms, base_end_ms=part[-1].end_ms,
            budget=budget, issues=issues,
        ))
    result = SourceChunkPlanDTO(
        asset_id=asset_id, source_alignment_sha256=source_alignment_sha256,
        media=media, policy=chunking_policy(), analyzer=dict(analyzer.identity),
        chunks=tuple(chunks), protected_spans=tuple(dict.fromkeys(spans)),
        analyzed_sentence_ids=tuple(analyzed),
    )
    result.validate_against_alignment(alignment)
    return result
