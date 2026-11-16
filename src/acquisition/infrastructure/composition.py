"""Receipt-backed production acquisition assembly."""

from datetime import UTC, datetime
from pathlib import Path

from archive_core.application import build_asset_workspace
from archive_core.interfaces import StructuredTranscriptDTO
from archive_core.interfaces.bilingual import StageManifestDTO
from infrastructure.infrastructure.artifacts import evidence, read_json, verify_stage_manifest, write_json
from acquisition.application.registry import DefaultCrawlerRegistry
from acquisition.domain import AcquisitionRequest
from acquisition.interfaces.workflow import AcquisitionOutcome
from .artifacts import LocalAcquisitionArtifactWriter
from .cnbc import CnbcCrawler
from .generic import GenericCrawler
from .http import RequestsHttpClient
from .youtube import YoutubeCrawler


class LocalAcquisitionHandler:
    def __init__(self, *, output_root, registry=None):
        self.root = str(Path(output_root).resolve())
        self.registry = registry

    def verify(self, command):
        workspace = build_asset_workspace(command.asset_id, self.root)
        path = workspace / "acquisition_receipt.json"
        manifest = verify_stage_manifest(path, stage="acquisition", asset_id=command.asset_id.value, inputs={})
        if dict(manifest.identity) != {"locator": command.locator, "policy": "single-asset-acquisition.v1"}:
            raise ValueError("acquisition request changed")
        required = {"meta", "media_ref"}
        if set(manifest.outputs) not in (required, required | {"chapters", "transcript"}):
            raise ValueError("acquisition receipt outputs mismatch")
        filenames = {"meta": "meta.json", "media_ref": "media_ref.json", "chapters": "chapters.json", "transcript": "transcript.txt"}
        for name, item in manifest.outputs.items():
            if Path(item.path) != workspace / filenames[name]:
                raise ValueError("acquisition output path mismatch")
        meta = read_json(workspace / "meta.json")
        if meta["asset_id"] != {"source": command.asset_id.source, "group": command.asset_id.group, "item": command.asset_id.item}:
            raise ValueError("acquisition meta asset mismatch")
        if "chapters" in manifest.outputs:
            StructuredTranscriptDTO.from_dict(read_json(workspace / "chapters.json"))
        return manifest

    def handle(self, command):
        workspace = build_asset_workspace(command.asset_id, self.root)
        receipt = workspace / "acquisition_receipt.json"
        if receipt.exists():
            self.verify(command)
            return AcquisitionOutcome("reused", str(receipt), 0, 0)
        if any((workspace / name).exists() for name in ("meta.json", "media_ref.json", "chapters.json", "transcript.txt")):
            raise ValueError("acquisition artifact conflict: partial outputs without receipt")
        registry = self.registry
        http = None
        if registry is None:
            class ObservedHttp(RequestsHttpClient):
                calls = 0

                def get_text(self, url):
                    self.calls += 1
                    return super().get_text(url)

            http = ObservedHttp()
            registry = DefaultCrawlerRegistry()
            for crawler in (CnbcCrawler(http_client=http), YoutubeCrawler(http_client=http), GenericCrawler(http_client=http)):
                registry.register(crawler)
        req = AcquisitionRequest(command.locator)
        crawler = registry.select(req)
        matches = [target for target in crawler.discover(req) if target.asset_id == command.asset_id]
        if len(matches) != 1:
            raise ValueError("acquisition locator must discover requested asset exactly once")
        result = crawler.fetch(matches[0])
        if result.asset_id != command.asset_id:
            raise ValueError("crawler returned another asset")
        LocalAcquisitionArtifactWriter(self.root).save(result)
        filenames = {"meta": "meta.json", "media_ref": "media_ref.json"}
        if result.transcript is not None:
            filenames.update(chapters="chapters.json", transcript="transcript.txt")
        manifest = StageManifestDTO("acquisition", command.asset_id.value, {},
                                    {name: evidence(workspace / filename) for name, filename in filenames.items()},
                                    {"locator": command.locator, "policy": "single-asset-acquisition.v1"},
                                    datetime.now(UTC).isoformat(), {"network_calls": http.calls if http else 0, "writes": len(filenames) + 1})
        write_json(receipt, manifest.to_dict())
        self.verify(command)
        return AcquisitionOutcome("succeeded", str(receipt), http.calls if http else 0, len(filenames) + 1)
