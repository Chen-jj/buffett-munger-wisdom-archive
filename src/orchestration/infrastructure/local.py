"""Advisory asset locks and persistent run receipts; failed files are retained."""

from contextlib import contextmanager
from datetime import UTC, datetime
import fcntl
from pathlib import Path
from uuid import uuid4

from archive_core.application import build_asset_workspace, build_pipeline_run_path
from infrastructure.infrastructure.artifacts import read_json, write_json


class AssetBusyError(RuntimeError):
    pass


class LocalAssetLock:
    @contextmanager
    def acquire(self, command):
        from contextlib import ExitStack
        workspaces = sorted({build_asset_workspace(asset, Path(command.output_root).resolve())
                             for asset in (command.source_asset_id, command.asset_id)})
        with ExitStack() as stack:
            for workspace in workspaces:
                if workspace.is_symlink() or (workspace / ".pipeline.lock").is_symlink():
                    raise ValueError("pipeline workspace/lock cannot be a symlink")
                workspace.mkdir(parents=True, exist_ok=True)
                # Files remain; deterministic lock order also covers a shared downloaded parent.
                stream = stack.enter_context((workspace / ".pipeline.lock").open("a+"))
                try:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise AssetBusyError("asset_busy") from None
                stack.callback(fcntl.flock, stream.fileno(), fcntl.LOCK_UN)
            yield



class LocalRunStore:
    def create_run(self, command, plan):
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:12]
        path = build_pipeline_run_path(command.asset_id, Path(command.output_root).resolve(), run_id)
        receipt = {"schema_version": "pipeline.run.v1", "run_id": run_id, "parent_run_id": command.resume_run_id,
                   "asset_id": command.asset_id.value, "status": "running", "plan_sha256": plan.sha256,
                   "stages": [], "receipt_writes": 0, "input_identity": command.input_identity(),
                   "quality": {"technical": "pending", "semantic": "not_run", "visual": "not_run", "audio_sync": "not_run", "human_release": "not_run"}}
        write_json(path / "plan.json", plan.to_dict())
        write_json(path / "input_bindings.json", {"schema_version": "pipeline.input-bindings.v1", "asset_id": command.asset_id.value,
                                                   "evidence": {stage.stage: dict(stage.evidence) for stage in plan.stages}})
        receipt["receipt_writes"] = 2
        self.save_run(command, receipt)
        return receipt

    def save_run(self, command, receipt):
        path = build_pipeline_run_path(command.asset_id, Path(command.output_root).resolve(), receipt["run_id"])
        receipt["receipt_writes"] += 1
        write_json(path / "run.json", receipt)

    def read_run(self, command, run_id):
        path = build_pipeline_run_path(command.asset_id, Path(command.output_root).resolve(), run_id)
        receipt = read_json(path / "run.json")
        if (receipt.get("schema_version") != "pipeline.run.v1" or receipt.get("run_id") != run_id
                or receipt.get("status") not in {"running", "succeeded", "failed", "reused"}
                or not isinstance(receipt.get("input_identity"), dict) or not isinstance(receipt.get("stages"), list)):
            raise ValueError("invalid pipeline run receipt")
        return receipt
