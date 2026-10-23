"""In-memory ports for workflow tests; no media tools or subtitle library."""

from __future__ import annotations

import json

from archive_core.interfaces import SubtitleCodecDTO, character_boundaries
from srt_processing.application import SrtCue, SrtProcessingWorkflow
from srt_processing.domain import plan_subtitles
from srt_processing.domain.rules import PROFILE, wrap_english_text

from tests.srt_processing.test_inputs import InputCase, MemoryStore


class RecordingStore(MemoryStore):
    def __init__(self, files) -> None:
        super().__init__()
        self.files = dict(files)
        self.operations = []
        self.stage_count = 0
        self.publish_count = 0
        self.fail_stage_at = None
        self.fail_publish_at = None
        self.corrupt_stage_at = None
        self.fail_failed_report = False
        self.staged_read_count = 0
        self.fail_staged_read_at = None

    def read_bytes(self, path):
        if ".staged." in path:
            self.staged_read_count += 1
            if self.staged_read_count == self.fail_staged_read_at:
                raise OSError("staged read failed /secret/path")
        return super().read_bytes(path)

    def stage_bytes(self, target_path, data):
        self.stage_count += 1
        self.operations.append(("stage", target_path))
        if self.stage_count == self.fail_stage_at:
            raise OSError("stage failed /secret/path")
        if self.fail_failed_report and target_path.endswith("srt_processing_report.json"):
            if json.loads(data)["status"] == "failed":
                raise OSError("failed report could not be written /secret/path")
        staged = f"{target_path}.staged.{self.stage_count}"
        self.files[staged] = data + b" " if self.stage_count == self.corrupt_stage_at else data
        return staged

    def publish(self, staged_path, target_path, *, overwrite):
        self.publish_count += 1
        self.operations.append(("publish", target_path))
        if self.publish_count == self.fail_publish_at:
            raise OSError("publish failed /secret/path")
        if target_path in self.files and not overwrite:
            raise FileExistsError(target_path)
        self.files[target_path] = self.files.pop(staged_path)


class FakeCodec:
    def __init__(self) -> None:
        self.identity = SubtitleCodecDTO(serialization_version="word-wrap-english-2x42.v2")
        self.encode_calls = []
        self.decode_calls = []
        self.failure = None
        self.bad_decode = None

    def encode(self, plan, language):
        self.encode_calls.append(language)
        if self.failure is not None:
            raise self.failure
        events = []
        for index, cue in enumerate(plan.cues, 1):
            english = wrap_english_text(cue.english_text)
            if language == "english":
                text = english
            elif language == "chinese":
                text = cue.chinese_text
            else:
                text = cue.chinese_text + "\n" + english
            events.append([index, cue.start_ms, cue.end_ms, text])
        return json.dumps(events, ensure_ascii=False).encode("utf-8")

    def decode(self, data):
        self.decode_calls.append(data)
        events = tuple(SrtCue(*fields) for fields in json.loads(data))
        return self.bad_decode(events) if self.bad_decode is not None else events


class FixedClock:
    def __init__(self):
        self.calls = 0

    def now_utc(self):
        self.calls += 1
        return "2026-10-21T12:00:00Z"


class FakeSegmenter:
    def __init__(self):
        self.identity = {key: PROFILE.parameters[key] for key in (
            "chinese_segmentation_engine", "chinese_dictionary_sha256", "chinese_segmentation_mode",
        )}
        self.calls = []

    def spans(self, text):
        self.calls.append(text)
        boundaries = character_boundaries(text)
        return tuple(zip(boundaries, boundaries[1:]))


class CountingPlanner:
    def __init__(self):
        self.calls = 0
        self.failure = None

    def __call__(self, *args, **kwargs):
        self.calls += 1
        if self.failure is not None:
            raise self.failure
        return plan_subtitles(*args, **kwargs)


class WorkflowCase(InputCase):
    def __init__(self):
        super().__init__()
        self.store = RecordingStore(self.store.files)
        self.codec = FakeCodec()
        self.clock = FixedClock()
        self.segmenter = FakeSegmenter()
        self.planner = CountingPlanner()
        self.workflow = SrtProcessingWorkflow(
            artifacts=self.store, probe=self.probe, codec=self.codec, clock=self.clock,
            segmenter=self.segmenter, output_root=self.root, planner=self.planner,
        )
        self.output_paths = {name: str(self.workspace / filename) for name, filename in {
            "subtitle_plan": "subtitle_plan.json", "english_srt": "english.srt",
            "chinese_srt": "chinese.srt", "bilingual_srt": "bilingual.srt",
            "report": "srt_processing_report.json", "manifest": "srt_processing_manifest.json",
        }.items()}

    def run(self, **overrides):
        arguments = dict(asset_id=self.asset.value,
                         transcription_manifest_path=self.paths["transcription_manifest"],
                         translation_manifest_path=self.paths["translation_manifest"],
                         overwrite=False)
        arguments.update(overrides)
        return self.workflow.execute(**arguments)

    def formal_outputs(self):
        return {key: self.store.files[path] for key, path in self.output_paths.items() if path in self.store.files}

    def read_output(self, name):
        return json.loads(self.store.files[self.output_paths[name]])

    def write_output(self, name, data):
        self.store.files[self.output_paths[name]] = json.dumps(data, ensure_ascii=False).encode("utf-8")
