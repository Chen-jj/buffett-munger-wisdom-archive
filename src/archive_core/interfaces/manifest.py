"""Explicit JSON DTOs for archive manifests and provenance."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from archive_core.domain import ArtifactRef, ArtifactType, AssetId


MANIFEST_SCHEMA_VERSION = "archive-core.manifest.v1"


@dataclass(frozen=True)
class ChecksumDTO:
    algorithm: str
    value: str

    def to_dict(self) -> dict[str, str]:
        return {"algorithm": self.algorithm, "value": self.value}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ChecksumDTO":
        return cls(algorithm=str(data["algorithm"]), value=str(data["value"]))


@dataclass(frozen=True)
class ArtifactRefDTO:
    asset_id: str
    artifact_type: str
    path: str
    checksum: ChecksumDTO | None = None

    @classmethod
    def from_domain(
        cls, ref: ArtifactRef, checksum: ChecksumDTO | None = None
    ) -> "ArtifactRefDTO":
        return cls(
            asset_id=ref.asset_id.value,
            artifact_type=ref.artifact_type.value,
            path=ref.relative_path,
            checksum=checksum,
        )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "asset_id": self.asset_id,
            "artifact_type": self.artifact_type,
            "path": self.path,
        }
        if self.checksum is not None:
            data["checksum"] = self.checksum.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ArtifactRefDTO":
        checksum_data = data.get("checksum")
        return cls(
            asset_id=str(data["asset_id"]),
            artifact_type=ArtifactType(str(data["artifact_type"])).value,
            path=str(data["path"]),
            checksum=(
                ChecksumDTO.from_dict(checksum_data)
                if isinstance(checksum_data, Mapping)
                else None
            ),
        )


@dataclass(frozen=True)
class ProvenanceDTO:
    stage: str
    tool: str
    input_artifacts: list[str] = field(default_factory=list)
    parameters: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "tool": self.tool,
            "input_artifacts": list(self.input_artifacts),
            "parameters": dict(self.parameters),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProvenanceDTO":
        return cls(
            stage=str(data["stage"]),
            tool=str(data["tool"]),
            input_artifacts=[str(item) for item in data.get("input_artifacts", [])],
            parameters={
                str(key): str(value)
                for key, value in dict(data.get("parameters", {})).items()
            },
        )


@dataclass(frozen=True)
class ManifestDTO:
    asset: dict[str, Any]
    artifacts: list[ArtifactRefDTO]
    provenance: list[ProvenanceDTO] = field(default_factory=list)
    schema_version: str = MANIFEST_SCHEMA_VERSION

    @classmethod
    def from_domain(
        cls,
        asset_id: AssetId,
        artifacts: list[ArtifactRef],
        provenance: list[ProvenanceDTO] | None = None,
    ) -> "ManifestDTO":
        return cls(
            asset={
                "id": asset_id.value,
                "source": asset_id.source,
                "group": asset_id.group,
                "item": asset_id.item,
            },
            artifacts=[ArtifactRefDTO.from_domain(ref) for ref in artifacts],
            provenance=list(provenance or []),
        )

    @property
    def asset_id(self) -> str:
        return str(self.asset["id"])

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "asset": dict(self.asset),
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "provenance": [item.to_dict() for item in self.provenance],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ManifestDTO":
        schema_version = str(data["schema_version"])
        if schema_version != MANIFEST_SCHEMA_VERSION:
            raise ValueError(f"unsupported manifest schema: {schema_version}")

        asset_data = dict(data["asset"])
        AssetId(
            source=str(asset_data["source"]),
            group=str(asset_data.get("group", "")),
            item=str(asset_data["item"]),
        )
        return cls(
            schema_version=schema_version,
            asset=asset_data,
            artifacts=[
                ArtifactRefDTO.from_dict(item) for item in data.get("artifacts", [])
            ],
            provenance=[
                ProvenanceDTO.from_dict(item) for item in data.get("provenance", [])
            ],
        )
