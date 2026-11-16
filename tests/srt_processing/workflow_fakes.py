"""Isolated final-draft export fakes; no external libraries or filesystem."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path

from srt_processing.application.ports import SrtCue
from srt_processing.application.workflow import SrtProcessingWorkflow
from srt_processing.interfaces.workflow import SrtProcessingCommand, SrtProcessingCommandHandler
from tests.support.current_bilingual import alignment, populate_current_chain


class MemoryStore:
    def __init__(self):
        self.files, self.operations = {}, []
        self.fail = None

    def exists(self, path):
        return path in self.files

    def read_bytes(self, path):
        self.operation("read", path)
        return self.files[path]

    def size(self, path):
        return len(self.files[path])

    def sha256(self, path):
        return hashlib.sha256(self.files[path]).hexdigest()

    def operation(self, action, path):
        self.operations.append((action, path))
        if self.fail and self.fail(action, path):
            raise OSError("injected storage fault")

    def stage_bytes(self, path, data):
        self.operation("stage", path)
        staged = path + ".stage"
        self.files[staged] = data
        return staged

    def publish(self, staged, path, *, overwrite):
        self.operation("publish", path)
        if not overwrite and path in self.files:
            raise FileExistsError(path)
        self.files[path] = self.files.pop(staged)


class Codec:
    identity = {"engine": "fake", "serialization": "fake.v1"}

    def __init__(self):
        self.calls = []
        self.mutate = lambda value: value

    def encode(self, draft, language):
        self.calls.append(language)
        def row(cue):
            return [int(cue.id[1:]), cue.start_ms, cue.end_ms, cue.english_text if language == "english" else cue.chinese_text
                    if language == "chinese" else cue.chinese_text + "\n" + cue.english_text]
        return json.dumps(self.mutate([row(cue) for cue in draft.cues]), ensure_ascii=False).encode()

    def decode(self, payload):
        return tuple(SrtCue(*row) for row in json.loads(payload))


class Clock:
    calls = 0

    def now_utc(self):
        self.calls += 1
        return "2026-11-06T00:00:00Z"


class WorkflowCase:
    root = "/archive"
    workspace = "/archive/cnbc_2000_sample"
    asset_id = "cnbc:2000:sample"
    output_names = ("english.srt", "chinese.srt", "bilingual.srt", "srt_processing_report.json", "srt_processing_manifest.json")

    def __init__(self):
        self.store, self.codec, self.clock = MemoryStore(), Codec(), Clock()
        self.put("video.mp4", b"mock media")
        self.put("source_alignment.json", alignment().to_dict())
        source_path = self.path("source_alignment.json")
        self.put("transcription_manifest.json", {"schema_version": "transcription.audio-vad-asr-cache.v1",
            "asset": {"source": "cnbc", "group": "2000", "item": "sample"}, "workflow": {"status": "succeeded"},
            "records": {"source_alignment": {"status": "succeeded", "path": source_path, "size_bytes": self.store.size(source_path),
                           "sha256": self.store.sha256(source_path)}, "audio": {"provenance": {"video_sha256": self.store.sha256(self.path("video.mp4"))}}}})
        self.draft = populate_current_chain(self, export=False)
        self.command = SrtProcessingCommand(self.asset_id, self.path("bilingual_postprocessing_manifest.json"))
        self.workflow = SrtProcessingWorkflow(artifacts=self.store, codec=self.codec, clock=self.clock, output_root=self.root)
        self.handler = SrtProcessingCommandHandler(self.workflow)
        self.upstream = dict(self.store.files)
        self.store.operations.clear()

    def path(self, name):
        return str(Path(self.workspace) / name)

    def put(self, name, value):
        self.store.files[self.path(name)] = value if isinstance(value, bytes) else (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode()

    def read(self, name):
        return json.loads(self.store.files[self.path(name)])

    def run(self, **kwargs):
        return self.handler.handle(replace(self.command, **kwargs))

    def resign_output(self, key, name):
        manifest = self.read("srt_processing_manifest.json")
        path = self.path(name)
        manifest["outputs"][key] = {"path": path, "size_bytes": self.store.size(path), "sha256": self.store.sha256(path)}
        self.put("srt_processing_manifest.json", manifest)
