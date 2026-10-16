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
        boundary_source=BoundarySource.OFFICIAL_PUNCTUATION,
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
                "section": None if section is None else {
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
    _write_json(manifest_path, {
        "schema_version": "transcription.audio-vad-asr-cache.v1",
        "asset": {"source": "cnbc", "group": "2000", "item": "morning"},
        "records": {"source_alignment": {
            "path": str(alignment_path), "size_bytes": len(raw), "sha256": digest,
            "cache_key": "source-key", "status": "succeeded", "provenance": {},
        }},
        "workflow": {"status": "succeeded"},
    })
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
    command = TranslationCommand(ASSET.value, str(manifest_path))
    return workflow, command, workspace


def test_workflow_publishes_stable_valid_pair_and_reuses_formal_result(tmp_path):
    provider = FakeProvider()
    logger = CapturingLogger()
    workflow, command, workspace = _workflow(tmp_path, provider, logger=logger)
    handler = TranslationCommandHandler(workflow)

    first = handler.handle(command)
    assert first.status == "succeeded"
    assert (first.request_count, first.checkpoint_reuse_count, first.attempt_count) == (2, 0, 2)
    assert len(provider.calls) == 2
    result_path = workspace / "translation_result.json"
    manifest = json.loads((workspace / "translation_manifest.json").read_text())
    result_before = result_path.read_bytes()
    assert hashlib.sha256(result_before).hexdigest() == manifest["output"]["sha256"]
    assert manifest["execution"] == {
        "request_count": 2, "checkpoint_reuse_count": 0, "attempt_count": 2,
        "input_tokens": 20, "output_tokens": 10,
    }
    assert set().union(*(metadata for _, metadata in logger.events)) <= {
        "asset_id", "request_kind", "request_id", "sentence_count", "checkpoint",
        "provider", "model", "attempt", "error_category", "output_path", "checksum",
    }

    second = handler.handle(command)
    assert second.status == "reused"
    assert second.attempt_count == 0
    assert len(provider.calls) == 2
    assert result_path.read_bytes() == result_before


def test_workflow_preserves_complete_provider_parameters_in_formal_provenance(
    tmp_path,
):
    provider = FakeProvider()
    provider.identity = ProviderIdentity(
        provider="codex-cli-chatgpt",
        model="gpt-5.6-sol",
        generation_parameters={
            "adapter_protocol": "translation.codex-cli.v1",
            "auth_method": "chatgpt",
            "codex_cli_version": "codex-cli 1.2.3",
            "execution_mode": "exec",
            "reasoning_effort": "high",
            "sandbox": "read-only",
            "session_persistence": "ephemeral",
            "structured_output": True,
        },
    )
    workflow, command, workspace = _workflow(tmp_path, provider)

    assert TranslationCommandHandler(workflow).handle(command).status == "succeeded"
    manifest = json.loads((workspace / "translation_manifest.json").read_text())
    assert manifest["translation"]["generation_parameters"] == (
        provider.identity.to_dict()["generation_parameters"]
    )

    provider.calls.clear()
    provider.identity = ProviderIdentity(
        provider="codex-cli-chatgpt",
        model="gpt-5.6-sol",
        generation_parameters={
            **provider.identity.to_dict()["generation_parameters"],
            "codex_cli_version": "codex-cli 1.2.4",
        },
    )
    with pytest.raises(TranslationArtifactConflict, match="configuration differs"):
        workflow.execute(
            asset_id=command.asset_id,
            transcription_manifest_path=command.transcription_manifest_path,
            glossary_path=None,
            overwrite=False,
            max_attempts=3,
        )
    assert provider.calls == []


def test_transient_retry_uses_identical_call_and_retry_after_then_fallback(tmp_path):
    provider = FakeProvider([
        TransientProviderError("timeout", code="timeout"),
        TransientProviderError("rate limited", code="http_429"),
    ])
    # After the two failures FakeProvider's normal success path is used.
    sleeper = FakeSleeper()
    workflow, command, _ = _workflow(tmp_path, provider, sleeper=sleeper)
    outcome = TranslationCommandHandler(workflow).handle(command)
    assert outcome.status == "succeeded"
    assert outcome.attempt_count == 4  # three calls for sec1, one for sec2
    assert provider.calls[0] == provider.calls[1] == provider.calls[2]
    assert sleeper.delays == [2.0, 4.0]


def test_retry_after_takes_precedence(tmp_path):
    provider = FakeProvider([
        TransientProviderError(
            "rate limited", code="http_429", retry_after_seconds=0.25
        ),
    ])
    sleeper = FakeSleeper()
    workflow, command, _ = _workflow(tmp_path, provider, sleeper=sleeper)
    assert TranslationCommandHandler(workflow).handle(command).status == "succeeded"
    assert sleeper.delays == [0.25]


@pytest.mark.parametrize("failure", [
    PermanentProviderError("bad credentials", code="authentication"),
])
def test_permanent_failure_is_not_retried_or_published(tmp_path, failure):
    provider = FakeProvider([failure])
    workflow, command, workspace = _workflow(tmp_path, provider)
    outcome = TranslationCommandHandler(workflow).handle(command)
    assert outcome.status == "failed"
    assert len(provider.calls) == 1
    assert not (workspace / "translation_result.json").exists()
    assert not (workspace / "translation_manifest.json").exists()


@pytest.mark.parametrize("status", [ProviderStatus.REFUSED, ProviderStatus.INCOMPLETE])
def test_noncompleted_response_is_not_retried(tmp_path, status):
    provider = FakeProvider([ProviderResponse(status=status, output=None, attempt_count=1)])
    workflow, command, _ = _workflow(tmp_path, provider)
    assert TranslationCommandHandler(workflow).handle(command).status == "failed"
    assert len(provider.calls) == 1


def test_business_invalid_response_is_not_retried_or_checkpointed(tmp_path):
    invalid = ProviderResponse(
        status=ProviderStatus.COMPLETED,
        output={
            "section": {"id": "wrong", "translated_title": "错"},
            "items": [
                {"id": "s1", "translated_text": "一"},
                {"id": "s2", "translated_text": "二"},
            ],
        },
        attempt_count=1,
    )
    provider = FakeProvider([invalid])
    workflow, command, workspace = _workflow(tmp_path, provider)
    assert TranslationCommandHandler(workflow).handle(command).status == "failed"
    assert len(provider.calls) == 1
    assert list((workspace / "translation_checkpoints").glob("*.json")) == []


def test_fail_fast_keeps_first_checkpoint_and_resume_calls_only_missing(tmp_path):
    provider = FakeProvider()
    workflow, command, workspace = _workflow(tmp_path, provider)
    original = provider.translate
    calls = 0
    def fail_second(call):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise PermanentProviderError("stop", code="request_too_large")
        return original(call)
    provider.translate = fail_second
    with pytest.raises(TranslationProviderFailure):
        workflow.execute(
            asset_id=command.asset_id,
            transcription_manifest_path=command.transcription_manifest_path,
            glossary_path=None, overwrite=False, max_attempts=3,
        )
    assert len(list((workspace / "translation_checkpoints").glob("*.json"))) == 1
    assert not (workspace / "translation_result.json").exists()

    resumed = FakeProvider()
    resumed_workflow = TranslationWorkflow(
        provider=resumed,
        checksum=LocalChecksumService(),
        artifacts=LocalTranslationArtifactStore(),
        prompts=LocalPromptLoader(), glossaries=LocalGlossaryLoader(),
        checkpoints=LocalCheckpointStore(str(workspace / "translation_checkpoints")),
        sleeper=FakeSleeper(), clock=FixedClock(), logger=CapturingLogger(),
        output_root=str(tmp_path / "output"),
    )
    outcome = TranslationCommandHandler(resumed_workflow).handle(command)
    assert outcome.status == "succeeded"
    assert outcome.checkpoint_reuse_count == 1
    assert len(resumed.calls) == 1
    assert resumed.calls[0].request.section.id == "sec2"


def test_overwrite_skips_checkpoints_and_corrupt_checkpoint_fails(tmp_path):
    provider = FakeProvider()
    workflow, command, workspace = _workflow(tmp_path, provider)
    assert TranslationCommandHandler(workflow).handle(command).status == "succeeded"
    assert len(provider.calls) == 2
    overwrite = TranslationCommand(
        command.asset_id, command.transcription_manifest_path, overwrite=True
    )
    assert TranslationCommandHandler(workflow).handle(overwrite).status == "succeeded"
    assert len(provider.calls) == 4

    (workspace / "translation_result.json").unlink()
    (workspace / "translation_manifest.json").unlink()
    checkpoint = next((workspace / "translation_checkpoints").glob("*.json"))
    checkpoint.write_text("{}", encoding="utf-8")
    with pytest.raises(TranslationCheckpointError):
        workflow.execute(
            asset_id=command.asset_id,
            transcription_manifest_path=command.transcription_manifest_path,
            glossary_path=None, overwrite=False, max_attempts=3,
        )


def test_conflicting_formal_pair_fails_without_provider_call(tmp_path):
    provider = FakeProvider()
    workflow, command, workspace = _workflow(tmp_path, provider)
    assert TranslationCommandHandler(workflow).handle(command).status == "succeeded"
    provider.calls.clear()
    (workspace / "translation_result.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(TranslationArtifactConflict):
        workflow.execute(
            asset_id=command.asset_id,
            transcription_manifest_path=command.transcription_manifest_path,
            glossary_path=None, overwrite=False, max_attempts=3,
        )
    assert provider.calls == []


class FailingPublicationStore(LocalTranslationArtifactStore):
    def publish_json_pair(self, *args, **kwargs):
        raise OSError("simulated publication failure")


def test_overwrite_publication_failure_preserves_old_pair(tmp_path):
    provider = FakeProvider()
    workflow, command, workspace = _workflow(tmp_path, provider)
    assert TranslationCommandHandler(workflow).handle(command).status == "succeeded"
    old_result = (workspace / "translation_result.json").read_bytes()
    old_manifest = (workspace / "translation_manifest.json").read_bytes()

    failing = TranslationWorkflow(
        provider=FakeProvider(),
        checksum=LocalChecksumService(),
        artifacts=FailingPublicationStore(),
        prompts=LocalPromptLoader(), glossaries=LocalGlossaryLoader(),
        checkpoints=LocalCheckpointStore(str(workspace / "translation_checkpoints")),
        sleeper=FakeSleeper(), clock=FixedClock(), logger=CapturingLogger(),
        output_root=str(tmp_path / "output"),
    )
    with pytest.raises(TranslationPublicationError):
        failing.execute(
            asset_id=command.asset_id,
            transcription_manifest_path=command.transcription_manifest_path,
            glossary_path=None, overwrite=True, max_attempts=3,
        )
    assert (workspace / "translation_result.json").read_bytes() == old_result
    assert (workspace / "translation_manifest.json").read_bytes() == old_manifest


def test_local_pair_store_rolls_back_partial_install(tmp_path, monkeypatch):
    store = LocalTranslationArtifactStore()
    result = tmp_path / "translation_result.json"
    manifest = tmp_path / "translation_manifest.json"
    result.write_bytes(b"old result\n")
    manifest.write_bytes(b"old manifest\n")
    old_result = result.read_bytes()
    old_manifest = manifest.read_bytes()
    original_replace = Path.replace
    failed = False

    def fail_first_manifest_install(source, target):
        nonlocal failed
        if Path(target) == manifest and not failed:
            failed = True
            raise OSError("simulated second install failure")
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", fail_first_manifest_install)
    with pytest.raises(OSError):
        store.publish_json_pair(
            str(result),
            {"new": "result"},
            str(manifest),
            lambda size, sha256: {"size": size, "sha256": sha256},
            overwrite=True,
        )
    assert result.read_bytes() == old_result
    assert manifest.read_bytes() == old_manifest
