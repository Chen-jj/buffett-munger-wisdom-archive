"""Complete sentence-group batching and read-only context for source chunks."""

from __future__ import annotations

import re

from archive_core.interfaces import SourceAlignmentDTO
from archive_core.interfaces.bilingual import SourceChunkPlanDTO

from .glossary import TranslationGlossary
from .models import TranslationRequest, TranslationRequestItem, TranslationRequestSection

BATCH_CHUNK_LIMIT = 50
TERM_MATCH_VERSION = "case-insensitive-unicode-word-boundary-longest-apostrophe.v2"


def matched_glossary(text: str, glossary: TranslationGlossary | None) -> tuple[dict, ...]:
    if glossary is None:
        return ()
    text = text.replace("’", "'")
    matches = []
    for index, entry in enumerate(glossary.entries):
        pattern = r"(?<!\w)" + re.escape(entry.source.replace("’", "'")) + r"(?!\w)"
        matches.extend((match.start(), -match.end(), index)
                       for match in re.finditer(pattern, text, flags=re.IGNORECASE))
    used, end = set(), 0
    for start, negative_end, index in sorted(matches):
        if start >= end:
            used.add(index)
            end = -negative_end
    return tuple(entry.to_dict() for index, entry in enumerate(glossary.entries) if index in used)


def sentence_groups(chunks) -> tuple[tuple, ...]:
    """Connected ordered components: a source sentence is never split between groups."""
    groups = []
    current, sentence_ids = [], set()
    for chunk in chunks:
        if current and not sentence_ids.intersection(chunk.sentence_ids):
            groups.append(tuple(current))
            current, sentence_ids = [], set()
        current.append(chunk)
        sentence_ids.update(chunk.sentence_ids)
    if current:
        groups.append(tuple(current))
    return tuple(groups)


def plan_translation_requests(alignment: SourceAlignmentDTO, chunks: SourceChunkPlanDTO,
                              glossary: TranslationGlossary | None = None) -> tuple[TranslationRequest, ...]:
    chunks.validate_against_alignment(alignment)
    positions = {sentence.id: index for index, sentence in enumerate(alignment.sentences)}
    section_for = {}
    for section in alignment.sections:
        for sentence in alignment.sentences[positions[section.first_sentence_id]:positions[section.last_sentence_id]+1]:
            section_for[sentence.id] = section
    batches, current, active_section = [], [], None
    for group in sentence_groups(chunks.chunks):
        section = section_for.get(group[0].sentence_ids[0])
        if current and (section != active_section or len(current) + len(group) > BATCH_CHUNK_LIMIT):
            batches.append((active_section, tuple(current)))
            current = []
        active_section = section
        current.extend(group)
        if len(group) > BATCH_CHUNK_LIMIT:
            batches.append((section, tuple(current)))
            current = []
    if current:
        batches.append((active_section, tuple(current)))
    requests, seen_sections = [], set()
    for section, batch in batches:
        if section:
            context = alignment.sentences[positions[section.first_sentence_id]:positions[section.last_sentence_id]+1]
        else:
            first = min(positions[sid] for chunk in batch for sid in chunk.sentence_ids)
            last = max(positions[sid] for chunk in batch for sid in chunk.sentence_ids)
            context = alignment.sentences[max(0,first-3):last+3]
        ids = {wid for chunk in batch for wid in chunk.word_ids}
        title_task = section is not None and bool(section.title.strip()) and section.id not in seen_sections
        if section:
            seen_sections.add(section.id)
        requests.append(TranslationRequest(
            source_language="en", target_language="zh-Hans",
            section=TranslationRequestSection(section.id, section.title) if section else None,
            items=tuple(TranslationRequestItem(chunk.id, chunk.english_text, chunk.budget.to_dict()) for chunk in batch),
            readonly_context=tuple({"id": sentence.id, "text": sentence.text} for sentence in context),
            annotations=tuple(annotation.to_dict() for annotation in alignment.annotations if annotation.after_word_id in ids),
            glossary=matched_glossary(" ".join(chunk.english_text for chunk in batch), glossary),
            translate_title=title_task,
        ))
    return tuple(requests)
