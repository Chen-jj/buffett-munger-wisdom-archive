"""Current final-draft/report contracts replace the historical proportional plan schema."""
from dataclasses import replace
import json
import pytest
from archive_core.interfaces.bilingual import FinalBilingualDraftDTO, FinalCueDTO
from archive_core.interfaces.subtitles import SrtExportReportDTO
from tests.support.current_bilingual import source_plan


def report():
    return SrtExportReportDTO(source_plan().asset_id, "succeeded", (), {"cue_count": 2, "warning_count": 0})


@pytest.mark.parametrize("factory", [source_plan, report])
def test_public_subtitle_artifacts_round_trip_through_json(factory):
    value = factory()
    assert type(value).from_dict(json.loads(json.dumps(value.to_dict(), ensure_ascii=False))) == value


@pytest.mark.parametrize("factory", [source_plan, report])
@pytest.mark.parametrize("operation", ["missing", "extra", "old_version"])
def test_unknown_schema_missing_and_extra_top_level_fields_fail(factory, operation):
    data = factory().to_dict()
    if operation == "missing":
        data.pop("schema_version")
    elif operation == "extra":
        data["legacy"] = True
    else:
        data["schema_version"] = "subtitle.plan.v1"
    with pytest.raises(ValueError):
        type(factory()).from_dict(data)


@pytest.mark.parametrize("field,value", [("english_text", ""), ("chinese_text", ""), ("start_ms", True),
    ("base_end_ms", -1), ("final_end_ms", 0), ("word_ids", ()), ("initial_chunk_ids", ())])
def test_final_cue_rejects_invalid_content_and_timing(field, value):
    with pytest.raises(ValueError):
        replace(source_plan().cues[0], **{field: value})


@pytest.mark.parametrize("change", [lambda d: d["cues"][0].update(fragments=[]),
    lambda d: d["cues"][0].update(timing_adjustment={}), lambda d: d["cues"][0].update(english_lines=["line"]),
    lambda d: d.update(rules={}), lambda d: d.update(source_language="en")])
def test_old_proportional_fields_are_not_current_schema(change):
    data = source_plan().to_dict()
    change(data)
    with pytest.raises(ValueError):
        FinalBilingualDraftDTO.from_dict(data)


@pytest.mark.parametrize("change", [lambda d: d.update(status="failed"), lambda d: d["summary"].update(warning_count=1),
    lambda d: d["summary"].update(cue_count=True), lambda d: d.update(semantic_review="pass")])
def test_success_report_does_not_forge_counts_or_quality(change):
    data = report().to_dict()
    change(data)
    with pytest.raises(ValueError):
        SrtExportReportDTO.from_dict(data)


def test_report_cross_checks_authoritative_asset_and_cue_count():
    report().validate_against_draft(source_plan())
    with pytest.raises(ValueError):
        report().validate_against_draft(replace(source_plan(), asset_id="other:test:id"))


def test_readonly_identity_and_logical_text_have_no_visual_or_semantic_claims():
    data = source_plan().to_dict()
    assert "english_lines" not in data["cues"][0]
    assert "semantic_pass" not in data
    with pytest.raises(TypeError):
        source_plan().policy["version"] = "rewritten"
