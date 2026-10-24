"""Deterministic planning, whole-set reuse, and manifest-last local publication."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Callable

from archive_core.domain import ArtifactType, canonical_filename
from archive_core.interfaces import (
    RENDER_ERROR_CATEGORIES, RenderArtifactEvidenceDTO, RenderFindingDTO, RenderMediaDTO,
    RenderPixelResultDTO, RenderProfileDTO, RenderSummaryDTO, RenderToolsDTO,
    SubtitleRenderManifestDTO, SubtitleRenderPlanDTO, SubtitleRenderReportDTO,
)
from subtitle_rendering.domain.layout import build_render_plan
from subtitle_rendering.domain.models import GraphemeSegmenter

from .inputs import canonical_path, fingerprint, load_render_inputs, parse_json
from .ports import AssCodec, Clock, FontFactory, MediaProbe, Renderer, RenderingArtifactStore


OUTPUT_TYPES = {"plan": ArtifactType.SUBTITLE_RENDER_PLAN, "ass": ArtifactType.BILINGUAL_ASS,
                "video": ArtifactType.RENDERED_VIDEO, "report": ArtifactType.SUBTITLE_RENDER_REPORT,
                "manifest": ArtifactType.SUBTITLE_RENDER_MANIFEST}


class SubtitleRenderingWorkflowError(RuntimeError):
    def __init__(self, category: str, diagnostic: str, report_path: str | None = None) -> None:
        self.category = category
        self.diagnostic = diagnostic[:2048]
        self.report_path = report_path
        super().__init__(category)


@dataclass(frozen=True)
class SubtitleRenderingRunResult:
    status: str
    action: str
    plan_path: str
    ass_path: str
    video_path: str
    report_path: str
    manifest_path: str
    cue_count: int
    warning_count: int
    command: tuple[str, ...] | None


def json_bytes(value) -> bytes:
    return (json.dumps(value.to_dict(), ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _summary(plan: SubtitleRenderPlanDTO | None, findings: tuple[RenderFindingDTO, ...], *, passed: bool) -> RenderSummaryDTO:
    cues = () if plan is None else plan.cues
    distributions = [tuple(sum(len(getattr(cue, language + "_lines")) == count for cue in cues) for count in (1, 2))
                     for language in ("chinese", "english")]
    return RenderSummaryDTO(
        len(cues), *distributions,
        sum(len(cue.chinese_lines) + len(cue.english_lines) == 4 for cue in cues),
        max((line.width for cue in cues for line in (*cue.chinese_lines, *cue.english_lines)), default=0),
        max((cue.expected_bounds.bottom - cue.expected_bounds.top for cue in cues), default=0),
        sum(item.severity == "warning" for item in findings), sum(item.severity == "error" for item in findings),
        passed, passed, passed, passed,
    )


def _successful_report(inputs, plan, pixels) -> SubtitleRenderReportDTO:
    # Upstream warnings remain context, never promoted to rendering errors.
    findings = tuple(RenderFindingDTO("upstream." + finding.code, "warning",
                                     diagnostic="Upstream subtitle warning; not a rendering hard error.")
                     for finding in inputs.srt_report.findings if finding.severity == "warning")
    report = SubtitleRenderReportDTO(plan.asset_id, "succeeded", _summary(plan, findings, passed=True), findings, tuple(pixels))
    report.validate_against_plan(plan)
    return report


def _validate_pixels(plan, pixels) -> None:
    if not isinstance(pixels, tuple) or len(pixels) != len(plan.cues):
        raise ValueError("pixel preflight must return every cue in order")
    for cue, pixel in zip(plan.cues, pixels):
        if (not isinstance(pixel, RenderPixelResultDTO) or pixel.cue_id != cue.id
                or pixel.time_ms != (cue.ass_start_ms + cue.ass_end_ms) // 2
                or not plan.safe_area.contains(pixel.bounds)
                or pixel.line_count != len(cue.chinese_lines) + len(cue.english_lines)
                or not pixel.font_identity_matches or not pixel.styles_match):
            raise ValueError("pixel preflight did not prove safe ordered styles and font")


class SubtitleRenderingWorkflow:
    def __init__(self, *, artifacts: RenderingArtifactStore, probe: MediaProbe, codec: AssCodec,
                 renderer: Renderer, font_factory: FontFactory, segmenter: GraphemeSegmenter,
                 pixel_preflight: Callable, media_validator: Callable, clock: Clock,
                 profile: RenderProfileDTO, output_root: str = "output") -> None:
        self.artifacts, self.probe, self.codec, self.renderer = artifacts, probe, codec, renderer
        self.font_factory, self.segmenter = font_factory, segmenter
        self.pixel_preflight, self.media_validator, self.clock = pixel_preflight, media_validator, clock
        self.profile = profile
        self.output_root = canonical_path(output_root)

    def execute(self, *, asset_id: str, srt_processing_manifest_path: str,
                dry_run: bool = False, overwrite: bool = False) -> SubtitleRenderingRunResult:
        stage_category, staging, paths, plan = "input_invalid", None, {}, None
        initially_occupied = False
        try:
            if type(dry_run) is not bool or type(overwrite) is not bool:
                raise ValueError("dry_run and overwrite must be booleans")
            # Version availability has its own category; source media errors remain input_invalid.
            stage_category = "tool_unavailable"
            probe_version = self.probe.version()
            stage_category = "input_invalid"
            inputs = load_render_inputs(asset_id=asset_id, srt_processing_manifest_path=srt_processing_manifest_path,
                                        artifacts=self.artifacts, probe=self.probe, output_root=self.output_root)
            paths = {key: str(inputs.workspace / canonical_filename(kind)) for key, kind in OUTPUT_TYPES.items()}
            occupied = tuple(self.artifacts.exists(path) for path in paths.values())
            initially_occupied = any(occupied)
            if initially_occupied and not all(occupied) and not overwrite:
                raise SubtitleRenderingWorkflowError("artifact_conflict", "Only part of the rendering set exists.")
            stage_category = "font_invalid"
            font = self.font_factory(self.profile.font, tuple(text for cue in inputs.source_plan.cues
                                                            for text in (cue.chinese_text, cue.english_text)))
            stage_category = "tool_unavailable"
            tools = self.renderer.tool_identity(pysubs2_version=self.codec.library_version, ffprobe_version=probe_version)
            if not isinstance(tools, RenderToolsDTO):
                raise ValueError("renderer did not return public tool identity")
            if all(occupied) and not overwrite:
                stage_category = "artifact_conflict"
                saved = SubtitleRenderManifestDTO.from_dict(parse_json(self.artifacts.read_bytes(paths["manifest"])))
                for name, current in (("inputs", inputs.evidence), ("profile", self.profile), ("font", font.identity),
                                      ("tools", tools), ("input_media", inputs.media)):
                    if getattr(saved, name) != current:
                        raise ValueError("Existing rendering identity differs from valid current inputs.")
            stage_category = "layout_failed"
            plan = build_render_plan(asset_id=asset_id, inputs=inputs.evidence, input_media=inputs.media,
                                     source_plan=inputs.source_plan, profile=self.profile, font=font.identity,
                                     tools=tools, measurer=font, segmenter=self.segmenter)
            stage_category = "ass_generation_failed"
            ass = self.codec.encode(plan, inputs.source_plan)
            self.codec.validate(ass, plan, inputs.source_plan)
            if all(occupied) and not overwrite:
                stage_category = "artifact_conflict"
                report = self._reuse(inputs, plan, ass, paths)
                return SubtitleRenderingRunResult("planned" if dry_run else "reused", "reuse", **{key + "_path": value for key, value in paths.items()},
                                                  cue_count=len(plan.cues), warning_count=report.summary.warning_count, command=None)
            stage_category = "publication_failed"
            staging = self.artifacts.plan_staging(str(inputs.workspace))
            staged = {key: str(Path(staging) / canonical_filename(kind)) for key, kind in OUTPUT_TYPES.items()}
            command = self.renderer.build_command(video_path=str(inputs.workspace / canonical_filename(ArtifactType.SOURCE_VIDEO)),
                                                  ass_path=canonical_filename(ArtifactType.BILINGUAL_ASS),
                                                  fonts_dir=str(Path(self.profile.font.path).parent), output_path=staged["video"],
                                                  profile=self.profile, mapping=plan.stream_mapping)
            if dry_run:
                return SubtitleRenderingRunResult("planned", "render", **{key + "_path": value for key, value in paths.items()},
                                                  cue_count=len(plan.cues), warning_count=sum(item.severity == "warning" for item in inputs.srt_report.findings), command=command)
            self.artifacts.create_staging(staging)
            self._stage(staged["ass"], ass)
            stage_category = "ass_generation_failed"
            self.codec.validate(self.artifacts.read_bytes(staged["ass"]), plan, inputs.source_plan)
            stage_category = "layout_failed"
            pixels = self.pixel_preflight(plan, inputs.source_plan, staged["ass"], self.renderer)
            _validate_pixels(plan, pixels)
            stage_category = "publication_failed"
            self._stage(staged["plan"], json_bytes(plan))
            read_plan = SubtitleRenderPlanDTO.from_dict(parse_json(self.artifacts.read_bytes(staged["plan"])))
            if read_plan != plan:
                raise ValueError("staged plan changed")
            if self.artifacts.exists(staged["video"]):
                raise ValueError("staged video already exists")
            stage_category = "render_failed"
            self.renderer.render(command, cwd=staging)
            stage_category = "render_validation_failed"
            video_fingerprint = fingerprint(self.artifacts, staged["video"])
            output_media = self.probe.probe(staged["video"])
            if not isinstance(output_media, RenderMediaDTO):
                raise ValueError("output probe did not return public media DTO")
            last_end = max(max(cue.end_ms, cue.ass_end_ms) for cue in plan.cues)
            self.media_validator(inputs.media, output_media, last_end)
            # A success report is only staged after real output media QA.
            report = _successful_report(inputs, plan, pixels)
            stage_category = "publication_failed"
            self._stage(staged["report"], json_bytes(report))
            if SubtitleRenderReportDTO.from_dict(parse_json(self.artifacts.read_bytes(staged["report"]))) != report:
                raise ValueError("staged report changed")
            outputs = {key: self._evidence(staged[key], OUTPUT_TYPES[key]) for key in ("plan", "ass", "video", "report")}
            if (outputs["video"].size_bytes, outputs["video"].sha256) != (video_fingerprint.size_bytes, video_fingerprint.sha256):
                raise ValueError("staged video changed after output media validation")
            # Revalidate staged bodies as well as every upstream fingerprint after lengthy encoding.
            if (self.artifacts.read_bytes(staged["plan"]) != json_bytes(plan) or self.artifacts.read_bytes(staged["ass"]) != ass
                    or self.artifacts.read_bytes(staged["report"]) != json_bytes(report)):
                raise ValueError("staged rendering content changed during encoding")
            stage_category = "input_invalid"
            inputs.verify_unchanged(self.artifacts)
            stage_category = "publication_failed"
            for key in ("plan", "ass", "video", "report"):
                self.artifacts.publish(staged[key], paths[key], overwrite=overwrite)
                if self._evidence(paths[key], OUTPUT_TYPES[key]) != outputs[key]:
                    raise ValueError("published body differs from validated staged evidence")
            manifest = SubtitleRenderManifestDTO(asset_id, "succeeded", self.clock.now_utc(), inputs.evidence,
                                                 plan.profile, plan.profile_sha256, plan.font, plan.tools,
                                                 inputs.media, output_media, outputs, report.summary)
            manifest.validate_against_plan_and_report(plan, report)
            self._stage(staged["manifest"], json_bytes(manifest))
            if SubtitleRenderManifestDTO.from_dict(parse_json(self.artifacts.read_bytes(staged["manifest"]))) != manifest:
                raise ValueError("staged manifest changed")
            self.artifacts.publish(staged["manifest"], paths["manifest"], overwrite=overwrite)
            if self.artifacts.read_bytes(paths["manifest"]) != json_bytes(manifest):
                raise ValueError("published manifest differs")
            return SubtitleRenderingRunResult("succeeded", "render", **{key + "_path": value for key, value in paths.items()},
                                              cue_count=len(plan.cues), warning_count=report.summary.warning_count, command=command)
        except (Exception, KeyboardInterrupt) as error:
            category = getattr(error, "category", stage_category)
            if category not in RENDER_ERROR_CATEGORIES:
                category = stage_category
            diagnostic = str(getattr(error, "diagnostic", str(error)))[:2048]
            report_path = None
            if not dry_run and category != "artifact_conflict":
                report_path = self._failure_report(asset_id, category, diagnostic, paths, plan, staging, initially_occupied)
            raise SubtitleRenderingWorkflowError(category, diagnostic, report_path) from error

    def _stage(self, path: str, data: bytes) -> None:
        self.artifacts.stage_bytes(path, data)
        if self.artifacts.read_bytes(path) != data:
            raise ValueError("staged bytes did not round-trip")

    def _evidence(self, path: str, kind: ArtifactType) -> RenderArtifactEvidenceDTO:
        actual = fingerprint(self.artifacts, path)
        return RenderArtifactEvidenceDTO(canonical_filename(kind), actual.size_bytes, actual.sha256)

    def _reuse(self, inputs, plan, ass, paths) -> SubtitleRenderReportDTO:
        try:
            saved_plan = SubtitleRenderPlanDTO.from_dict(parse_json(self.artifacts.read_bytes(paths["plan"])))
            if saved_plan != plan:
                raise ValueError("render plan identity changed")
            saved_ass = self.artifacts.read_bytes(paths["ass"])
            self.codec.validate(saved_ass, plan, inputs.source_plan)
            if saved_ass != ass:
                raise ValueError("ASS serialization identity changed")
            report = SubtitleRenderReportDTO.from_dict(parse_json(self.artifacts.read_bytes(paths["report"])))
            report.validate_against_plan(plan)
            expected = _successful_report(inputs, plan, report.pixel_results)
            if report != expected:
                raise ValueError("saved report differs from recomputed QA")
            manifest = SubtitleRenderManifestDTO.from_dict(parse_json(self.artifacts.read_bytes(paths["manifest"])))
            manifest.validate_against_plan_and_report(plan, report)
            for key in ("plan", "ass", "video", "report"):
                if self._evidence(paths[key], OUTPUT_TYPES[key]) != manifest.outputs[key]:
                    raise ValueError("saved output evidence changed")
            output_media = self.probe.probe(paths["video"])
            if output_media != manifest.output_media:
                raise ValueError("saved output media changed")
            self.media_validator(inputs.media, output_media, max(max(cue.end_ms, cue.ass_end_ms) for cue in plan.cues))
            inputs.verify_unchanged(self.artifacts)
            return report
        except Exception as error:
            raise SubtitleRenderingWorkflowError("artifact_conflict", "Existing rendering set failed read-only revalidation.") from error

    def _failure_report(self, asset_id, category, diagnostic, paths, plan, staging, initially_occupied) -> str | None:
        try:
            finding = RenderFindingDTO("rendering." + category, "error", diagnostic=(diagnostic + ("; retained staging: " + staging if staging else ""))[:2048])
            report = SubtitleRenderReportDTO(asset_id, "failed", _summary(plan, (finding,), passed=False), (finding,), (), category)
            # Never replace an existing report/body, even during explicit overwrite failures.
            if staging is not None and self.artifacts.exists(staging):
                target = str(Path(staging) / "failure-report.json")
                self._stage(target, json_bytes(report))
                return target
            if paths and not initially_occupied and not any(self.artifacts.exists(path) for path in paths.values()):
                failure_staging = self.artifacts.plan_staging(str(Path(paths["report"]).parent))
                self.artifacts.create_staging(failure_staging)
                target = str(Path(failure_staging) / canonical_filename(ArtifactType.SUBTITLE_RENDER_REPORT))
                self._stage(target, json_bytes(report))
                self.artifacts.publish(target, paths["report"], overwrite=False)
                return paths["report"]
        except Exception:
            pass
        return None
