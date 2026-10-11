"""Versioned publication policy for the assembled transcription workflow."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping


TRANSCRIPTION_QA_POLICY_VERSION = "transcription-qa.v1"


@dataclass(frozen=True)
class TranscriptionQaPolicy:
    """Small set of workflow-level gates not owned by an individual stage."""

    max_interpolated_word_ratio: float = 0.10
    require_non_empty_alignment: bool = True
    version: str = TRANSCRIPTION_QA_POLICY_VERSION

    def __post_init__(self) -> None:
        if self.version != TRANSCRIPTION_QA_POLICY_VERSION:
            raise ValueError(f"unsupported transcription QA policy: {self.version}")
        if (
            isinstance(self.max_interpolated_word_ratio, bool)
            or not isinstance(self.max_interpolated_word_ratio, (int, float))
            or not math.isfinite(float(self.max_interpolated_word_ratio))
            or not 0 <= float(self.max_interpolated_word_ratio) <= 1
        ):
            raise ValueError("max_interpolated_word_ratio must be between 0 and 1")
        if not isinstance(self.require_non_empty_alignment, bool):
            raise ValueError("require_non_empty_alignment must be a bool")
        object.__setattr__(
            self,
            "max_interpolated_word_ratio",
            float(self.max_interpolated_word_ratio),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "max_interpolated_word_ratio": self.max_interpolated_word_ratio,
            "require_non_empty_alignment": self.require_non_empty_alignment,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TranscriptionQaPolicy":
        return cls(
            version=data.get("version"),
            max_interpolated_word_ratio=data.get("max_interpolated_word_ratio"),
            require_non_empty_alignment=data.get("require_non_empty_alignment"),
        )
