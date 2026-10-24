"""Mechanical rendering contracts; no fonts, probe or renderer is invoked."""

from dataclasses import replace
import hashlib
import json

import pytest

from archive_core.domain import ArtifactType, canonical_filename
from archive_core.interfaces import (
    ASS_SERIALIZATION_VERSION, ASS_TIMING_POLICY, RenderArtifactEvidenceDTO, RenderAudioStreamDTO,
    RenderBoundsDTO, RenderChapterDTO, RenderCueDTO, RenderEncoderDTO,
    RenderFindingDTO, RenderFontIdentityDTO, RenderFontSpecDTO, RenderLineMetricsDTO,
    RenderMediaDTO, RenderPixelResultDTO, RenderProfileDTO, RenderScaledStyleDTO,
    RenderStreamMappingDTO, RenderSummaryDTO, RenderTagDTO, RenderTextStyleDTO, RenderToolsDTO,
    RenderVideoStreamDTO, SubtitleRenderManifestDTO, SubtitleRenderPlanDTO,
    SubtitleRenderReportDTO, project_ass_time_ms,
)
from tests.archive_core.test_subtitle_contracts import plan as source_plan


def evidence(path="subtitle_plan.json", sha="a" * 64):
    return RenderArtifactEvidenceDTO(path, 10, sha)


def font_identity():
    return RenderFontIdentityDTO(RenderFontSpecDTO(), 120000, "pillow-font.v1:Pillow=12.0;FreeType=2.14", "HiraginoSansGB-W3")


def tools():
    return RenderToolsDTO("1.8.1", "ffmpeg 9.0.1", "ffprobe 9.0.1", "0.17.4", "164 r3204")


def video():
    return RenderVideoStreamDTO(0, "h264", 640, 360, 1, 1, 16, 9, 24, 1, 24, 1,
                                0, 3500123, 84, "yuv420p", 0, ())


def audio():
    return RenderAudioStreamDTO(1, "aac", 48000, 2, "stereo", 0, 3000000, True,
                                (RenderTagDTO("language", "eng"),))


def media():
    return RenderMediaDTO("mov,mp4,m4a,3gp,3g2,mj2", 3500123, 0, video(), (audio(),),
                          1, 0, 0, (RenderTagDTO("title", "Example"),),
                          (RenderChapterDTO(0, 0, 3000000, (RenderTagDTO("title", "Chapter one"),)),))


def scaled_style():
    return RenderScaledStyleDTO(640, 360, 32, 42, 160, 30, 20, 2, 1)


def render_cues():
    result = []
    for index, source in enumerate(source_plan().cues):
        start, end = project_ass_time_ms(source.start_ms), project_ass_time_ms(source.end_ms)
        count = 2 if index == 0 else 1
        result.append(RenderCueDTO(
            source.id, source.start_ms, source.end_ms, start, end, start - source.start_ms, end - source.end_ms,
            hashlib.sha256(source.chinese_text.encode()).hexdigest(), hashlib.sha256(source.english_text.encode()).hexdigest(),
            (3,) if count == 2 else (), (3,) if count == 2 else (),
            tuple(RenderLineMetricsDTO(120, 30) for _ in range(count)),
            tuple(RenderLineMetricsDTO(80, 20) for _ in range(count)),
            RenderBoundsDTO(260, 190 if count == 2 else 230, 380, 310),
        ))
    return tuple(result)


def render_plan():
    profile = RenderProfileDTO()
    return SubtitleRenderPlanDTO(
        "cnbc:2000:sample",
        {"srt_processing_manifest": evidence("srt_processing_manifest.json"),
         "subtitle_plan": evidence(), "video": evidence("video.mp4", source_plan().video_sha256)},
        media(), profile, profile.sha256, font_identity(), tools(), scaled_style(),
        RenderBoundsDTO(32, 158, 608, 318), render_cues(),
    )


def summary():
    return RenderSummaryDTO(2, (1, 1), (1, 1), 1, 120, 120, 1, 0, True, True, True, True)


def report():
    plan = render_plan()
    return SubtitleRenderReportDTO(
        plan.asset_id, "succeeded", summary(),
        (RenderFindingDTO("upstream.context", "warning", diagnostic="Known upstream warning, not a hard rendering error."),),
        tuple(RenderPixelResultDTO(cue.id, (cue.ass_start_ms + cue.ass_end_ms) // 2,
                                   cue.expected_bounds, len(cue.chinese_lines) + len(cue.english_lines), True, True)
              for cue in plan.cues),
    )


def manifest():
    plan = render_plan()
    return SubtitleRenderManifestDTO(
        plan.asset_id, "succeeded", "2026-10-23T14:32:16.123Z", plan.inputs,
        plan.profile, plan.profile_sha256, plan.font, plan.tools, plan.input_media, media(),
        {"plan": evidence("subtitle_rendering_plan.json"), "ass": evidence("bilingual.ass"),
         "video": evidence("video_中文字幕.mp4"), "report": evidence("subtitle_rendering_report.json")},
        summary(),
    )


FACTORIES = (
    evidence, RenderFontSpecDTO, font_identity, lambda: RenderTextStyleDTO(30, "&H00FFFFFF"),
    RenderEncoderDTO, RenderStreamMappingDTO, RenderProfileDTO, tools, lambda: RenderTagDTO("title", "A"),
    lambda: RenderChapterDTO(0, 0, 1000), video, audio, media,
    lambda: RenderBoundsDTO(0, 0, 1, 1), lambda: RenderLineMetricsDTO(10, 20),
    scaled_style, lambda: render_cues()[0], render_plan,
    lambda: RenderFindingDTO("qa.safe", "info"), lambda: report().pixel_results[0],
    summary, report, manifest,
)


@pytest.mark.parametrize("factory", FACTORIES)
def test_render_dtos_have_explicit_json_round_trip(factory):
    dto = factory()
    data = json.loads(json.dumps(dto.to_dict(), ensure_ascii=False, allow_nan=False))
    assert type(dto).from_dict(data).to_dict() == dto.to_dict()


@pytest.mark.parametrize("factory", FACTORIES)
@pytest.mark.parametrize("operation", ("missing", "extra"))
def test_every_render_dto_rejects_unknown_or_missing_fields(factory, operation):
    dto = factory()
    data = dto.to_dict()
    if operation == "missing":
        data.pop(next(iter(data)))
    else:
        data["unknown"] = True
    with pytest.raises(ValueError, match="exactly"):
        type(dto).from_dict(data)


@pytest.mark.parametrize("factory", (render_plan, report, manifest))
def test_render_artifacts_reject_unknown_schema(factory):
    dto = factory()
    data = dto.to_dict()
    data["schema_version"] = "unknown.v99"
    with pytest.raises(ValueError, match="unsupported"):
        type(dto).from_dict(data)


@pytest.mark.parametrize(("kind", "filename"), (
    (ArtifactType.SUBTITLE_RENDER_PLAN, "subtitle_rendering_plan.json"),
    (ArtifactType.BILINGUAL_ASS, "bilingual.ass"),
    (ArtifactType.SUBTITLE_RENDER_REPORT, "subtitle_rendering_report.json"),
    (ArtifactType.SUBTITLE_RENDER_MANIFEST, "subtitle_rendering_manifest.json"),
    (ArtifactType.RENDERED_VIDEO, "video_中文字幕.mp4"),
))
def test_rendering_filenames_are_canonical(kind, filename):
    assert canonical_filename(kind) == filename


@pytest.mark.parametrize("change", (
    {"path": "../bilingual.ass"}, {"path": "/bilingual.ass"}, {"path": "report.json"},
    {"path": []}, {"size_bytes": True}, {"size_bytes": 0}, {"size_bytes": 1.5},
    {"sha256": "A" * 64}, {"sha256": "abc"},
))
def test_render_evidence_rejects_unsafe_or_untyped_fields(change):
    with pytest.raises(ValueError):
        RenderArtifactEvidenceDTO.from_dict({**evidence().to_dict(), **change})


@pytest.mark.parametrize(("source", "projected"), ((0, 0), (4, 0), (5, 10), (6, 10), (14, 10), (15, 20), (1216, 1220)))
def test_ass_projection_is_half_up_not_bankers_rounding(source, projected):
    assert project_ass_time_ms(source) == projected
    assert abs(source - projected) <= 5
    assert ASS_TIMING_POLICY == "nearest-centisecond-half-up.v1"
    assert ASS_SERIALIZATION_VERSION == "bilingual-ass.word-joiner.v1"


@pytest.mark.parametrize("value", (True, False, -1, 1.5, "5", None))
def test_ass_projection_requires_non_negative_integer(value):
    with pytest.raises(ValueError):
        project_ass_time_ms(value)


@pytest.mark.parametrize("change", (
    lambda d: d.update(start_ms=True), lambda d: d.update(ass_start_ms=101),
    lambda d: d.update(start_delta_ms=True), lambda d: d.update(end_delta_ms=3),
    lambda d: d.update(ass_end_ms=1210), lambda d: d.update(id="c0"),
    lambda d: d.update(chinese_break_offsets=[True]), lambda d: d.update(chinese_break_offsets=[0]),
    lambda d: d.update(english_break_offsets=[2, 3]), lambda d: d.update(chinese_lines=[]),
    lambda d: d["chinese_lines"][0].update(width=float("nan")),
    lambda d: d["expected_bounds"].update(left=float("inf")),
    lambda d: d["english_lines"][0].update(height=True),
))
def test_render_cue_rejects_non_finite_untyped_and_inconsistent_projection(change):
    data = render_cues()[0].to_dict()
    change(data)
    with pytest.raises(ValueError):
        RenderCueDTO.from_dict(data)


def test_ass_projection_must_not_collapse_positive_source_interval():
    cue = render_cues()[0]
    with pytest.raises(ValueError, match="positive duration"):
        replace(cue, start_ms=101, end_ms=104, ass_start_ms=100, ass_end_ms=100,
                start_delta_ms=-1, end_delta_ms=-4)


def test_source_text_and_milliseconds_remain_authoritative():
    plan = render_plan()
    source = source_plan()
    plan.validate_against_subtitle_plan(source)
    chinese, english = plan.cues[0].visual_lines(source.cues[0])
    assert "".join(chinese) == source.cues[0].chinese_text
    assert english == ("We ", "agree.")
    assert "".join(english) == source.cues[0].english_text
    assert plan.cues[0].end_ms == 1216
    assert plan.cues[0].ass_end_ms == 1220
    assert "completed_at" not in plan.to_dict()
    assert "argv" not in plan.to_dict()


@pytest.mark.parametrize("field", ("chinese_text_sha256", "english_text_sha256"))
def test_changing_source_fingerprint_cannot_bypass_source_validation(field):
    plan = render_plan()
    corrupt = replace(plan, cues=(replace(plan.cues[0], **{field: "f" * 64}), plan.cues[1]))
    with pytest.raises(ValueError, match="fingerprint"):
        corrupt.validate_against_subtitle_plan(source_plan())


def test_out_of_text_offsets_are_checked_against_authoritative_text():
    plan = render_plan()
    corrupt = replace(plan, cues=(replace(plan.cues[0], english_break_offsets=(999,)), plan.cues[1]))
    with pytest.raises(ValueError, match="internal"):
        corrupt.validate_against_subtitle_plan(source_plan())


def test_source_normalization_prevents_blank_edge_lines_and_legal_word_gap_is_preserved():
    with pytest.raises(ValueError, match="normalized"):
        replace(source_plan().cues[0], english_text=" A")
    source = replace(source_plan().cues[0], english_text="A B")
    cue = replace(render_cues()[0], english_text_sha256=hashlib.sha256(b"A B").hexdigest(), english_break_offsets=(1,))
    _, english = cue.visual_lines(source)
    assert english == ("A", " B")
    assert "".join(english) == source.english_text


@pytest.mark.parametrize("change", (
    lambda d: d.update(asset_id="invalid"), lambda d: d.update(profile_sha256="f" * 64),
    lambda d: d["inputs"].pop("video"), lambda d: d["inputs"].update(extra=d["inputs"]["video"]),
    lambda d: d["inputs"]["video"].update(path="bilingual.ass"),
    lambda d: d["font"]["spec"].update(face_index=1),
    lambda d: d["scaled_style"].update(chinese_font_size=29),
    lambda d: d["safe_area"].update(top=157), lambda d: d["cues"][0]["expected_bounds"].update(left=0),
    lambda d: d["cues"][0]["chinese_lines"][0].update(width=600),
    lambda d: d["cues"][1].update(id="c3"), lambda d: d.update(cues=[]),
    lambda d: d.update(ass_timing_policy="floor"), lambda d: d.update(ass_serialization_version="unknown"),
    lambda d: d["stream_mapping"].update(include_subtitles=True),
    lambda d: d["stream_mapping"].update(audio_selector="0:a:0"),
))
def test_render_plan_rejects_identity_timeline_or_safe_area_tampering(change):
    data = render_plan().to_dict()
    change(data)
    with pytest.raises(ValueError):
        SubtitleRenderPlanDTO.from_dict(data)


def test_mutated_and_resigned_profile_cannot_bypass_scaled_style_check():
    plan = render_plan()
    profile = replace(plan.profile, horizontal_margin=33)
    with pytest.raises(ValueError, match="scaling"):
        replace(plan, profile=profile, profile_sha256=profile.sha256)


def test_original_and_ass_timeline_must_fit_media_and_not_overlap():
    plan = render_plan()
    shortened_media = replace(plan.input_media, video=replace(plan.input_media.video, duration_us=2133000))
    with pytest.raises(ValueError, match="duration"):
        replace(plan, input_media=shortened_media)
    overlap = replace(plan.cues[1], start_ms=1215, ass_start_ms=1220, start_delta_ms=5)
    with pytest.raises(ValueError, match="non-overlapping"):
        replace(plan, cues=(plan.cues[0], overlap))


def test_ass_projection_end_must_fit_authoritative_audio_video_minimum():
    plan = render_plan()
    source = source_plan()
    last = replace(plan.cues[-1], end_ms=2996, ass_end_ms=3000, end_delta_ms=4)
    # Keep the source endpoint identical, but its smaller usable media end cannot contain the projection.
    source_last = replace(source.cues[-1], end_ms=2996,
                          timing_adjustment=replace(source.cues[-1].timing_adjustment, extension_ms=1196))
    source = replace(source, cues=(source.cues[0], source_last), media=replace(source.media, audio_duration_ms=2998, usable_duration_ms=2998))
    plan = replace(plan, cues=(plan.cues[0], last))
    with pytest.raises(ValueError, match="usable"):
        plan.validate_against_subtitle_plan(source)


def test_profile_fingerprint_is_full_content_deterministic_and_immutable():
    profile = RenderProfileDTO()
    reordered = dict(reversed(tuple(profile.to_dict().items())))
    assert RenderProfileDTO.from_dict(reordered).sha256 == profile.sha256
    assert replace(profile, horizontal_margin=33).sha256 != profile.sha256
    assert replace(profile, chinese=RenderTextStyleDTO(31, "&H00FFFFFF")).sha256 != profile.sha256
    assert profile.sha256 == hashlib.sha256(json.dumps(profile.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    plan = render_plan()
    with pytest.raises(TypeError):
        plan.inputs["video"] = evidence("video.mp4")


@pytest.mark.parametrize("change", (
    {"outline_width": True}, {"horizontal_margin": 320}, {"vertical_margin": 300},
    {"reference_width": 1280}, {"maximum_chinese_lines": 3}, {"version": "v2"},
    {"alignment": 8}, {"outline_color": "#000"},
))
def test_profile_rejects_unsupported_or_impossible_parameters(change):
    with pytest.raises(ValueError):
        RenderProfileDTO.from_dict({**RenderProfileDTO().to_dict(), **change})


@pytest.mark.parametrize("change", (
    lambda d: d["video"].update(fps_denominator=0), lambda d: d["video"].update(duration_us=None),
    lambda d: d["video"].update(width=True), lambda d: d["video"].update(dar_numerator=17),
    lambda d: d["audio_streams"][0].update(index=0), lambda d: d["audio_streams"][0].update(default=1),
    lambda d: d["audio_streams"][0].update(sample_rate=0), lambda d: d.update(duration_us=float("inf")),
    lambda d: d.update(tags=[{"key": "title", "value": "one"}, {"key": "title", "value": "two"}]),
    lambda d: d.update(tags=[{"key": "z", "value": "one"}, {"key": "a", "value": "two"}]),
    lambda d: d["chapters"][0].update(end_us=4000000),
))
def test_media_identity_is_typed_and_precise(change):
    data = media().to_dict()
    change(data)
    with pytest.raises(ValueError):
        RenderMediaDTO.from_dict(data)


def test_precise_stream_durations_and_nullable_audio_duration_round_trip():
    dto = replace(media(), audio_streams=(replace(audio(), duration_us=None),))
    assert RenderMediaDTO.from_dict(dto.to_dict()).video.duration_us == 3500123
    assert RenderMediaDTO.from_dict(dto.to_dict()).audio_streams[0].duration_us is None


def test_report_and_manifest_validate_complete_plan_and_pixel_evidence():
    plan = render_plan()
    report().validate_against_plan(plan)
    manifest().validate_against_plan_and_report(plan, report())
    assert report().summary.all_qa_passed


@pytest.mark.parametrize("change", (
    lambda d: d.update(status="partial"), lambda d: d.update(error_category="render_failed"),
    lambda d: d["summary"].update(font_glyph_passed=False),
    lambda d: d["summary"].update(warning_count=0), lambda d: d["summary"].update(chinese_line_counts=[2, 1]),
    lambda d: d["summary"].update(chinese_line_counts=[True, 1]),
    lambda d: d["summary"].update(maximum_width=float("nan")),
    lambda d: d.update(pixel_results=d["pixel_results"][:1]),
    lambda d: d["pixel_results"][0].update(font_identity_matches=False),
    lambda d: d["pixel_results"][0].update(styles_match=1),
    lambda d: d["pixel_results"][0].update(line_count=5),
    lambda d: d["findings"][0].update(diagnostic="x" * 2049),
    lambda d: d["findings"][0].update(start_ms=1),
))
def test_success_report_rejects_incomplete_qa_or_inconsistent_summary(change):
    data = report().to_dict()
    change(data)
    with pytest.raises(ValueError):
        SubtitleRenderReportDTO.from_dict(data)


@pytest.mark.parametrize("change", (
    lambda d: d["summary"].update(maximum_width=121),
    lambda d: d["summary"].update(four_line_cue_count=0),
    lambda d: d["pixel_results"][0].update(time_ms=100),
    lambda d: d["pixel_results"][0]["bounds"].update(top=0),
    lambda d: d["pixel_results"][0].update(line_count=3),
    lambda d: d["findings"][0].update(cue_id="c9"),
))
def test_resigned_report_cannot_bypass_plan_mechanical_checks(change):
    data = report().to_dict()
    change(data)
    dto = SubtitleRenderReportDTO.from_dict(data)
    with pytest.raises(ValueError):
        dto.validate_against_plan(render_plan())


def test_failed_report_has_controlled_category_and_may_preserve_partial_evidence():
    good = report()
    failed = replace(good, status="failed", error_category="render_failed")
    assert SubtitleRenderReportDTO.from_dict(failed.to_dict()) == failed
    with pytest.raises(ValueError, match="stable"):
        replace(failed, error_category="raw stderr")


@pytest.mark.parametrize("change", (
    lambda d: d.update(status="failed"), lambda d: d.update(completed_at="2026-10-23T23:00:00+08:00"),
    lambda d: d.update(completed_at="2026-02-30T12:00:00Z"),
    lambda d: d["outputs"].pop("ass"), lambda d: d["outputs"]["video"].update(path="video.mp4"),
    lambda d: d["output_media"].update(subtitle_stream_count=1),
    lambda d: d["output_media"]["video"].update(codec_name="hevc"),
    lambda d: d["summary"].update(pixel_preflight_passed=False),
))
def test_success_manifest_requires_canonical_complete_evidence_and_qa(change):
    data = manifest().to_dict()
    change(data)
    with pytest.raises(ValueError):
        SubtitleRenderManifestDTO.from_dict(data)


def test_manifest_report_and_plan_cross_checks_cannot_be_resigned_away():
    dto = manifest()
    with pytest.raises(ValueError, match="summary"):
        replace(dto, summary=replace(dto.summary, maximum_width=121)).validate_against_plan_and_report(render_plan(), report())
    with pytest.raises(ValueError, match="tools"):
        replace(dto, tools=replace(dto.tools, ffmpeg_version="other")).validate_against_plan_and_report(render_plan(), report())
    with pytest.raises(ValueError, match="inputs"):
        replace(dto, inputs={**dto.inputs, "video": evidence("video.mp4", "f" * 64)}).validate_against_plan_and_report(render_plan(), report())
