from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from archive_core.application import build_asset_workspace

from acquisition.application import AcquireUseCase, CrawlerRegistry
from acquisition.domain import AcquisitionRequest
from acquisition.infrastructure import CnbcCrawler, LocalAcquisitionArtifactWriter


def _require_live_dependencies() -> None:
    if os.environ.get("RUN_REAL_NETWORK") != "1":
        pytest.skip("set RUN_REAL_NETWORK=1 to hit live CNBC pages")
    for package in ("requests", "bs4"):
        pytest.importorskip(package)


@pytest.mark.live
def test_crawl_year_1994_generates_normalized_artifacts(tmp_path: Path) -> None:
    _require_live_dependencies()
    crawler = CnbcCrawler(delay_seconds=0)
    writer = LocalAcquisitionArtifactWriter(root=tmp_path / "output", overwrite=True)
    registry = CrawlerRegistry([crawler])

    results = AcquireUseCase(registry=registry, writer=writer).execute(
        AcquisitionRequest("cnbc:1994")
    )

    sessions = {item.asset_id.item: item for item in results}
    assert "morning" in sessions
    assert "afternoon" in sessions
    assert "highlight" not in sessions
    assert sessions["morning"].transcript is not None
    assert len(sessions["morning"].transcript.chapters) > 0
    assert sessions["morning"].transcript.length > 10000

    morning_dir = build_asset_workspace(sessions["morning"].asset_id, tmp_path / "output")
    morning_meta_path = morning_dir / "meta.json"
    morning_chapters_path = morning_dir / "chapters.json"
    morning_transcript_path = morning_dir / "transcript.txt"
    morning_media_ref_path = morning_dir / "media_ref.json"
    assert morning_meta_path.exists()
    assert morning_chapters_path.exists()
    assert morning_transcript_path.exists()
    assert morning_media_ref_path.exists()

    morning_meta = json.loads(morning_meta_path.read_text(encoding="utf-8"))
    chapters = json.loads(morning_chapters_path.read_text(encoding="utf-8"))
    transcript = morning_transcript_path.read_text(encoding="utf-8")

    assert morning_meta["schema_version"] == "acquisition.source-metadata.v1"
    assert morning_meta["provenance"]["crawler"] == "cnbc"
    assert morning_meta["provenance"]["transcript_available"] is True
    assert len(chapters) > 0
    assert "=== Chapter" in transcript
