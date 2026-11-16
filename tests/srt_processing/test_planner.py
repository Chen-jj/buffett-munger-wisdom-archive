"""The final-draft export boundary does not reconstruct or alter a proportional plan."""
from dataclasses import replace
import pytest
from srt_processing.application.workflow import export_report
from tests.support.current_bilingual import source_plan


@pytest.mark.parametrize("english,chinese", [("x"*81,"甲"),("Fine.","甲"*40),("x"*90,"甲"*40)])
def test_warning_metrics_never_replan_or_modify_final_draft(english,chinese):
    draft = source_plan()
    draft = replace(draft,cues=(replace(draft.cues[0],english_text=english,chinese_text=chinese),draft.cues[1]))
    original = draft.to_dict()
    report = export_report(draft)
    assert report["status"] == "succeeded" and report["summary"]["warning_count"] > 0
    assert draft.to_dict() == original


@pytest.mark.parametrize("length", [83, 84, 85])
def test_export_english_capacity_reports_whole_cue_codepoints(length):
    draft = source_plan()
    english = "x" * (length - 3) + ", y"
    draft = replace(draft, cues=(replace(draft.cues[0], english_text=english), draft.cues[1]))
    findings = [x for x in export_report(draft)["findings"] if x["code"] == "english.capacity"]
    assert [x["observed"] for x in findings] == ([{"characters": 85, "limit": 84}] if length > 84 else [])


def test_actual_overlap_is_not_a_warning():
    draft = source_plan()
    with pytest.raises(ValueError,match="overlap"):
        replace(draft,cues=(replace(draft.cues[0],final_end_ms=1310),draft.cues[1]))
