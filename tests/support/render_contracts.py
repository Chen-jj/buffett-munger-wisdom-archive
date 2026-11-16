"""Mechanical rendering contracts; no fonts, probe or renderer is invoked."""

from dataclasses import replace
import hashlib
import json


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
from tests.support.current_bilingual import source_plan


def evidence(path="final_bilingual_draft.json", sha="a" * 64):
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
         "subtitle_plan": evidence(), "video": evidence("video.mp4", source_plan().media.video_sha256)},
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
