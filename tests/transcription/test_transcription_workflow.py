from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from archive_core.application import build_asset_workspace
from archive_core.domain import AssetId, ArtifactType, canonical_filename
from archive_core.interfaces import (
    StructuredTranscriptDTO,
    TranscriptChapterDTO,
    TranscriptParagraphDTO,
    SourceAlignmentDTO,
)
from media_download.domain import DownloadedArtifact
from transcription.application import (
    AudioVadAsrService,
    ForcedAlignmentService,
    SentenceBoundaryService,
    TranscriptionWorkflow,
    TranscriptionWorkflowConfig,
    TranscriptionWorkflowEventRecorder,
    TranscriptionWorkflowInput,
    WorkflowStatus,
)
from transcription.interfaces import TranscriptionCommand, TranscriptionCommandHandler
from transcription.domain import (
    AlignmentCandidate,
    AsrConfig,
    ForcedAlignmentConfig,
    InterpolationPolicy,
    OfficialAlignmentConfig,
    ProviderIdentity,
    RawAsrSegment,
    SentenceBoundaryPolicy,
    VadConfig,
    VadRegion,
)
from transcription.application import TranscriptFusionService
from transcription.infrastructure import (
    RuleBasedSentenceBoundaryDetector,
    WhisperXForcedAligner,
)


ASSET = AssetId("cnbc", "1994", "morning")


class MemoryStore:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.writes: list[tuple[str, bool]] = []
        self.fail_pair_after_canonical = False

    def exists(self, path: str) -> bool:
        return path in self.files

    def size(self, path: str) -> int:
        return len(self.files[path])

    def read_json(self, path: str) -> Mapping[str, Any]:
        return json.loads(self.files[path].decode())

    def write_json(self, path: str, data: Mapping[str, Any], *, overwrite: bool) -> str:
        if path in self.files and not overwrite:
            raise FileExistsError(path)
        self.files[path] = json.dumps(data, ensure_ascii=False, sort_keys=True).encode()
        self.writes.append((path, overwrite))
        return path

    def write_text(self, path: str, text: str, *, overwrite: bool) -> str:
        if path in self.files and not overwrite:
            raise FileExistsError(path)
        self.files[path] = text.encode()
        self.writes.append((path, overwrite))
        return path

    def publish_json_pair(self, canonical_path, canonical_data, manifest_path,
                          manifest_factory, *, overwrite):
        if Path(canonical_path).parent != Path(manifest_path).parent:
            raise ValueError("published pair must share directory")
        if canonical_path in self.files and not overwrite:
            raise FileExistsError(canonical_path)
        canonical_bytes = json.dumps(
            canonical_data, ensure_ascii=False, sort_keys=True
        ).encode()
        manifest_data = manifest_factory(
            len(canonical_bytes), hashlib.sha256(canonical_bytes).hexdigest()
        )
        old_files = dict(self.files)
        try:
            self.files[canonical_path] = canonical_bytes
            if self.fail_pair_after_canonical:
                self.fail_pair_after_canonical = False
                raise RuntimeError("injected final pair failure")
            self.write_json(manifest_path, manifest_data, overwrite=True)
        except Exception:
            self.files = old_files
            raise
        return len(canonical_bytes), hashlib.sha256(canonical_bytes).hexdigest()

    def sha256(self, path: str) -> str:
        return hashlib.sha256(self.files[path]).hexdigest()


class FakeExtractor:
    identity = ProviderIdentity("fake-ffmpeg", "1")

    def __init__(self, store: MemoryStore) -> None:
        self.store, self.calls = store, 0

    def extract(self, video_path, output_path, config, *, overwrite):
        self.calls += 1
        self.store.files[output_path] = b"audio bytes"
        return type("AudioResult", (), {"command": ("ffmpeg",)})()


class FakeVad:
    identity = ProviderIdentity("fake-vad", "1")

    def __init__(self) -> None:
        self.calls = 0

    def detect(self, audio_path, config):
        self.calls += 1
        return (VadRegion("vr1", 100, 1_000),)


class FakeAsr:
    identity = ProviderIdentity("fake-asr", "1")

    def __init__(self) -> None:
        self.calls = 0

    def transcribe(self, audio_path, vad, config):
        self.calls += 1
        return (RawAsrSegment("seg1", "Good morning. Welcome.", 100, 1_000),)


class FakeProbe:
    def duration_ms(self, media_path):
        return 2_000


class FakeAligner:
    identity = ProviderIdentity("fake-aligner", "1")

    def __init__(self) -> None:
        self.calls = 0
        self.failure: Exception | None = None

    def align(self, audio_path, raw_asr, tokens, config):
        self.calls += 1
        if self.failure:
            raise self.failure
        starts = (100, 350, 600)
        return tuple(
            AlignmentCandidate(
                raw_word_id=token.id,
                segment_id=token.segment_id,
                text=token.text,
                start_ms=starts[index],
                end_ms=starts[index] + 150,
                alignment_score=0.9,
            )
            for index, token in enumerate(tokens)
        )


class FakeOfficialAligner:
    identity = ProviderIdentity("fake-official-aligner", "1")

    def align_official(self, audio_path, tokens, left_anchor, right_anchor, config):
        raise AssertionError("exact transcript match must not call local aligner")


class CountingDetector(RuleBasedSentenceBoundaryDetector):
    def __init__(self) -> None:
        self.calls = 0

    def detect(self, words, policy):
        self.calls += 1
        return super().detect(words, policy)


def _official() -> StructuredTranscriptDTO:
    return StructuredTranscriptDTO(
        language="en",
        chapters=(TranscriptChapterDTO(
            number=1,
            title="Meeting",
            paragraphs=(TranscriptParagraphDTO(
                speaker_label="WARREN BUFFETT", text="Good morning. Welcome."
            ),),
        ),),
    )


def _two_chapter_official() -> StructuredTranscriptDTO:
    return StructuredTranscriptDTO(
        language="en",
        chapters=(
            TranscriptChapterDTO(
                number=6,
                title="Opening exchange",
                paragraphs=(
                    TranscriptParagraphDTO(
                        speaker_label="WARREN BUFFETT", text="Good morning"
                    ),
                ),
            ),
            TranscriptChapterDTO(
                number=7,
                title="Welcome",
                paragraphs=(
                    TranscriptParagraphDTO(
                        speaker_label="WARREN BUFFETT", text="Welcome."
                    ),
                ),
            ),
        ),
    )


def _make(
    tmp_path: Path,
    *,
    source: AssetId = ASSET,
    official: bool = True,
    transcript: StructuredTranscriptDTO | None = None,
):
    store = MemoryStore()
    workspace = build_asset_workspace(source, tmp_path / "output")
    video = str(workspace / canonical_filename(ArtifactType.SOURCE_VIDEO))
    store.files[video] = b"source video"
    manifest_path = str(workspace / "download_manifest.json")
    downloaded = DownloadedArtifact(
        asset_id=source,
        media_kind="youtube",
        media_ref_value="fixture",
        media_url="https://example.invalid/video",
        output_path=video,
        format_selector="best",
        size_bytes=len(store.files[video]),
        checksum_algorithm="sha256",
        checksum_value=store.sha256(video),
        downloader_name="yt-dlp",
        downloader_version="test",
        downloaded_at="2026-01-01T00:00:00Z",
        status="downloaded",
    )
    store.write_json(manifest_path, downloaded.to_manifest_dict(), overwrite=False)
    chapters_path = str(workspace / canonical_filename(ArtifactType.CHAPTERS))
    chapters_hash = None
    if official:
        store.write_json(
            chapters_path,
            (transcript or _official()).to_dict(),
            overwrite=False,
        )
        chapters_hash = store.sha256(chapters_path)

    extractor, vad, asr, aligner, detector = (
        FakeExtractor(store), FakeVad(), FakeAsr(), FakeAligner(), CountingDetector()
    )
    events = TranscriptionWorkflowEventRecorder(source.value)
    workflow = TranscriptionWorkflow(
        audio_vad_asr=AudioVadAsrService(
            audio_extractor=extractor, vad_detector=vad, asr_engine=asr,
            media_probe=FakeProbe(), checksum=store, artifacts=store,
            events=events, output_root=str(tmp_path / "output"),
        ),
        forced_alignment=ForcedAlignmentService(
            aligner=aligner, checksum=store, artifacts=store, events=events,
            output_root=str(tmp_path / "output"),
        ),
        transcript_fusion=TranscriptFusionService(
            checksum=store, artifacts=store, events=events,
            official_aligner=FakeOfficialAligner(),
            output_root=str(tmp_path / "output"),
        ),
        sentence_boundaries=SentenceBoundaryService(
            detector=detector, checksum=store, artifacts=store, events=events,
            output_root=str(tmp_path / "output"),
        ),
        checksum=store, artifacts=store, events=events,
        config=TranscriptionWorkflowConfig(
            vad=VadConfig(model="fake-vad", model_version="1"),
            asr=AsrConfig.development(model="tiny.en"),
            alignment=ForcedAlignmentConfig(
                model="fake-align", model_version="1", device="cpu",
                interpolation=InterpolationPolicy(version="interpolation.v1"),
            ),
            sentence_boundary=SentenceBoundaryPolicy(
                max_fallback_sentences=10, max_fallback_ratio=1.0
            ),
            official_alignment=OfficialAlignmentConfig(
                model="fake-align", model_version="1", device="cpu",
                min_alignment_score=0.5, min_anchor_alignment_score=0.5,
            ),
        ),
        output_root=str(tmp_path / "output"),
    )
    request = TranscriptionWorkflowInput(
        asset_id=source, download_manifest_path=manifest_path,
        chapters_sha256=chapters_hash,
    )
    return workflow, store, request, (extractor, vad, asr, aligner, detector)


def test_cnbc_and_youtube_workflow_order_and_public_outputs(tmp_path: Path) -> None:
    workflow, store, request, providers = _make(tmp_path)
    outcome = workflow.execute(request)
    assert outcome.status is WorkflowStatus.SUCCEEDED
    manifest = store.read_json(outcome.manifest_path)
    assert manifest["workflow"]["stage_order"] == [
        "audio_vad_asr", "forced_alignment", "official_transcript_fusion", "sentence_boundaries"
    ]
    assert manifest["workflow"]["completed_stages"] == manifest["workflow"]["stage_order"]
    assert set(("audio", "vad", "raw_asr", "aligned_asr", "transcript_fusion", "source_alignment")) <= set(manifest["records"])
    dto = SourceAlignmentDTO.from_dict(store.read_json(outcome.source_alignment_path))
    assert [word.text for word in dto.words] == ["Good", "morning.", "Welcome."]
    assert dto.words[0].official_token_ids
    assert [section.title for section in dto.sections] == ["Meeting"]

    yt, yt_store, yt_request, _ = _make(tmp_path / "yt", source=AssetId("youtube", "", "dQw4w9WgXcQ"), official=False)
    yt_outcome = yt.execute(yt_request)
    yt_dto = SourceAlignmentDTO.from_dict(yt_store.read_json(yt_outcome.source_alignment_path))
    assert all(not word.official_token_ids for word in yt_dto.words)
    assert yt_dto.sections == ()
    assert "transcript_fusion" not in yt_store.read_json(yt_outcome.manifest_path)["records"]


def test_workflow_persists_provider_restored_trailing_punctuation(
    tmp_path: Path,
) -> None:
    class Backend:
        def load_audio(self, path: str):
            return "audio"

        def load_align_model(self, **kwargs):
            return "model", {}

        def align(self, *args, **kwargs):
            return {
                "word_segments": [
                    {"word": "Good", "start": 0.1, "end": 0.25, "score": 0.91},
                    {
                        "word": "morning",
                        "start": 0.35,
                        "end": 0.5,
                        "score": 0.82,
                    },
                    {
                        "word": "Welcome",
                        "start": 0.6,
                        "end": 0.75,
                        "score": 0.73,
                    },
                ]
            }

    workflow, store, request, _ = _make(tmp_path, official=False)
    workflow.forced_alignment.aligner = WhisperXForcedAligner(
        whisperx_version="3.8.5",
        backend=Backend(),
        model_resolver=lambda model, version: f"/models/{model}/{version}",
    )

    outcome = workflow.execute(request)

    workspace = build_asset_workspace(request.asset_id, tmp_path / "output")
    aligned = store.read_json(str(workspace / "aligned_asr.json"))
    assert [word["text"] for word in aligned["words"]] == [
        "Good",
        "morning.",
        "Welcome.",
    ]
    assert [word["alignment_score"] for word in aligned["words"]] == [
        0.91,
        0.82,
        0.73,
    ]
    assert all(
        word["timing_source"] == "acoustic_alignment"
        for word in aligned["words"]
    )
    canonical = SourceAlignmentDTO.from_dict(
        store.read_json(outcome.source_alignment_path)
    )
    assert [word.text for word in canonical.words] == [
        "Good",
        "morning.",
        "Welcome.",
    ]
    assert outcome.report.counts["interpolated"] == 0


def test_two_chapter_workflow_publishes_sections_and_reuses_new_cache(
    tmp_path: Path,
) -> None:
    workflow, store, request, providers = _make(
        tmp_path, transcript=_two_chapter_official()
    )

    first = workflow.execute(request)
    alignment = SourceAlignmentDTO.from_dict(
        store.read_json(first.source_alignment_path)
    )

    assert [section.to_dict() for section in alignment.sections] == [
        {
            "id": "sec1",
            "title": "Opening exchange",
            "first_sentence_id": "s1",
            "last_sentence_id": "s1",
        },
        {
            "id": "sec2",
            "title": "Welcome",
            "first_sentence_id": "s2",
            "last_sentence_id": "s2",
        },
    ]
    assert (
        alignment.sentences[0].boundary_source.value
        == "document_section_change"
    )
    assert any(
        event.code.value == "section.published" for event in workflow.events.events
    )
    manifest = store.read_json(first.manifest_path)
    provenance = manifest["records"]["source_alignment"]["provenance"]
    assert provenance["section_policy"] == {"version": "document-sections.v1"}
    assert provenance["chapter_input_sha256"] == request.chapters_sha256

    second = workflow.execute(request)
    assert second.cache_hits == (
        "audio",
        "vad",
        "raw_asr",
        "aligned_asr",
        "transcript_fusion",
        "source_alignment",
    )
    assert [provider.calls for provider in providers] == [1, 1, 1, 1, 1]

    stale_manifest = store.read_json(second.manifest_path)
    stale_manifest["records"]["source_alignment"]["cache_key"] = (
        "pre-document-section-cache-key"
    )
    store.write_json(second.manifest_path, stale_manifest, overwrite=True)
    replaced = workflow.execute(replace(request, overwrite=True))
    assert set(replaced.cache_hits) == {
        "audio",
        "vad",
        "raw_asr",
        "aligned_asr",
        "transcript_fusion",
    }
    assert [provider.calls for provider in providers] == [1, 1, 1, 1, 2]


def test_verified_cache_hit_skips_providers_and_rejects_bad_checksum(tmp_path: Path) -> None:
    workflow, store, request, providers = _make(tmp_path)
    first = workflow.execute(request)
    second = workflow.execute(request)
    assert second.cache_hits == ("audio", "vad", "raw_asr", "aligned_asr", "transcript_fusion", "source_alignment")
    assert [provider.calls for provider in providers] == [1, 1, 1, 1, 1]
    record = store.read_json(first.manifest_path)["records"]["source_alignment"]
    store.files[record["path"]] = b"tampered canonical"
    with pytest.raises(Exception, match="explicit overwrite"):
        workflow.execute(request)
    workflow.execute(replace(request, overwrite=True))
    assert providers[-1].calls == 2


def test_bad_download_checksum_does_not_start_expensive_providers(tmp_path: Path) -> None:
    workflow, store, request, providers = _make(tmp_path, official=False)
    manifest = store.read_json(request.download_manifest_path)
    manifest["artifact"]["checksum"]["value"] = "bad"
    store.write_json(request.download_manifest_path, manifest, overwrite=True)
    with pytest.raises(Exception):
        workflow.execute(request)
    assert [provider.calls for provider in providers] == [0, 0, 0, 0, 0]


def test_stale_inputs_invalidate_only_their_downstream_stages(tmp_path: Path) -> None:
    workflow, store, request, providers = _make(tmp_path)
    workflow.execute(request)

    chapters_path = str(
        build_asset_workspace(request.asset_id, tmp_path / "output")
        / canonical_filename(ArtifactType.CHAPTERS)
    )
    transcript = _official()
    paragraph = replace(
        transcript.chapters[0].paragraphs[0], text="Good morning! Welcome."
    )
    chapter = replace(transcript.chapters[0], paragraphs=(paragraph,))
    changed = replace(transcript, chapters=(chapter,))
    store.write_json(chapters_path, changed.to_dict(), overwrite=True)
    transcript_result = workflow.execute(
        replace(request, chapters_sha256=store.sha256(chapters_path), overwrite=True)
    )
    assert set(transcript_result.cache_hits) == {"audio", "vad", "raw_asr", "aligned_asr"}
    assert [provider.calls for provider in providers] == [1, 1, 1, 1, 2]

    workflow.config = replace(
        workflow.config,
        sentence_boundary=replace(
            workflow.config.sentence_boundary, inferred_pause_ms=701
        ),
    )
    boundary_result = workflow.execute(
        replace(request, chapters_sha256=store.sha256(chapters_path), overwrite=True)
    )
    assert set(boundary_result.cache_hits) == {
        "audio", "vad", "raw_asr", "aligned_asr", "transcript_fusion"
    }
    assert [provider.calls for provider in providers] == [1, 1, 1, 1, 3]

    workflow.config = replace(
        workflow.config,
        alignment=replace(workflow.config.alignment, model_version="2"),
    )
    alignment_result = workflow.execute(
        replace(request, chapters_sha256=store.sha256(chapters_path), overwrite=True)
    )
    assert set(alignment_result.cache_hits) == {"audio", "vad", "raw_asr"}
    assert [provider.calls for provider in providers] == [1, 1, 1, 2, 4]

    workflow.config = replace(
        workflow.config,
        vad=replace(workflow.config.vad, model_version="2"),
    )
    vad_result = workflow.execute(
        replace(request, chapters_sha256=store.sha256(chapters_path), overwrite=True)
    )
    assert set(vad_result.cache_hits) == {"audio"}
    assert [provider.calls for provider in providers] == [1, 2, 2, 3, 5]


def test_command_summary_and_explicit_overwrite(tmp_path: Path) -> None:
    workflow, store, request, _ = _make(tmp_path)
    handler = TranscriptionCommandHandler(workflow)
    result = handler.execute(TranscriptionCommand(
        asset_id=request.asset_id,
        download_manifest_path=request.download_manifest_path,
        chapters_sha256=request.chapters_sha256,
    ))
    assert result.summary["aligned"] == 3
    assert not result.findings
    canonical = store.files[result.source_alignment_path]
    store.files[result.source_alignment_path] = b"stale canonical"
    with pytest.raises(Exception, match="explicit overwrite"):
        workflow.execute(request)
    overwrite = replace(request, overwrite=True)
    outcome = workflow.execute(overwrite)
    assert outcome.status is WorkflowStatus.SUCCEEDED
    assert store.files[result.source_alignment_path] != b"stale canonical"
    assert canonical != b"stale canonical"


def test_final_pair_failure_never_publishes_first_canonical(tmp_path: Path) -> None:
    workflow, store, request, _ = _make(tmp_path)
    store.fail_pair_after_canonical = True

    with pytest.raises(RuntimeError, match="injected final pair failure"):
        workflow.execute(request)

    paths = workflow._paths(request.asset_id)
    assert paths["source_alignment"] not in store.files
    manifest = store.read_json(paths["manifest"])
    assert manifest["workflow"]["status"] == "failed"
    assert "source_alignment" not in manifest["records"]
    assert store.read_json(paths["report"])["status"] == "failed"


def test_final_pair_failure_preserves_replaced_canonical(tmp_path: Path) -> None:
    workflow, store, request, _ = _make(tmp_path)
    successful = workflow.execute(request)
    canonical_before = store.files[successful.source_alignment_path]
    record_before = store.read_json(successful.manifest_path)["records"]["source_alignment"]
    workflow.config = replace(
        workflow.config,
        sentence_boundary=replace(
            workflow.config.sentence_boundary, inferred_pause_ms=701
        ),
    )
    store.fail_pair_after_canonical = True

    with pytest.raises(RuntimeError, match="injected final pair failure"):
        workflow.execute(replace(request, overwrite=True))

    assert store.files[successful.source_alignment_path] == canonical_before
    manifest = store.read_json(successful.manifest_path)
    assert manifest["workflow"]["status"] == "failed"
    assert manifest["records"]["source_alignment"] == record_before


def test_event_recorder_is_run_local_for_repeated_success(tmp_path: Path) -> None:
    workflow, store, request, _ = _make(tmp_path)
    first = workflow.execute(request)
    first_log = store.files[first.log_path]
    first_events = workflow.events.events

    second = workflow.execute(request)

    assert second.report.to_dict() == first.report.to_dict()
    assert len(workflow.events.events) < len(first_events)
    assert len(store.files[second.log_path].decode().splitlines()) == len(workflow.events.events)
    assert len(first_log.decode().splitlines()) == len(first_events)
    assert sum(event.action == "run_transcription" for event in workflow.events.events) == 1


def test_failure_records_report_and_manifest_without_publishing_canonical(tmp_path: Path) -> None:
    workflow, store, request, providers = _make(tmp_path)
    successful = workflow.execute(request)
    canonical_before = store.files[successful.source_alignment_path]
    workflow.config = replace(
        workflow.config,
        sentence_boundary=replace(
            workflow.config.sentence_boundary, inferred_pause_ms=701
        ),
    )
    providers[4].detect = lambda *args: (_ for _ in ()).throw(
        RuntimeError("boundary failed")
    )
    with pytest.raises(RuntimeError, match="boundary failed"):
        workflow.execute(replace(request, overwrite=True))
    workspace = build_asset_workspace(request.asset_id, tmp_path / "output")
    manifest = store.read_json(str(workspace / "transcription_manifest.json"))
    assert manifest["workflow"]["status"] == "failed"
    assert "failure_reason" in manifest["workflow"]
    report = store.read_json(str(workspace / "transcription_report.json"))
    assert report["status"] == "failed"
    assert any(json.loads(line)["severity"] == "ERROR" for line in store.files[str(workspace / "transcription.log")].decode().splitlines())
    assert store.files[successful.source_alignment_path] == canonical_before

    providers[4].detect = RuleBasedSentenceBoundaryDetector().detect
    rerun = workflow.execute(replace(request, overwrite=True))
    assert rerun.status is WorkflowStatus.SUCCEEDED
    assert rerun.report.status.value == "succeeded"
    assert rerun.report.failure_reason is None
    assert rerun.report.counts["error"] == 0
    assert all(finding.reason != "boundary failed" for finding in rerun.report.findings)
    assert all("boundary failed" not in event.reason for event in workflow.events.events)
    assert set(rerun.cache_hits) >= {"audio", "vad", "raw_asr"}
