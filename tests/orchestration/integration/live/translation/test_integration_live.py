"""Provider-contract scenario: real Codex with an explicit synthetic input, never the CNBC production sample."""

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
    reconstruct_sentence_text,
)
from archive_core.interfaces.bilingual import (ArtifactEvidenceDTO, ChunkTranslationResultDTO, MediaBoundaryDTO,
    ReadingBudgetDTO, SourceChunkDTO, SourceChunkPlanDTO, StageManifestDTO)
from archive_core.interfaces.transcription import EditorialBreakDTO
from infrastructure.infrastructure.config import load_yaml_config
from infrastructure.infrastructure.process import run_process
from translation.infrastructure import (
    CodexCliChatGPTTranslationProvider,
    LocalCheckpointStore,
    LocalPromptLoader,
    build_translation_provider,
)
from translation.interfaces import TranslationCommand, build_translation_handler


ASSET = AssetId("synthetic", "translation", "live")
SENTENCES = (
    "Berkshire Hathaway paid 10 dollars for an asset worth 15 dollars.",
    "A margin of safety does not eliminate risk.",
    "Warren Buffett said intrinsic value is not a precise number.",
    "I hope your question isn't going to be whether we can continue that, but go ahead.",
)
SECTION_TITLES = (
    "A margin of safety for Berkshire Hathaway",
    "Intrinsic value and uncertainty",
)


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _alignment() -> SourceAlignmentDTO:
    words, sentences = [], []
    for position, text in enumerate(SENTENCES, 1):
        first = len(words)
        for token in text.split():
            index = len(words) + 1
            words.append(TimedWordDTO(f"w{index}", token, (index-1)*100, index*100,
                (f"a{index}",), (f"ot{index}",), MatchType.EXACT, TextSource.OFFICIAL_TRANSCRIPT,
                TimingSource.ACOUSTIC_ALIGNMENT))
        selected = words[first:]
        sentences.append(SourceSentenceDTO(f"s{position}",selected[0].id,selected[-1].id,
            selected[0].start_ms,selected[-1].end_ms,reconstruct_sentence_text(selected),
            "Warren Buffett" if position < 3 else "Charlie Munger",TextSource.OFFICIAL_TRANSCRIPT,
            BoundarySource.OFFICIAL_PUNCTUATION,BoundaryStatus.VERIFIED))
    go = next(word for word in words if word.text == "go")
    return SourceAlignmentDTO("en",words[-1].end_ms,tuple(words),tuple(sentences),(
        SourceSectionDTO("sec1",SECTION_TITLES[0],"s1","s2"),
        SourceSectionDTO("sec2",SECTION_TITLES[1],"s3","s4"),
    ), annotations=(EditorialBreakDTO("e1",go.id,go.official_token_ids),))


def _write_input(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    output_root = tmp_path / "output"
    workspace = build_asset_workspace(ASSET, output_root)
    alignment_path = workspace / canonical_filename(ArtifactType.SOURCE_ALIGNMENT)
    alignment = _alignment()
    alignment_bytes = _json_bytes(alignment.to_dict())
    alignment_path.parent.mkdir(parents=True, exist_ok=True)
    alignment_path.write_bytes(alignment_bytes)
    alignment_sha256 = hashlib.sha256(alignment_bytes).hexdigest()

    manifest_path = workspace / canonical_filename(
        ArtifactType.TRANSCRIPTION_MANIFEST
    )
    video = workspace / canonical_filename(ArtifactType.SOURCE_VIDEO)
    video.write_bytes(b"synthetic provider-contract boundary; not playable media")
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
                    },
                    "audio":{"provenance":{"video_sha256":hashlib.sha256(video.read_bytes()).hexdigest()}},
                },
                "workflow": {"status": "succeeded"},
            }
        )
    )

    def evidence(path):
        raw = path.read_bytes()
        return ArtifactEvidenceDTO(str(path),len(raw),hashlib.sha256(raw).hexdigest())
    media = MediaBoundaryDTO(evidence(video).sha256,alignment.audio_duration_ms,None)
    media_path = workspace / canonical_filename(ArtifactType.MEDIA_BOUNDARY)
    media_path.write_bytes(_json_bytes(media.to_dict()))
    chunks_path = workspace / canonical_filename(ArtifactType.SOURCE_CHUNKS)
    chunks = SourceChunkPlanDTO(ASSET.value,alignment_sha256,media,{"version":"synthetic-provider-contract"},
        {"source":"synthetic"},tuple(SourceChunkDTO(f"k{i}",
            tuple(word.id for word in alignment.words[int(sentence.first_word_id[1:])-1:int(sentence.last_word_id[1:])]),
            (sentence.id,),sentence.text,sentence.start_ms,sentence.end_ms,ReadingBudgetDTO(0,0,0),())
            for i,sentence in enumerate(alignment.sentences,1)),(),())
    chunks_path.write_bytes(_json_bytes(chunks.to_dict()))
    report = workspace / canonical_filename(ArtifactType.SOURCE_CHUNKING_REPORT)
    report.write_bytes(_json_bytes({"status":"succeeded","origin":"synthetic-provider-contract"}))
    chunk_manifest = StageManifestDTO("source_chunking",ASSET.value,
        {"transcription_manifest":evidence(manifest_path),"source_alignment":evidence(alignment_path),
         "video":evidence(video),"media_boundary":evidence(media_path)},
        {"source_chunks":evidence(chunks_path),"report":evidence(report)},
        {"fixture":"synthetic-provider-contract"},"2026-11-05T00:00:00Z",{})
    (workspace / canonical_filename(ArtifactType.SOURCE_CHUNKING_MANIFEST)).write_bytes(_json_bytes(chunk_manifest.to_dict()))

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

    scenarios = {value.strip() for value in os.environ.get("ORCHESTRATION_INTEGRATION_SCENARIOS", "").split(",")}
    if os.environ.get("RUN_ORCHESTRATION_INTEGRATION") != "1" or "provider_contract" not in scenarios:
        pytest.skip("enable orchestration provider_contract scenario explicitly")

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
    handler = build_translation_handler(output_root=str(output_root),provider=provider,
        checkpoints=LocalCheckpointStore(str(workspace / "translation_checkpoints")))
    command = TranslationCommand(asset_id=ASSET.value,
        transcription_manifest_path=str(transcription_manifest_path),
        source_chunking_manifest_path=str(workspace / canonical_filename(ArtifactType.SOURCE_CHUNKING_MANIFEST)),
        glossary_path=glossary_path)

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
    ] == [["k1", "k2"], ["k3", "k4"]]
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
    result = ChunkTranslationResultDTO.from_dict(json.loads(result_bytes))
    source_chunks = SourceChunkPlanDTO.from_dict(json.loads((workspace / canonical_filename(ArtifactType.SOURCE_CHUNKS)).read_bytes()))
    result.validate_against_inputs(_alignment(),source_chunks)
    manifest = StageManifestDTO.from_dict(
        json.loads(manifest_path.read_text(encoding="utf-8"))
    )

    assert [item.section_id for item in result.section_titles] == [
        "sec1",
        "sec2",
    ]
    assert all(
        item.translated_title and item.translated_title.strip()
        for item in result.section_titles
    )
    assert [item.id for item in result.chunks] == [
        "k1",
        "k2",
        "k3",
        "k4",
    ]
    assert all(item.translated_text.strip() for item in result.chunks)
    dash_example = next(
        item.translated_text
        for item in result.chunks
        if item.id == "k4"
    )
    assert "请继续" in dash_example
    assert "—" not in dash_example
    assert result.source_alignment_sha256 == manifest.inputs["source_alignment"].sha256
    assert result.source_chunks_sha256 == manifest.inputs["source_chunks"].sha256
    assert all((call.request.source_language,call.request.target_language)==("en","zh-Hans") for call in provider.calls)
    assert not provider.calls[0].request.annotations and len(provider.calls[1].request.annotations)==1
    assert all("—" not in item.text for call in provider.calls for item in call.request.items)
    assert manifest.asset_id == ASSET.value
    assert manifest.outputs["translation_result"].path == str(result_path)
    assert manifest.outputs["translation_result"].size_bytes == len(result_bytes)
    assert manifest.outputs["translation_result"].sha256 == result_sha256 == first.result_sha256
    assert manifest.identity["prompt_version"] == "translation.contextual-chunks.zh-hans.v1"
    assert manifest.identity["prompt_sha256"] == prompt.sha256
    assert manifest.identity["glossary_path"] == glossary_path
    assert manifest.identity["glossary_sha256"] == glossary_sha256
    assert manifest.identity["provider"]["provider"] == "codex-cli-chatgpt"
    assert manifest.identity["provider"]["model"] == "gpt-5.6-sol"
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
    assert manifest.identity["provider"]["generation_parameters"] == (
        expected_generation_parameters
    )
    assert expected_generation_parameters["codex_cli_version"].startswith(
        "codex-cli "
    )
    assert manifest.execution["request_count"] == 2
    assert manifest.execution["checkpoint_reuse_count"] == 0
    assert manifest.execution["provider_calls"] == first.attempt_count == 2
    assert manifest.execution["unknown_usage_count"] == 2

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
                "section_titles": [
                    item.to_dict() for item in result.section_titles
                ],
                "chunks": [
                    item.to_dict() for item in result.chunks
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
