from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from archive_core.interfaces import (
    SourceAlignmentDTO, SrtProcessingManifestDTO, SrtProcessingReportDTO,
    SubtitleFragmentDTO, SubtitlePlanDTO, SubtitleTimingAdjustmentDTO,
    TranslationManifestDTO, TranslationResultDTO,
    character_boundaries, normalize_chinese_text,
)
from srt_processing.infrastructure import LocalSubtitleArtifactStore, Pysubs2SrtCodec
from srt_processing.domain.rules import chinese_half_units, wrap_english_text

from tests.srt_processing.acceptance_fakes import LocalCase
from tests.srt_processing.test_planner import inputs as planner_inputs


@pytest.fixture(autouse=True)
def no_real_process_or_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("cross-layer tests must not start media tools, ASR, providers or networking")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr("socket.create_connection", forbidden)


def test_real_local_adapters_bind_both_chains_and_three_srt_projections(tmp_path):
    case = LocalCase(tmp_path)
    upstream = case.upstream_bytes()
    handler = case.handler()
    first = handler.handle(case.command)
    assert first.status == "succeeded" and first.cue_count >= 3
    plan = SubtitlePlanDTO.from_dict(json.loads(case.outputs["subtitle_plan"].read_bytes()))
    manifest = SrtProcessingManifestDTO.from_dict(json.loads(case.outputs["manifest"].read_bytes()))
    source = SourceAlignmentDTO.from_dict(case.read_input("source_alignment"))
    translation = TranslationResultDTO.from_dict(case.read_input("translation_result"))
    translated_manifest = TranslationManifestDTO.from_dict(case.read_input("translation_manifest"))
    plan.validate_against_inputs(source, translation)
    manifest.validate_against_plan(plan)
    assert plan.source_alignment_sha256 == translated_manifest.input.sha256 == translation.source_alignment_sha256
    for key, evidence in manifest.inputs.items():
        raw = case.inputs[key].read_bytes()
        assert (evidence.size_bytes, evidence.sha256) == (len(raw), hashlib.sha256(raw).hexdigest())
    codec = Pysubs2SrtCodec()
    projections = {key: codec.decode(case.outputs[key].read_bytes()) for key in ("english_srt", "chinese_srt", "bilingual_srt")}
    for index, cue in enumerate(plan.cues):
        english = wrap_english_text(cue.english_text)
        for language, expected in (("english_srt", english), ("chinese_srt", cue.chinese_text),
                                    ("bilingual_srt", cue.chinese_text + "\n" + english)):
            event = projections[language][index]
            assert (event.index, event.start_ms, event.end_ms, event.text) == (index + 1, cue.start_ms, cue.end_ms, expected)
    assert case.upstream_bytes() == upstream
    snapshots = {key: (path.read_bytes(), path.stat().st_mtime_ns) for key, path in case.outputs.items()}
    second = case.handler().handle(case.command)
    assert second.status == "reused" and second.cue_count == first.cue_count
    assert snapshots == {key: (path.read_bytes(), path.stat().st_mtime_ns) for key, path in case.outputs.items()}
    assert case.upstream_bytes() == upstream and case.clock.calls == 1


def test_independent_local_generations_have_identical_content_artifacts(tmp_path):
    first, second = LocalCase(tmp_path / "first"), LocalCase(tmp_path / "second")
    assert first.handler().handle(first.command).status == second.handler().handle(second.command).status == "succeeded"
    for key in ("subtitle_plan", "english_srt", "chinese_srt", "bilingual_srt", "report"):
        assert first.outputs[key].read_bytes() == second.outputs[key].read_bytes()


def test_combining_zwj_and_layout_ranges_survive_actual_codec_and_filesystem(tmp_path):
    data = planner_inputs([("a" * 30, "b" * 30)], ["\t甲 e\u0301👩\u200d💻乙\n"])
    case = LocalCase(tmp_path, data)
    assert case.handler().handle(case.command).status == "succeeded"
    plan = SubtitlePlanDTO.from_dict(json.loads(case.outputs["subtitle_plan"].read_bytes()))
    normalized = normalize_chinese_text(data[1].sentence_translations[0].translated_text)
    fragments = [part for cue in plan.cues for part in cue.fragments]
    assert "".join(normalized[part.chinese_start_offset:part.chinese_end_offset] for part in fragments) == normalized
    assert all(part.chinese_start_offset in character_boundaries(normalized)
               and part.chinese_end_offset in character_boundaries(normalized) for part in fragments)
    decoded = Pysubs2SrtCodec().decode(case.outputs["bilingual_srt"].read_bytes())
    assert tuple(event.text for event in decoded) == tuple(cue.chinese_text + "\n" + wrap_english_text(cue.english_text)
                                                         for cue in plan.cues)


def test_extreme_cps_remains_warning_through_real_projection_and_publication(tmp_path):
    case = LocalCase(tmp_path, planner_inputs([("a" * 30, "b" * 30)], ["甲乙丙丁戊己庚辛壬癸"], duration=1))
    outcome = case.handler().handle(case.command)
    assert outcome.status == "succeeded"
    report = SrtProcessingReportDTO.from_dict(json.loads(case.outputs["report"].read_bytes()))
    assert report.summary.chinese_cps_exceeded_count >= 1
    assert report.summary.english_cps_exceeded_count == 1
    assert any(finding.code == "reading.chinese_cps" for finding in report.findings)
    events = Pysubs2SrtCodec().decode(case.outputs["english_srt"].read_bytes())
    assert len(events) == 1 and len(events[0].text.split("\n")) == 2


@pytest.mark.parametrize("projection", ["english_srt", "bilingual_srt"])
def test_resigned_real_multiline_srt_cannot_reuse_flattened_english(tmp_path, projection):
    case = LocalCase(tmp_path, planner_inputs([("a" * 30, "b" * 30)], ["甲乙"]))
    assert case.handler().handle(case.command).status == "succeeded"
    plan = SubtitlePlanDTO.from_dict(json.loads(case.outputs["subtitle_plan"].read_bytes()))
    assert len(plan.cues) == 1 and "\n" not in plan.cues[0].english_text
    wrapped = wrap_english_text(plan.cues[0].english_text)
    assert len(wrapped.split("\n")) == 2
    raw = case.outputs[projection].read_text()
    case.outputs[projection].write_text(raw.replace(wrapped, plan.cues[0].english_text))
    case.resign_output(projection)
    before = case.output_bytes()
    outcome = case.handler().handle(case.command)
    assert outcome.status == "failed" and outcome.error_category == "artifact_conflict"
    assert case.output_bytes() == before


@pytest.mark.parametrize("field", ["range", "speaker", "section", "anchor", "method"])
def test_resigned_real_plan_still_fails_source_provenance_or_rule_qa(tmp_path, field):
    case = LocalCase(tmp_path)
    assert case.handler().handle(case.command).status == "succeeded"
    plan = json.loads(case.outputs["subtitle_plan"].read_bytes())
    cue = plan["cues"][0]
    if field == "range":
        cue["fragments"][0]["chinese_start_offset"] += 1
    elif field == "speaker":
        cue["fragments"][0]["speaker_label"] = "MUNGER"
    elif field == "section":
        cue["section_id"] = "sec2"
    elif field == "anchor":
        cue["start_ms"] += 1
    else:
        cue["break_methods"] = ["english_clause", "chinese_clause"]
    case.outputs["subtitle_plan"].write_bytes(json.dumps(plan, ensure_ascii=False).encode("utf-8"))
    case.resign_output("subtitle_plan")
    before = case.output_bytes()
    outcome = case.handler().handle(case.command)
    assert outcome.status == "failed" and outcome.error_category == "artifact_conflict"
    assert case.output_bytes() == before


@pytest.mark.parametrize("name", ["english_srt", "chinese_srt", "bilingual_srt"])
@pytest.mark.parametrize("damage", ["bom", "crlf", "index", "time", "text", "html"])
def test_resigned_real_srt_cannot_hide_noncanonical_or_lossy_projection(tmp_path, name, damage):
    case = LocalCase(tmp_path)
    assert case.handler().handle(case.command).status == "succeeded"
    raw = case.outputs[name].read_bytes()
    if damage == "bom":
        raw = b"\xef\xbb\xbf" + raw
    elif damage == "crlf":
        raw = raw.replace(b"\n", b"\r\n")
    elif damage == "index":
        raw = b"2" + raw[1:]
    elif damage == "time":
        raw = raw.replace(b"00:00:00,100", b"00:00:00,101", 1)
    else:
        lines = raw.decode("utf-8").split("\n")
        lines[2] = "Wrong source text." if damage == "text" else "<b>" + lines[2] + "</b>"
        raw = "\n".join(lines).encode("utf-8")
    case.outputs[name].write_bytes(raw)
    case.resign_output(name)
    before = case.output_bytes()
    outcome = case.handler().handle(case.command)
    assert outcome.status == "failed" and outcome.error_category == "artifact_conflict"
    assert case.output_bytes() == before


@pytest.mark.parametrize("chinese", ["<b>原文</b>", r"字面\N文本", r"{\p1}drawing"])
def test_real_lossy_codec_failure_never_publishes_a_success_bundle(tmp_path, chinese):
    case = LocalCase(tmp_path, planner_inputs([("Hello.",)], [chinese]))
    upstream = case.upstream_bytes()
    outcome = case.handler().handle(case.command)
    assert outcome.status == "failed" and outcome.error_category == "projection_failed"
    assert set(case.output_bytes()) == {"report"}
    report = SrtProcessingReportDTO.from_dict(json.loads(case.outputs["report"].read_bytes()))
    assert report.status == "failed" and report.error_code == "projection_failed"
    assert case.upstream_bytes() == upstream


def test_actual_replace_failure_leaves_partial_set_and_no_false_success(tmp_path, monkeypatch):
    case = LocalCase(tmp_path)
    upstream = case.upstream_bytes()
    original = Path.replace

    def fail_chinese(source, target):
        if target == case.outputs["chinese_srt"]:
            raise OSError("injected rename failure")
        return original(source, target)

    monkeypatch.setattr(Path, "replace", fail_chinese)
    outcome = case.handler().handle(case.command)
    assert outcome.status == "failed" and outcome.error_category == "publication_failed"
    assert set(case.output_bytes()) == {"subtitle_plan", "english_srt"}
    assert not case.outputs["manifest"].exists()
    assert any(path.name.startswith(".chinese.srt.") for path in case.workspace.iterdir())
    before = {path.name: path.read_bytes() for path in case.workspace.iterdir()}
    retry = case.handler().handle(case.command)
    assert retry.status == "failed" and retry.error_category == "artifact_conflict"
    assert {path.name: path.read_bytes() for path in case.workspace.iterdir()} == before
    assert case.upstream_bytes() == upstream


def test_actual_staged_byte_change_is_detected_before_any_success_publish(tmp_path):
    case = LocalCase(tmp_path)
    upstream = case.upstream_bytes()

    class CorruptingStore(LocalSubtitleArtifactStore):
        def stage_bytes(self, target_path, data):
            return super().stage_bytes(target_path, data + b" " if target_path.endswith("chinese.srt") else data)

    outcome = case.handler(artifacts=CorruptingStore()).handle(case.command)
    assert outcome.status == "failed" and outcome.error_category == "publication_failed"
    assert set(case.output_bytes()) == {"report"}
    assert json.loads(case.outputs["report"].read_bytes())["status"] == "failed"
    assert any(path.name.startswith(".subtitle_plan.json.") for path in case.workspace.iterdir())
    assert not case.outputs["manifest"].exists()
    assert case.upstream_bytes() == upstream


def test_real_failed_overwrite_cannot_make_old_manifest_accept_mixed_generations(tmp_path, monkeypatch):
    case = LocalCase(tmp_path)
    assert case.handler().handle(case.command).status == "succeeded"
    old_manifest = case.outputs["manifest"].read_bytes()
    result = case.read_input("translation_result")
    result["sentence_translations"][0]["translated_text"] = "我们完整保留字幕文字，不进行压缩或重新翻译。"
    case.write_input("translation_result", result)
    case.rebind()
    upstream = case.upstream_bytes()
    original = Path.replace

    def fail_chinese(source, target):
        if target == case.outputs["chinese_srt"]:
            raise OSError("stop in the middle of explicit overwrite")
        return original(source, target)

    monkeypatch.setattr(Path, "replace", fail_chinese)
    outcome = case.handler().handle(replace(case.command, overwrite=True))
    assert outcome.status == "failed" and outcome.error_category == "publication_failed"
    assert case.outputs["manifest"].read_bytes() == old_manifest
    assert json.loads(case.outputs["report"].read_bytes())["status"] == "failed"
    before = case.output_bytes()
    retry = case.handler().handle(case.command)
    assert retry.status == "failed" and retry.error_category == "artifact_conflict"
    assert case.output_bytes() == before and case.upstream_bytes() == upstream


def test_non_greedy_choice_survives_input_gates_actual_srt_and_reuse(tmp_path):
    data = planner_inputs([("a" * 30, "b" * 30, "c" * 30)], ["甲乙，丙丁戊"], duration=100, word_gap=300)
    case = LocalCase(tmp_path, data)
    assert case.handler().handle(case.command).status == "succeeded"
    plan = SubtitlePlanDTO.from_dict(json.loads(case.outputs["subtitle_plan"].read_bytes()))
    assert [(cue.fragments[-1].last_word_id, cue.fragments[-1].chinese_end_offset)
            for cue in plan.cues] == [("w1", 3), ("w3", 6)]
    # A locally greedy first edge consumes w1+w2 and leaves two too-short cues.
    report = SrtProcessingReportDTO.from_dict(json.loads(case.outputs["report"].read_bytes()))
    assert report.summary.too_short_count == 1
    assert len(Pysubs2SrtCodec().decode(case.outputs["bilingual_srt"].read_bytes())) == 2
    assert case.handler().handle(case.command).status == "reused"


def test_known_null_different_known_speakers_are_never_bridged_in_actual_files(tmp_path):
    data = planner_inputs([("Yes.",)] * 3, ["是。"] * 3, duration=100,
                          sentence_gap=100, speakers=("BUFFETT", None, "MUNGER"))
    case = LocalCase(tmp_path, data)
    assert case.handler().handle(case.command).status == "succeeded"
    plan = SubtitlePlanDTO.from_dict(json.loads(case.outputs["subtitle_plan"].read_bytes()))
    assert len(plan.cues) >= 2
    assert [part.speaker_label for cue in plan.cues for part in cue.fragments] == ["BUFFETT", None, "MUNGER"]
    assert all(len({part.speaker_label for part in cue.fragments if part.speaker_label is not None}) <= 1
               for cue in plan.cues)


@pytest.mark.parametrize("duration", [500, 7001, 10001, 25000])
def test_soft_chinese_and_duration_targets_publish_read_back_and_reuse_without_forced_splits(tmp_path, duration):
    chinese = "我们完整保留这段超过中文目标的长句。"
    case = LocalCase(tmp_path, planner_inputs([("Business.",)], [chinese], duration=duration))
    upstream = case.upstream_bytes()
    first = case.handler().handle(case.command)
    assert first.status == "succeeded" and first.cue_count == 1
    plan = SubtitlePlanDTO.from_dict(json.loads(case.outputs["subtitle_plan"].read_bytes()))
    report = SrtProcessingReportDTO.from_dict(json.loads(case.outputs["report"].read_bytes()))
    manifest = SrtProcessingManifestDTO.from_dict(json.loads(case.outputs["manifest"].read_bytes()))
    assert manifest.profile.parameters["version"] == "v3"
    assert manifest.profile.parameters["chinese_target_half_units"] == 32
    assert manifest.profile.parameters["target_duration_ms"] == 7000
    assert "maximum_duration_ms" not in manifest.profile.parameters
    assert manifest.codec.serialization_version == "word-wrap-english-2x42.v2"
    assert all(finding.severity != "error" for finding in report.findings)
    assert plan.cues[0].chinese_text == chinese and "\n" not in plan.cues[0].chinese_text
    assert plan.cues[0].base_end_ms - plan.cues[0].start_ms == duration
    warnings = {finding.code: finding for finding in report.findings}
    assert warnings["reading.chinese_length"].severity == "warning"
    assert warnings["reading.chinese_length"].observed == {
        "half_units": chinese_half_units(chinese), "target_half_units": 32,
    }
    assert ("timing.target_duration" in warnings) == (duration > 7000)
    if duration > 7000:
        assert warnings["timing.target_duration"].severity == "warning"
        assert warnings["timing.target_duration"].observed == {
            "duration_ms": duration, "target_duration_ms": 7000,
        }
    codec = Pysubs2SrtCodec()
    for name, expected in (("english_srt", "Business."), ("chinese_srt", chinese),
                           ("bilingual_srt", chinese + "\nBusiness.")):
        events = codec.decode(case.outputs[name].read_bytes())
        assert len(events) == 1 and events[0].text == expected
        assert (events[0].start_ms, events[0].end_ms) == (plan.cues[0].start_ms, plan.cues[0].end_ms)
    if duration == 500:
        assert report.summary.chinese_cps_exceeded_count == 1
    before = {name: (path.read_bytes(), path.stat().st_mtime_ns) for name, path in case.outputs.items()}
    assert case.handler().handle(case.command).status == "reused"
    assert before == {name: (path.read_bytes(), path.stat().st_mtime_ns) for name, path in case.outputs.items()}
    assert case.upstream_bytes() == upstream


def test_exact_chinese_and_duration_targets_do_not_create_exceeded_findings(tmp_path):
    chinese = "甲" * 15 + "。"
    case = LocalCase(tmp_path, planner_inputs([("Business.",)], [chinese], duration=7000))
    assert case.handler().handle(case.command).status == "succeeded"
    report = SrtProcessingReportDTO.from_dict(json.loads(case.outputs["report"].read_bytes()))
    assert not {"reading.chinese_length", "timing.target_duration"}.intersection(
        finding.code for finding in report.findings
    )


def test_duration_warning_uses_final_display_time_including_gap_extension(tmp_path):
    data = planner_inputs([("First.",), ("Second.",)], ["甲。", "乙。"],
                          times=[(100, 7000), (7300, 7900)], section_sizes=(1, 1))
    case = LocalCase(tmp_path, data)
    assert case.handler().handle(case.command).status == "succeeded"
    plan = SubtitlePlanDTO.from_dict(json.loads(case.outputs["subtitle_plan"].read_bytes()))
    assert len(plan.cues) == 2
    first = plan.cues[0]
    assert first.base_end_ms - first.start_ms == 6900
    assert first.end_ms - first.start_ms == 6900 + 300 - plan.media.gap_threshold_ms > 7000
    report = SrtProcessingReportDTO.from_dict(json.loads(case.outputs["report"].read_bytes()))
    warning = next(finding for finding in report.findings if finding.code == "timing.target_duration")
    assert warning.cue_ids == ("c1",)
    assert warning.observed == {"duration_ms": first.end_ms - first.start_ms, "target_duration_ms": 7000}


@pytest.mark.parametrize("code", ["reading.chinese_length", "timing.target_duration"])
def test_resigned_report_cannot_omit_recomputed_soft_target_warning(tmp_path, code):
    case = LocalCase(tmp_path, planner_inputs([("Business.",)], ["我们完整保留这段超过中文目标的长句。"],
                                             duration=10001))
    assert case.handler().handle(case.command).status == "succeeded"
    report = json.loads(case.outputs["report"].read_bytes())
    assert any(finding["code"] == code for finding in report["findings"])
    report["findings"] = [finding for finding in report["findings"] if finding["code"] != code]
    case.outputs["report"].write_bytes(json.dumps(report, ensure_ascii=False).encode())
    case.resign_output("report")
    before = case.output_bytes()
    result = case.handler().handle(case.command)
    assert result.status == "failed" and result.error_category == "artifact_conflict"
    assert case.output_bytes() == before


@pytest.mark.parametrize("words", [("a" * 43,), ("a" * 28, "b" * 28, "c" * 28)])
def test_english_hard_budget_cannot_fall_back_to_nonpause_chinese_cuts(tmp_path, words):
    case = LocalCase(tmp_path, planner_inputs([words], ["甲乙丙丁戊。"], duration=1000))
    upstream = case.upstream_bytes()
    result = case.handler().handle(case.command)
    assert result.status == "failed" and result.error_category == "planning_failed"
    assert set(case.output_bytes()) == {"report"}
    assert not case.outputs["manifest"].exists() and case.upstream_bytes() == upstream


def test_resigned_publicly_valid_nonpause_chinese_split_is_rejected_on_reuse(tmp_path):
    data = planner_inputs([("First", "second.")], ["甲乙丙丁戊己庚辛壬癸。"])
    case = LocalCase(tmp_path, data)
    assert case.handler().handle(case.command).status == "succeeded"
    original = SubtitlePlanDTO.from_dict(json.loads(case.outputs["subtitle_plan"].read_bytes()))
    assert len(original.cues) == 1
    cue = original.cues[0]
    words = data[0].words
    fragments = (SubtitleFragmentDTO("s1", "w1", "w1", 0, 5, None),
                 SubtitleFragmentDTO("s1", "w2", "w2", 5, len(cue.chinese_text), None))
    forged = replace(original, cues=(
        replace(cue, id="c1", start_ms=words[0].start_ms, base_end_ms=words[0].end_ms, end_ms=words[0].end_ms,
                english_text=words[0].text, chinese_text=cue.chinese_text[:5], fragments=(fragments[0],),
                timing_adjustment=SubtitleTimingAdjustmentDTO(0, (), 0, "preserved_gap"),
                break_methods=("english_emergency", "chinese_emergency")),
        replace(cue, id="c2", start_ms=words[1].start_ms, base_end_ms=words[1].end_ms, end_ms=words[1].end_ms,
                english_text=words[1].text, chinese_text=cue.chinese_text[5:], fragments=(fragments[1],),
                timing_adjustment=SubtitleTimingAdjustmentDTO(0, (), None, "last_cue")),
    ))
    # Exact source coverage still holds; only the new Chinese pause contract is violated.
    forged.validate_against_inputs(
        SourceAlignmentDTO.from_dict(case.read_input("source_alignment")),
        TranslationResultDTO.from_dict(case.read_input("translation_result")),
    )
    case.outputs["subtitle_plan"].write_bytes(json.dumps(forged.to_dict(), ensure_ascii=False).encode())
    case.resign_output("subtitle_plan")
    before = case.output_bytes()
    result = case.handler().handle(case.command)
    assert result.status == "failed" and result.error_category == "artifact_conflict"
    assert case.output_bytes() == before
