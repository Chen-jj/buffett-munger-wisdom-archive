"""Pure rendering for the versioned translation instructions resource."""

from __future__ import annotations

import json

from .glossary import TranslationGlossary


PROMPT_VERSION = "translation.zh-hans.v1"
GLOSSARY_PLACEHOLDER = "{{GLOSSARY_JSON}}"


def render_translation_instructions(
    prompt_template: str, glossary: TranslationGlossary | None
) -> str:
    """Render optional glossary data into a caller-loaded prompt resource."""

    if not isinstance(prompt_template, str) or not prompt_template.strip():
        raise ValueError("prompt_template must be a non-blank string")
    if prompt_template.count(GLOSSARY_PLACEHOLDER) != 1:
        raise ValueError("prompt_template must contain one glossary placeholder")
    if glossary is not None and not isinstance(glossary, TranslationGlossary):
        raise ValueError("glossary must be a TranslationGlossary or null")

    glossary_data = None if glossary is None else glossary.to_dict()
    rendered_glossary = json.dumps(
        glossary_data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return prompt_template.replace(GLOSSARY_PLACEHOLDER, rendered_glossary)
