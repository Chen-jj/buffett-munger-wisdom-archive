"""Pure current contracts: identity, exact coverage and mechanical timing only."""

from dataclasses import replace
import json

import pytest

from archive_core.application import build_pipeline_run_path
from archive_core.domain import AssetId
from archive_core.interfaces import (
    BoundarySource, BoundaryStatus, MatchType, SourceAlignmentDTO,
    SourceSentenceDTO, TextSource, TimedWordDTO, TimingSource,
)
from archive_core.interfaces.bilingual import (
    ArtifactEvidenceDTO, ChunkTranslationDTO, ChunkTranslationResultDTO, FinalBilingualDraftDTO,
    FinalCueDTO, MediaBoundaryDTO, ProtectedSpanDTO, ReadingBudgetDTO,
    SourceChunkDTO, SourceChunkPlanDTO, StageManifestDTO,
)
from archive_core.interfaces.bilingual_timing import (
    chinese_half_units, empty_frame_count, english_characters, maximum_extension_ms,
)


HASH = "a" * 64


def inputs():
    words = tuple(TimedWordDTO(f"w{n}", text, start, end, (f"aw{n}",), (), MatchType.ASR_ONLY,
                              TextSource.ASR, TimingSource.ACOUSTIC_ALIGNMENT)
                  for n, (text, start, end) in enumerate((("Hello", 0, 400), ("world.", 500, 1000)), 1))
    sentence = SourceSentenceDTO("s1", "w1", "w2", 0, 1000, "Hello world.", None,
                                 TextSource.ASR, BoundarySource.ASR_PUNCTUATION, BoundaryStatus.INFERRED)
    alignment = SourceAlignmentDTO("en", 3000, words, (sentence,), ())
    media = MediaBoundaryDTO(HASH, 3000, tuple(range(0, 3000000, 40000)))
    chunk = SourceChunkDTO("k1", ("w1", "w2"), ("s1",), "Hello world.", 0, 1000,
                           ReadingBudgetDTO(9, 13, 500), ())
    chunks = SourceChunkPlanDTO("test:group:item", HASH, media, {"version": "test"},
                               {"version": "test"}, (chunk,), (), ())
    translation = ChunkTranslationResultDTO(chunks.asset_id, HASH, HASH,
                                           (ChunkTranslationDTO("k1", "你好，世界。"),), ())
    cue = FinalCueDTO("c1", chunk.word_ids, chunk.sentence_ids, chunk.english_text, "你好，世界。",
                      0, 1000, 1200, ("k1",))
    draft = FinalBilingualDraftDTO(chunks.asset_id, HASH, HASH, HASH, media, {"version": "test"},
                                   (cue,), (), ({"code": "pending.semantic"},))
    return alignment, chunks, translation, draft


@pytest.mark.parametrize("position", range(1, 4))
def test_new_artifacts_round_trip_and_cross_validate(position):
    alignment, chunks, translation, draft = inputs()
    value = (chunks, translation, draft)[position - 1]
    assert type(value).from_dict(json.loads(json.dumps(value.to_dict()))) == value
    chunks.validate_against_alignment(alignment)
    translation.validate_against_inputs(alignment, chunks)
    draft.validate_against_inputs(alignment, chunks, translation)


@pytest.mark.parametrize("position", range(1, 4))
@pytest.mark.parametrize("mutation", ("extra", "missing", "version"))
def test_new_artifacts_reject_legacy_unknown_or_partial_shapes(position, mutation):
    value = inputs()[position]
    data = value.to_dict()
    if mutation == "extra":
        data["legacy"] = True
    elif mutation == "missing":
        del data["asset_id"]
    else:
        data["schema_version"] = "old.v1"
    with pytest.raises(ValueError):
        type(value).from_dict(data)


@pytest.mark.parametrize("changes", ({"word_ids": ("w1",)}, {"english_text": "Hello there."},
                                      {"start_ms": 1}, {"sentence_ids": ("s2",)}))
def test_source_chunks_cannot_change_source(changes):
    alignment, chunks, _, _ = inputs()
    wrong = replace(chunks, chunks=(replace(chunks.chunks[0], **changes),))
    with pytest.raises(ValueError):
        wrong.validate_against_alignment(alignment)


def test_final_chinese_is_not_required_to_be_initial_translation_slice():
    alignment, chunks, translation, draft = inputs()
    revised = replace(draft, cues=(replace(draft.cues[0], chinese_text="大家好。"),))
    revised.validate_against_inputs(alignment, chunks, translation)


@pytest.mark.parametrize("changes", ({"final_end_ms": 1501}, {"final_end_ms": 999},
                                      {"word_ids": ("w1", "w3")}, {"chinese_text": " "}))
def test_final_cue_rejects_hard_correctness_errors(changes):
    with pytest.raises(ValueError):
        replace(inputs()[3].cues[0], **changes)


def test_final_preserves_initial_chunk_provenance():
    alignment, chunks, translation, draft = inputs()
    with pytest.raises(ValueError, match="provenance"):
        replace(draft, cues=(replace(draft.cues[0], initial_chunk_ids=("k2",)),)).validate_against_inputs(alignment, chunks, translation)


def test_protected_spans_and_analysis_references_are_validated():
    alignment, chunks, _, _ = inputs()
    with pytest.raises(ValueError, match="unknown"):
        replace(chunks, protected_spans=(ProtectedSpanDTO("w1", "w3", "name"),)).validate_against_alignment(alignment)
    with pytest.raises(ValueError, match="unknown"):
        replace(chunks, analyzed_sentence_ids=("s2",)).validate_against_alignment(alignment)


@pytest.mark.parametrize("text,half_units", (("中文", 4), ("Coca-Cola", 2), ("See’s", 2), ("12%", 3),
                                            ("中 Latin word，", 8), ("a\u0301", 2), (" ", 0)))
def test_frozen_chinese_mixed_count(text, half_units):
    assert chinese_half_units(text) == half_units


def test_english_count_includes_spaces_punctuation_and_codepoints():
    assert english_characters("a b.") == 4
    assert english_characters("e\u0301") == 2


@pytest.mark.parametrize("end,next_start,count", ((1000, 1000, 0), (1000, 1040, 1), (1000, 1080, 2), (1001, 1080, 1)))
def test_actual_frame_half_open_count(end, next_start, count):
    assert empty_frame_count(inputs()[1].media, end, next_start) == count


def test_actual_frame_borrowing_floors_second_last_reserved_pts():
    media = MediaBoundaryDTO(HASH, 3000, (1000123, 1040123, 1080123, 1120123, 1160123))
    assert maximum_extension_ms(media, 0, 1000, 1161) == 120
    assert maximum_extension_ms(media, 0, 1000, 1041) == 0
    assert maximum_extension_ms(replace(media, frame_timestamps_us=None), 0, 1000, 2000) == 0
    assert maximum_extension_ms(replace(media, frame_timestamps_us=None), 0, 1000, None) == 500
    assert empty_frame_count(replace(media, frame_timestamps_us=None), 1000, 2000) is None
    with pytest.raises(ValueError, match="overlap"):
        empty_frame_count(media, 1000, 999)


@pytest.mark.parametrize("frames", ((0, 0), (2, 1), (-1,), (3000000,), (True,), ()))
def test_frame_evidence_rejects_invalid_timestamps(frames):
    with pytest.raises(ValueError):
        MediaBoundaryDTO(HASH, 3000, frames)


def test_stage_manifest_roundtrip_and_strict_evidence():
    evidence = ArtifactEvidenceDTO("/tmp/source.json", 10, HASH)
    manifest = StageManifestDTO("translation", "test:group:item", {"source": evidence},
                                {"result": replace(evidence, path="/tmp/result.json")}, {"version": "x"},
                                "2026-11-05T00:00:00Z", {"provider_calls": 0})
    assert StageManifestDTO.from_dict(manifest.to_dict()) == manifest
    with pytest.raises(ValueError):
        replace(manifest, inputs={})
    assert replace(manifest, stage="acquisition", inputs={}).inputs == {}
    with pytest.raises(ValueError):
        replace(manifest, identity={"x": float("nan")})
    with pytest.raises(ValueError):
        replace(manifest, execution={"provider_calls": True})
    with pytest.raises(ValueError):
        replace(manifest, status="failed")


@pytest.mark.parametrize("run_id", ("../x", "x/y", "", "/tmp", "a.b"))
def test_run_path_rejects_unsafe_ids(run_id):
    with pytest.raises(ValueError):
        build_pipeline_run_path(AssetId("test", "group", "item"), "/tmp", run_id)


def test_run_path_uses_workspace_contract_without_io():
    assert str(build_pipeline_run_path(AssetId("test", "group", "item"), "/tmp", "run-1")) == "/tmp/test_group_item/pipeline_runs/run-1"
