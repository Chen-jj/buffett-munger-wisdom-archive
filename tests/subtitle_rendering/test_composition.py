"""Composition is strict and inert until command execution."""

from pathlib import Path

import pytest
import yaml

from subtitle_rendering.infrastructure.composition import build_subtitle_rendering_handler
from tests.subtitle_rendering.workflow_fakes import WorkflowCase


def test_default_composition_does_not_touch_fonts_media_or_external_processes(tmp_path, monkeypatch):
    import subtitle_rendering.infrastructure.composition as module
    def forbidden(*args, **kwargs):
        raise AssertionError("must not start a tool or read a font during construction")
    monkeypatch.setattr(module.ExactFontAdapter, "__init__", forbidden)
    monkeypatch.setattr(module.FfprobeMediaProbe, "version", forbidden)
    monkeypatch.setattr(module.FfprobeMediaProbe, "probe", forbidden)
    monkeypatch.setattr(module.FfmpegRenderer, "tool_identity", forbidden)
    handler = build_subtitle_rendering_handler(output_root=str(tmp_path))
    assert handler.workflow.profile.name == "bilingual-burnin.hiragino-640x360.v1"
    assert not tuple(tmp_path.iterdir())


def test_explicit_fake_composition_uses_same_production_workflow(tmp_path):
    case = WorkflowCase()
    handler = build_subtitle_rendering_handler(output_root=case.root, artifacts=case.store, probe=case.probe,
        codec=case.codec, renderer=case.renderer, font_factory=case.fonts, segmenter=case.segmenter,
        pixel_preflight=case.pixels, media_validator=case.validate_media, clock=case.clock)
    assert handler.workflow.execute(asset_id=case.asset_id, srt_processing_manifest_path=case.path("srt_processing_manifest.json")).status == "succeeded"


@pytest.mark.parametrize("change", [
    lambda c: c.pop("subtitle_rendering"),
    lambda c: c["subtitle_rendering"].update(unknown=True),
    lambda c: c["subtitle_rendering"].update(name="not-allowed"),
    lambda c: c["subtitle_rendering"]["encoder"].update(video_codec="h264_videotoolbox"),
    lambda c: c["subtitle_rendering"].pop("font"),
])
def test_configuration_has_no_legacy_or_partial_fallback(tmp_path, change):
    config = yaml.safe_load(Path("config.yaml").read_text())
    change(config)
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config))
    with pytest.raises(ValueError):
        build_subtitle_rendering_handler(config_path=path)
