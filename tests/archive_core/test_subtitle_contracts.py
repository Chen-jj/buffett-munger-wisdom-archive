"""Strict subtitle schemas and source-preserving range contracts (ADR-0003)."""

from dataclasses import replace
import hashlib
import json

import pytest

from archive_core.domain import ArtifactType, canonical_filename
from archive_core.interfaces import (
    BoundarySource, BoundaryStatus, MatchType, SectionTitleTranslationDTO,
    SentenceTranslationDTO, SourceAlignmentDTO, SourceSectionDTO, SourceSentenceDTO,
    SrtProcessingManifestDTO, SrtProcessingReportDTO, SubtitleArtifactEvidenceDTO,
    SubtitleCodecDTO, SubtitleCueDTO, SubtitleFindingDTO, SubtitleFragmentDTO,
    SubtitleMediaDTO, SubtitlePlanDTO, SubtitleProbeDTO, SubtitleProfileDTO,
    SubtitleRulesDTO, SubtitleSummaryDTO, SubtitleTimingAdjustmentDTO, TextSource,
    TimedWordDTO, TimingSource, TranslationResultDTO, character_boundaries,
    is_combining_mark, is_layout_whitespace, normalize_chinese_text,
)


ALIGNMENT_SHA = "a" * 64
RESULT_SHA = "b" * 64
VIDEO_SHA = "c" * 64


def profile() -> SubtitleProfileDTO:
    return SubtitleProfileDTO({
        "name": "netflix-audio-gap.zh-priority.v1", "version": "v1",
        "english_capacity": 42, "chinese_capacity_half_units": 32,
        "chinese_target_cps": 9, "english_reference_cps": 17,
        "minimum_duration_ms": 834, "maximum_duration_ms": 7000,
        "maximum_extension_ms": 500, "short_gap_upper_ms": 500,
        "cross_sentence_gap_upper_ms": 500, "pause_boundary_ms": 250,
        "algorithm_version": "bilingual-monotonic-dp.v1",
        "text_normalization_version": "logical-text.v1",
        "character_count_version": "unicode14-halfwidth.v1",
        "boundary_rules_version": "boundaries.v1", "cost_rules_version": "d39.v1",
    })


def rules() -> SubtitleRulesDTO:
    p = profile()
    return SubtitleRulesDTO(
        profile_name=p.parameters["name"], profile_version=p.parameters["version"],
        profile_sha256=p.sha256, algorithm_version=p.parameters["algorithm_version"],
        text_normalization_version=p.parameters["text_normalization_version"],
        character_count_version=p.parameters["character_count_version"],
        boundary_rules_version=p.parameters["boundary_rules_version"],
        cost_rules_version=p.parameters["cost_rules_version"],
    )


def alignment(*, sections: bool = True, last_speaker: str | None = "BUFFETT") -> SourceAlignmentDTO:
    texts = ("We", "agree.", "Indeed.")
    words = tuple(TimedWordDTO(
        id=f"w{i + 1}", text=text, start_ms=start, end_ms=end,
        asr_word_ids=(f"a{i + 1}",), official_token_ids=(f"o{i + 1}",),
        match_type=MatchType.EXACT, text_source=TextSource.OFFICIAL_TRANSCRIPT,
        timing_source=TimingSource.ACOUSTIC_ALIGNMENT,
    ) for i, (text, start, end) in enumerate(zip(texts, (100, 400, 1300), (350, 1000, 1800), strict=True)))
    sentences = (
        SourceSentenceDTO("s1", "w1", "w2", 100, 1000, "We agree.", None,
                          TextSource.OFFICIAL_TRANSCRIPT, BoundarySource.OFFICIAL_PUNCTUATION, BoundaryStatus.VERIFIED),
        SourceSentenceDTO("s2", "w3", "w3", 1300, 1800, "Indeed.", last_speaker,
                          TextSource.OFFICIAL_TRANSCRIPT, BoundarySource.OFFICIAL_PUNCTUATION, BoundaryStatus.VERIFIED),
    )
    return SourceAlignmentDTO("en", 3000, words, sentences,
                              (SourceSectionDTO("sec1", "Question", "s1", "s2"),) if sections else ())


def translation(*, sections: bool = True) -> TranslationResultDTO:
    return TranslationResultDTO(ALIGNMENT_SHA, "en", "zh-Hans",
                                (SectionTitleTranslationDTO("sec1", "问题"),) if sections else (),
                                (SentenceTranslationDTO("s1", "\n 我们\t同意。  "), SentenceTranslationDTO("s2", "确实。")))


def plan(*, sections: bool = True) -> SubtitlePlanDTO:
    return SubtitlePlanDTO(
        ALIGNMENT_SHA, RESULT_SHA, VIDEO_SHA, "en", "zh-Hans",
        SubtitleMediaDTO(3500, 3000, 3000, 24, 1, 84), rules(),
        (
            SubtitleCueDTO("c1", "sec1" if sections else None, 100, 1000, 1216, "We agree.", "我们 同意。",
                           (SubtitleFragmentDTO("s1", "w1", "w2", 0, 6, None),),
                           SubtitleTimingAdjustmentDTO(216, ("gap_closing",), 300, "short_gap"),
                           ("english_sentence", "chinese_sentence")),
            SubtitleCueDTO("c2", "sec1" if sections else None, 1300, 1800, 2134, "Indeed.", "确实。",
                           (SubtitleFragmentDTO("s2", "w3", "w3", 0, 3, "BUFFETT"),),
                           SubtitleTimingAdjustmentDTO(334, ("minimum_duration",), None, "last_cue"),
                           ("english_sentence", "chinese_sentence")),
        ),
    )


def summary() -> SubtitleSummaryDTO:
    return SubtitleSummaryDTO(2, 0, 0, 0, 0, 0, 0, 2, 1)


def report() -> SrtProcessingReportDTO:
    return SrtProcessingReportDTO("cnbc:2000:sample", "succeeded", summary(), (
        SubtitleFindingDTO("timing.average_frame_rate_approximation", "warning", "Average FPS is approximate.",
                           observed={"fps_numerator": 24, "fps_denominator": 1}),
    ))


def manifest() -> SrtProcessingManifestDTO:
    filenames = {"transcription_manifest": "transcription_manifest.json", "source_alignment": "source_alignment.json",
                 "translation_manifest": "translation_manifest.json", "translation_result": "translation_result.json", "video": "video.mp4"}
    hashes = {"source_alignment": ALIGNMENT_SHA, "translation_result": RESULT_SHA, "video": VIDEO_SHA}
    inputs = {key: SubtitleArtifactEvidenceDTO(path, 10, hashes.get(key, "d" * 64)) for key, path in filenames.items()}
    outputs = {key: SubtitleArtifactEvidenceDTO(path, 10, "e" * 64) for key, path in
               {"subtitle_plan": "subtitle_plan.json", "english_srt": "english.srt", "chinese_srt": "chinese.srt",
                "bilingual_srt": "bilingual.srt", "report": "srt_processing_report.json"}.items()}
    return SrtProcessingManifestDTO("cnbc:2000:sample", "succeeded", "2026-10-21T03:04:05Z", inputs,
                                    rules(), profile(), plan().media, SubtitleProbeDTO("ffprobe version 8.0"),
                                    SubtitleCodecDTO(), outputs, summary())


@pytest.mark.parametrize("factory", [plan, report, manifest])
def test_public_subtitle_artifacts_round_trip_through_json(factory) -> None:
    dto = factory()
    data = dto.to_dict()
    assert type(dto).from_dict(json.loads(json.dumps(data, ensure_ascii=False))).to_dict() == data
    assert "completed_at" not in plan().to_dict()
    assert "findings" not in plan().to_dict()
    assert "english_lines" not in plan().cues[0].to_dict()


@pytest.mark.parametrize("factory", [plan, report, manifest])
def test_unknown_schema_missing_and_extra_top_level_fields_fail(factory) -> None:
    data = factory().to_dict()
    data["schema_version"] = "unknown.v2"
    with pytest.raises(ValueError, match="unsupported"):
        type(factory()).from_dict(data)
    data = factory().to_dict()
    del data["schema_version"]
    with pytest.raises(ValueError, match="exactly"):
        type(factory()).from_dict(data)
    data = factory().to_dict()
    data["legacy"] = True
    with pytest.raises(ValueError, match="exactly"):
        type(factory()).from_dict(data)


@pytest.mark.parametrize("change", [
    lambda d: d["cues"][0]["fragments"][0].update(unknown=True),
    lambda d: d["cues"][0]["timing_adjustment"].update(unknown=True),
    lambda d: d["cues"][0].update(english_lines=["line"]),
    lambda d: d["media"].update(fps_numerator=True),
    lambda d: d["rules"].update(profile_sha256="A" * 64),
    lambda d: d["cues"][0].update(start_ms=True),
    lambda d: d["cues"][0]["fragments"][0].update(chinese_start_offset=False),
    lambda d: d["cues"][0]["timing_adjustment"].update(extension_ms=True),
    lambda d: d["cues"][0].update(id="c2"),
    lambda d: d["cues"][0].update(english_text="We\nagree."),
    lambda d: d["cues"][0].update(chinese_text=" "),
    lambda d: d["cues"][0].update(break_methods=["semantic_model"]),
    lambda d: d["cues"][0].update(mapping_method="semantic_model.v1"),
    lambda d: d["media"].update(usable_duration_ms=3500),
    lambda d: d["media"].update(gap_threshold_ms=83),
])
def test_plan_rejects_malformed_nested_data(change) -> None:
    data = plan().to_dict()
    change(data)
    with pytest.raises(ValueError):
        SubtitlePlanDTO.from_dict(data)


@pytest.mark.parametrize("change", [
    lambda d: d["cues"][0]["timing_adjustment"].update(original_gap_ms=299),
    lambda d: d["cues"][0]["timing_adjustment"].update(original_gap_class="long_gap"),
    lambda d: d["cues"][1]["timing_adjustment"].update(original_gap_ms=0),
    lambda d: d["cues"][0]["timing_adjustment"].update(purposes=[]),
    lambda d: d["cues"][0].update(end_ms=1217),
    lambda d: d["cues"][1].update(end_ms=4000),
])
def test_plan_timing_metadata_must_describe_actual_timeline(change) -> None:
    data = plan().to_dict()
    change(data)
    with pytest.raises(ValueError):
        SubtitlePlanDTO.from_dict(data)


def test_plan_cross_validation_supports_sections_absent_and_preserves_null_speaker() -> None:
    plan().validate_against_inputs(alignment(), translation())
    plan(sections=False).validate_against_inputs(alignment(sections=False), translation(sections=False))
    assert plan().cues[0].fragments[0].speaker_label is None


@pytest.mark.parametrize("change", [
    lambda d: d["cues"][0]["fragments"][0].update(first_word_id="w2"),
    lambda d: d["cues"][0]["fragments"][0].update(last_word_id="w3"),
    lambda d: d["cues"][0]["fragments"][0].update(sentence_id="s2"),
    lambda d: d["cues"][0]["fragments"][0].update(speaker_label="BUFFETT"),
    lambda d: d["cues"][1]["fragments"][0].update(speaker_label=None),
    lambda d: d["cues"][0]["fragments"][0].update(chinese_start_offset=1),
    lambda d: d["cues"][0]["fragments"][0].update(chinese_end_offset=5),
    lambda d: d["cues"][0]["fragments"][0].update(chinese_end_offset=7),
    lambda d: d["cues"][0].update(section_id="sec2"),
    lambda d: d["cues"][0].update(english_text="We disagree."),
    lambda d: d["cues"][0].update(chinese_text="同意 我们。"),
    lambda d: d["cues"][0].update(start_ms=99),
    lambda d: d["media"].update(audio_duration_ms=3001, usable_duration_ms=3001),
])
def test_plan_cross_validation_rejects_source_or_chinese_mismatch(change) -> None:
    data = plan().to_dict()
    change(data)
    with pytest.raises(ValueError):
        dto = SubtitlePlanDTO.from_dict(data)
        dto.validate_against_inputs(alignment(), translation())


def test_missing_or_repeated_source_words_fail_even_when_lengths_could_match() -> None:
    data = plan().to_dict()
    data["cues"] = data["cues"][:1]
    data["cues"][0]["timing_adjustment"].update(original_gap_ms=None, original_gap_class="last_cue", purposes=["minimum_duration"])
    with pytest.raises(ValueError, match="every source word"):
        SubtitlePlanDTO.from_dict(data).validate_against_inputs(alignment(), translation())
    data = plan().to_dict()
    data["cues"][1]["fragments"][0].update(first_word_id="w2", last_word_id="w2", sentence_id="s1", speaker_label=None)
    with pytest.raises(ValueError, match="exactly once in order"):
        SubtitlePlanDTO.from_dict(data).validate_against_inputs(alignment(), translation())


def test_multi_sentence_cue_keeps_null_and_known_speaker_separate() -> None:
    p = plan()
    merged = SubtitleCueDTO("c1", "sec1", 100, 1800, 1800, "We agree. Indeed.", "我们 同意。确实。",
                             (p.cues[0].fragments[0], p.cues[1].fragments[0]),
                             SubtitleTimingAdjustmentDTO(0, (), None, "last_cue"),
                             ("english_sentence", "chinese_sentence"))
    replace(p, cues=(merged,)).validate_against_inputs(alignment(), translation())
    assert tuple(item.speaker_label for item in merged.fragments) == (None, "BUFFETT")
    with pytest.raises(ValueError, match="different known speakers"):
        replace(merged, fragments=(replace(merged.fragments[0], speaker_label="MUNGER"), merged.fragments[1]))


def test_chinese_partial_ranges_are_ordered_nonoverlapping_and_end_with_sentence() -> None:
    p = plan()
    a = replace(alignment(), words=(replace(alignment().words[0], end_ms=300),
                                  replace(alignment().words[1], start_ms=600), alignment().words[2]))
    pieces = (
        SubtitleCueDTO("c1", "sec1", 100, 300, 516, "We", "我们",
                       (SubtitleFragmentDTO("s1", "w1", "w1", 0, 3, None),),
                       SubtitleTimingAdjustmentDTO(216, ("minimum_duration", "gap_closing"), 300, "short_gap"),
                       ("english_emergency", "chinese_emergency")),
        replace(p.cues[0], id="c2", start_ms=600, english_text="agree.", chinese_text="同意。",
                fragments=(SubtitleFragmentDTO("s1", "w2", "w2", 3, 6, None),)),
        replace(p.cues[1], id="c3"),
    )
    split = replace(p, cues=pieces)
    split.validate_against_inputs(a, translation())
    with pytest.raises(ValueError, match="exactly once in order"):
        replace(split, cues=(pieces[0], replace(pieces[1], fragments=(replace(pieces[1].fragments[0], chinese_start_offset=2),)), pieces[2])).validate_against_inputs(a, translation())
    with pytest.raises(ValueError, match="endpoints must coincide"):
        replace(split, cues=(replace(pieces[0], chinese_text="我们 同意。", fragments=(replace(pieces[0].fragments[0], chinese_end_offset=6),)), *pieces[1:])).validate_against_inputs(a, translation())


def test_merged_cue_cannot_cross_source_sections() -> None:
    source = alignment()
    source = replace(source, sections=(
        SourceSectionDTO("sec1", "One", "s1", "s1"),
        SourceSectionDTO("sec2", "Two", "s2", "s2"),
    ))
    result = replace(translation(), section_title_translations=(
        SectionTitleTranslationDTO("sec1", "一"),
        SectionTitleTranslationDTO("sec2", "二"),
    ))
    p = plan()
    merged = SubtitleCueDTO("c1", "sec1", 100, 1800, 1800, "We agree. Indeed.", "我们 同意。确实。",
                            (p.cues[0].fragments[0], p.cues[1].fragments[0]),
                            SubtitleTimingAdjustmentDTO(0, (), None, "last_cue"),
                            ("english_sentence", "chinese_sentence"))
    with pytest.raises(ValueError, match="section must match"):
        replace(p, cues=(merged,)).validate_against_inputs(source, result)


def test_null_speaker_cannot_bridge_different_known_speakers() -> None:
    fragments = (
        SubtitleFragmentDTO("s1", "w1", "w1", 0, 1, "BUFFETT"),
        SubtitleFragmentDTO("s2", "w2", "w2", 0, 1, None),
        SubtitleFragmentDTO("s3", "w3", "w3", 0, 1, "MUNGER"),
    )
    with pytest.raises(ValueError, match="different known speakers"):
        replace(plan().cues[0], fragments=fragments)


def test_chinese_range_cannot_split_combining_sequence() -> None:
    p = plan()
    source = alignment()
    source = replace(source, words=(replace(source.words[0], end_ms=300),
                                   replace(source.words[1], start_ms=600), source.words[2]))
    result = replace(translation(), sentence_translations=(
        SentenceTranslationDTO("s1", "e\u0301中"), SentenceTranslationDTO("s2", "确实。"),
    ))
    pieces = (
        SubtitleCueDTO("c1", "sec1", 100, 300, 516, "We", "e",
                       (SubtitleFragmentDTO("s1", "w1", "w1", 0, 1, None),),
                       SubtitleTimingAdjustmentDTO(216, ("minimum_duration", "gap_closing"), 300, "short_gap"),
                       ("english_emergency", "chinese_emergency")),
        replace(p.cues[0], id="c2", start_ms=600, english_text="agree.", chinese_text="\u0301中",
                fragments=(SubtitleFragmentDTO("s1", "w2", "w2", 1, 3, None),)),
        replace(p.cues[1], id="c3"),
    )
    with pytest.raises(ValueError, match="combining character sequences"):
        replace(p, cues=pieces).validate_against_inputs(source, result)


@pytest.mark.parametrize("path", ["../subtitle_plan.json", "/tmp/subtitle_plan.json", "nested/subtitle_plan.json", "video.srt", True, []])
def test_evidence_only_accepts_canonical_workspace_basenames(path) -> None:
    with pytest.raises(ValueError):
        SubtitleArtifactEvidenceDTO(path, 1, ALIGNMENT_SHA)


@pytest.mark.parametrize("change", [
    lambda d: d["inputs"].pop("transcription_manifest"),
    lambda d: d["outputs"].pop("bilingual_srt"),
    lambda d: d["inputs"].update(extra=d["inputs"]["video"]),
    lambda d: d["inputs"]["video"].update(path="source_alignment.json"),
    lambda d: d["outputs"]["subtitle_plan"].update(size_bytes=True),
    lambda d: d["outputs"]["subtitle_plan"].update(sha256="not-a-hash"),
    lambda d: d["profile"].pop("pause_boundary_ms"),
    lambda d: d["profile"].update(english_capacity=True),
    lambda d: d["profile"].update(english_capacity=43),
    lambda d: d["rules"].update(profile_sha256="f" * 64),
    lambda d: d["codec"].update(library_version="1.9.0"),
    lambda d: d["codec"].update(bom=0),
    lambda d: d["codec"].update(newline="\r\n"),
    lambda d: d["codec"].update(bilingual_order=["en", "zh-Hans"]),
    lambda d: d["probe"].update(stream_selector="a:0"),
    lambda d: d.update(status="failed"),
    lambda d: d.update(completed_at="2026-02-30T03:04:05Z"),
    lambda d: d.update(completed_at="2026-10-21T03:04:05+00:00"),
])
def test_manifest_rejects_missing_or_invalid_required_evidence(change) -> None:
    data = manifest().to_dict()
    change(data)
    with pytest.raises(ValueError):
        SrtProcessingManifestDTO.from_dict(data)


def test_manifest_cross_checks_plan_identity_and_immutable_evidence() -> None:
    m = manifest()
    m.validate_against_plan(plan())
    with pytest.raises(ValueError, match="fingerprints"):
        m.validate_against_plan(replace(plan(), video_sha256="f" * 64))
    with pytest.raises(TypeError):
        m.inputs["video"] = m.inputs["source_alignment"]
    data = m.to_dict()
    data["profile"]["english_capacity"] = 44
    assert m.profile.parameters["english_capacity"] == 42


def test_profile_hash_is_sorted_compact_utf8_and_binds_all_parameters() -> None:
    p = profile()
    expected = hashlib.sha256(json.dumps(p.to_dict(), sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
    assert p.sha256 == expected
    assert SubtitleProfileDTO(dict(reversed(list(p.to_dict().items())))).sha256 == expected


def candidate_profile() -> SubtitleProfileDTO:
    parameters = profile().to_dict()
    parameters.update(
        name="audio-gap.zh-priority.v2", version="v2", english_capacity=84,
        english_line_capacity=42, english_max_lines=2,
        chinese_segmentation_engine="jieba-0.42.1", chinese_dictionary_sha256="e" * 64,
        chinese_segmentation_mode="default-hmm-false",
    )
    return SubtitleProfileDTO(parameters)


def test_profile_v2_binds_all_line_budget_and_segmentation_parameters() -> None:
    candidate = candidate_profile()
    assert SubtitleProfileDTO.from_dict(candidate.to_dict()) == candidate
    assert "english_line_capacity" not in profile().to_dict()
    for key in ("english_line_capacity", "english_max_lines", "chinese_segmentation_engine",
                "chinese_dictionary_sha256", "chinese_segmentation_mode"):
        changed = candidate.to_dict()
        value = changed[key]
        changed[key] = value + 1 if isinstance(value, int) else ("f" * 64 if key.endswith("sha256") else value + ".changed")
        assert SubtitleProfileDTO(changed).sha256 != candidate.sha256


@pytest.mark.parametrize("key", ["english_line_capacity", "english_max_lines", "chinese_segmentation_engine",
                                "chinese_dictionary_sha256", "chinese_segmentation_mode"])
def test_profile_versions_require_their_exact_field_shape(key) -> None:
    new = candidate_profile().to_dict()
    new.pop(key)
    with pytest.raises(ValueError):
        SubtitleProfileDTO.from_dict(new)
    old = profile().to_dict()
    old[key] = candidate_profile().parameters[key]
    with pytest.raises(ValueError):
        SubtitleProfileDTO.from_dict(old)


@pytest.mark.parametrize("key,value", [
    ("version", "v4"), ("english_line_capacity", True), ("english_max_lines", 0),
    ("chinese_dictionary_sha256", "A" * 64), ("chinese_dictionary_sha256", "missing"),
    ("chinese_segmentation_engine", ""), ("chinese_segmentation_mode", None),
])
def test_profile_v2_rejects_unknown_versions_and_invalid_parameters(key, value) -> None:
    parameters = candidate_profile().to_dict()
    parameters[key] = value
    with pytest.raises(ValueError):
        SubtitleProfileDTO.from_dict(parameters)


def pause_profile() -> SubtitleProfileDTO:
    parameters = candidate_profile().to_dict()
    parameters.update(name="audio-gap.zh-priority.v3", version="v3")
    parameters["chinese_target_half_units"] = parameters.pop("chinese_capacity_half_units")
    parameters["target_duration_ms"] = parameters.pop("maximum_duration_ms")
    return SubtitleProfileDTO(parameters)


def test_profile_v3_uses_soft_target_names_without_legacy_aliases_or_new_codec_version() -> None:
    candidate = pause_profile()
    assert candidate.parameters["chinese_target_half_units"] == 32
    assert candidate.parameters["target_duration_ms"] == 7000
    assert "chinese_capacity_half_units" not in candidate.to_dict()
    assert "maximum_duration_ms" not in candidate.to_dict()
    assert SubtitleProfileDTO.from_dict(candidate.to_dict()) == candidate
    for key in ("chinese_target_half_units", "target_duration_ms"):
        changed = candidate.to_dict()
        changed[key] += 1
        assert SubtitleProfileDTO(changed).sha256 != candidate.sha256
    # Soft target ordering is not an additional configuration or cue hard gate.
    changed = candidate.to_dict()
    changed["target_duration_ms"] = 1
    assert SubtitleProfileDTO(changed).parameters["minimum_duration_ms"] == 834
    codec = SubtitleCodecDTO(serialization_version="word-wrap-english-2x42.v2")
    assert SubtitleCodecDTO.from_dict(codec.to_dict()) == codec
    new_rules = replace(rules(), profile_name=candidate.parameters["name"], profile_version="v3",
                        profile_sha256=candidate.sha256)
    new_manifest = replace(manifest(), profile=candidate, rules=new_rules, codec=codec)
    restored = SrtProcessingManifestDTO.from_dict(new_manifest.to_dict())
    assert restored == new_manifest
    restored.validate_against_plan(replace(plan(), rules=new_rules))


@pytest.mark.parametrize("target,old", [
    ("chinese_target_half_units", "chinese_capacity_half_units"),
    ("target_duration_ms", "maximum_duration_ms"),
])
def test_profile_v3_and_legacy_versions_reject_each_others_parameter_names(target, old) -> None:
    data = pause_profile().to_dict()
    data.pop(target)
    with pytest.raises(ValueError):
        SubtitleProfileDTO.from_dict(data)
    data[old] = 32
    with pytest.raises(ValueError):
        SubtitleProfileDTO.from_dict(data)
    for legacy in (profile(), candidate_profile()):
        data = legacy.to_dict()
        data[target] = data[old]
        with pytest.raises(ValueError):
            SubtitleProfileDTO.from_dict(data)


@pytest.mark.parametrize("key,value", [
    ("chinese_target_half_units", True), ("chinese_target_half_units", 0),
    ("target_duration_ms", "7000"), ("target_duration_ms", -1), ("target_duration_ms", None),
    ("chinese_dictionary_sha256", "A" * 64), ("chinese_segmentation_mode", ""),
    ("english_max_lines", False), ("version", "v4"),
])
def test_profile_v3_rejects_unknown_shape_and_invalid_parameter_types(key, value) -> None:
    data = pause_profile().to_dict()
    data[key] = value
    with pytest.raises(ValueError):
        SubtitleProfileDTO.from_dict(data)


@pytest.mark.parametrize("legacy,expected_hash", [
    (profile, "a98a374cf80e293a042bd35e66911e657c9920b9bc9a9362543e0b947e50f368"),
    (candidate_profile, "b673d8cad038f5b80044ef564dac2c3007294cd979e210410627df7178d04143"),
])
def test_v1_v2_golden_hash_and_manifest_round_trip_remain_exact_after_v3(legacy, expected_hash) -> None:
    old = legacy()
    assert old.sha256 == expected_hash
    assert SubtitleProfileDTO.from_dict(old.to_dict()).to_dict() == old.to_dict()
    old_rules = replace(rules(), profile_name=old.parameters["name"], profile_version=old.parameters["version"],
                        profile_sha256=old.sha256)
    old_manifest = replace(manifest(), profile=old, rules=old_rules)
    raw = old_manifest.to_dict()
    assert SrtProcessingManifestDTO.from_dict(raw).to_dict() == raw
    assert "chinese_target_half_units" not in raw["profile"] and "target_duration_ms" not in raw["profile"]


def test_legacy_manifest_profile_and_codec_shapes_and_hash_round_trip_unchanged() -> None:
    legacy = manifest().to_dict()
    restored = SrtProcessingManifestDTO.from_dict(legacy)
    assert restored.to_dict() == legacy
    assert restored.profile.sha256 == legacy["rules"]["profile_sha256"]
    assert "english_max_lines" not in restored.profile.to_dict()
    assert "serialization_version" not in restored.codec.to_dict()
    candidate = SubtitleCodecDTO(serialization_version="word-wrap-english-2x42.v2")
    assert SubtitleCodecDTO.from_dict(candidate.to_dict()) == candidate
    assert candidate != restored.codec


@pytest.mark.parametrize("version", [None, "legacy", "word-wrap-english-2x42.v3", True])
def test_codec_rejects_explicit_null_or_unknown_serialization_versions(version) -> None:
    data = SubtitleCodecDTO().to_dict()
    data["serialization_version"] = version
    with pytest.raises(ValueError):
        SubtitleCodecDTO.from_dict(data)


@pytest.mark.parametrize("change", [
    lambda d: d["summary"].update(cue_count=True),
    lambda d: d["summary"].update(extended_cue_count=3),
    lambda d: d["findings"][0].update(severity="fatal"),
    lambda d: d["findings"][0].update(observed={"bad": float("nan")}),
    lambda d: d["findings"][0].update(unknown=True),
    lambda d: d["findings"][0].update(cue_ids=["c0"]),
    lambda d: d["findings"][0].update(original_start_ms=True, original_end_ms=5),
    lambda d: d["findings"][0].update(original_start_ms=5),
    lambda d: d.update(error_code="failed_but_claiming_success"),
    lambda d: d["findings"][0].update(severity="error"),
])
def test_report_rejects_inconsistent_or_non_json_findings(change) -> None:
    data = report().to_dict()
    change(data)
    with pytest.raises(ValueError):
        SrtProcessingReportDTO.from_dict(data)


def test_report_accepts_failure_and_freezes_observed_values() -> None:
    finding = SubtitleFindingDTO("input.invalid", "error", "Input validation failed.",
                                 observed={"detail": [1, {"safe": None}]})
    failed = SrtProcessingReportDTO("asset", "failed", SubtitleSummaryDTO(0, 0, 0, 0, 0, 0, 0, 0, 0),
                                     (finding,), "input_error")
    data = failed.to_dict()
    data["findings"][0]["observed"]["detail"][1]["safe"] = False
    assert finding.observed["detail"][1]["safe"] is None
    assert SrtProcessingReportDTO.from_dict(failed.to_dict()) == failed


@pytest.mark.parametrize("text, expected", [
    ("  中\n文\tA \u3000B\u00a0", "中 文 A B"),
    ("e\u0301  10%", "e\u0301 10%"),
    ("甲\u200b乙", "甲\u200b乙"),
])
def test_chinese_normalization_uses_only_frozen_layout_whitespace(text, expected) -> None:
    assert normalize_chinese_text(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("", (0,)), ("abc", (0, 1, 2, 3)), ("e\u0301中", (0, 2, 3)),
    ("क\u093f中", (0, 2, 3)), ("✈\ufe0f中", (0, 2, 3)),
    ("👩\u200d💻中", (0, 3, 4)), ("👍🏽中", (0, 2, 3)),
])
def test_character_boundaries_guard_combining_zwj_variation_and_emoji_modifiers(text, expected) -> None:
    assert character_boundaries(text) == expected


def test_text_classification_helpers_are_fixed_and_reject_noncharacters() -> None:
    assert is_combining_mark("\u0301")
    assert is_combining_mark("\u093f")
    assert not is_combining_mark("A")
    assert is_layout_whitespace("\u3000")
    assert not is_layout_whitespace("\u200b")
    with pytest.raises(ValueError):
        is_combining_mark("ab")
    with pytest.raises(ValueError):
        is_layout_whitespace(1)


def test_new_subtitle_artifacts_have_canonical_filenames() -> None:
    assert canonical_filename(ArtifactType.SUBTITLE_PLAN) == "subtitle_plan.json"
    assert canonical_filename(ArtifactType.BILINGUAL_SRT) == "bilingual.srt"
    assert canonical_filename(ArtifactType.SRT_PROCESSING_REPORT) == "srt_processing_report.json"
    assert canonical_filename(ArtifactType.SRT_PROCESSING_MANIFEST) == "srt_processing_manifest.json"
    assert canonical_filename(ArtifactType.ENGLISH_SRT) == "english.srt"
    assert canonical_filename(ArtifactType.CHINESE_SRT) == "chinese.srt"
