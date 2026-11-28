from __future__ import annotations

from collections import deque
import hashlib
import json
from pathlib import Path

import pytest

from archive_core.application import build_asset_workspace
from archive_core.domain import ArtifactType, AssetId, canonical_filename
from archive_core.interfaces import (
    BoundarySource,
    BoundaryStatus,
    MatchType,
    SourceAlignmentDTO,
    SourceSectionDTO,
    SourceSentenceDTO,
    TextSource,
    TimedWordDTO,
    TimingSource,
)
from translation.application import (
    TranslationArtifactConflict,
    TranslationCheckpointError,
    TranslationProviderFailure,
    TranslationPublicationError,
    TranslationWorkflow,
)
from translation.domain import (
    PermanentProviderError,
    ProviderIdentity,
    ProviderResponse,
    ProviderStatus,
    ProviderUsage,
    TransientProviderError,
)
from translation.infrastructure import (
    LocalCheckpointStore,
    LocalChecksumService,
    LocalGlossaryLoader,
    LocalPromptLoader,
    LocalTranslationArtifactStore,
)
from translation.interfaces import TranslationCommand, TranslationCommandHandler


ASSET = AssetId("cnbc", "2000", "morning")


def _word(position: int, text: str) -> TimedWordDTO:
    return TimedWordDTO(
        id=f"w{position}", text=text, start_ms=position * 100,
        end_ms=position * 100 + 50, asr_word_ids=(f"a{position}",),
        official_token_ids=(f"o{position}",), match_type=MatchType.EXACT,
        text_source=TextSource.OFFICIAL_TRANSCRIPT,
        timing_source=TimingSource.ACOUSTIC_ALIGNMENT,
    )


def _sentence(position: int, text: str) -> SourceSentenceDTO:
    return SourceSentenceDTO(
        id=f"s{position}", first_word_id=f"w{position}", last_word_id=f"w{position}",
        start_ms=position * 100, end_ms=position * 100 + 50, text=text,
        speaker_label="Warren Buffett", text_source=TextSource.OFFICIAL_TRANSCRIPT,
        boundary_source=BoundarySource.FUSED_PUNCTUATION,
        boundary_status=BoundaryStatus.VERIFIED,
    )


def _alignment() -> SourceAlignmentDTO:
    texts = ("First.", "Second.", "Third.")
    return SourceAlignmentDTO(
        language="en", audio_duration_ms=1000,
        words=tuple(_word(i, text) for i, text in enumerate(texts, 1)),
        sentences=tuple(_sentence(i, text) for i, text in enumerate(texts, 1)),
        sections=(
            SourceSectionDTO("sec1", "Opening", "s1", "s2"),
            SourceSectionDTO("sec2", "", "s3", "s3"),
        ),
    )


class FakeProvider:
    identity = ProviderIdentity(
        provider="fake", model="fake-v1",
        generation_parameters={
            "reasoning_effort": "high", "temperature": None,
            "max_output_tokens": 128000, "store": False,
        },
    )

    def __init__(self, actions=()) -> None:
        self.actions = deque(actions)
        self.calls = []

    def translate(self, call):
        self.calls.append(call)
        if self.actions:
            action = self.actions.popleft()
            if isinstance(action, Exception):
                raise action
            return action
        section = call.request.section
        return ProviderResponse(
            status=ProviderStatus.COMPLETED,
            output={
                "section": None if not call.request.translate_title else {
                    "id": section.id,
                    "translated_title": f"译-{section.title}" if section.title else None,
                },
                "items": [
                    {"id": item.id, "translated_text": f"译-{item.text}"}
                    for item in call.request.items
                ],
            },
            attempt_count=1,
            usage=ProviderUsage(input_tokens=10, output_tokens=5),
        )


class FakeSleeper:
    def __init__(self) -> None:
        self.delays = []

    def sleep(self, seconds):
        self.delays.append(seconds)


class FixedClock:
    def now_utc(self):
        return "2026-10-15T12:34:56Z"


class CapturingLogger:
    def __init__(self) -> None:
        self.events = []

    def log(self, event, metadata):
        self.events.append((event, dict(metadata)))


def _write_json(path: Path, data) -> bytes:
    raw = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return raw


def _input(tmp_path: Path):
    output_root = tmp_path / "output"
    workspace = build_asset_workspace(ASSET, output_root)
    alignment_path = workspace / canonical_filename(ArtifactType.SOURCE_ALIGNMENT)
    raw = _write_json(alignment_path, _alignment().to_dict())
    digest = hashlib.sha256(raw).hexdigest()
    manifest_path = workspace / canonical_filename(ArtifactType.TRANSCRIPTION_MANIFEST)
    video = workspace / "video.mp4"
    video.write_bytes(b"fake-boundary-media-fixture")
    _write_json(manifest_path, {
        "schema_version": "transcription.audio-vad-asr-cache.v1",
        "asset": {"source": "cnbc", "group": "2000", "item": "morning"},
        "records": {"source_alignment": {
            "path": str(alignment_path), "size_bytes": len(raw), "sha256": digest,
            "cache_key": "source-key", "status": "succeeded", "provenance": {},
        }, "audio":{"provenance":{"video_sha256":hashlib.sha256(video.read_bytes()).hexdigest()}}},
        "workflow": {"status": "succeeded"},
    })
    from archive_core.interfaces.bilingual import ArtifactEvidenceDTO, SourceChunkDTO, SourceChunkPlanDTO, MediaBoundaryDTO, ReadingBudgetDTO, StageManifestDTO
    from archive_core.interfaces.bilingual_timing import COUNTING_VERSION
    def ev(path):
        return ArtifactEvidenceDTO(str(path),path.stat().st_size,hashlib.sha256(path.read_bytes()).hexdigest())
    media=MediaBoundaryDTO(ev(video).sha256,1000,None)
    _write_json(workspace/"media_boundary.json",media.to_dict())
    plan=SourceChunkPlanDTO(ASSET.value,digest,media,{"version":"test"},{"model":"fake"},
        tuple(SourceChunkDTO(f"k{i}",(word.id,),(f"s{i}",),word.text,word.start_ms,word.end_ms,
              ReadingBudgetDTO(0,0,0,counting_version=COUNTING_VERSION),()) for i,word in enumerate(_alignment().words,1)),(),())
    _write_json(workspace/"source_chunks.json",plan.to_dict())
    _write_json(workspace/"source_chunking_report.json",{"status":"succeeded"})
    chunk_manifest=StageManifestDTO("source_chunking",ASSET.value,
        {"transcription_manifest":ev(manifest_path),"source_alignment":ev(alignment_path),
         "video":ev(video),"media_boundary":ev(workspace/"media_boundary.json")},
        {"source_chunks":ev(workspace/"source_chunks.json"),"report":ev(workspace/"source_chunking_report.json")},
        {"test":"fake-syntax-boundary"},"2026-11-05T00:00:00Z",{})
    _write_json(workspace/"source_chunking_manifest.json",chunk_manifest.to_dict())
    return output_root, workspace, manifest_path


def _workflow(tmp_path: Path, provider, *, artifacts=None, sleeper=None, logger=None):
    output_root, workspace, manifest_path = _input(tmp_path)
    workflow = TranslationWorkflow(
        provider=provider,
        checksum=LocalChecksumService(),
        artifacts=artifacts or LocalTranslationArtifactStore(),
        prompts=LocalPromptLoader(),
        glossaries=LocalGlossaryLoader(),
        checkpoints=LocalCheckpointStore(str(workspace / "translation_checkpoints")),
        sleeper=sleeper or FakeSleeper(), clock=FixedClock(),
        logger=logger or CapturingLogger(), output_root=str(output_root),
    )
    command = TranslationCommand(ASSET.value, str(manifest_path),str(workspace/"source_chunking_manifest.json"))
    return workflow, command, workspace
