from types import SimpleNamespace
import pytest
from srt_processing.interfaces.workflow import SrtProcessingCommand, SrtProcessingCommandHandler
from tests.srt_processing.workflow_fakes import WorkflowCase


def test_thin_handler_exposes_success_and_reuse_paths_and_counts():
    case = WorkflowCase()
    first = case.run()
    second = case.run()
    assert (first.status, second.status) == ("succeeded", "reused")
    assert first.cue_count == second.cue_count == 2
    assert first.plan_path == second.plan_path == case.path("final_bilingual_draft.json")
    assert first.writes == 5 and second.writes == 0


def test_actual_input_failure_is_a_failed_outcome_not_a_leaked_exception():
    case = WorkflowCase()
    assert case.run(bilingual_postprocessing_manifest_path="/unknown/path").error_category == "input_invalid"


def test_handler_rejects_noncommand_objects():
    with pytest.raises(ValueError):
        WorkflowCase().handler.handle(SimpleNamespace(asset_id="wrong"))
