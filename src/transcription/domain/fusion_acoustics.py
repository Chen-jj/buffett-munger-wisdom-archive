"""Evidence from a candidate reading of a fixed acoustic window."""

from dataclasses import dataclass


@dataclass(frozen=True)
class AcousticWordEvidence:
    text: str
    start_ms: int
    end_ms: int
    score: float


@dataclass(frozen=True)
class AcousticCandidateEvidence:
    ctc_log_likelihood: float | None
    start_ms: int | None = None
    end_ms: int | None = None
    mean_character_score: float = 0.0
    weakest_two_mean: float = 0.0
    energy_coverage: float = 0.0
    longest_weak_character_run: int = 0
    word_evidence: tuple[AcousticWordEvidence, ...] = ()
