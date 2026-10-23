from __future__ import annotations

import pytest

from srt_processing import SrtProcessingCommand, SrtProcessingCommandHandler, SrtProcessingOutcome
from srt_processing.application import SrtProcessingWorkflowError

from tests.srt_processing.workflow_fakes import WorkflowCase


def _command(case, **overrides):
    data = dict(asset_id=case.asset.value,
                transcription_manifest_path=case.paths["transcription_manifest"],
                translation_manifest_path=case.paths["translation_manifest"])
    data.update(overrides)
    return SrtProcessingCommand(**data)


def test_thin_handler_exposes_success_and_reuse_paths_and_counts() -> None:
    case = WorkflowCase()
    handler = SrtProcessingCommandHandler(case.workflow)
    first = handler.handle(_command(case))
    second = handler.handle(_command(case))
    assert isinstance(first, SrtProcessingOutcome)
    assert (first.status, second.status) == ("succeeded", "reused")
    assert first.plan_path == second.plan_path == case.output_paths["subtitle_plan"]
    assert first.manifest_path == second.manifest_path == case.output_paths["manifest"]
    assert first.cue_count == second.cue_count == 1
    assert first.warning_count == second.warning_count >= 2
    assert first.error_category is None and first.error_message is None


@pytest.mark.parametrize("category", ["input_invalid", "media_invalid", "artifact_conflict",
                                      "planning_failed", "projection_failed", "publication_failed",
                                      "srt_processing_failed"])
def test_handler_returns_only_safe_failure_messages(category) -> None:
    class FailingWorkflow:
        def execute(self, **arguments):
            error = SrtProcessingWorkflowError("secret upstream data /Users/private/file")
            error.category = category
            raise error

    case = WorkflowCase()
    result = SrtProcessingCommandHandler(FailingWorkflow()).handle(_command(case))
    assert result.status == "failed" and result.error_category == category
    assert "secret" not in result.error_message and "/Users" not in result.error_message
    assert result.plan_path is None and result.manifest_path is None
    assert result.cue_count == result.warning_count == 0


def test_unknown_internal_error_category_is_not_exposed() -> None:
    class FailingWorkflow:
        def execute(self, **arguments):
            error = SrtProcessingWorkflowError("private")
            error.category = "private-provider-detail"
            raise error

    case = WorkflowCase()
    result = SrtProcessingCommandHandler(FailingWorkflow()).handle(_command(case))
    assert result.error_category == "srt_processing_failed"


def test_actual_input_failure_is_a_failed_outcome_not_a_leaked_exception() -> None:
    case = WorkflowCase()
    result = SrtProcessingCommandHandler(case.workflow).handle(_command(case, asset_id="bad"))
    assert result.status == "failed" and result.error_category == "input_invalid"
    assert case.store.operations == [] and case.probe.calls == []


def test_handler_rejects_noncommand_objects() -> None:
    with pytest.raises(ValueError, match="SrtProcessingCommand"):
        SrtProcessingCommandHandler(WorkflowCase().workflow).handle({})
