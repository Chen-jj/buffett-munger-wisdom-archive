"""Real Codex CLI acceptance for the section-aware translation workflow."""

from __future__ import annotations

import hashlib
import json
import os
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
    TranslationManifestDTO,
    TranslationResultDTO,
)
from infrastructure.infrastructure.config import load_yaml_config
from infrastructure.infrastructure.process import run_process
from translation.application import TranslationWorkflow
from translation.infrastructure import (
    CodexCliChatGPTTranslationProvider,
    LocalCheckpointStore,
    LocalChecksumService,
    LocalGlossaryLoader,
    LocalPromptLoader,
    LocalTranslationArtifactStore,
    NullMetadataLogger,
    SystemClock,
    SystemSleeper,
    build_translation_provider,
)
from translation.interfaces import TranslationCommand, TranslationCommandHandler


ASSET = AssetId("synthetic", "translation", "live")
SENTENCES = (
    "Berkshire Hathaway paid 10 dollars for an asset worth 15 dollars.",
    "A margin of safety does not eliminate risk.",
    "Warren Buffett said intrinsic value is not a precise number.",
    "I hope your question isn't going to be whether we can continue that, but go— ahead.",
)
SECTION_TITLES = (
    "A margin of safety for Berkshire Hathaway",
    "Intrinsic value and uncertainty",
)


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _alignment() -> SourceAlignmentDTO:
    words = tuple(
        TimedWordDTO(
            id=f"w{position}",
            text=text,
            start_ms=(position - 1) * 1_000,
            end_ms=position * 1_000,
            asr_word_ids=(f"a{position}",),
            official_token_ids=(f"o{position}",),
            match_type=MatchType.EXACT,
            text_source=TextSource.OFFICIAL_TRANSCRIPT,
            timing_source=TimingSource.ACOUSTIC_ALIGNMENT,
        )
        for position, text in enumerate(SENTENCES, start=1)
    )
    sentences = tuple(
        SourceSentenceDTO(
            id=f"s{position}",
            first_word_id=f"w{position}",
            last_word_id=f"w{position}",
            start_ms=(position - 1) * 1_000,
            end_ms=position * 1_000,
            text=text,
            speaker_label=(
                "Warren Buffett" if position < 3 else "Charlie Munger"
            ),
            text_source=TextSource.OFFICIAL_TRANSCRIPT,
            boundary_source=BoundarySource.OFFICIAL_PUNCTUATION,
            boundary_status=BoundaryStatus.VERIFIED,
        )
        for position, text in enumerate(SENTENCES, start=1)
    )
    return SourceAlignmentDTO(
        language="en",
        audio_duration_ms=4_000,
        words=words,
        sentences=sentences,
        sections=(
            SourceSectionDTO("sec1", SECTION_TITLES[0], "s1", "s2"),
            SourceSectionDTO("sec2", SECTION_TITLES[1], "s3", "s4"),
        ),
    )


def _write_input(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    output_root = tmp_path / "output"
    workspace = build_asset_workspace(ASSET, output_root)
    alignment_path = workspace / canonical_filename(ArtifactType.SOURCE_ALIGNMENT)
    alignment_bytes = _json_bytes(_alignment().to_dict())
    alignment_path.parent.mkdir(parents=True, exist_ok=True)
    alignment_path.write_bytes(alignment_bytes)
    alignment_sha256 = hashlib.sha256(alignment_bytes).hexdigest()

    manifest_path = workspace / canonical_filename(
        ArtifactType.TRANSCRIPTION_MANIFEST
    )
    manifest_path.write_bytes(
        _json_bytes(
            {
                "schema_version": "transcription.audio-vad-asr-cache.v1",
                "asset": {
                    "source": ASSET.source,
                    "group": ASSET.group,
                    "item": ASSET.item,
                },
                "records": {
                    "source_alignment": {
                        "path": str(alignment_path),
                        "size_bytes": len(alignment_bytes),
                        "sha256": alignment_sha256,
                        "cache_key": "synthetic-live-source",
                        "status": "succeeded",
                        "provenance": {},
                    }
                },
                "workflow": {"status": "succeeded"},
            }
        )
    )

    glossary_path = tmp_path / "translation_glossary.json"
    glossary_path.write_bytes(
        _json_bytes(
            {
                "schema_version": "translation.glossary.v1",
                "entries": [
                    {"source": "margin of safety", "target": "安全边际"},
                    {"source": "intrinsic value", "target": "内在价值"},
                    {
                        "source": "Berkshire Hathaway",
                        "target": "Berkshire Hathaway",
                    },
                ],
            }
        )
    )
    return output_root, workspace, manifest_path, str(glossary_path)


class CountingProcessRunner:
    def __init__(self) -> None:
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((tuple(command), kwargs))
        return run_process(command, **kwargs)

    @property
    def translation_calls(self):
        return [
            call
            for call in self.calls
            if len(call[0]) > 1
            and call[0][1] == "exec"
            and call[0][-1] == "-"
        ]


class CountingProvider:
    def __init__(self, delegate) -> None:
        self.delegate = delegate
        self.calls = []
        self.successful_calls = []
        self.responses = []

    @property
    def identity(self):
        return self.delegate.identity

    def translate(self, call):
        self.calls.append(call)
        response = self.delegate.translate(call)
        self.successful_calls.append(call)
        self.responses.append(response)
        return response


@pytest.mark.live
def test_real_codex_cli_translation_publishes_and_reuses_two_sections(
    tmp_path: Path,
) -> None:
    """Requires explicit ChatGPT/Codex opt-in; no real response is stored in git."""

    if os.environ.get("RUN_CODEX_CLI_TRANSLATION_INTEGRATION") != "1":
        pytest.skip(
            "set RUN_CODEX_CLI_TRANSLATION_INTEGRATION=1 for the Codex CLI test"
        )

    output_root, workspace, transcription_manifest_path, glossary_path = (
        _write_input(tmp_path)
    )
    process_runner = CountingProcessRunner()

    def codex_provider_factory(**kwargs):
        return CodexCliChatGPTTranslationProvider(
            **kwargs,
            process_runner=process_runner,
        )

    production_provider = build_translation_provider(
        load_yaml_config(),
        codex_provider_factory=codex_provider_factory,
    )
    provider = CountingProvider(production_provider)
    prompt = LocalPromptLoader().load()
    glossary_sha256 = hashlib.sha256(Path(glossary_path).read_bytes()).hexdigest()
    workflow = TranslationWorkflow(
        provider=provider,
        checksum=LocalChecksumService(),
        artifacts=LocalTranslationArtifactStore(),
        prompts=LocalPromptLoader(),
        glossaries=LocalGlossaryLoader(),
        checkpoints=LocalCheckpointStore(str(workspace / "translation_checkpoints")),
        sleeper=SystemSleeper(),
        clock=SystemClock(),
        logger=NullMetadataLogger(),
        output_root=str(output_root),
    )
    command = TranslationCommand(
        asset_id=ASSET.value,
        transcription_manifest_path=str(transcription_manifest_path),
        glossary_path=glossary_path,
    )
    handler = TranslationCommandHandler(workflow)

    first = handler.handle(command)

    assert first.status == "succeeded", first.error_message
    assert first.request_count == 2
    assert first.checkpoint_reuse_count == 0
    assert first.attempt_count == len(provider.calls) == 2
    assert len(process_runner.translation_calls) == 2
    assert [call.request.section.id for call in provider.successful_calls] == [
        "sec1",
        "sec2",
    ]
    assert [
        [item.id for item in call.request.items] for call in provider.successful_calls
    ] == [["s1", "s2"], ["s3", "s4"]]
    assert all(response.usage is None for response in provider.responses)
    assert all(response.provider_request_id is None for response in provider.responses)
    assert any(
        call[0][-2:] == ("login", "status") for call in process_runner.calls
    )
    assert all(
        "OPENAI_API_KEY" not in call[1]["env"] for call in process_runner.calls
    )

    result_path = workspace / canonical_filename(ArtifactType.TRANSLATION_RESULT)
    manifest_path = workspace / canonical_filename(ArtifactType.TRANSLATION_MANIFEST)
    result_bytes = result_path.read_bytes()
    manifest_bytes = manifest_path.read_bytes()
    result_sha256 = hashlib.sha256(result_bytes).hexdigest()
    result = TranslationResultDTO.from_dict(json.loads(result_bytes))
    result.validate_against_alignment(_alignment())
    manifest = TranslationManifestDTO.from_dict(
        json.loads(manifest_path.read_text(encoding="utf-8"))
    )

    assert [item.section_id for item in result.section_title_translations] == [
        "sec1",
        "sec2",
    ]
    assert all(
        item.translated_title and item.translated_title.strip()
        for item in result.section_title_translations
    )
    assert [item.sentence_id for item in result.sentence_translations] == [
        "s1",
        "s2",
        "s3",
        "s4",
    ]
    assert all(item.translated_text.strip() for item in result.sentence_translations)
    dash_example = next(
        item.translated_text
        for item in result.sentence_translations
        if item.sentence_id == "s4"
    )
    assert "请继续" in dash_example
    assert "—" not in dash_example
    assert result.source_alignment_sha256 == manifest.input.sha256
    assert result.source_language == "en"
    assert result.target_language == "zh-Hans"
    assert manifest.asset_id == ASSET.value
    assert manifest.output.path == canonical_filename(ArtifactType.TRANSLATION_RESULT)
    assert manifest.output.size_bytes == len(result_bytes)
    assert manifest.output.sha256 == result_sha256 == first.result_sha256
    assert manifest.translation.prompt_version == "translation.zh-hans.v1"
    assert manifest.translation.prompt_sha256 == prompt.sha256
    assert manifest.translation.glossary_path == glossary_path
    assert manifest.translation.glossary_sha256 == glossary_sha256
    assert manifest.translation.provider == "codex-cli-chatgpt"
    assert manifest.translation.model == "gpt-5.6-sol"
    expected_generation_parameters = {
        "adapter_protocol": "translation.codex-cli.v1",
        "auth_method": "chatgpt",
        "codex_cli_version": provider.identity.generation_parameters[
            "codex_cli_version"
        ],
        "execution_mode": "exec",
        "reasoning_effort": "high",
        "sandbox": "read-only",
        "session_persistence": "ephemeral",
        "structured_output": True,
    }
    assert provider.identity.to_dict() == {
        "provider": "codex-cli-chatgpt",
        "model": "gpt-5.6-sol",
        "generation_parameters": expected_generation_parameters,
    }
    assert manifest.translation.generation_parameters.to_dict() == (
        expected_generation_parameters
    )
    assert expected_generation_parameters["codex_cli_version"].startswith(
        "codex-cli "
    )
    assert manifest.execution.request_count == 2
    assert manifest.execution.checkpoint_reuse_count == 0
    assert manifest.execution.attempt_count == first.attempt_count == 2
    assert manifest.execution.input_tokens is None
    assert manifest.execution.output_tokens is None

    call_count_before_reuse = len(provider.calls)
    response_count_before_reuse = len(provider.responses)
    process_count_before_reuse = len(process_runner.calls)
    translation_process_count_before_reuse = len(process_runner.translation_calls)
    second = handler.handle(command)

    assert second.status == "reused", second.error_message
    assert second.request_count == 2
    assert second.checkpoint_reuse_count == 0
    assert second.attempt_count == 0
    assert len(provider.calls) == call_count_before_reuse
    assert len(provider.responses) == response_count_before_reuse
    assert len(process_runner.calls) == process_count_before_reuse
    assert len(process_runner.translation_calls) == (
        translation_process_count_before_reuse
    )
    assert result_path.read_bytes() == result_bytes
    assert manifest_path.read_bytes() == manifest_bytes
    assert second.result_sha256 == result_sha256

    print(f"Codex CLI version: {expected_generation_parameters['codex_cli_version']}")
    print(f"live translation artifacts: {workspace}")
    print(
        json.dumps(
            {
                "section_title_translations": [
                    item.to_dict() for item in result.section_title_translations
                ],
                "sentence_translations": [
                    item.to_dict() for item in result.sentence_translations
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
