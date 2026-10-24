"""Small fully signed upstream chain and capability spies; no media tools or system font."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path

from archive_core.interfaces import RenderPixelResultDTO, RenderProfileDTO
from subtitle_rendering.application.workflow import SubtitleRenderingWorkflow
from subtitle_rendering.domain.layout import UNICODE_CLASSIFICATION_VERSION
from subtitle_rendering.interfaces import SubtitleRenderingCommand, SubtitleRenderingCommandHandler
from tests.archive_core.test_rendering_contracts import font_identity, media, tools
from tests.archive_core.test_subtitle_contracts import alignment, manifest, plan, report, translation
from tests.subtitle_rendering.test_layout import Measurer, Segments


def encoded(data):
    return (json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


class Store:
    def __init__(self):
        self.files, self.directories, self.operations = {}, set(), []
        self.failure, self.serial = None, 0

    def _op(self, operation, path):
        self.operations.append((operation, path))
        if self.failure and self.failure(operation, path):
            raise OSError("private path /secret; simulated store failure")

    def exists(self, path):
        return path in self.files or path in self.directories

    def read_bytes(self, path):
        self._op("read", path)
        return self.files[path]

    def size(self, path):
        self._op("size", path)
        return len(self.files[path])

    def sha256(self, path):
        self._op("sha256", path)
        return sha(self.files[path])

    def plan_staging(self, workspace):
        self.serial += 1
        return str(Path(workspace) / (".subtitle-rendering." + f"{self.serial:032x}"))

    def create_staging(self, path):
        self._op("mkdir", path)
        if path in self.directories:
            raise FileExistsError(path)
        self.directories.add(path)

    def stage_bytes(self, path, data):
        self._op("stage", path)
        if self.exists(path):
            raise FileExistsError(path)
        self.files[path] = data

    def publish(self, staged, target, *, overwrite):
        self._op("publish", target)
        if self.exists(target) and not overwrite:
            raise FileExistsError(target)
        self.files[target] = self.files.pop(staged)

    @property
    def writes(self):
        return [op for op in self.operations if op[0] in ("mkdir", "stage", "publish")]


class Probe:
    def __init__(self):
        self.calls = []
        self.source = self.output = media()

    def version(self):
        return "ffprobe 9.0.1"

    def probe(self, path):
        self.calls.append(path)
        return self.source if Path(path).name == "video.mp4" else self.output


class Fonts:
    def __init__(self):
        self.calls = []
        self.identity = replace(font_identity(), measurement_adapter_version="fake-font.v1;" + Segments.version + ";" + UNICODE_CLASSIFICATION_VERSION)
        self.measurer = Measurer()

    def __call__(self, spec, texts):
        self.calls.append((spec, tuple(texts)))
        assert spec == self.identity.spec
        return self

    def measure(self, *args):
        return self.measurer.measure(*args)


class Codec:
    library_version = "fake-ass.v1"

    def __init__(self):
        self.calls = []

    def encode(self, plan, source):
        self.calls.append("encode")
        return encoded({"plan": plan.to_dict(), "source": source.to_dict()})

    def validate(self, data, plan, source):
        self.calls.append("validate")
        assert data == encoded({"plan": plan.to_dict(), "source": source.to_dict()})


class Renderer:
    def __init__(self, store):
        self.store, self.calls, self.tools, self.on_render = store, [], tools(), None

    def tool_identity(self, **kwargs):
        return self.tools

    def build_command(self, **kwargs):
        return ("fake-ffmpeg", "-i", kwargs["video_path"], "-vf", kwargs["ass_path"], "-n", kwargs["output_path"])

    def render(self, command, *, cwd):
        self.calls.append((command, cwd))
        assert not self.store.exists(command[-1])
        assert self.store.exists(str(Path(cwd) / "bilingual.ass"))
        self.store.files[command[-1]] = b"encoded complete video"
        if self.on_render:
            self.on_render()


class Clock:
    def __init__(self):
        self.calls = 0

    def now_utc(self):
        self.calls += 1
        return "2026-10-24T01:02:03Z"


class WorkflowCase:
    root = "/archive"
    workspace = "/archive/cnbc_2000_sample"
    asset_id = "cnbc:2000:sample"

    def __init__(self, *, chapters=False, download=False):
        self.store, self.probe, self.fonts, self.codec, self.clock = Store(), Probe(), Fonts(), Codec(), Clock()
        self.renderer, self.segmenter, self.pixel_calls = Renderer(self.store), Segments(), []
        self.prepare(chapters=chapters, download=download)
        self.workflow = SubtitleRenderingWorkflow(artifacts=self.store, probe=self.probe, codec=self.codec,
            renderer=self.renderer, font_factory=self.fonts, segmenter=self.segmenter, pixel_preflight=self.pixels,
            media_validator=self.validate_media, clock=self.clock, profile=RenderProfileDTO(), output_root=self.root)
        self.handler = SubtitleRenderingCommandHandler(self.workflow)
        self.output_paths = {key: str(Path(self.workspace) / filename) for key, filename in {
            "plan": "subtitle_rendering_plan.json", "ass": "bilingual.ass", "video": "video_中文字幕.mp4",
            "report": "subtitle_rendering_report.json", "manifest": "subtitle_rendering_manifest.json"}.items()}

    def path(self, name):
        return str(Path(self.workspace) / name)

    def put(self, name, data):
        self.store.files[self.path(name)] = data if isinstance(data, bytes) else encoded(data)

    def read(self, name):
        return json.loads(self.store.files[self.path(name)])

    def evidence(self, name):
        data = self.store.files[self.path(name)]
        return {"path": name, "size_bytes": len(data), "sha256": sha(data)}

    def prepare(self, *, chapters, download):
        self.put("video.mp4", b"original complete video")
        self.put("audio.wav", b"canonical audio")
        self.put("source_alignment.json", alignment().to_dict())
        alignment_sha = self.evidence("source_alignment.json")["sha256"]
        translated = replace(translation(), source_alignment_sha256=alignment_sha)
        self.put("translation_result.json", translated.to_dict())
        self.put("translation_manifest.json", {
            "schema_version": "translation.manifest.v1", "asset_id": self.asset_id, "status": "succeeded", "completed_at": "2026-10-24T01:00:00Z",
            "input": {"path": "source_alignment.json", "sha256": alignment_sha},
            "translation": {"source_language": "en", "target_language": "zh-Hans", "prompt_version": "prompt.v1", "prompt_sha256": "a" * 64,
                            "glossary_path": None, "glossary_sha256": None, "provider": "fake", "model": "fake", "generation_parameters": {}},
            "output": self.evidence("translation_result.json"),
            "execution": {"request_count": 1, "checkpoint_reuse_count": 0, "attempt_count": 1, "input_tokens": None, "output_tokens": None},
        })
        chapter_sha = None
        if chapters:
            from archive_core.interfaces import StructuredTranscriptDTO
            self.put("chapters.json", StructuredTranscriptDTO("en", ()).to_dict())
            chapter_sha = self.evidence("chapters.json")["sha256"]
        audio_sha = self.evidence("audio.wav")["sha256"]
        records = {}
        providers, config = {"name": "fake", "version": "1"}, {}
        for name in ("vad", "raw_asr", "aligned_asr", "transcript_fusion"):
            common = {"audio_duration_ms": 3000, "cache_key": sha(name.encode())}
            if name == "vad":
                payload = {**common, "schema_version": "transcription.vad.v1", "audio_sha256": audio_sha, "provider": providers, "config": config, "regions": [], "chunks": []}
            elif name == "raw_asr":
                payload = {**common, "schema_version": "transcription.raw-asr.v1", "audio_sha256": audio_sha, "vad_cache_key": records["vad"]["cache_key"],
                           "language": "en", "task": "transcribe", "profile": "production", "provider": providers, "config": config, "segments": []}
            elif name == "aligned_asr":
                payload = {**common, "schema_version": "transcription.aligned-asr.v1", "audio_sha256": audio_sha, "raw_asr_sha256": records["raw_asr"]["sha256"],
                           "language": "en", "provider": providers, "config": config, "words": []}
            else:
                payload = {**common, "schema_version": "transcription.transcript-fusion.v1", "aligned_asr_sha256": records["aligned_asr"]["sha256"],
                           "chapters_sha256": chapter_sha, "mode": "official", "normalization": {}, "matching": {}, "official_aligner": {},
                           "official_alignment_config": {}, "official_tokens": [], "ignored_content": [], "words": [], "excluded_official": [], "local_validations": []}
            self.put(name + ".json", payload)
            records[name] = {**self.evidence(name + ".json"), "path": self.path(name + ".json"), "cache_key": common["cache_key"], "status": "succeeded",
                             "provenance": {"provider": providers, "config": config} if name != "transcript_fusion" else {"aligned_asr_sha256": records["aligned_asr"]["sha256"], "chapters_sha256": chapter_sha}}
        counts = {"aligned": 3, "interpolated": 0, "error": 0, "warning": 0}
        self.put("transcription_report.json", {"schema_version": "transcription.report.v1", "asset_id": self.asset_id,
            "status": "succeeded", "counts": counts, "findings": [], "qa": [{"name": "public_contract", "passed": True, "detail": "passed"}]})
        self.put("transcription.log", b"successful transcription diagnostic log\n")
        for name, filename, provenance in (
            ("audio", "audio.wav", {"duration_ms": 3000, "video_sha256": self.evidence("video.mp4")["sha256"]}),
            ("source_alignment", "source_alignment.json", {"sentence_input_sha256": records["transcript_fusion"]["sha256"], "chapter_input_sha256": chapter_sha}),
            ("transcription_report", "transcription_report.json", {"status": "succeeded"}),
            ("transcription_log", "transcription.log", {"status": "succeeded"}),
        ):
            records[name] = {**self.evidence(filename), "path": self.path(filename), "cache_key": sha(name.encode()), "status": "succeeded", "provenance": provenance}
        stages = ["audio_vad_asr", "forced_alignment", "official_transcript_fusion", "sentence_boundaries"]
        download_path = None
        if download:
            download_path = "/original/cnbc_2000_sample/download_manifest.json"
            original_video = "/original/cnbc_2000_sample/video.mp4"
            self.store.files[original_video] = self.store.files[self.path("video.mp4")]
            self.store.files[download_path] = encoded({"schema_version": "media-download.manifest.1", "asset": {"source": "cnbc", "group": "2000", "item": "sample"},
                "media": {}, "artifact": {"path": original_video, "size_bytes": self.evidence("video.mp4")["size_bytes"], "checksum": {"algorithm": "sha256", "value": self.evidence("video.mp4")["sha256"]}}, "download": {"status": "downloaded"}})
        self.put("transcription_manifest.json", {"schema_version": "transcription.audio-vad-asr-cache.v1", "asset": {"source": "cnbc", "group": "2000", "item": "sample"},
            "records": records, "workflow": {"status": "succeeded", "stage_order": stages, "completed_stages": stages, "cache_hits": [],
            "inputs": {"chapters_sha256": chapter_sha, "download_manifest_path": download_path}, "qa_policy": {"version": "transcription-qa.v1", "require_non_empty_alignment": True, "max_interpolated_word_ratio": 0.1}, "summary": counts}})
        source = replace(plan(), source_alignment_sha256=alignment_sha, translation_result_sha256=self.evidence("translation_result.json")["sha256"], video_sha256=self.evidence("video.mp4")["sha256"])
        self.put("subtitle_plan.json", source.to_dict())
        self.put("srt_processing_report.json", report().to_dict())
        for name in ("english.srt", "chinese.srt", "bilingual.srt"):
            self.put(name, b"SRT bytes are evidence only; never authoritative rendering text\n")
        self.put("srt_processing_manifest.json", manifest().to_dict())
        self.resign_srt()

    def resign_srt(self):
        data = self.read("srt_processing_manifest.json")
        for items in (data["inputs"], data["outputs"]):
            for key, evidence in items.items():
                items[key] = self.evidence(evidence["path"])
        self.put("srt_processing_manifest.json", data)

    def resign_transcription(self, name):
        data = self.read("transcription_manifest.json")
        record = data["records"][name]
        raw = self.store.files[record["path"]]
        record.update(size_bytes=len(raw), sha256=sha(raw))
        self.put("transcription_manifest.json", data)
        self.resign_srt()

    def pixels(self, plan, source, ass_path, renderer):
        self.pixel_calls.append(ass_path)
        assert self.store.exists(ass_path)
        return tuple(RenderPixelResultDTO(cue.id, (cue.ass_start_ms + cue.ass_end_ms) // 2,
                                         cue.expected_bounds, len(cue.chinese_lines) + len(cue.english_lines), True, True) for cue in plan.cues)

    def validate_media(self, source, output, last):
        assert source == output and last * 1000 <= output.video.duration_us

    def run(self, **kwargs):
        return self.workflow.execute(asset_id=self.asset_id, srt_processing_manifest_path=self.path("srt_processing_manifest.json"), **kwargs)

    def outcome(self, **kwargs):
        return self.handler.handle(SubtitleRenderingCommand(self.asset_id, self.path("srt_processing_manifest.json"), **kwargs))
