"""Temporary canonical inputs for offline acceptance, never formal CNBC media."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from archive_core.application import build_asset_workspace
from archive_core.domain import ArtifactType, canonical_filename
from srt_processing.infrastructure import build_srt_processing_handler
from srt_processing.interfaces import SrtProcessingCommand

from tests.srt_processing.sample_runner import INPUT_TYPES, OUTPUT_TYPES
from tests.srt_processing.test_inputs import FakeProbe, InputCase
from tests.srt_processing.test_planner import inputs as planner_inputs
from tests.srt_processing.workflow_fakes import FakeSegmenter, FixedClock


def default_data():
    return planner_inputs(
        [("Investment,",) * 5, ("Yes.",), ("Indeed.",)],
        ["我们保留全部译文，字幕不代表语义对齐。", "是。", "确实。"],
        times=[(100, 1300), (1300, 2500), (2500, 3700), (3700, 4900),
               (4900, 6100), (6200, 6300), (6400, 6500)],
        speakers=(None, None, "BUFFETT"), section_sizes=(2, 1),
    )


class LocalCase:
    def __init__(self, root: Path, data=None):
        template = InputCase()
        alignment, translation, media = default_data() if data is None else data
        self.root = str(root / "output")
        self.asset = template.asset
        self.workspace = build_asset_workspace(self.asset, self.root)
        self.workspace.mkdir(parents=True)
        self.inputs = {key: self.workspace / canonical_filename(kind) for key, kind in INPUT_TYPES.items()}
        self.outputs = {key: self.workspace / canonical_filename(kind) for key, kind in OUTPUT_TYPES.items()}
        for name, path in self.inputs.items():
            path.write_bytes(template.store.files[template.paths[name]])
        self.write_input("source_alignment", alignment.to_dict())
        self.write_input("translation_result", translation.to_dict())
        transcription = self.read_input("transcription_manifest")
        transcription["records"]["source_alignment"]["path"] = str(self.inputs["source_alignment"])
        transcription["records"]["audio"]["path"] = str(self.workspace / canonical_filename(ArtifactType.SOURCE_AUDIO))
        self.write_input("transcription_manifest", transcription)
        self.rebind()
        # Non-input upstream assets are also protected by the sample runner.
        (self.workspace / "audio.wav").write_bytes(b"offline audio fixture")
        (self.workspace / "raw_asr.json").write_bytes(b'{"offline": true}\n')
        self.probe = FakeProbe(duration=media.video_duration_ms)
        self.clock = FixedClock()
        self.segmenter = FakeSegmenter()
        self.command = SrtProcessingCommand(self.asset.value, str(self.inputs["transcription_manifest"]),
                                            str(self.inputs["translation_manifest"]))

    def read_input(self, name):
        return json.loads(self.inputs[name].read_bytes())

    def write_input(self, name, value):
        self.inputs[name].write_bytes((json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"))

    def rebind(self):
        raw = self.inputs["source_alignment"].read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        transcription = self.read_input("transcription_manifest")
        transcription["records"]["source_alignment"].update(size_bytes=len(raw), sha256=digest)
        self.write_input("transcription_manifest", transcription)
        result = self.read_input("translation_result")
        result["source_alignment_sha256"] = digest
        self.write_input("translation_result", result)
        manifest = self.read_input("translation_manifest")
        manifest["input"]["sha256"] = digest
        translated = self.inputs["translation_result"].read_bytes()
        manifest["output"].update(size_bytes=len(translated), sha256=hashlib.sha256(translated).hexdigest())
        self.write_input("translation_manifest", manifest)

    def handler(self, **overrides):
        arguments = dict(output_root=self.root, probe=self.probe, clock=self.clock, segmenter=self.segmenter)
        arguments.update(overrides)
        return build_srt_processing_handler(**arguments)

    def upstream_bytes(self):
        output_names = {path.name for path in self.outputs.values()}
        return {path.name: path.read_bytes() for path in self.workspace.iterdir()
                if path.is_file() and path.name not in output_names and not path.name.startswith(".")}

    def output_bytes(self):
        return {key: path.read_bytes() for key, path in self.outputs.items() if path.is_file()}

    def resign_output(self, name):
        manifest = json.loads(self.outputs["manifest"].read_bytes())
        raw = self.outputs[name].read_bytes()
        manifest["outputs"][name].update(size_bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        self.outputs["manifest"].write_bytes(json.dumps(manifest, ensure_ascii=False).encode("utf-8"))
