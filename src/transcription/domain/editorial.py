"""Source-specific editorial annotation projection after completed fusion."""

from dataclasses import replace
from typing import Sequence

from archive_core.interfaces import EditorialBreakDTO, TextSource, TimedWordDTO

from .fusion import OfficialTranscriptToken


EDITORIAL_POLICY_VERSION = "cnbc-editorial-break.v1"


def separate_editorial_breaks(
    words: Sequence[TimedWordDTO],
    official_tokens: Sequence[OfficialTranscriptToken],
    *,
    source: str,
) -> tuple[tuple[TimedWordDTO, ...], tuple[EditorialBreakDTO, ...]]:
    """Remove only retained, officially sourced CNBC U+2014; never change timing."""
    if source != "cnbc":
        return tuple(words), ()
    token_map = {token.id: token for token in official_tokens}
    projected = []
    annotations = []
    for word in words:
        evidence = tuple(token_id for token_id in word.official_token_ids
                         if token_id in token_map and "—" in token_map[token_id].text)
        if "—" not in word.text or not evidence or word.text_source is not TextSource.OFFICIAL_TRANSCRIPT:
            projected.append(word)
            continue
        # A discrepancy is not permission to remove an unproven ASR symbol.
        count = sum(token_map[token_id].text.count("—") for token_id in evidence)
        if word.text.count("—") > count:
            raise ValueError("retained editorial symbols exceed official provenance")
        for _ in range(word.text.count("—")):
            annotations.append(EditorialBreakDTO(f"e{len(annotations) + 1}", word.id, evidence))
        projected.append(replace(word, text=word.text.replace("—", "")))
    return tuple(projected), tuple(annotations)
