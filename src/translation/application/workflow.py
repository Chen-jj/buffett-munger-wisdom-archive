"""Provider-neutral, resumable translation workflow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from archive_core.application import build_asset_workspace
from archive_core.domain import ArtifactType, AssetId, canonical_filename
from archive_core.interfaces import (
    SectionTitleTranslationDTO,
    SentenceTranslationDTO,
    SourceAlignmentDTO,
    TranslationExecutionDTO,
    TranslationGenerationParametersDTO,
    TranslationInputDTO,
    TranslationManifestDTO,
    TranslationOutputDTO,
    TranslationProvenanceDTO,
    TranslationResultDTO,
)
from translation.domain import (
    PROMPT_VERSION,
    RESPONSE_SCHEMA_VERSION,
    CheckpointCacheKeyInput,
    ProviderCall,
    ProviderError,
    ProviderErrorCategory,
    ProviderResponse,
    ProviderStatus,
    TranslationRequest,
    ValidatedTranslationOutput,
    plan_translation_requests,
    render_translation_instructions,
    translation_response_schema,
    validate_provider_response,
)

from .ports import (
    CheckpointStore,
    ChecksumService,
    Clock,
    GlossaryLoader,
    MetadataLogger,
    PromptLoader,
    Sleeper,
    TranslationArtifactStore,
    TranslationProvider,
)


TRANSCRIPTION_MANIFEST_SCHEMA = "transcription.audio-vad-asr-cache.v1"
CHECKPOINT_SCHEMA_VERSION = "translation.checkpoint.v1"
_LOG_KEYS = {
    "asset_id", "request_kind", "request_id", "sentence_count", "checkpoint",
    "provider", "model", "attempt", "error_category", "output_path", "checksum",
}


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


class TranslationWorkflow:
    def __init__(
        self,
        *,
        provider: TranslationProvider,
        checksum: ChecksumService,
        artifacts: TranslationArtifactStore,
        prompts: PromptLoader,
        glossaries: GlossaryLoader,
        checkpoints: CheckpointStore,
        sleeper: Sleeper,
        clock: Clock,
        logger: MetadataLogger,
        output_root: str = "output",
    ) -> None:
        self.provider = provider
        self.checksum = checksum
        self.artifacts = artifacts
        self.prompts = prompts
        self.glossaries = glossaries
        self.checkpoints = checkpoints
        self.sleeper = sleeper
        self.clock = clock
        self.logger = logger
        self.output_root = output_root

    def execute(
        self,
        *,
        asset_id: str,
        transcription_manifest_path: str,
        glossary_path: str | None,
        overwrite: bool,
        max_attempts: int,
    ) -> TranslationRunResult:
        if not isinstance(overwrite, bool):
            raise TranslationInputError("overwrite must be a boolean")
        if (
            isinstance(max_attempts, bool)
            or not isinstance(max_attempts, int)
            or max_attempts <= 0
        ):
            raise TranslationInputError("max_attempts must be a positive integer")
        asset = _parse_asset_id(asset_id)
        workspace = build_asset_workspace(asset, self.output_root)
        expected_manifest = (
            workspace / canonical_filename(ArtifactType.TRANSCRIPTION_MANIFEST)
        )
        if Path(transcription_manifest_path) != expected_manifest:
            raise TranslationInputError("transcription manifest path is not canonical")
        alignment_path = workspace / canonical_filename(ArtifactType.SOURCE_ALIGNMENT)
        result_path = workspace / canonical_filename(ArtifactType.TRANSLATION_RESULT)
        manifest_path = workspace / canonical_filename(ArtifactType.TRANSLATION_MANIFEST)

        alignment, alignment_sha256 = self._load_input(
            asset, transcription_manifest_path, str(alignment_path)
        )
        try:
            prompt = self.prompts.load()
        except Exception as error:
            raise TranslationInputError(f"prompt is missing or invalid: {error}") from error
        if prompt.version != PROMPT_VERSION:
            raise TranslationInputError("prompt version is not supported")
        try:
            glossary_resource = (
                self.glossaries.load(glossary_path) if glossary_path is not None else None
            )
        except Exception as error:
            raise TranslationInputError(f"glossary is missing or invalid: {error}") from error
        glossary = glossary_resource.glossary if glossary_resource else None
        glossary_sha256 = glossary_resource.sha256 if glossary_resource else None
        instructions = render_translation_instructions(prompt.text, glossary)
        requests = plan_translation_requests(alignment)
        provenance = self._provenance(
            prompt.sha256, glossary_path, glossary_sha256
        )

        existing = self._reuse_existing(
            asset_id=asset_id,
            alignment=alignment,
            alignment_sha256=alignment_sha256,
            result_path=str(result_path),
            manifest_path=str(manifest_path),
            provenance=provenance,
            overwrite=overwrite,
        )
        if existing is not None:
            return existing

        translated_sections: list[SectionTitleTranslationDTO] = []
        translated_sentences: list[SentenceTranslationDTO] = []
        checkpoint_hits = 0
        attempts = 0
        usages: list[tuple[int, int] | None] = []

        for request in requests:
            key_input = CheckpointCacheKeyInput.from_request(
                source_alignment_sha256=alignment_sha256,
                request=request,
                prompt_version=prompt.version,
                prompt_sha256=prompt.sha256,
                glossary_sha256=glossary_sha256,
                provider_identity=self.provider.identity,
                response_schema_version=RESPONSE_SCHEMA_VERSION,
            )
            cache_key = key_input.cache_key()
            request_id = request.section.id if request.section is not None else "document"
            self._log(
                "translation_request",
                asset_id=asset_id,
                request_kind="section" if request.section is not None else "document",
                request_id=request_id,
                sentence_count=len(request.items),
                checkpoint="miss" if overwrite else "lookup",
                provider=self.provider.identity.provider,
                model=self.provider.identity.model,
            )
            if not overwrite and self.checkpoints.exists(cache_key):
                output = self._load_checkpoint(cache_key, key_input.request_sha256, request)
                checkpoint_hits += 1
                self._log(
                    "translation_checkpoint",
                    asset_id=asset_id,
                    request_id=request_id,
                    checkpoint="hit",
                )
            else:
                call = ProviderCall(
                    instructions=instructions,
                    request=request,
                    output_schema=translation_response_schema(),
                    max_attempts=max_attempts,
                )
                response, call_attempts = self._call_provider(
                    call, asset_id, request_id, max_attempts
                )
                attempts += call_attempts
                try:
                    output = validate_provider_response(request, response)
                except (ValueError, TypeError) as error:
                    raise TranslationProviderFailure(str(error)) from error
                usages.append(
                    (response.usage.input_tokens, response.usage.output_tokens)
                    if response.usage is not None
                    else None
                )
                checkpoint = {
                    "schema_version": CHECKPOINT_SCHEMA_VERSION,
                    "cache_key": cache_key,
                    "request_sha256": key_input.request_sha256,
                    "output": output.to_dict(),
                }
                try:
                    self.checkpoints.write(cache_key, checkpoint, overwrite=overwrite)
                except Exception as error:
                    raise TranslationCheckpointError(
                        f"checkpoint could not be persisted: {error}"
                    ) from error
            if output.section is not None:
                translated_sections.append(
                    SectionTitleTranslationDTO(
                        section_id=output.section.id,
                        translated_title=output.section.translated_title,
                    )
                )
            translated_sentences.extend(
                SentenceTranslationDTO(
                    sentence_id=item.id, translated_text=item.translated_text
                )
                for item in output.items
            )

        result = TranslationResultDTO(
            source_alignment_sha256=alignment_sha256,
            source_language=alignment.language,
            target_language="zh-Hans",
            section_title_translations=tuple(translated_sections),
            sentence_translations=tuple(translated_sentences),
        )
        result.validate_against_alignment(alignment)
        token_counts = _token_totals(usages)
        execution = TranslationExecutionDTO(
            request_count=len(requests),
            checkpoint_reuse_count=checkpoint_hits,
            attempt_count=attempts,
            input_tokens=token_counts[0],
            output_tokens=token_counts[1],
        )

        def manifest_factory(size_bytes: int, result_sha256: str) -> Mapping[str, Any]:
            return TranslationManifestDTO(
                asset_id=asset_id,
                status="succeeded",
                completed_at=self.clock.now_utc(),
                input=TranslationInputDTO(
                    path=canonical_filename(ArtifactType.SOURCE_ALIGNMENT),
                    sha256=alignment_sha256,
                ),
                translation=provenance,
                output=TranslationOutputDTO(
                    path=canonical_filename(ArtifactType.TRANSLATION_RESULT),
                    size_bytes=size_bytes,
                    sha256=result_sha256,
                ),
                execution=execution,
            ).to_dict()

        try:
            _, result_sha256 = self.artifacts.publish_json_pair(
                str(result_path),
                result.to_dict(),
                str(manifest_path),
                manifest_factory,
                overwrite=overwrite,
            )
        except Exception as error:
            raise TranslationPublicationError(
                f"translation artifact pair could not be published: {error}"
            ) from error
        self._log(
            "translation_published",
            asset_id=asset_id,
            output_path=str(result_path),
            checksum=result_sha256,
        )
        return TranslationRunResult(
            status="succeeded",
            result_path=str(result_path),
            manifest_path=str(manifest_path),
            request_count=len(requests),
            checkpoint_reuse_count=checkpoint_hits,
            attempt_count=attempts,
            result_sha256=result_sha256,
        )

    def _load_input(
        self, asset: AssetId, manifest_path: str, alignment_path: str
    ) -> tuple[SourceAlignmentDTO, str]:
        try:
            manifest = self.artifacts.read_json(manifest_path)
            if set(manifest) != {"schema_version", "asset", "records", "workflow"}:
                raise ValueError("transcription manifest fields are invalid")
            if manifest.get("schema_version") != TRANSCRIPTION_MANIFEST_SCHEMA:
                raise ValueError("unsupported transcription manifest schema")
            manifest_asset = manifest.get("asset")
            if not isinstance(manifest_asset, Mapping):
                raise ValueError("transcription manifest asset is invalid")
            if set(manifest_asset) != {"source", "group", "item"}:
                raise ValueError("transcription manifest asset fields are invalid")
            recorded_asset = AssetId(
                source=manifest_asset.get("source"),
                group=manifest_asset.get("group", ""),
                item=manifest_asset.get("item"),
            )
            if recorded_asset != asset:
                raise ValueError("transcription manifest asset identity is invalid")
            workflow = manifest.get("workflow")
            if not isinstance(workflow, Mapping) or workflow.get("status") != "succeeded":
                raise ValueError("transcription workflow did not succeed")
            records = manifest.get("records")
            if not isinstance(records, Mapping):
                raise ValueError("transcription manifest records are invalid")
            for name, value in records.items():
                if not isinstance(name, str) or not isinstance(value, Mapping):
                    raise ValueError("transcription manifest record is invalid")
                _validate_transcription_record(value)
            record = records.get("source_alignment")
            if not isinstance(record, Mapping) or record.get("status") != "succeeded":
                raise ValueError("successful source_alignment record is missing")
            if Path(str(record.get("path"))) != Path(alignment_path):
                raise ValueError("source_alignment record path is not canonical")
            size = record.get("size_bytes")
            sha256 = record.get("sha256")
            if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
                raise ValueError("source_alignment size evidence is invalid")
            if self.artifacts.size(alignment_path) != size:
                raise ValueError("source_alignment size does not match manifest")
            actual_sha256 = self.checksum.sha256(alignment_path)
            if sha256 != actual_sha256:
                raise ValueError("source_alignment checksum does not match manifest")
            alignment = SourceAlignmentDTO.from_dict(
                self.artifacts.read_json(alignment_path)
            )
            if alignment.language != "en":
                raise ValueError("source alignment language must be en")
            return alignment, actual_sha256
        except TranslationInputError:
            raise
        except Exception as error:
            raise TranslationInputError(str(error)) from error

    def _provenance(
        self,
        prompt_sha256: str,
        glossary_path: str | None,
        glossary_sha256: str | None,
    ) -> TranslationProvenanceDTO:
        identity = self.provider.identity
        try:
            parameters = TranslationGenerationParametersDTO.from_dict(
                dict(identity.generation_parameters)
            )
        except (ValueError, TypeError, KeyError) as error:
            raise TranslationInputError(
                "provider generation parameters do not match the public contract"
            ) from error
        return TranslationProvenanceDTO(
            source_language="en",
            target_language="zh-Hans",
            prompt_version=PROMPT_VERSION,
            prompt_sha256=prompt_sha256,
            glossary_path=glossary_path,
            glossary_sha256=glossary_sha256,
            provider=identity.provider,
            model=identity.model,
            generation_parameters=parameters,
        )

    def _reuse_existing(
        self,
        *,
        asset_id: str,
        alignment: SourceAlignmentDTO,
        alignment_sha256: str,
        result_path: str,
        manifest_path: str,
        provenance: TranslationProvenanceDTO,
        overwrite: bool,
    ) -> TranslationRunResult | None:
        result_exists = self.artifacts.exists(result_path)
        manifest_exists = self.artifacts.exists(manifest_path)
        if overwrite:
            return None
        if not result_exists and not manifest_exists:
            return None
        if result_exists != manifest_exists:
            raise TranslationArtifactConflict(
                "translation result/manifest pair is incomplete"
            )
        try:
            result = TranslationResultDTO.from_dict(self.artifacts.read_json(result_path))
            result.validate_against_alignment(alignment)
            manifest = TranslationManifestDTO.from_dict(
                self.artifacts.read_json(manifest_path)
            )
            if manifest.asset_id != asset_id:
                raise ValueError("translation manifest asset identity differs")
            if result.source_alignment_sha256 != alignment_sha256:
                raise ValueError("translation result input checksum differs")
            if manifest.input.sha256 != alignment_sha256:
                raise ValueError("translation manifest input checksum differs")
            if manifest.translation != provenance:
                raise ValueError("translation configuration differs")
            size = self.artifacts.size(result_path)
            sha256 = self.checksum.sha256(result_path)
            if manifest.output.size_bytes != size or manifest.output.sha256 != sha256:
                raise ValueError("translation result evidence differs")
        except Exception as error:
            raise TranslationArtifactConflict(str(error)) from error
        return TranslationRunResult(
            status="reused",
            result_path=result_path,
            manifest_path=manifest_path,
            request_count=manifest.execution.request_count,
            checkpoint_reuse_count=manifest.execution.checkpoint_reuse_count,
            attempt_count=0,
            result_sha256=manifest.output.sha256,
        )

    def _load_checkpoint(
        self, cache_key: str, request_sha256: str, request: TranslationRequest
    ) -> ValidatedTranslationOutput:
        try:
            data = self.checkpoints.read(cache_key)
            expected = {"schema_version", "cache_key", "request_sha256", "output"}
            if set(data) != expected:
                raise ValueError("checkpoint fields are invalid")
            if data["schema_version"] != CHECKPOINT_SCHEMA_VERSION:
                raise ValueError("checkpoint schema is invalid")
            if data["cache_key"] != cache_key or data["request_sha256"] != request_sha256:
                raise ValueError("checkpoint identity is stale")
            response = ProviderResponse(
                status=ProviderStatus.COMPLETED,
                output=data["output"],
                attempt_count=1,
            )
            return validate_provider_response(request, response)
        except Exception as error:
            raise TranslationCheckpointError(str(error)) from error

    def _call_provider(
        self,
        call: ProviderCall,
        asset_id: str,
        request_id: str,
        max_attempts: int,
    ) -> tuple[ProviderResponse, int]:
        for attempt in range(1, max_attempts + 1):
            self._log(
                "translation_attempt",
                asset_id=asset_id,
                request_id=request_id,
                attempt=attempt,
            )
            try:
                response = self.provider.translate(call)
            except ProviderError as error:
                self._log(
                    "translation_provider_error",
                    asset_id=asset_id,
                    request_id=request_id,
                    attempt=attempt,
                    error_category=error.code,
                )
                if (
                    error.category != ProviderErrorCategory.TRANSIENT
                    or attempt == max_attempts
                ):
                    raise TranslationProviderFailure(str(error)) from error
                delay = error.retry_after_seconds
                if delay is None:
                    delay = float(2 ** attempt)
                self.sleeper.sleep(delay)
                continue
            except Exception as error:
                raise TranslationProviderFailure(str(error)) from error
            if not isinstance(response, ProviderResponse):
                raise TranslationProviderFailure(
                    "provider returned an invalid response type"
                )
            if response.status != ProviderStatus.COMPLETED:
                raise TranslationProviderFailure(
                    f"provider response status is {response.status.value}"
                )
            return response, attempt
        raise AssertionError("unreachable provider retry loop")

    def _log(self, event: str, **metadata: object) -> None:
        if not set(metadata).issubset(_LOG_KEYS):
            raise ValueError("translation log metadata is not allowlisted")
        self.logger.log(event, metadata)


def _parse_asset_id(value: str) -> AssetId:
    if not isinstance(value, str):
        raise TranslationInputError("asset_id must be a string")
    parts = value.split(":")
    if len(parts) != 3:
        raise TranslationInputError("asset_id must use source:group:item")
    try:
        return AssetId(source=parts[0], group=parts[1], item=parts[2])
    except ValueError as error:
        raise TranslationInputError(str(error)) from error


def _token_totals(usages: list[tuple[int, int] | None]) -> tuple[int | None, int | None]:
    if any(usage is None for usage in usages):
        return None, None
    return (
        sum(usage[0] for usage in usages if usage is not None),
        sum(usage[1] for usage in usages if usage is not None),
    )


def _validate_transcription_record(record: Mapping[str, Any]) -> None:
    if set(record) != {
        "path", "size_bytes", "sha256", "cache_key", "status", "provenance"
    }:
        raise ValueError("transcription manifest record fields are invalid")
    if not isinstance(record["path"], str) or not record["path"].strip():
        raise ValueError("transcription manifest record path is invalid")
    if (
        isinstance(record["size_bytes"], bool)
        or not isinstance(record["size_bytes"], int)
        or record["size_bytes"] <= 0
    ):
        raise ValueError("transcription manifest record size is invalid")
    if (
        not isinstance(record["sha256"], str)
        or len(record["sha256"]) != 64
        or any(character not in "0123456789abcdef" for character in record["sha256"])
    ):
        raise ValueError("transcription manifest record checksum is invalid")
    if not isinstance(record["cache_key"], str) or not record["cache_key"].strip():
        raise ValueError("transcription manifest record cache key is invalid")
    if not isinstance(record["status"], str) or not record["status"].strip():
        raise ValueError("transcription manifest record status is invalid")
    if not isinstance(record["provenance"], Mapping):
        raise ValueError("transcription manifest record provenance is invalid")
