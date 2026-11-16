from __future__ import annotations

import json
from pathlib import Path

import pytest

from archive_core.application import build_asset_workspace

from archive_core.domain import AssetId
from acquisition.interfaces import AcquisitionCommand, build_acquisition_handler
from tests.orchestration.integration.gates import enabled


@pytest.mark.live
def test_crawl_year_1994_generates_normalized_artifacts(tmp_path: Path) -> None:
    if not enabled("network"):
        pytest.skip("enable the explicit orchestration network scenario")
    output_root = tmp_path / "output"
    handler = build_acquisition_handler(output_root=output_root)
    morning = AssetId("cnbc", "1994", "morning")
    for asset in (morning, AssetId("cnbc", "1994", "afternoon")):
        assert handler.handle(AcquisitionCommand(asset, "cnbc:1994")).status == "succeeded"
    with pytest.raises(ValueError, match="discover"):
        handler.handle(AcquisitionCommand(AssetId("cnbc", "1994", "highlight"), "cnbc:1994"))
    morning_dir = build_asset_workspace(morning, output_root)
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
    assert chapters["schema_version"] == "acquisition.transcript.v2"
    assert len(chapters["chapters"]) > 0
    assert len(transcript) > 10000
    assert "=== Chapter" in transcript
