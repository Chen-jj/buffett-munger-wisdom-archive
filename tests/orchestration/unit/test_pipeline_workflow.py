"""Pure orchestration authorization/recovery with every external boundary fake."""

from contextlib import contextmanager
from dataclasses import replace

import pytest

from archive_core.domain import AssetId
from orchestration.application.workflow import PipelineService
from orchestration.domain.models import MediaSelection, PipelineCommand, STAGES, StageInspection


def command(**changes):
    return PipelineCommand(AssetId("test", "group", "derived"), AssetId("test", "group", "source"),
                           "test:group", "/unused", MediaSelection(0, 1000, (1,)), **changes)


class Stage:
    def __init__(self):
        self.complete = False
        self.calls = 0
        self.fail = False
        self.fingerprint = "unchanged"

    def inspect(self, command):
        return StageInspection("verified", {"artifact": self.fingerprint}) if self.complete else StageInspection("absent")

    def run(self, command):
        self.calls += 1
        if self.fail:
            return {"status": "failed"}
        status = "reused" if self.complete else "succeeded"
        self.complete = True
        return {"status": status, "counts": {"content_calls": int(status == "succeeded"), "writes": int(status == "succeeded")}}


class Store:
    def __init__(self):
        self.writes = 0
        self.receipts = {}

    def create_run(self, command, plan):
        receipt = {"run_id": str(len(self.receipts)), "asset_id": command.asset_id.value, "status": "running", "stages": [], "input_identity": command.input_identity()}
        self.receipts[receipt["run_id"]] = receipt
        return receipt

    def save_run(self, command, receipt):
        self.writes += 1

    def read_run(self, command, run_id):
        return self.receipts[run_id]


class Lock:
    def __init__(self):
        self.calls = 0
        self.during_lock = lambda: None

    @contextmanager
    def acquire(self, command):
        self.calls += 1
        self.during_lock()
        yield


def service():
    stages = {name: Stage() for name in STAGES}
    store, lock = Store(), Lock()
    return PipelineService(stages=stages, store=store, lock=lock), stages, store, lock


def test_plan_and_verify_are_zero_write_zero_execution_and_no_lock():
    workflow, stages, store, lock = service()
    assert not workflow.plan_asset(command()).executable
    assert not workflow.verify_run(command()).executable
    assert not any(stage.calls for stage in stages.values())
    assert store.writes == lock.calls == 0


def test_missing_authorization_and_budget_block_before_lock_or_write():
    workflow, stages, store, lock = service()
    result = workflow.run_asset(command(allowed_actions=STAGES, max_stage_executions=1))
    assert result["status"] == "blocked"
    assert store.writes == lock.calls == 0
    assert not any(stage.calls for stage in stages.values())


def test_target_limits_plan_and_successful_execution():
    workflow, stages, store, _ = service()
    result = workflow.run_asset(command(target_stage="transcription", allowed_actions=STAGES, max_stage_executions=4))
    assert result["status"] == "succeeded"
    assert [item["stage"] for item in result["stages"]] == list(STAGES[:4])
    assert all(stage.calls == (index < 4) for index, stage in enumerate(stages.values()))


def test_failure_stops_successors_and_resume_reuses_successful_predecessors():
    workflow, stages, store, _ = service()
    stages["translation"].fail = True
    cmd = command(allowed_actions=STAGES, max_stage_executions=len(STAGES))
    first = workflow.run_asset(cmd)
    assert first["status"] == "failed"
    assert stages["source_chunking"].complete
    assert stages["bilingual_postprocessing"].calls == 0
    stages["translation"].fail = False
    resumed = workflow.resume_asset(replace(cmd, resume_run_id=first["run_id"]))
    assert resumed["status"] == "succeeded"
    assert all(item["status"] == "reused" for item in resumed["stages"][:5])
    verified_writes = store.writes
    assert workflow.verify_run(cmd).executable
    assert store.writes == verified_writes


def test_full_reuse_has_zero_content_calls_and_output_writes():
    workflow, _, _, _ = service()
    cmd = command(allowed_actions=STAGES, max_stage_executions=len(STAGES))
    workflow.run_asset(cmd)
    second = workflow.run_asset(replace(cmd, allowed_actions=(), max_stage_executions=0))
    assert second["status"] == "reused"
    assert all(item["counts"] == {"content_calls": 0, "writes": 0} for item in second["stages"])


def test_stale_plan_is_rejected_after_lock_revalidation():
    workflow, stages, store, lock = service()
    cmd = command(allowed_actions=STAGES, max_stage_executions=len(STAGES))
    for stage in stages.values():
        stage.complete = True
    plan = workflow.plan_asset(cmd)
    lock.during_lock = lambda: setattr(stages["acquisition"], "fingerprint", "changed")
    with pytest.raises(ValueError, match="stale"):
        workflow.run_asset(cmd, expected_plan_sha256=plan.sha256)
    assert store.writes == 0


@pytest.mark.parametrize("changes", ({"target_stage": "unknown"}, {"allowed_actions": ("unknown",)},
                                      {"max_stage_executions": True}, {"max_stage_executions": -1}))
def test_commands_reject_invalid_authorization(changes):
    with pytest.raises(ValueError):
        command(**changes)
