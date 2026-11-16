from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from archive_core.application import build_asset_workspace
from archive_core.domain import AssetId
from archive_core.interfaces import StructuredTranscriptDTO

from acquisition.domain import (
    AcquisitionResult,
    Chapter,
    MediaReference,
    Provenance,
    SourceMetadata,
    Transcript,
    TranscriptParagraph,
)
from acquisition.infrastructure import LocalAcquisitionArtifactWriter


_DEFAULT_TRANSCRIPT = object()


def _sample_result(
    transcript: Transcript | None | object = _DEFAULT_TRANSCRIPT,
) -> AcquisitionResult:
    asset_id = AssetId("cnbc", "1994", "morning")
    normalized_transcript = (
        Transcript(
            chapters=(
                Chapter(
                    number=1,
                    title="Opening",
                    paragraphs=(
                        TranscriptParagraph(
                            text="Welcome to the meeting.",
                            speaker_label="WARREN BUFFETT",
                            stage_directions=("APPLAUSE",),
                        ),
                        TranscriptParagraph(
                            text="",
                            stage_directions=("BREAK",),
                        ),
                    ),
                ),
            )
        )
        if transcript is _DEFAULT_TRANSCRIPT
        else transcript
    )
    return AcquisitionResult(
        asset_id=asset_id,
        source_ref="https://buffett.cnbc.com/video/morning-session.html",
        media_ref=MediaReference(
            kind="page_url",
            value="https://buffett.cnbc.com/video/morning-session.html",
            extra={"video_id": "123"},
        ),
        transcript=normalized_transcript,
        metadata=SourceMetadata(
            schema_version="acquisition.source-metadata.v1",
            title="Sample",
            video_id="123",
            raw_metadata={"id": "123"},
        ),
        provenance=Provenance(
            crawler="cnbc",
            fetched_at="2026-01-01T00:00:00+00:00",
            transcript_available=True,
        ),
    )




def test_unversioned_transcript_shape_is_not_accepted_as_current_schema() -> None:
    with pytest.raises(ValueError, match="unsupported structured transcript schema"):
        StructuredTranscriptDTO.from_dict(
            {
                "chapters": [
                    {
                        "number": 1,
                        "title": "Opening",
                        "paragraphs": ["legacy paragraph"],
                    }
                ]
            }
        )
