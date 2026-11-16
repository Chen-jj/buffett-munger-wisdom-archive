"""Stable public composition boundary for orchestration."""

from typing import Any, Mapping


def build_transcription_handler(*, output_root: str = "output", runtime: Mapping[str, Any] | None = None):
    from transcription.infrastructure.composition import build_transcription_handler as build

    return build(output_root=output_root, runtime=runtime)
