"""Public single-asset acquisition command and composition boundary."""

from dataclasses import dataclass

from archive_core.domain import AssetId


@dataclass(frozen=True)
class AcquisitionCommand:
    asset_id: AssetId
    locator: str

    def __post_init__(self):
        if not isinstance(self.asset_id, AssetId) or not isinstance(self.locator, str) or not self.locator.strip():
            raise ValueError("acquisition requires an asset and locator")


@dataclass(frozen=True)
class AcquisitionOutcome:
    status: str
    receipt_path: str
    network_calls: int
    writes: int


def build_acquisition_handler(*, output_root="output", registry=None):
    from acquisition.infrastructure.composition import LocalAcquisitionHandler

    return LocalAcquisitionHandler(output_root=output_root, registry=registry)
