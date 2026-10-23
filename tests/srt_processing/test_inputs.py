from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from archive_core.application import build_asset_workspace
from archive_core.domain import ArtifactType, AssetId, canonical_filename
from srt_processing.application.inputs import (
    SubtitleInputError,
    SubtitleMediaError,
    load_subtitle_inputs,
)
from srt_processing.application.ports import MediaProbeResult


class MemoryStore:
    def __init__(self) -> None:
        self.files = {}
        self.reads = []
        self.fingerprints = []

    def exists(self, path):
        return path in self.files

    def read_bytes(self, path):
        self.reads.append(path)
        return self.files[path]

    def size(self, path):
        self.fingerprints.append(("size", path))
        return len(self.files[path])

    def sha256(self, path):
        self.fingerprints.append(("sha256", path))
        return hashlib.sha256(self.files[path]).hexdigest()


class FakeProbe:
    def __init__(self, duration=1000, error=None) -> None:
        self.calls = []
        self.duration = duration
        self.error = error

    def probe(self, path):
        self.calls.append(path)
        if self.error is not None:
            raise self.error
        return MediaProbeResult(self.duration, 24, 1, "ffprobe version fake")


class InputCase:
    def __init__(self) -> None:
        self.asset = AssetId("cnbc", "2000", "morning")
        self.root = "/output"
        self.workspace = build_asset_workspace(self.asset, self.root)
        self.paths = {
            "transcription_manifest": str(self.workspace / canonical_filename(ArtifactType.TRANSCRIPTION_MANIFEST)),
            "source_alignment": str(self.workspace / canonical_filename(ArtifactType.SOURCE_ALIGNMENT)),
            "translation_manifest": str(self.workspace / canonical_filename(ArtifactType.TRANSLATION_MANIFEST)),
            "translation_result": str(self.workspace / canonical_filename(ArtifactType.TRANSLATION_RESULT)),
            "video": str(self.workspace / canonical_filename(ArtifactType.SOURCE_VIDEO)),
        }
        self.store = MemoryStore()
        self.probe = FakeProbe()
        self.store.files[self.paths["video"]] = b"canonical-video"
        self.write("source_alignment", {
            "schema_version": "transcription.source-alignment.v1", "language": "en",
            "audio_duration_ms": 1000,
            "words": [{
                "id": "w1", "text": "Hello.", "start_ms": 100, "end_ms": 500,
                "asr_word_ids": ["a1"], "official_token_ids": ["o1"], "match_type": "exact",
                "text_source": "official_transcript", "timing_source": "acoustic_alignment",
            }],
            "sentences": [{
                "id": "s1", "first_word_id": "w1", "last_word_id": "w1",
                "start_ms": 100, "end_ms": 500, "text": "Hello.", "speaker_label": None,
                "text_source": "official_transcript", "boundary_source": "official_punctuation",
                "boundary_status": "verified",
            }],
            "sections": [{"id": "sec1", "title": "Greeting", "first_sentence_id": "s1",
                          "last_sentence_id": "s1"}],
        })
        self.write("transcription_manifest", {
            "schema_version": "transcription.audio-vad-asr-cache.v1",
            "asset": {"source": "cnbc", "group": "2000", "item": "morning"},
            "workflow": {"status": "succeeded"},
            "records": {
                "source_alignment": self.record(self.paths["source_alignment"], b"pending"),
                "audio": self.record(str(self.workspace / "audio.wav"), b"audio", {
                    "video_sha256": hashlib.sha256(b"canonical-video").hexdigest(),
                }),
            },
        })
        self.write("translation_result", {
            "schema_version": "translation.result.v1", "source_language": "en",
            "target_language": "zh-Hans", "source_alignment_sha256": "a" * 64,
            "section_title_translations": [{"section_id": "sec1", "translated_title": "问候"}],
            "sentence_translations": [{"sentence_id": "s1", "translated_text": "你好。"}],
        })
        self.write("translation_manifest", {
            "schema_version": "translation.manifest.v1", "asset_id": self.asset.value,
            "status": "succeeded", "completed_at": "2026-10-21T00:00:00Z",
            "input": {"path": "source_alignment.json", "sha256": "a" * 64},
            "translation": {
                "source_language": "en", "target_language": "zh-Hans",
                "prompt_version": "fake", "prompt_sha256": "a" * 64,
                "glossary_path": None, "glossary_sha256": None,
                "provider": "fake", "model": "fake", "generation_parameters": {},
            },
            "output": {"path": "translation_result.json", "size_bytes": 1, "sha256": "a" * 64},
            "execution": {"request_count": 1, "checkpoint_reuse_count": 0, "attempt_count": 1,
                          "input_tokens": None, "output_tokens": None},
        })
        self.rebind_alignment()

    @staticmethod
    def record(path, raw, provenance=None):
        return {"path": path, "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                "cache_key": "key", "status": "succeeded", "provenance": provenance or {}}

    def read(self, name):
        return json.loads(self.store.files[self.paths[name]])

    def write(self, name, value):
        self.store.files[self.paths[name]] = json.dumps(value, ensure_ascii=False).encode("utf-8")

    def edit(self, name, path, value):
        data = self.read(name)
        target = data
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        self.write(name, data)

    def rebind_alignment(self):
        raw = self.store.files[self.paths["source_alignment"]]
        digest = hashlib.sha256(raw).hexdigest()
        self.edit("transcription_manifest", ("records", "source_alignment", "size_bytes"), len(raw))
        self.edit("transcription_manifest", ("records", "source_alignment", "sha256"), digest)
        self.edit("translation_result", ("source_alignment_sha256",), digest)
        self.edit("translation_manifest", ("input", "sha256"), digest)
        self.rebind_translation()

    def rebind_translation(self):
        raw = self.store.files[self.paths["translation_result"]]
        self.edit("translation_manifest", ("output", "size_bytes"), len(raw))
        self.edit("translation_manifest", ("output", "sha256"), hashlib.sha256(raw).hexdigest())

    def load(self, **overrides):
        arguments = dict(asset_id=self.asset.value,
                         transcription_manifest_path=self.paths["transcription_manifest"],
                         translation_manifest_path=self.paths["translation_manifest"],
                         artifacts=self.store, probe=self.probe, output_root=self.root)
        arguments.update(overrides)
        return load_subtitle_inputs(**arguments)


@pytest.fixture
def case():
    return InputCase()


def test_both_chains_are_bound_to_the_exact_parsed_bytes(case) -> None:
    inputs = case.load()
    assert inputs.asset == case.asset
    assert inputs.workspace == case.workspace
    assert inputs.alignment.words[0].id == "w1"
    assert inputs.translation.sentence_translations[0].translated_text == "你好。"
    assert inputs.media.usable_duration_ms == 1000
    assert inputs.media.gap_threshold_ms == 84
    assert inputs.probe.ffprobe_version == "ffprobe version fake"
    assert set(inputs.evidence) == set(case.paths)
    for key, evidence in inputs.evidence.items():
        assert evidence.path == Path(case.paths[key]).name
        assert evidence.size_bytes == len(case.store.files[case.paths[key]])
        assert evidence.sha256 == hashlib.sha256(case.store.files[case.paths[key]]).hexdigest()
    assert case.probe.calls == [case.paths["video"]]
    assert case.store.fingerprints == [("size", case.paths["video"]), ("sha256", case.paths["video"])]
    assert len(case.store.reads) == 4
    with pytest.raises(TypeError):
        inputs.evidence["video"] = None


@pytest.mark.parametrize("path,value", [
    (("schema_version",), "legacy"), (("legacy",), []),
    (("asset", "source"), "youtube"), (("asset", "extra"), 1),
    (("workflow", "status"), "failed"), (("workflow",), None),
    (("records",), []), (("records", "source_alignment"), None),
    (("records", "source_alignment", "status"), "failed"),
    (("records", "source_alignment", "path"), "/elsewhere/source_alignment.json"),
    (("records", "source_alignment", "size_bytes"), 1),
    (("records", "source_alignment", "size_bytes"), True),
    (("records", "source_alignment", "sha256"), "b" * 64),
    (("records", "source_alignment", "cache_key"), ""),
    (("records", "source_alignment", "provenance"), None),
    (("records", "source_alignment", "extra"), 1),
    (("records", "audio", "status"), "failed"),
    (("records", "audio", "path"), "/elsewhere/audio.wav"),
    (("records", "audio", "provenance", "video_sha256"), None),
    (("records", "audio", "provenance", "video_sha256"), "b" * 64),
])
def test_transcription_chain_fails_independently_before_probe(case, path, value) -> None:
    case.edit("transcription_manifest", path, value)
    with pytest.raises(SubtitleInputError) as caught:
        case.load()
    assert caught.value.category == "input_invalid"
    assert case.probe.calls == []


@pytest.mark.parametrize("path,value", [
    (("schema_version",), "legacy"), (("language",), "zh"), (("units",), []),
    (("words",), []), (("sentences",), []), (("sections",), None),
    (("words", 0, "legacy"), True), (("words", 0, "start_ms"), True),
    (("words", 0, "id"), "w2"), (("words", 0, "end_ms"), 1001),
    (("sentences", 0, "legacy"), True), (("sentences", 0, "text"), "Wrong."),
    (("sections", 0, "legacy"), True), (("sections", 0, "first_sentence_id"), "s2"),
])
def test_strict_alignment_rejects_old_fields_and_invalid_content(case, path, value) -> None:
    case.edit("source_alignment", path, value)
    case.rebind_alignment()
    with pytest.raises(SubtitleInputError):
        case.load()
    assert case.probe.calls == []


def test_alignment_requires_explicit_sections_field(case) -> None:
    data = case.read("source_alignment")
    data.pop("sections")
    case.write("source_alignment", data)
    case.rebind_alignment()
    with pytest.raises(SubtitleInputError):
        case.load()


@pytest.mark.parametrize("collection,field", [("words", "asr_word_ids"),
                                              ("sentences", "speaker_label"),
                                              ("sections", "title")])
def test_nested_alignment_fields_cannot_be_defaulted(case, collection, field) -> None:
    data = case.read("source_alignment")
    data[collection][0].pop(field)
    case.write("source_alignment", data)
    case.rebind_alignment()
    with pytest.raises(SubtitleInputError, match="fields are invalid"):
        case.load()


@pytest.mark.parametrize("path,value", [
    (("schema_version",), "legacy"), (("status",), "failed"),
    (("asset_id",), "cnbc:2000:afternoon"), (("input", "path"), "other.json"),
    (("input", "sha256"), "b" * 64), (("output", "path"), "other.json"),
    (("output", "size_bytes"), 1), (("output", "sha256"), "b" * 64),
    (("extra",), True), (("translation", "target_language"), "zh-Hant"),
])
def test_translation_manifest_fails_independently_before_probe(case, path, value) -> None:
    case.edit("translation_manifest", path, value)
    with pytest.raises(SubtitleInputError):
        case.load()
    assert case.probe.calls == []


@pytest.mark.parametrize("path,value", [
    (("schema_version",), "legacy"), (("source_language",), "fr"),
    (("target_language",), "zh-Hant"), (("source_alignment_sha256",), "b" * 64),
    (("sentence_translations",), []), (("sentence_translations", 0, "sentence_id"), "s2"),
    (("sentence_translations", 0, "translated_text"), " "),
    (("section_title_translations",), []),
    (("section_title_translations", 0, "translated_title"), None), (("units",), []),
])
def test_translation_result_fails_independently_before_probe(case, path, value) -> None:
    case.edit("translation_result", path, value)
    case.rebind_translation()
    with pytest.raises(SubtitleInputError):
        case.load()
    assert case.probe.calls == []


def test_empty_sections_are_accepted_without_guessing_grouping(case) -> None:
    case.edit("source_alignment", ("sections",), [])
    case.edit("translation_result", ("section_title_translations",), [])
    case.rebind_alignment()
    assert case.load().alignment.sections == ()


def test_empty_section_title_requires_null_translation(case) -> None:
    case.edit("source_alignment", ("sections", 0, "title"), "")
    case.rebind_alignment()
    with pytest.raises(SubtitleInputError, match="empty source section title"):
        case.load()
    case.edit("translation_result", ("section_title_translations", 0, "translated_title"), None)
    case.rebind_translation()
    assert case.load().translation.section_title_translations[0].translated_title is None


def test_empty_alignment_cannot_pass_by_matching_empty_translation(case) -> None:
    case.edit("source_alignment", ("words",), [])
    case.edit("source_alignment", ("sentences",), [])
    case.edit("source_alignment", ("sections",), [])
    case.edit("translation_result", ("sentence_translations",), [])
    case.edit("translation_result", ("section_title_translations",), [])
    case.rebind_alignment()
    with pytest.raises(SubtitleInputError, match="must contain words"):
        case.load()


@pytest.mark.parametrize("field,value", [
    ("asset_id", "invalid"), ("asset_id", None), ("asset_id", "cnbc:2000:../bad"),
    ("transcription_manifest_path", "/other/transcription_manifest.json"),
    ("translation_manifest_path", "/other/translation_manifest.json"),
])
def test_noncanonical_commands_fail_before_reads(case, field, value) -> None:
    with pytest.raises(SubtitleInputError):
        case.load(**{field: value})
    assert case.store.reads == []
    assert case.probe.calls == []


@pytest.mark.parametrize("name", ["transcription_manifest", "source_alignment", "translation_manifest", "translation_result"])
def test_damaged_json_is_not_an_upstream_success(case, name) -> None:
    case.store.files[case.paths[name]] = b"{not-json"
    with pytest.raises(SubtitleInputError):
        case.load()
    assert case.probe.calls == []


@pytest.mark.parametrize("name", ["transcription_manifest", "source_alignment", "translation_manifest", "translation_result", "video"])
def test_missing_input_fails_before_probe(case, name) -> None:
    case.store.files.pop(case.paths[name])
    with pytest.raises(SubtitleInputError):
        case.load()
    assert case.probe.calls == []


@pytest.mark.parametrize("name", ["transcription_manifest", "source_alignment", "translation_manifest", "translation_result"])
def test_json_array_is_not_an_input_object(case, name) -> None:
    case.write(name, [])
    with pytest.raises(SubtitleInputError, match="JSON object"):
        case.load()
    assert case.probe.calls == []


@pytest.mark.parametrize("name", ["source_alignment", "translation_result"])
def test_equal_size_tampering_still_fails_content_hash(case, name) -> None:
    raw = case.store.files[case.paths[name]]
    case.store.files[case.paths[name]] = raw.replace(b"en", b"fr", 1)
    assert len(case.store.files[case.paths[name]]) == len(raw)
    with pytest.raises(SubtitleInputError, match="checksum does not match"):
        case.load()
    assert case.probe.calls == []


def test_replacing_video_fails_before_probe(case) -> None:
    case.store.files[case.paths["video"]] = b"another-video"
    with pytest.raises(SubtitleInputError, match="video checksum"):
        case.load()
    assert case.probe.calls == []


@pytest.mark.parametrize("duration,expected", [(800, 800), (1500, 1000)])
def test_usable_end_is_earlier_of_audio_and_video(case, duration, expected) -> None:
    case.probe.duration = duration
    assert case.load().media.usable_duration_ms == expected


def test_word_past_video_end_fails_without_clipping(case) -> None:
    before = dict(case.store.files)
    case.probe.duration = 499
    with pytest.raises(SubtitleMediaError, match="source word exceeds") as caught:
        case.load()
    assert caught.value.category == "media_invalid"
    assert case.store.files == before


def test_probe_exception_is_a_media_failure(case) -> None:
    case.probe.error = RuntimeError("cannot inspect")
    with pytest.raises(SubtitleMediaError, match="cannot inspect"):
        case.load()


def test_probe_fraction_is_preserved_and_gap_rounded_up(case) -> None:
    case.probe.probe = lambda path: MediaProbeResult(1000, 60000, 2002, "ffprobe version fake")
    media = case.load().media
    assert (media.fps_numerator, media.fps_denominator, media.gap_threshold_ms) == (60000, 2002, 67)
