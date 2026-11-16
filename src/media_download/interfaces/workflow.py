"""Public production download and explicit media-derivation boundaries."""

from dataclasses import dataclass

from archive_core.domain import AssetId


@dataclass(frozen=True)
class DownloadCommand:
    asset_id: AssetId
    prepare_boundary: bool = False
    height: int | None = None

    def __post_init__(self):
        if not isinstance(self.asset_id, AssetId) or type(self.prepare_boundary) is not bool:
            raise ValueError("invalid download command")
        if self.height is not None and (type(self.height) is not int or self.height <= 0):
            raise ValueError("download height must be a positive integer")


@dataclass(frozen=True)
class MediaDerivationCommand:
    parent_asset_id: AssetId
    asset_id: AssetId
    start_ms: int
    end_ms: int
    chapter_numbers: tuple[int, ...]

    def __post_init__(self):
        if not isinstance(self.parent_asset_id, AssetId) or not isinstance(self.asset_id, AssetId) or self.parent_asset_id == self.asset_id:
            raise ValueError("derivation requires distinct parent and derived asset IDs")
        if self.asset_id.source != self.parent_asset_id.source:
            raise ValueError("derivation must preserve source identity")
        if any(isinstance(value, bool) or not isinstance(value, int) for value in (self.start_ms, self.end_ms)) or not 0 <= self.start_ms < self.end_ms:
            raise ValueError("derivation requires a positive explicit source range")
        if not self.chapter_numbers or any(isinstance(value, bool) or not isinstance(value, int) for value in self.chapter_numbers):
            raise ValueError("derivation requires explicit complete source chapters")
        if tuple(self.chapter_numbers) != tuple(sorted(set(self.chapter_numbers))):
            raise ValueError("derivation chapters must be unique and in order")
        object.__setattr__(self, "chapter_numbers", tuple(self.chapter_numbers))


def build_download_handler(*, output_root="output", service=None, process_runner=None):
    from media_download.infrastructure.composition import LocalDownloadHandler
    return LocalDownloadHandler(output_root=output_root, service=service, process_runner=process_runner)


def build_media_derivation_handler(*, output_root="output", process_runner=None):
    from media_download.infrastructure.derivation import LocalMediaDerivationHandler
    return LocalMediaDerivationHandler(output_root=output_root, process_runner=process_runner)
