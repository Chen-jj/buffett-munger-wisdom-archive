"""Dependency-free local sentence boundary detector."""

from __future__ import annotations

from transcription.domain import (
    ProviderIdentity,
    SentenceBoundaryPolicy,
    is_sentence_terminal,
)


class RuleBasedSentenceBoundaryDetector:
    """Detect conservative English punctuation boundaries without network or ML."""

    @property
    def identity(self) -> ProviderIdentity:
        return ProviderIdentity(
            name="local-rule-sentence-detector",
            version="1",
        )

    def detect(
        self,
        words: tuple[str, ...],
        policy: SentenceBoundaryPolicy,
    ) -> tuple[int, ...]:
        return tuple(
            index
            for index in range(len(words))
            if is_sentence_terminal(words, index, policy)
        )
