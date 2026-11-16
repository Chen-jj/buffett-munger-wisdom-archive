"""The current SRT export report contract; content authority lives in bilingual.py."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .bilingual import FinalBilingualDraftDTO, _json, _plain


@dataclass(frozen=True)
class SrtExportReportDTO:
    asset_id: str
    status: str
    findings: tuple[Mapping[str, Any], ...]
    summary: Mapping[str, int]
    semantic_review: str = "not_run"
    schema_version: str = "subtitle.export-report.v1"

    def __post_init__(self):
        if (self.schema_version != "subtitle.export-report.v1" or self.status != "succeeded"
                or self.semantic_review != "not_run" or not isinstance(self.asset_id, str) or not self.asset_id.strip()):
            raise ValueError("invalid current SRT export report identity/status")
        findings = []
        for item in self.findings:
            if (not isinstance(item, Mapping) or set(item) != {"code", "severity", "cue_id", "start_ms", "end_ms", "observed"}
                    or item["severity"] != "warning" or not isinstance(item["code"], str) or not item["code"]
                    or not isinstance(item["cue_id"], str) or not item["cue_id"].startswith("c")
                    or type(item["start_ms"]) is not int or type(item["end_ms"]) is not int
                    or not 0 <= item["start_ms"] < item["end_ms"] or not isinstance(item["observed"], Mapping)):
                raise ValueError("invalid SRT export warning")
            findings.append(_json(item))
        if (not isinstance(self.summary, Mapping) or set(self.summary) != {"cue_count", "warning_count"}
                or any(type(value) is not int or value < 0 for value in self.summary.values())
                or self.summary["warning_count"] != len(findings)):
            raise ValueError("invalid SRT export summary")
        object.__setattr__(self, "findings", tuple(findings))
        object.__setattr__(self, "summary", _json(self.summary))

    def validate_against_draft(self, draft: FinalBilingualDraftDTO):
        if self.asset_id != draft.asset_id or self.summary["cue_count"] != len(draft.cues):
            raise ValueError("SRT report does not match authoritative draft")
        cues = {cue.id: cue for cue in draft.cues}
        for finding in self.findings:
            cue = cues.get(finding["cue_id"])
            if cue is None or (finding["start_ms"], finding["end_ms"]) != (cue.start_ms, cue.end_ms):
                raise ValueError("SRT report warning location differs from draft")

    def to_dict(self):
        return {"schema_version": self.schema_version, "asset_id": self.asset_id, "status": self.status,
                "findings": _plain(self.findings), "summary": _plain(self.summary), "semantic_review": self.semantic_review}

    @classmethod
    def from_dict(cls, data):
        if (not isinstance(data, Mapping) or set(data) != {"schema_version", "asset_id", "status", "findings", "summary", "semantic_review"}
                or not isinstance(data["findings"], (tuple, list))):
            raise ValueError("SRT export report has missing or unknown fields")
        return cls(**data)
