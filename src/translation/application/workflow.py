"""Resumable contextual chunk translation; one current production contract."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from archive_core.application import build_asset_workspace
from archive_core.domain import ArtifactType, AssetId, canonical_filename
from archive_core.interfaces import SourceAlignmentDTO, SectionTitleTranslationDTO
from archive_core.interfaces.bilingual import (
    ArtifactEvidenceDTO, ChunkTranslationDTO, ChunkTranslationResultDTO,
    SourceChunkPlanDTO, StageManifestDTO,
)
from translation.domain import (
    PROMPT_VERSION, RESPONSE_SCHEMA_VERSION, CheckpointCacheKeyInput, ProviderCall, ProviderError,
    ProviderErrorCategory, ProviderResponse, ProviderStatus, canonical_json_sha256,
    plan_translation_requests, render_translation_instructions,
    translation_response_schema, validate_provider_response,
)
from translation.domain.planning import TERM_MATCH_VERSION

CHECKPOINT_SCHEMA_VERSION = "translation.chunk-checkpoint.v1"
TRANSCRIPTION_MANIFEST_SCHEMA = "transcription.audio-vad-asr-cache.v1"


class TranslationWorkflowError(RuntimeError):
    category = "translation_failed"


class TranslationInputError(TranslationWorkflowError):
    category = "input_invalid"


class TranslationArtifactConflict(TranslationWorkflowError):
    category = "artifact_conflict"


class TranslationCheckpointError(TranslationWorkflowError):
    category = "checkpoint_invalid"


class TranslationProviderFailure(TranslationWorkflowError):
    category = "provider_failed"


class TranslationPublicationError(TranslationWorkflowError):
    category = "publication_failed"


@dataclass(frozen=True)
class TranslationRunResult:
    status: str
    result_path: str
    manifest_path: str
    request_count: int
    checkpoint_reuse_count: int
    attempt_count: int
    result_sha256: str


def parse_asset(value: str) -> AssetId:
    try:
        source, group, item = value.split(":")
        return AssetId(source, group, item)
    except (AttributeError, ValueError) as error:
        raise TranslationInputError("asset_id must use source:group:item") from error


def evidence(path: str, artifacts, checksum) -> ArtifactEvidenceDTO:
    return ArtifactEvidenceDTO(str(Path(path).absolute()), artifacts.size(path), checksum.sha256(path))


def verify_evidence(item: ArtifactEvidenceDTO, artifacts, checksum, expected_path: str | None = None) -> None:
    if expected_path is not None and Path(item.path) != Path(expected_path):
        raise TranslationInputError("evidence path is not canonical")
    if evidence(item.path, artifacts, checksum) != item:
        raise TranslationInputError("artifact evidence mismatch")


def load_source_inputs(asset_id: str, workspace: Path, transcription_manifest_path: str,
                       source_chunking_manifest_path: str, artifacts, checksum):
    """Validate canonical upstream evidence before any model/config work."""
    try:
        expected_transcription = workspace / canonical_filename(ArtifactType.TRANSCRIPTION_MANIFEST)
        expected_chunking = workspace / canonical_filename(ArtifactType.SOURCE_CHUNKING_MANIFEST)
        if Path(transcription_manifest_path) != expected_transcription or Path(source_chunking_manifest_path) != expected_chunking:
            raise ValueError("upstream manifest path is not canonical")
        transcription = artifacts.read_json(str(expected_transcription))
        if transcription.get("schema_version") != TRANSCRIPTION_MANIFEST_SCHEMA or set(transcription) != {"schema_version", "asset", "records", "workflow"}:
            raise ValueError("invalid transcription manifest")
        if AssetId(**transcription["asset"]).value != asset_id or transcription["workflow"].get("status") != "succeeded":
            raise ValueError("transcription identity/status mismatch")
        record = transcription["records"]["source_alignment"]
        if record.get("status") != "succeeded":
            raise ValueError("source alignment record did not succeed")
        source = ArtifactEvidenceDTO(record["path"], record["size_bytes"], record["sha256"])
        verify_evidence(source, artifacts, checksum, str(workspace / canonical_filename(ArtifactType.SOURCE_ALIGNMENT)))
        alignment = SourceAlignmentDTO.from_dict(artifacts.read_json(source.path))
        manifest = StageManifestDTO.from_dict(artifacts.read_json(str(expected_chunking)))
        if manifest.stage != "source_chunking" or manifest.asset_id != asset_id:
            raise ValueError("source chunk manifest identity mismatch")
        if set(manifest.inputs) != {"transcription_manifest", "source_alignment", "video", "media_boundary"} or set(manifest.outputs) != {"source_chunks", "report"}:
            raise ValueError("source chunk manifest evidence keys mismatch")
        for name, item in manifest.inputs.items():
            kind = {"transcription_manifest": ArtifactType.TRANSCRIPTION_MANIFEST,
                    "source_alignment": ArtifactType.SOURCE_ALIGNMENT, "video": ArtifactType.SOURCE_VIDEO,
                    "media_boundary": ArtifactType.MEDIA_BOUNDARY}[name]
            verify_evidence(item, artifacts, checksum, str(workspace / canonical_filename(kind)))
        for name, item in manifest.outputs.items():
            verify_evidence(item, artifacts, checksum, str(workspace / canonical_filename(ArtifactType.SOURCE_CHUNKS if name == "source_chunks" else ArtifactType.SOURCE_CHUNKING_REPORT)))
        if manifest.inputs["source_alignment"] != source:
            raise ValueError("source chunk alignment chain mismatch")
        if transcription["records"]["audio"]["provenance"]["video_sha256"] != manifest.inputs["video"].sha256:
            raise ValueError("transcription video fingerprint differs")
        chunk_evidence = manifest.outputs["source_chunks"]
        chunks = SourceChunkPlanDTO.from_dict(artifacts.read_json(chunk_evidence.path))
        chunks.validate_against_alignment(alignment)
        if chunks.media.to_dict() != artifacts.read_json(manifest.inputs["media_boundary"].path):
            raise ValueError("media boundary differs from source chunk plan")
        if artifacts.read_json(manifest.outputs["report"].path).get("status") != "succeeded":
            raise ValueError("source chunk report did not succeed")
        if chunks.asset_id != asset_id or chunks.source_alignment_sha256 != source.sha256 or chunks.media.video_sha256 != manifest.inputs["video"].sha256:
            raise ValueError("source chunk input fingerprint mismatch")
        inputs = {
            "transcription_manifest": evidence(str(expected_transcription), artifacts, checksum),
            "source_alignment": source,
            "source_chunking_manifest": evidence(str(expected_chunking), artifacts, checksum),
            "source_chunks": chunk_evidence,
        }
        return alignment, chunks, inputs
    except TranslationInputError:
        raise
    except Exception as error:
        raise TranslationInputError("source/chunk evidence validation failed") from error


class TranslationWorkflow:
    def __init__(self, *, provider, checksum, artifacts, prompts, glossaries,
                 checkpoints, sleeper, clock, logger, output_root: str = "output",
                 default_glossary_path: str | None = None):
        self.provider, self.checksum, self.artifacts = provider, checksum, artifacts
        self.prompts, self.glossaries, self.checkpoints = prompts, glossaries, checkpoints
        self.sleeper, self.clock, self.logger = sleeper, clock, logger
        self.output_root = output_root
        self.default_glossary_path = default_glossary_path

    def verify(self, **arguments):
        arguments["overwrite"] = False
        return self.execute(**arguments, _verify=True)

    def execute(self, *, asset_id: str, transcription_manifest_path: str,
                source_chunking_manifest_path: str, glossary_path: str | None = None,
                overwrite: bool = False, max_attempts: int = 3, _verify: bool = False) -> TranslationRunResult:
        if not isinstance(overwrite, bool) or isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
            raise TranslationInputError("invalid execution policy")
        workspace = build_asset_workspace(parse_asset(asset_id), self.output_root).absolute()
        alignment, chunks, inputs = load_source_inputs(asset_id, workspace,
            transcription_manifest_path, source_chunking_manifest_path, self.artifacts, self.checksum)
        try:
            prompt = self.prompts.load()
            if prompt.version != PROMPT_VERSION:
                raise ValueError("unsupported prompt version")
            glossary_path = glossary_path or self.default_glossary_path
            resource = self.glossaries.load(glossary_path) if glossary_path else None
            provider_identity = None if _verify else self.provider.identity
            requests = plan_translation_requests(alignment, chunks, resource.glossary if resource else None)
            # Only target-matched terms are in each request; never expose the whole glossary.
            instructions = render_translation_instructions(prompt.text, None)
            identity = {
                "prompt_version": prompt.version, "prompt_sha256": prompt.sha256,
                "schema": translation_response_schema(), "schema_version": RESPONSE_SCHEMA_VERSION,
                "glossary_path": str(Path(glossary_path).absolute()) if resource else None,
                "glossary_sha256": resource.sha256 if resource else None,
                "term_match_version": TERM_MATCH_VERSION,
                "provider": (self.artifacts.read_json(str(workspace / canonical_filename(ArtifactType.TRANSLATION_MANIFEST)))["identity"]["provider"]
                             if _verify else provider_identity.to_dict()),
                "configuration_sha256": getattr(self.provider, "configuration_sha256", None),
                "requests": [request.to_dict() for request in requests],
            }
        except ProviderError as error:
            raise TranslationProviderFailure(f"translation provider configuration failed ({error.code})") from error
        except Exception as error:
            raise TranslationInputError("translation configuration invalid") from error
        result_path, manifest_path = str(workspace / canonical_filename(ArtifactType.TRANSLATION_RESULT)), str(workspace / canonical_filename(ArtifactType.TRANSLATION_MANIFEST))
        occupied = self.artifacts.exists(result_path), self.artifacts.exists(manifest_path)
        if not overwrite and any(occupied):
            if not all(occupied):
                raise TranslationArtifactConflict("incomplete translation output pair")
            try:
                result = ChunkTranslationResultDTO.from_dict(self.artifacts.read_json(result_path))
                result.validate_against_inputs(alignment, chunks)
                manifest = StageManifestDTO.from_dict(self.artifacts.read_json(manifest_path))
                output = evidence(result_path, self.artifacts, self.checksum)
                if manifest.stage != "translation" or manifest.asset_id != asset_id or manifest.inputs != inputs or canonical_json_sha256(manifest.identity) != canonical_json_sha256(identity) or manifest.outputs != {"translation_result": output} or result.source_chunks_sha256 != inputs["source_chunks"].sha256:
                    raise ValueError("translation identity/evidence differs")
            except Exception as error:
                raise TranslationArtifactConflict("translation output pair failed verification") from error
            return TranslationRunResult("reused", result_path, manifest_path, len(requests), 0, 0, output.sha256)
        if _verify:
            raise TranslationArtifactConflict("verified translation outputs are missing")
        translated, titles, checkpoint_hits, calls = [], [], 0, 0
        input_tokens, output_tokens, unknown_usage_count = 0, 0, 0
        for batch_number, request in enumerate(requests, 1):
            batch_identity = CheckpointCacheKeyInput.from_request(
                source_alignment_sha256=inputs["source_alignment"].sha256,
                source_chunks_sha256=inputs["source_chunks"].sha256, request=request,
                prompt_version=prompt.version, prompt_sha256=prompt.sha256,
                glossary_sha256=identity["glossary_sha256"], provider_identity=provider_identity,
            )
            key = canonical_json_sha256({"batch": batch_identity.to_dict(),
                "inputs": {k: v.to_dict() for k, v in inputs.items()}, "schema": identity["schema"],
                "term_match_version": TERM_MATCH_VERSION, "configuration_sha256": identity["configuration_sha256"]})
            if self.checkpoints.exists(key):
                try:
                    checkpoint = self.checkpoints.read(key)
                    if set(checkpoint) != {"schema_version", "cache_key", "output"} or checkpoint["schema_version"] != CHECKPOINT_SCHEMA_VERSION or checkpoint["cache_key"] != key:
                        raise ValueError("checkpoint identity mismatch")
                    validated = validate_provider_response(request, ProviderResponse(ProviderStatus.COMPLETED, checkpoint["output"], 1))
                    checkpoint_hits += 1
                    self.logger.log("translation_checkpoint_reused", {"asset_id": asset_id, "request_id": batch_number})
                except Exception as error:
                    raise TranslationCheckpointError("batch checkpoint failed verification") from error
            else:
                call = ProviderCall(instructions, request, translation_response_schema(), max_attempts)
                response = None
                for attempt in range(1, max_attempts + 1):
                    calls += 1
                    self.logger.log("translation_attempt", {"asset_id": asset_id, "request_id": batch_number, "attempt": attempt})
                    try:
                        response = self.provider.translate(call)
                        break
                    except ProviderError as error:
                        if error.category != ProviderErrorCategory.TRANSIENT or attempt == max_attempts:
                            raise TranslationProviderFailure(f"translation provider failed ({error.code})") from error
                        self.sleeper.sleep(error.retry_after_seconds if error.retry_after_seconds is not None else float(2 ** attempt))
                    except Exception as error:
                        raise TranslationProviderFailure("translation provider failed") from error
                try:
                    validated = validate_provider_response(request, response)
                except Exception as error:
                    raise TranslationProviderFailure("invalid chunk translation response") from error
                if response.usage is None:
                    unknown_usage_count += 1
                else:
                    input_tokens += response.usage.input_tokens
                    output_tokens += response.usage.output_tokens
                try:
                    self.checkpoints.write(key, {"schema_version": CHECKPOINT_SCHEMA_VERSION, "cache_key": key, "output": validated.to_dict()}, overwrite=overwrite)
                except Exception as error:
                    raise TranslationCheckpointError("batch checkpoint publication failed") from error
            translated.extend(ChunkTranslationDTO(item.id, item.translated_text) for item in validated.items)
            if validated.section:
                titles.append(SectionTitleTranslationDTO(validated.section.id, validated.section.translated_title))
        result = ChunkTranslationResultDTO(asset_id, inputs["source_alignment"].sha256,
            inputs["source_chunks"].sha256, tuple(translated), tuple(titles))
        result.validate_against_inputs(alignment, chunks)
        # Rehash all inputs after provider calls/checkpoints, before any formal publication.
        for item in inputs.values():
            verify_evidence(item, self.artifacts, self.checksum)
        def manifest_factory(size, sha):
            return StageManifestDTO("translation", asset_id, inputs,
                {"translation_result": ArtifactEvidenceDTO(result_path, size, sha)}, identity,
                self.clock.now_utc(), {"provider_calls": calls, "request_count": len(requests),
                    "checkpoint_reuse_count": checkpoint_hits, "input_tokens": input_tokens,
                    "output_tokens": output_tokens, "unknown_usage_count": unknown_usage_count}).to_dict()
        try:
            _, sha = self.artifacts.publish_json_pair(result_path, result.to_dict(), manifest_path,
                                                     manifest_factory, overwrite=overwrite)
        except Exception as error:
            raise TranslationPublicationError("translation publication failed") from error
        return TranslationRunResult("succeeded", result_path, manifest_path, len(requests), checkpoint_hits, calls, sha)
