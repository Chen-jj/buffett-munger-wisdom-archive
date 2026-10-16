from pathlib import Path

import pytest

from archive_core.application import build_asset_workspace
from archive_core.domain import ArtifactRef, ArtifactType, AssetId, canonical_filename
from archive_core.interfaces import (
    BoundarySource,
    BoundaryStatus,
    MatchType,
    SourceAlignmentDTO,
    SourceSectionDTO,
    SourceSentenceDTO,
    StructuredTranscriptDTO,
    TextSource,
    TimedWordDTO,
    TimingSource,
    TranscriptChapterDTO,
    TranscriptParagraphDTO,
    reconstruct_sentence_text,
    source_sentence_id,
    timed_word_id,
)


TRANSCRIPTION_FILENAMES = {
    ArtifactType.SOURCE_AUDIO: "audio.wav",
    ArtifactType.VAD: "vad.json",
    ArtifactType.RAW_ASR: "raw_asr.json",
    ArtifactType.ALIGNED_ASR: "aligned_asr.json",
    ArtifactType.TRANSCRIPT_FUSION: "transcript_fusion.json",
    ArtifactType.SOURCE_ALIGNMENT: "source_alignment.json",
    ArtifactType.TRANSCRIPTION_LOG: "transcription.log",
    ArtifactType.TRANSCRIPTION_REPORT: "transcription_report.json",
    ArtifactType.TRANSCRIPTION_MANIFEST: "transcription_manifest.json",
}


def _word(
    position: int,
    text: str,
    start_ms: int,
    end_ms: int,
    *,
    match_type: MatchType = MatchType.NORMALIZED_EXACT,
) -> TimedWordDTO:
    return TimedWordDTO(
        id=timed_word_id(position),
        text=text,
        start_ms=start_ms,
        end_ms=end_ms,
        asr_word_ids=(f"aw{position}",),
        official_token_ids=(f"ot{position}",),
        match_type=match_type,
        text_source=TextSource.OFFICIAL_TRANSCRIPT,
        timing_source=TimingSource.ACOUSTIC_ALIGNMENT,
    )


def _sentence(
    position: int,
    first_word_position: int,
    last_word_position: int,
    start_ms: int,
    end_ms: int,
    text: str,
    *,
    speaker_label: str | None = None,
) -> SourceSentenceDTO:
    return SourceSentenceDTO(
        id=source_sentence_id(position),
        first_word_id=timed_word_id(first_word_position),
        last_word_id=timed_word_id(last_word_position),
        start_ms=start_ms,
        end_ms=end_ms,
        text=text,
        speaker_label=speaker_label,
        text_source=TextSource.OFFICIAL_TRANSCRIPT,
        boundary_source=BoundarySource.OFFICIAL_PUNCTUATION,
        boundary_status=BoundaryStatus.VERIFIED,
    )


def _valid_alignment() -> SourceAlignmentDTO:
    return SourceAlignmentDTO(
        language="en",
        audio_duration_ms=4_000,
        words=(
            _word(1, "Good", 2_100, 2_320),
            _word(2, "morning,", 2_400, 2_700),
            _word(3, "everyone.", 2_750, 3_050),
        ),
        sentences=(
            _sentence(
                1,
                1,
                3,
                2_100,
                3_050,
                "Good morning, everyone.",
                speaker_label="WARREN BUFFETT",
            ),
        ),
        sections=(),
    )


def _valid_sectioned_alignment() -> SourceAlignmentDTO:
    return SourceAlignmentDTO(
        language="en",
        audio_duration_ms=1_000,
        words=(
            _word(1, "One.", 100, 200),
            _word(2, "Two.", 300, 400),
            _word(3, "Three.", 500, 600),
        ),
        sentences=(
            _sentence(1, 1, 1, 100, 200, "One."),
            _sentence(2, 2, 2, 300, 400, "Two."),
            _sentence(3, 3, 3, 500, 600, "Three."),
        ),
        sections=(
            SourceSectionDTO(
                id="sec1",
                title="",
                first_sentence_id="s1",
                last_sentence_id="s2",
            ),
            SourceSectionDTO(
                id="sec2",
                title="Closing",
                first_sentence_id="s3",
                last_sentence_id="s3",
            ),
        ),
    )


@pytest.mark.parametrize(
    ("artifact_type", "filename"), TRANSCRIPTION_FILENAMES.items()
)
def test_transcription_artifacts_use_canonical_workspace_filenames(
    tmp_path: Path, artifact_type: ArtifactType, filename: str
) -> None:
    asset_id = AssetId("cnbc", "1994", "morning")
    workspace = build_asset_workspace(asset_id, tmp_path)

    ref = ArtifactRef.canonical(asset_id, artifact_type)

    assert canonical_filename(artifact_type) == filename
    assert workspace / canonical_filename(artifact_type) == workspace / filename
    assert ref.relative_path == f"cnbc_1994_morning/{filename}"


def test_structured_transcript_round_trips_explicit_versioned_shape() -> None:
    transcript = StructuredTranscriptDTO(
        language="en",
        chapters=(
            TranscriptChapterDTO(
                number=1,
                title="Opening Remarks",
                paragraphs=(
                    TranscriptParagraphDTO(
                        text="Good morning. We welcome shareholders.",
                        speaker_label="WARREN BUFFETT",
                        stage_directions=("Applause.",),
                    ),
                    TranscriptParagraphDTO(
                        text="Please take your seats.", speaker_label=None
                    ),
                    TranscriptParagraphDTO(
                        text="", stage_directions=("Laughter.",)
                    ),
                ),
            ),
        ),
    )

    data = transcript.to_dict()

    assert data == {
        "schema_version": "acquisition.transcript.v2",
        "language": "en",
        "chapters": [
            {
                "number": 1,
                "title": "Opening Remarks",
                "paragraphs": [
                    {
                        "speaker_label": "WARREN BUFFETT",
                        "text": "Good morning. We welcome shareholders.",
                        "stage_directions": ["Applause."],
                    },
                    {
                        "speaker_label": None,
                        "text": "Please take your seats.",
                        "stage_directions": [],
                    },
                    {
                        "speaker_label": None,
                        "text": "",
                        "stage_directions": ["Laughter."],
                    },
                ],
            }
        ],
    }
    assert StructuredTranscriptDTO.from_dict(data).to_dict() == data


@pytest.mark.parametrize("speaker_label", [0, False, [], {}])
def test_structured_transcript_rejects_non_string_speaker_labels(
    speaker_label: object,
) -> None:
    data = {
        "schema_version": "acquisition.transcript.v2",
        "language": "en",
        "chapters": [
            {
                "number": 1,
                "title": "Opening",
                "paragraphs": [{"speaker_label": speaker_label, "text": "Hello."}],
            }
        ],
    }

    with pytest.raises(ValueError, match="speaker_label"):
        StructuredTranscriptDTO.from_dict(data)


def test_structured_transcript_defaults_missing_stage_directions_to_empty() -> None:
    data = {
        "schema_version": "acquisition.transcript.v2",
        "language": "en",
        "chapters": [
            {
                "number": 1,
                "title": "Opening",
                "paragraphs": [{"speaker_label": None, "text": "Hello."}],
            }
        ],
    }

    paragraph = StructuredTranscriptDTO.from_dict(data).chapters[0].paragraphs[0]

    assert paragraph.stage_directions == ()


@pytest.mark.parametrize(
    "stage_directions",
    ["Applause.", [""], ["  "], [1], [None], [{}]],
)
def test_structured_transcript_rejects_invalid_stage_directions(
    stage_directions: object,
) -> None:
    data = {
        "schema_version": "acquisition.transcript.v2",
        "language": "en",
        "chapters": [
            {
                "number": 1,
                "title": "Opening",
                "paragraphs": [
                    {
                        "speaker_label": None,
                        "text": "Hello.",
                        "stage_directions": stage_directions,
                    }
                ],
            }
        ],
    }

    with pytest.raises(ValueError, match="stage_directions"):
        StructuredTranscriptDTO.from_dict(data)


@pytest.mark.parametrize("text", ["", "  "])
def test_structured_transcript_rejects_paragraph_without_content(text: str) -> None:
    with pytest.raises(ValueError, match="text or stage_directions|spoken text"):
        TranscriptParagraphDTO(text=text)


def test_versioned_transcription_contracts_reject_unknown_versions() -> None:
    transcript_data = StructuredTranscriptDTO(language="en").to_dict()
    alignment_data = SourceAlignmentDTO(
        language="en", audio_duration_ms=0, words=(), sentences=(), sections=()
    ).to_dict()

    with pytest.raises(ValueError, match="unsupported structured transcript schema"):
        StructuredTranscriptDTO.from_dict(
            {**transcript_data, "schema_version": "acquisition.transcript.v1"}
        )
    with pytest.raises(ValueError, match="unsupported source alignment schema"):
        SourceAlignmentDTO.from_dict(
            {**alignment_data, "schema_version": "transcription.source-alignment.v2"}
        )


def test_source_alignment_round_trips_with_null_and_string_speakers() -> None:
    alignment = SourceAlignmentDTO(
        language="en",
        audio_duration_ms=2_000,
        words=(
            _word(1, "Hello.", 100, 500),
            _word(2, "Welcome.", 1_000, 1_500),
        ),
        sentences=(
            _sentence(1, 1, 1, 100, 500, "Hello.", speaker_label=None),
            _sentence(
                2, 2, 2, 1_000, 1_500, "Welcome.", speaker_label="CHARLIE MUNGER"
            ),
        ),
        sections=(),
    )

    data = alignment.to_dict()
    restored = SourceAlignmentDTO.from_dict(data)

    assert data["schema_version"] == "transcription.source-alignment.v1"
    assert data["audio_duration_ms"] == 2_000
    assert data["sentences"][0]["speaker_label"] is None
    assert data["sentences"][1]["speaker_label"] == "CHARLIE MUNGER"
    assert data["sections"] == []
    assert restored.to_dict() == data


def test_source_alignment_round_trips_multi_section_shape_with_empty_title() -> None:
    alignment = _valid_sectioned_alignment()

    data = alignment.to_dict()

    assert data["sections"] == [
        {
            "id": "sec1",
            "title": "",
            "first_sentence_id": "s1",
            "last_sentence_id": "s2",
        },
        {
            "id": "sec2",
            "title": "Closing",
            "first_sentence_id": "s3",
            "last_sentence_id": "s3",
        },
    ]
    assert SourceAlignmentDTO.from_dict(data) == alignment


def test_source_alignment_rejects_missing_sections() -> None:
    data = _valid_alignment().to_dict()
    del data["sections"]

    with pytest.raises(ValueError, match="sections must be an array"):
        SourceAlignmentDTO.from_dict(data)


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("id", 1),
        ("title", None),
        ("first_sentence_id", False),
        ("last_sentence_id", []),
    ],
)
def test_source_section_rejects_invalid_field_types(
    field_name: str, value: object
) -> None:
    data = {
        "id": "sec1",
        "title": "Opening",
        "first_sentence_id": "s1",
        "last_sentence_id": "s1",
    }
    data[field_name] = value

    with pytest.raises(ValueError, match=field_name):
        SourceSectionDTO.from_dict(data)


@pytest.mark.parametrize("sections", [None, {}, "sections", ["sec1"]])
def test_source_alignment_rejects_invalid_sections_shape(sections: object) -> None:
    data = _valid_alignment().to_dict()
    data["sections"] = sections

    with pytest.raises(ValueError, match="sections"):
        SourceAlignmentDTO.from_dict(data)


@pytest.mark.parametrize(
    ("sections", "message"),
    [
        (
            [
                {
                    "id": "sec1",
                    "title": "First",
                    "first_sentence_id": "s1",
                    "last_sentence_id": "s1",
                },
                {
                    "id": "sec1",
                    "title": "Rest",
                    "first_sentence_id": "s2",
                    "last_sentence_id": "s3",
                },
            ],
            "sec1..secN",
        ),
        (
            [
                {
                    "id": "sec1",
                    "title": "All",
                    "first_sentence_id": "s1",
                    "last_sentence_id": "s4",
                }
            ],
            "reference existing sentences",
        ),
        (
            [
                {
                    "id": "sec1",
                    "title": "First",
                    "first_sentence_id": "s1",
                    "last_sentence_id": "s1",
                },
                {
                    "id": "sec2",
                    "title": "Third",
                    "first_sentence_id": "s3",
                    "last_sentence_id": "s3",
                },
            ],
            "consecutive sentences once",
        ),
        (
            [
                {
                    "id": "sec1",
                    "title": "First two",
                    "first_sentence_id": "s1",
                    "last_sentence_id": "s2",
                },
                {
                    "id": "sec2",
                    "title": "Overlap",
                    "first_sentence_id": "s2",
                    "last_sentence_id": "s3",
                },
            ],
            "consecutive sentences once",
        ),
        (
            [
                {
                    "id": "sec1",
                    "title": "Backwards",
                    "first_sentence_id": "s2",
                    "last_sentence_id": "s1",
                }
            ],
            "consecutive sentences once",
        ),
        (
            [
                {
                    "id": "sec1",
                    "title": "Incomplete",
                    "first_sentence_id": "s1",
                    "last_sentence_id": "s2",
                }
            ],
            "cover every sentence",
        ),
    ],
)
def test_source_alignment_rejects_invalid_section_coverage(
    sections: list[dict[str, object]], message: str
) -> None:
    data = _valid_sectioned_alignment().to_dict()
    data["sections"] = sections

    with pytest.raises(ValueError, match=message):
        SourceAlignmentDTO.from_dict(data)


@pytest.mark.parametrize("speaker_label", [1, False, [], {}])
def test_source_sentence_rejects_non_string_non_null_speaker(
    speaker_label: object,
) -> None:
    data = _valid_alignment().to_dict()
    data["sentences"][0]["speaker_label"] = speaker_label

    with pytest.raises(ValueError, match="speaker_label"):
        SourceAlignmentDTO.from_dict(data)


def test_stable_ids_are_one_based_and_must_follow_document_order() -> None:
    assert [timed_word_id(position) for position in range(1, 4)] == ["w1", "w2", "w3"]
    assert [source_sentence_id(position) for position in range(1, 3)] == ["s1", "s2"]

    invalid_word = _word(2, "Good", 100, 200)
    valid_sentence = _sentence(1, 2, 2, 100, 200, "Good")
    with pytest.raises(ValueError, match="w1..wN"):
        SourceAlignmentDTO(
            language="en",
            audio_duration_ms=500,
            words=(invalid_word,),
            sentences=(valid_sentence,),
            sections=(),
        )

    alignment = _valid_alignment()
    invalid_sentence = SourceSentenceDTO(
        **{**alignment.sentences[0].__dict__, "id": "s2"}
    )
    with pytest.raises(ValueError, match="s1..sN"):
        SourceAlignmentDTO(
            language="en",
            audio_duration_ms=alignment.audio_duration_ms,
            words=alignment.words,
            sentences=(invalid_sentence,),
            sections=(),
        )


@pytest.mark.parametrize(
    ("start_ms", "end_ms"),
    [(-1, 10), (0, 0), (10, 10), (20, 10), (False, 10), (0, True)],
)
def test_timed_word_rejects_invalid_integer_millisecond_ranges(
    start_ms: object, end_ms: object
) -> None:
    with pytest.raises(ValueError):
        TimedWordDTO(
            id="w1",
            text="word",
            start_ms=start_ms,  # type: ignore[arg-type]
            end_ms=end_ms,  # type: ignore[arg-type]
            asr_word_ids=("aw1",),
            official_token_ids=(),
            match_type=MatchType.ASR_ONLY,
            text_source=TextSource.ASR,
            timing_source=TimingSource.ACOUSTIC_ALIGNMENT,
        )


@pytest.mark.parametrize("text", ["", "  ", "\n\t", "...", "?!"])
def test_timed_word_rejects_empty_text(text: str) -> None:
    with pytest.raises(ValueError, match="text must be|word text must"):
        _word(1, text, 100, 200)


def test_source_alignment_rejects_word_overlap_and_audio_overrun() -> None:
    overlap_words = (
        _word(1, "one", 100, 300),
        _word(2, "two", 250, 400),
    )
    sentence = _sentence(1, 1, 2, 100, 400, "one two")

    with pytest.raises(ValueError, match="must not overlap"):
        SourceAlignmentDTO(
            language="en",
            audio_duration_ms=500,
            words=overlap_words,
            sentences=(sentence,),
            sections=(),
        )

    with pytest.raises(ValueError, match="must not exceed audio_duration_ms"):
        SourceAlignmentDTO(
            language="en",
            audio_duration_ms=399,
            words=(
                _word(1, "one", 100, 200),
                _word(2, "two", 300, 400),
            ),
            sentences=(sentence,),
            sections=(),
        )


def test_source_alignment_rejects_missing_duplicate_or_non_contiguous_coverage() -> None:
    words = (
        _word(1, "one", 100, 200),
        _word(2, "two", 300, 400),
        _word(3, "three", 500, 600),
    )

    with pytest.raises(ValueError, match="every timed word"):
        SourceAlignmentDTO(
            language="en",
            audio_duration_ms=1_000,
            words=words,
            sentences=(_sentence(1, 1, 2, 100, 400, "one two"),),
            sections=(),
        )

    with pytest.raises(ValueError, match="consecutive words once"):
        SourceAlignmentDTO(
            language="en",
            audio_duration_ms=1_000,
            words=words,
            sentences=(
                _sentence(1, 1, 2, 100, 400, "one two"),
                _sentence(2, 2, 3, 300, 600, "two three"),
            ),
            sections=(),
        )

    with pytest.raises(ValueError, match="consecutive words once"):
        SourceAlignmentDTO(
            language="en",
            audio_duration_ms=1_000,
            words=words,
            sentences=(
                _sentence(1, 1, 1, 100, 200, "one"),
                _sentence(2, 3, 3, 500, 600, "three"),
            ),
            sections=(),
        )


def test_source_alignment_rejects_missing_word_references() -> None:
    words = (_word(1, "one", 100, 200),)
    sentence = _sentence(1, 1, 2, 100, 200, "one")

    with pytest.raises(ValueError, match="reference existing words"):
        SourceAlignmentDTO(
            language="en",
            audio_duration_ms=500,
            words=words,
            sentences=(sentence,),
            sections=(),
        )


@pytest.mark.parametrize(
    ("start_ms", "end_ms", "message"),
    [
        (99, 3_050, "start_ms must equal"),
        (2_100, 3_051, "end_ms must equal"),
    ],
)
def test_sentence_times_must_equal_referenced_edge_word_times(
    start_ms: int, end_ms: int, message: str
) -> None:
    alignment = _valid_alignment()
    sentence = _sentence(
        1, 1, 3, start_ms, end_ms, "Good morning, everyone."
    )

    with pytest.raises(ValueError, match=message):
        SourceAlignmentDTO(
            language="en",
            audio_duration_ms=4_000,
            words=alignment.words,
            sentences=(sentence,),
            sections=(),
        )


def test_sentence_text_must_reconstruct_from_word_surface_text() -> None:
    alignment = _valid_alignment()
    sentence = _sentence(
        1, 1, 3, 2_100, 3_050, "Good evening, everyone."
    )

    with pytest.raises(ValueError, match="reconstructable"):
        SourceAlignmentDTO(
            language="en",
            audio_duration_ms=4_000,
            words=alignment.words,
            sentences=(sentence,),
            sections=(),
        )


def test_sentence_text_reconstruction_normalizes_spaces_and_attached_punctuation() -> None:
    words = (
        _word(1, "Good", 100, 200),
        _word(2, "morning ,", 300, 400),
        _word(3, "everyone.", 600, 800),
    )

    assert reconstruct_sentence_text(words) == "Good morning, everyone."

    alignment = SourceAlignmentDTO(
        language="en",
        audio_duration_ms=1_000,
        words=words,
        sentences=(
            _sentence(1, 1, 3, 100, 800, "Good  morning,   everyone."),
        ),
        sections=(),
    )
    assert alignment.sentences[0].text == "Good  morning,   everyone."


def test_source_alignment_round_trip_preserves_all_source_enums() -> None:
    alignment = _valid_alignment()
    data = alignment.to_dict()

    assert data["words"][0]["match_type"] == "normalized_exact"
    assert data["words"][0]["text_source"] == "official_transcript"
    assert data["words"][0]["timing_source"] == "acoustic_alignment"
    assert data["sentences"][0]["boundary_source"] == "official_punctuation"
    assert data["sentences"][0]["boundary_status"] == "verified"
    assert SourceAlignmentDTO.from_dict(data) == alignment

    data["sentences"][0]["boundary_source"] = "document_section_change"
    assert (
        SourceAlignmentDTO.from_dict(data).sentences[0].boundary_source
        is BoundarySource.DOCUMENT_SECTION_CHANGE
    )
