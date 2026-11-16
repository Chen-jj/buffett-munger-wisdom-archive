"""Synchronous orchestration through stage/store/lock ports, with no business imports."""

from typing import Protocol

from orchestration.domain.models import PipelineCommand, PipelinePlan, STAGES, StageInspection, StagePlan


class StagePort(Protocol):
    def inspect(self, command: PipelineCommand) -> StageInspection: ...
    def run(self, command: PipelineCommand) -> dict: ...


class RunStore(Protocol):
    def create_run(self, command: PipelineCommand, plan: PipelinePlan) -> dict: ...
    def save_run(self, command: PipelineCommand, receipt: dict) -> None: ...
    def read_run(self, command: PipelineCommand, run_id: str) -> dict: ...


class AssetLock(Protocol):
    def acquire(self, command: PipelineCommand): ...


class PipelineService:
    def __init__(self, *, stages: dict[str, StagePort], store: RunStore, lock: AssetLock):
        if set(stages) != set(STAGES):
            raise ValueError("composition must explicitly provide every production stage")
        self.stages, self.store, self.lock = stages, store, lock

    def plan_asset(self, command: PipelineCommand) -> PipelinePlan:
        plans = []
        blocked = False
        execution_count = 0
        for name in STAGES[:STAGES.index(command.target_stage) + 1]:
            if name == "media_derivation" and command.selection is None:
                continue
            inspection = self.stages[name].inspect(command)
            if blocked:
                action, reason = "blocked", "upstream stage is blocked"
            elif inspection.status == "verified":
                action, reason = "verify_reuse", "current stage evidence verified"
            elif inspection.status == "conflict":
                action, reason = "blocked", inspection.reason
            elif name not in command.allowed_actions:
                action, reason = "blocked", "stage execution is not authorized"
            elif execution_count >= command.max_stage_executions:
                action, reason = "blocked", "stage execution budget exhausted"
            else:
                action, reason = "execute", "missing current stage evidence; authorized execution"
                execution_count += 1
            blocked = blocked or action == "blocked"
            plans.append(StagePlan(name, action, reason, inspection.evidence))
        return PipelinePlan(command, tuple(plans))

    def verify_run(self, command: PipelineCommand) -> PipelinePlan:
        # No run record is created, no lock file is touched and no stage is executed.
        from dataclasses import replace
        return self.plan_asset(replace(command, allowed_actions=(), max_stage_executions=0))

    def resume_asset(self, command: PipelineCommand, *, expected_plan_sha256=None):
        if command.resume_run_id is None:
            raise ValueError("resume requires a previous run ID")
        previous = self.store.read_run(command, command.resume_run_id)
        if previous.get("input_identity") != command.input_identity():
            raise ValueError("resume source, workspace or selection identity mismatch")
        return self.run_asset(command, expected_plan_sha256=expected_plan_sha256)

    def run_asset(self, command: PipelineCommand, *, expected_plan_sha256=None):
        initial = self.plan_asset(command)
        if not initial.executable:
            return {"schema_version": "pipeline.run.v1", "asset_id": command.asset_id.value,
                    "status": "blocked", "plan": initial.to_dict(), "stages": [], "receipt_writes": 0}
        with self.lock.acquire(command):
            plan = self.plan_asset(command)
            if expected_plan_sha256 is not None and plan.sha256 != expected_plan_sha256:
                raise ValueError("pipeline plan is stale; replan before execution")
            if not plan.executable:
                return {"schema_version": "pipeline.run.v1", "asset_id": command.asset_id.value,
                        "status": "blocked", "plan": plan.to_dict(), "stages": [], "receipt_writes": 0}
            receipt = self.store.create_run(command, plan)
            for stage in plan.stages:
                entry = {"stage": stage.stage, "action": stage.action, "status": "running"}
                receipt["stages"].append(entry)
                self.store.save_run(command, receipt)
                try:
                    current = self.stages[stage.stage].inspect(command)
                    if stage.action == "verify_reuse" and (current.status != "verified" or dict(current.evidence) != dict(stage.evidence)):
                        raise ValueError("stage inputs changed after planning")
                    outcome = self.stages[stage.stage].run(command)
                    if outcome.get("status") not in {"succeeded", "reused"}:
                        raise ValueError(f"stage failed: {outcome.get('error_category', outcome.get('status'))}")
                    verified = self.stages[stage.stage].inspect(command)
                    if verified.status != "verified":
                        raise ValueError("stage did not publish verifiable current evidence")
                    entry.update(outcome)
                    entry["evidence"] = dict(verified.evidence)
                except Exception as error:
                    entry.update(status="failed", error_category=type(error).__name__, error_message=str(error)[:1000])
                    receipt["status"] = "failed"
                    self.store.save_run(command, receipt)
                    return receipt
                self.store.save_run(command, receipt)
            receipt["status"] = "reused" if all(stage["status"] == "reused" for stage in receipt["stages"]) else "succeeded"
            receipt["final_bindings"] = {stage["stage"]: stage["evidence"] for stage in receipt["stages"]}
            self.store.save_run(command, receipt)
            return receipt
