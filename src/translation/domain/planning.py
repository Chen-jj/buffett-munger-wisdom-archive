"""Deterministic translation request planning from public source alignment."""

from __future__ import annotations

from archive_core.interfaces import SourceAlignmentDTO

from .models import (
    SOURCE_LANGUAGE,
    TARGET_LANGUAGE,
    TranslationRequest,
    TranslationRequestItem,
    TranslationRequestSection,
)


def plan_translation_requests(
    alignment: SourceAlignmentDTO,
) -> tuple[TranslationRequest, ...]:
    """Plan one complete request per section, or one complete document request."""

    if not isinstance(alignment, SourceAlignmentDTO):
        raise ValueError("alignment must be a SourceAlignmentDTO")
    if alignment.language != SOURCE_LANGUAGE:
        raise ValueError(f"alignment language must be {SOURCE_LANGUAGE}")

    if not alignment.sections:
        return (
            TranslationRequest(
                source_language=SOURCE_LANGUAGE,
                target_language=TARGET_LANGUAGE,
                section=None,
                items=tuple(
                    TranslationRequestItem(sentence.id, sentence.text)
                    for sentence in alignment.sentences
                ),
            ),
        )

    sentence_positions = {
        sentence.id: position for position, sentence in enumerate(alignment.sentences)
    }
    requests = []
    for section in alignment.sections:
        first_position = sentence_positions[section.first_sentence_id]
        last_position = sentence_positions[section.last_sentence_id]
        requests.append(
            TranslationRequest(
                source_language=SOURCE_LANGUAGE,
                target_language=TARGET_LANGUAGE,
                section=TranslationRequestSection(section.id, section.title),
                items=tuple(
                    TranslationRequestItem(sentence.id, sentence.text)
                    for sentence in alignment.sentences[
                        first_position : last_position + 1
                    ]
                ),
            )
        )
    return tuple(requests)
