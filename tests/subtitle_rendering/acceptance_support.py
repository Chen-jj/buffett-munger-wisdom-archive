"""Independent SR-06 local fixtures: public contracts, real files and ASS, fake media."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import socket
import subprocess

import pytest

from archive_core.application import build_asset_workspace
from archive_core.domain import AssetId
from archive_core.interfaces import (
    RenderFontIdentityDTO, RenderLineMetricsDTO, RenderPixelResultDTO, RenderProfileDTO,
    SourceAlignmentDTO, SrtProcessingManifestDTO, SrtProcessingReportDTO, SubtitlePlanDTO,
    SubtitleRenderManifestDTO, SubtitleRenderPlanDTO, SubtitleRenderReportDTO,
    TranslationManifestDTO, TranslationResultDTO,
)
from subtitle_rendering.application.workflow import SubtitleRenderingWorkflow
from subtitle_rendering.domain.layout import UNICODE_CLASSIFICATION_VERSION
from subtitle_rendering.infrastructure.ass import Pysubs2AssCodec
from subtitle_rendering.infrastructure.fonts import RegexGraphemeSegmenter
from subtitle_rendering.infrastructure.local import LocalRenderingArtifactStore
from subtitle_rendering.infrastructure.probe import validate_rendered_media
from subtitle_rendering.interfaces import SubtitleRenderingCommand, SubtitleRenderingCommandHandler
from tests.archive_core.test_rendering_contracts import media, tools
from tests.archive_core.test_subtitle_contracts import alignment, manifest, plan, report, translation


OUTPUT_NAMES = {
    "plan": "subtitle_rendering_plan.json", "ass": "bilingual.ass", "video": "video_中文字幕.mp4",
    "report": "subtitle_rendering_report.json", "manifest": "subtitle_rendering_manifest.json",
}


@pytest.fixture(autouse=True)
def offline_guard(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("SR-06 must not execute external processes, networking or system font loading")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr("subtitle_rendering.infrastructure.fonts.ExactFontAdapter.__init__", forbidden)


def encoded(value):
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def snapshot(root):
    """Include retained stage files and lexical symlinks, not only canonical outputs."""
    result = {}
    for path in sorted(Path(root).rglob("*")):
        if path.is_symlink():
            result[str(path.relative_to(root))] = ("link", str(path.readlink()), path.lstat().st_mtime_ns,
                                                    path.read_bytes() if path.exists() else None)
        elif path.is_file():
            result[str(path.relative_to(root))] = ("file", path.read_bytes(), path.stat().st_mtime_ns)
        elif path.is_dir():
            result[str(path.relative_to(root))] = ("directory",)
    return result


class RecordingStore(LocalRenderingArtifactStore):
    """Observe actual local operations; optional hooks only inject test failures."""

    def __init__(self):
        self.operations = []
        self.before = self.after = None

    def _before(self, operation, path):
        self.operations.append((operation, str(path)))
        if self.before:
            self.before(operation, str(path))

    def _after(self, operation, path):
        if self.after:
            self.after(operation, str(path))

    def read_bytes(self, path):
        self._before("read", path)
        value = super().read_bytes(path)
        self._after("read", path)
        return value

    def size(self, path):
        self._before("size", path)
        return super().size(path)

    def sha256(self, path):
        self._before("sha256", path)
        return super().sha256(path)

    def plan_staging(self, workspace):
        self._before("plan_staging", workspace)
        return super().plan_staging(workspace)

    def create_staging(self, path):
        self._before("mkdir", path)
        super().create_staging(path)
        self._after("mkdir", path)

    def stage_bytes(self, path, data):
        self._before("stage", path)
        super().stage_bytes(path, data)
        self._after("stage", path)

    def publish(self, staged, target, *, overwrite):
        self._before("publish", target)
        super().publish(staged, target, overwrite=overwrite)
        self._after("publish", target)

    @property
    def writes(self):
        return tuple(item for item in self.operations if item[0] in ("mkdir", "stage", "publish"))


class FakeFont:
    def __init__(self):
        self.calls, self.measurements = [], []
        self.identity = RenderFontIdentityDTO(
            RenderProfileDTO().font, 123456,
            ";".join(("independent-test-font.v1", RegexGraphemeSegmenter.version, UNICODE_CLASSIFICATION_VERSION)),
            "HiraginoSansGB-W3",
        )

    def __call__(self, spec, texts):
        self.calls.append((spec, tuple(texts)))
        assert spec == self.identity.spec
        return self

    def measure(self, text, font_size, outline_width, shadow):
        self.measurements.append((text, font_size, outline_width, shadow))
        return RenderLineMetricsDTO(len(text) * font_size / 2 + 2 * outline_width + shadow,
                                    font_size + 2 * outline_width + shadow)


class FakeProbe:
    def __init__(self):
        self.source = self.output = media()
        self.calls = []

    def version(self):
        return "ffprobe 9.0.1"

    def probe(self, path):
        self.calls.append(str(path))
        return self.source if Path(path).name == "video.mp4" else self.output


class FakeRenderer:
    def __init__(self):
        self.tools, self.calls, self.commands, self.on_render = tools(), [], [], None

    def tool_identity(self, *, pysubs2_version, ffprobe_version):
        return replace(self.tools, pysubs2_version=pysubs2_version, ffprobe_version=ffprobe_version)

    def build_command(self, **kwargs):
        command = ("test-encoder", "-i", kwargs["video_path"], "-vf", kwargs["ass_path"], "-n", kwargs["output_path"])
        self.commands.append(command)
        return command

    def render(self, command, *, cwd):
        self.calls.append((command, cwd))
        output, ass = Path(command[-1]), Path(cwd) / "bilingual.ass"
        assert not output.exists() and ass.is_file()
        assert ass.read_bytes().startswith(b"[Script Info]")
        with output.open("xb") as stream:
            stream.write(b"fake complete encoded media; probe is explicitly injected\n")
        if self.on_render:
            self.on_render()


class FakeClock:
    def __init__(self):
        self.calls = 0

    def now_utc(self):
        self.calls += 1
        return "2026-10-24T02:00:00Z"


class LocalCase:
    """Own local chain; fixture factories below only supply public DTO data."""

    asset_id = "cnbc:2000:sample"

    def __init__(self, root):
        self.root = Path(root)
        self.workspace = build_asset_workspace(AssetId("cnbc", "2000", "sample"), str(root))
        self.workspace.mkdir(parents=True)
        self.store, self.font, self.probe = RecordingStore(), FakeFont(), FakeProbe()
        self.codec, self.renderer, self.clock = Pysubs2AssCodec(), FakeRenderer(), FakeClock()
        self.segmenter, self.pixel_calls = RegexGraphemeSegmenter(), []
        self.outputs = {key: self.workspace / name for key, name in OUTPUT_NAMES.items()}
        self.prepare()
        self.input_paths = tuple(path for path in self.workspace.iterdir() if path.is_file())
        self.workflow = SubtitleRenderingWorkflow(
            artifacts=self.store, probe=self.probe, codec=self.codec, renderer=self.renderer,
            font_factory=self.font, segmenter=self.segmenter, pixel_preflight=self.pixels,
            media_validator=validate_rendered_media, clock=self.clock, profile=RenderProfileDTO(),
            output_root=str(root),
        )
        self.command = SubtitleRenderingCommand(self.asset_id, str(self.workspace / "srt_processing_manifest.json"))

    def handler(self):
        return SubtitleRenderingCommandHandler(self.workflow)

    def run(self, **changes):
        return self.handler().handle(replace(self.command, **changes))

    def put(self, name, value):
        (self.workspace / name).write_bytes(value if isinstance(value, bytes) else encoded(value))

    def read(self, name):
        return json.loads((self.workspace / name).read_bytes())

    def evidence(self, name):
        data = (self.workspace / name).read_bytes()
        return {"path": name, "size_bytes": len(data), "sha256": digest(data)}

    def resign_srt(self):
        data = self.read("srt_processing_manifest.json")
        for mapping in (data["inputs"], data["outputs"]):
            for key, item in tuple(mapping.items()):
                mapping[key] = self.evidence(item["path"])
        self.put("srt_processing_manifest.json", data)

    def resign_transcription(self, key):
        data = self.read("transcription_manifest.json")
        record = data["records"][key]
        raw = Path(record["path"]).read_bytes()
        record.update(size_bytes=len(raw), sha256=digest(raw))
        self.put("transcription_manifest.json", data)
        self.resign_srt()

    def resign_render_outputs(self):
        data = self.read(OUTPUT_NAMES["manifest"])
        for key, name in OUTPUT_NAMES.items():
            if key != "manifest":
                data["outputs"][key] = self.evidence(name)
        self.put(OUTPUT_NAMES["manifest"], data)

    def assert_explicit_chain(self):
        """Independently prove signatures and public cross-links before exercising workflow."""
        srt = SrtProcessingManifestDTO.from_dict(self.read("srt_processing_manifest.json"))
        source = SubtitlePlanDTO.from_dict(self.read("subtitle_plan.json"))
        aligned = SourceAlignmentDTO.from_dict(self.read("source_alignment.json"))
        translated = TranslationResultDTO.from_dict(self.read("translation_result.json"))
        translated_manifest = TranslationManifestDTO.from_dict(self.read("translation_manifest.json"))
        srt_report = SrtProcessingReportDTO.from_dict(self.read("srt_processing_report.json"))
        for evidence in (*srt.inputs.values(), *srt.outputs.values()):
            assert self.evidence(evidence.path) == evidence.to_dict()
        source.validate_against_inputs(aligned, translated)
        translated.validate_against_alignment(aligned)
        srt.validate_against_plan(source)
        assert srt_report.summary == srt.summary
        assert translated.source_alignment_sha256 == translated_manifest.input.sha256 == source.source_alignment_sha256
        for record in self.read("transcription_manifest.json")["records"].values():
            raw = Path(record["path"]).read_bytes()
            assert (len(raw), digest(raw)) == (record["size_bytes"], record["sha256"])

    def pixels(self, render_plan, source_plan, ass_path, renderer):
        self.pixel_calls.append(str(ass_path))
        self.codec.validate(Path(ass_path).read_bytes(), render_plan, source_plan)
        return tuple(RenderPixelResultDTO(cue.id, (cue.ass_start_ms + cue.ass_end_ms) // 2,
                                         cue.expected_bounds, len(cue.chinese_lines) + len(cue.english_lines), True, True)
                     for cue in render_plan.cues)

    def prepare(self):
        self.put("video.mp4", b"fake input video; no real tools in independent offline acceptance\n")
        self.put("audio.wav", b"fake input audio\n")
        self.put("source_alignment.json", alignment())
        source_sha = self.evidence("source_alignment.json")["sha256"]
        self.put("translation_result.json", replace(translation(), source_alignment_sha256=source_sha))
        self.put("translation_manifest.json", {
            "schema_version": "translation.manifest.v1", "asset_id": self.asset_id, "status": "succeeded", "completed_at": "2026-10-24T01:00:00Z",
            "input": {"path": "source_alignment.json", "sha256": source_sha},
            "translation": {"source_language": "en", "target_language": "zh-Hans", "prompt_version": "test.v1", "prompt_sha256": "a" * 64,
                            "glossary_path": None, "glossary_sha256": None, "provider": "offline-fake", "model": "offline-fake", "generation_parameters": {}},
            "output": self.evidence("translation_result.json"),
            "execution": {"request_count": 1, "checkpoint_reuse_count": 0, "attempt_count": 1, "input_tokens": None, "output_tokens": None},
        })
        provider, audio_sha, records = {"name": "offline-fake", "version": "1"}, self.evidence("audio.wav")["sha256"], {}
        for name in ("vad", "raw_asr", "aligned_asr", "transcript_fusion"):
            common = {"audio_duration_ms": 3000, "cache_key": digest(name.encode())}
            audio = {"audio_sha256": audio_sha, "provider": provider, "config": {}}
            if name == "vad":
                data = {**common, **audio, "schema_version": "transcription.vad.v1", "regions": [], "chunks": []}
            elif name == "raw_asr":
                data = {**common, **audio, "schema_version": "transcription.raw-asr.v1", "vad_cache_key": records["vad"]["cache_key"],
                        "language": "en", "task": "transcribe", "profile": "production", "segments": []}
            elif name == "aligned_asr":
                data = {**common, **audio, "schema_version": "transcription.aligned-asr.v1", "language": "en",
                        "raw_asr_sha256": records["raw_asr"]["sha256"], "words": []}
            else:
                data = {**common, "schema_version": "transcription.transcript-fusion.v1", "aligned_asr_sha256": records["aligned_asr"]["sha256"],
                        "chapters_sha256": None, "mode": "official", "normalization": {}, "matching": {}, "official_aligner": {},
                        "official_alignment_config": {}, "official_tokens": [], "ignored_content": [], "words": [], "excluded_official": [], "local_validations": []}
            self.put(name + ".json", data)
            provenance = {"provider": provider, "config": {}} if name != "transcript_fusion" else {
                "aligned_asr_sha256": records["aligned_asr"]["sha256"], "chapters_sha256": None}
            records[name] = {**self.evidence(name + ".json"), "path": str(self.workspace / (name + ".json")),
                             "cache_key": common["cache_key"], "status": "succeeded", "provenance": provenance}
        counts = {"aligned": len(alignment().words), "interpolated": 0, "error": 0, "warning": 0}
        self.put("transcription_report.json", {"schema_version": "transcription.report.v1", "asset_id": self.asset_id,
                 "status": "succeeded", "counts": counts, "findings": [], "qa": [{"name": "public-contract", "passed": True, "detail": "passed"}]})
        self.put("transcription.log", b"offline successful transcription log\n")
        for name, filename, provenance in (
            ("audio", "audio.wav", {"duration_ms": 3000, "video_sha256": self.evidence("video.mp4")["sha256"]}),
            ("source_alignment", "source_alignment.json", {"sentence_input_sha256": records["transcript_fusion"]["sha256"], "chapter_input_sha256": None}),
            ("transcription_report", "transcription_report.json", {"status": "succeeded"}),
            ("transcription_log", "transcription.log", {"status": "succeeded"}),
        ):
            records[name] = {**self.evidence(filename), "path": str(self.workspace / filename), "cache_key": digest(name.encode()),
                             "status": "succeeded", "provenance": provenance}
        stages = ["audio_vad_asr", "forced_alignment", "official_transcript_fusion", "sentence_boundaries"]
        self.put("transcription_manifest.json", {"schema_version": "transcription.audio-vad-asr-cache.v1",
            "asset": {"source": "cnbc", "group": "2000", "item": "sample"}, "records": records,
            "workflow": {"status": "succeeded", "stage_order": stages, "completed_stages": stages, "cache_hits": [],
                         "inputs": {"chapters_sha256": None, "download_manifest_path": None},
                         "qa_policy": {"version": "transcription-qa.v1", "max_interpolated_word_ratio": 0.1, "require_non_empty_alignment": True}, "summary": counts}})
        self.put("subtitle_plan.json", replace(plan(), source_alignment_sha256=source_sha,
                 translation_result_sha256=self.evidence("translation_result.json")["sha256"], video_sha256=self.evidence("video.mp4")["sha256"]))
        self.put("srt_processing_report.json", report())
        for filename in ("english.srt", "chinese.srt", "bilingual.srt"):
            self.put(filename, b"SRT evidence only; rendering must not parse authoritative text here\n")
        self.put("srt_processing_manifest.json", manifest())
        self.resign_srt()
        self.assert_explicit_chain()

    def parsed_rendering(self):
        return (SubtitleRenderPlanDTO.from_dict(self.read(OUTPUT_NAMES["plan"])),
                SubtitleRenderReportDTO.from_dict(self.read(OUTPUT_NAMES["report"])),
                SubtitleRenderManifestDTO.from_dict(self.read(OUTPUT_NAMES["manifest"])))
