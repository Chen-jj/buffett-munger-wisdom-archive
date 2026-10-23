"""Manifest-driven subtitle generation with prepared outputs and manifest-last publication."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from archive_core.application import build_asset_workspace
from archive_core.domain import ArtifactType, AssetId, canonical_filename
from archive_core.interfaces import (
    SrtProcessingManifestDTO,
    SrtProcessingReportDTO,
    SubtitleArtifactEvidenceDTO,
    SubtitleFindingDTO,
    SubtitlePlanDTO,
    SubtitleSummaryDTO,
    normalize_chinese_text,
)
from srt_processing.domain.planner import PlanningResult, analyze_plan, plan_subtitles
from srt_processing.domain.rules import PROFILE, rules_identity, wrap_english_text

from .inputs import SubtitleInputError, ValidatedSubtitleInputs, load_subtitle_inputs
from .ports import ChineseWordSegmenter, Clock, MediaProbe, SrtCodec, SrtCue, SubtitleArtifactStore


_OUTPUT_TYPES = {
    "subtitle_plan": ArtifactType.SUBTITLE_PLAN,
    "english_srt": ArtifactType.ENGLISH_SRT,
    "chinese_srt": ArtifactType.CHINESE_SRT,
    "bilingual_srt": ArtifactType.BILINGUAL_SRT,
    "report": ArtifactType.SRT_PROCESSING_REPORT,
}
_LANGUAGES = {"english_srt": "english", "chinese_srt": "chinese", "bilingual_srt": "bilingual"}


class SrtProcessingWorkflowError(RuntimeError):
    category = "srt_processing_failed"


class SrtProcessingArtifactConflict(SrtProcessingWorkflowError):
    category = "artifact_conflict"


class SrtProcessingPlanningFailure(SrtProcessingWorkflowError):
    category = "planning_failed"


class SrtProcessingProjectionFailure(SrtProcessingWorkflowError):
    category = "projection_failed"


class SrtProcessingPublicationFailure(SrtProcessingWorkflowError):
    category = "publication_failed"


@dataclass(frozen=True)
class SrtProcessingRunResult:
    status: str
    plan_path: str
    manifest_path: str
    report_path: str
    english_srt_path: str
    chinese_srt_path: str
    bilingual_srt_path: str
    cue_count: int
    warning_count: int


class SrtProcessingWorkflow:
    def __init__(
        self,
        *,
        artifacts: SubtitleArtifactStore,
        probe: MediaProbe,
        codec: SrtCodec,
        clock: Clock,
        segmenter: ChineseWordSegmenter,
        output_root: str = "output",
        planner: Callable[..., PlanningResult] = plan_subtitles,
    ) -> None:
        self.artifacts = artifacts
        self.probe = probe
        self.codec = codec
        self.clock = clock
        self.segmenter = segmenter
        self.output_root = output_root
        self.planner = planner

    def execute(
        self,
        *,
        asset_id: str,
        transcription_manifest_path: str,
        translation_manifest_path: str,
        overwrite: bool = False,
    ) -> SrtProcessingRunResult:
        paths: dict[str, str] | None = None
        try:
            if not isinstance(overwrite, bool):
                raise SubtitleInputError("overwrite must be a boolean")
            if not isinstance(asset_id, str) or len(asset_id.split(":")) != 3:
                raise SubtitleInputError("asset_id must use source:group:item")
            try:
                asset = AssetId(*asset_id.split(":"))
            except ValueError as error:
                raise SubtitleInputError(str(error)) from error
            workspace = build_asset_workspace(asset, self.output_root)
            paths = {key: str(workspace / canonical_filename(kind)) for key, kind in _OUTPUT_TYPES.items()}
            paths["manifest"] = str(workspace / canonical_filename(ArtifactType.SRT_PROCESSING_MANIFEST))
            inputs = load_subtitle_inputs(
                asset_id=asset_id,
                transcription_manifest_path=transcription_manifest_path,
                translation_manifest_path=translation_manifest_path,
                artifacts=self.artifacts,
                probe=self.probe,
                output_root=self.output_root,
            )
            try:
                expected_segmenter = {key: PROFILE.parameters[key] for key in (
                    "chinese_segmentation_engine", "chinese_dictionary_sha256", "chinese_segmentation_mode",
                )}
                if self.segmenter.identity != expected_segmenter:
                    raise ValueError("Chinese segmenter identity does not match the subtitle profile")
                chinese_word_spans = {
                    sentence.sentence_id: self.segmenter.spans(normalize_chinese_text(sentence.translated_text))
                    for sentence in inputs.translation.sentence_translations
                }
            except Exception as error:
                if not overwrite and any(self.artifacts.exists(path) for path in paths.values()):
                    raise SrtProcessingArtifactConflict(str(error)) from error
                raise SrtProcessingPlanningFailure(str(error)) from error
            if self.codec.identity.serialization_version != "word-wrap-english-2x42.v2":
                if not overwrite and any(self.artifacts.exists(path) for path in paths.values()):
                    raise SrtProcessingArtifactConflict("subtitle codec does not use the current serialization")
                raise SrtProcessingProjectionFailure("subtitle codec does not use the current serialization")
            reused = self._reuse(inputs, paths, overwrite, chinese_word_spans)
            if reused is not None:
                return reused

            try:
                planned = self.planner(
                    inputs.alignment,
                    inputs.translation,
                    source_alignment_sha256=inputs.evidence["source_alignment"].sha256,
                    translation_result_sha256=inputs.evidence["translation_result"].sha256,
                    video_sha256=inputs.evidence["video"].sha256,
                    media=inputs.media,
                    chinese_word_spans=chinese_word_spans,
                )
                self._validate_plan_identity(planned.plan, inputs)
                findings, summary = analyze_plan(
                    planned.plan, inputs.alignment, inputs.translation, chinese_word_spans=chinese_word_spans
                )
            except Exception as error:
                raise SrtProcessingPlanningFailure(str(error)) from error
            report = SrtProcessingReportDTO(asset_id, "succeeded", summary, findings)
            try:
                contents = {"subtitle_plan": _json_bytes(planned.plan.to_dict()),
                            "report": _json_bytes(report.to_dict())}
                for key, language in _LANGUAGES.items():
                    contents[key] = self.codec.encode(planned.plan, language)
                self._validate_bundle(contents, inputs, chinese_word_spans)
            except Exception as error:
                raise SrtProcessingProjectionFailure(str(error)) from error

            try:
                staged = {key: self.artifacts.stage_bytes(paths[key], contents[key]) for key in _OUTPUT_TYPES}
                staged_contents = {key: self.artifacts.read_bytes(staged[key]) for key in _OUTPUT_TYPES}
                if staged_contents != contents:
                    raise ValueError("staging changed subtitle artifact bytes")
                self._validate_bundle(staged_contents, inputs, chinese_word_spans)
                evidence = {key: _evidence(paths[key], staged_contents[key]) for key in _OUTPUT_TYPES}
                for key in _OUTPUT_TYPES:
                    self.artifacts.publish(staged[key], paths[key], overwrite=overwrite)
                manifest = SrtProcessingManifestDTO(
                    asset_id=asset_id, status="succeeded", completed_at=self.clock.now_utc(),
                    inputs=inputs.evidence, rules=rules_identity(), profile=PROFILE,
                    media=inputs.media, probe=inputs.probe, codec=self.codec.identity,
                    outputs=evidence, summary=summary,
                )
                manifest.validate_against_plan(planned.plan)
                staged_manifest = self.artifacts.stage_bytes(paths["manifest"], _json_bytes(manifest.to_dict()))
                manifest_bytes = self.artifacts.read_bytes(staged_manifest)
                if manifest_bytes != _json_bytes(manifest.to_dict()):
                    raise ValueError("staging changed subtitle manifest bytes")
                SrtProcessingManifestDTO.from_dict(_json_object(manifest_bytes)).validate_against_plan(planned.plan)
                self.artifacts.publish(staged_manifest, paths["manifest"], overwrite=overwrite)
            except Exception as error:
                raise SrtProcessingPublicationFailure(str(error)) from error
            return _run_result("succeeded", paths, summary, findings)
        except (SubtitleInputError, SrtProcessingWorkflowError) as error:
            self._failure_report(asset_id, paths, overwrite, error)
            raise
        except Exception as error:
            failure = SrtProcessingWorkflowError(str(error))
            self._failure_report(asset_id, paths, overwrite, failure)
            raise failure from error

    def _reuse(
        self, inputs: ValidatedSubtitleInputs, paths: Mapping[str, str], overwrite: bool,
        chinese_word_spans: Mapping[str, tuple[tuple[int, int], ...]],
    ) -> SrtProcessingRunResult | None:
        if overwrite:
            return None
        present = [self.artifacts.exists(path) for path in paths.values()]
        if not any(present):
            return None
        if not all(present):
            raise SrtProcessingArtifactConflict("subtitle artifact set is incomplete")
        try:
            manifest = SrtProcessingManifestDTO.from_dict(
                _json_object(self.artifacts.read_bytes(paths["manifest"]))
            )
            if (manifest.asset_id != inputs.asset.value or manifest.inputs != inputs.evidence
                    or manifest.rules != rules_identity() or manifest.profile != PROFILE
                    or manifest.media != inputs.media or manifest.probe != inputs.probe
                    or manifest.codec != self.codec.identity):
                raise ValueError("subtitle reuse identity does not match current inputs and tools")
            contents = {key: self.artifacts.read_bytes(paths[key]) for key in _OUTPUT_TYPES}
            for key, raw in contents.items():
                if _evidence(paths[key], raw) != manifest.outputs[key]:
                    raise ValueError(f"{key} evidence does not match subtitle manifest")
            plan, findings, summary = self._validate_bundle(contents, inputs, chinese_word_spans)
            manifest.validate_against_plan(plan)
            if manifest.summary != summary:
                raise ValueError("subtitle manifest summary does not match current QA")
            return _run_result("reused", paths, summary, findings)
        except Exception as error:
            raise SrtProcessingArtifactConflict(str(error)) from error

    def _validate_plan_identity(self, plan: SubtitlePlanDTO, inputs: ValidatedSubtitleInputs) -> None:
        if (plan.source_alignment_sha256 != inputs.evidence["source_alignment"].sha256
                or plan.translation_result_sha256 != inputs.evidence["translation_result"].sha256
                or plan.video_sha256 != inputs.evidence["video"].sha256
                or plan.media != inputs.media or plan.rules != rules_identity()):
            raise ValueError("subtitle plan identity does not match current inputs and rules")

    def _validate_bundle(
        self, contents: Mapping[str, bytes], inputs: ValidatedSubtitleInputs,
        chinese_word_spans: Mapping[str, tuple[tuple[int, int], ...]],
    ) -> tuple[SubtitlePlanDTO, tuple[SubtitleFindingDTO, ...], SubtitleSummaryDTO]:
        plan = SubtitlePlanDTO.from_dict(_json_object(contents["subtitle_plan"]))
        self._validate_plan_identity(plan, inputs)
        findings, summary = analyze_plan(
            plan, inputs.alignment, inputs.translation, chinese_word_spans=chinese_word_spans
        )
        expected_report = SrtProcessingReportDTO(inputs.asset.value, "succeeded", summary, findings)
        report = SrtProcessingReportDTO.from_dict(_json_object(contents["report"]))
        if report != expected_report:
            raise ValueError("subtitle report does not match current plan QA")
        for key, language in _LANGUAGES.items():
            expected = []
            for position, cue in enumerate(plan.cues, 1):
                english = wrap_english_text(cue.english_text)
                if language == "english":
                    text = english
                elif language == "chinese":
                    text = cue.chinese_text
                else:
                    text = cue.chinese_text + "\n" + english
                expected.append(SrtCue(position, cue.start_ms, cue.end_ms, text))
            if self.codec.decode(contents[key]) != tuple(expected):
                raise ValueError(f"{key} does not preserve plan cues, timing and text")
            if self.codec.encode(plan, language) != contents[key]:
                raise ValueError(f"{key} does not use the fixed serialization")
        return plan, findings, summary

    def _failure_report(
        self, asset_id: str, paths: Mapping[str, str] | None, overwrite: bool, error: Exception
    ) -> None:
        if paths is None or isinstance(error, SrtProcessingArtifactConflict):
            return
        try:
            if not overwrite and any(self.artifacts.exists(path) for path in paths.values()):
                return
            summary = SubtitleSummaryDTO(0, 0, 0, 0, 0, 0, 0, 0, 0)
            category = error.category
            finding = SubtitleFindingDTO(category, "error", "Subtitle processing did not complete.")
            report = SrtProcessingReportDTO(asset_id, "failed", summary, (finding,), category)
            staged = self.artifacts.stage_bytes(paths["report"], _json_bytes(report.to_dict()))
            self.artifacts.publish(staged, paths["report"], overwrite=overwrite)
        except Exception:
            # Diagnostic publication must never replace the original failure.
            pass


def _json_bytes(data: Mapping[str, Any]) -> bytes:
    return (json.dumps(dict(data), ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _json_object(data: bytes) -> Mapping[str, Any]:
    value = json.loads(data.decode("utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError("subtitle artifact JSON must be an object")
    return value


def _evidence(path: str, data: bytes) -> SubtitleArtifactEvidenceDTO:
    return SubtitleArtifactEvidenceDTO(Path(path).name, len(data), hashlib.sha256(data).hexdigest())


def _run_result(
    status: str, paths: Mapping[str, str], summary: SubtitleSummaryDTO,
    findings: tuple[SubtitleFindingDTO, ...],
) -> SrtProcessingRunResult:
    return SrtProcessingRunResult(
        status=status, plan_path=paths["subtitle_plan"], manifest_path=paths["manifest"],
        report_path=paths["report"], english_srt_path=paths["english_srt"],
        chinese_srt_path=paths["chinese_srt"], bilingual_srt_path=paths["bilingual_srt"],
        cue_count=summary.cue_count,
        warning_count=sum(finding.severity == "warning" for finding in findings),
    )
