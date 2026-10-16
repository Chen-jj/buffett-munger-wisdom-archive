"""Canonical translation request and checkpoint cache identities."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from .models import ProviderIdentity, TranslationRequest
from .response import RESPONSE_SCHEMA_VERSION
from .serialization import canonical_json_sha256


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _require_sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _require_non_blank(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-blank string")
    return value


@dataclass(frozen=True)
class CheckpointCacheKeyInput:
    source_alignment_sha256: str
    request_sha256: str
    source_language: str
    target_language: str
    prompt_version: str
    prompt_sha256: str
    glossary_sha256: str | None
    response_schema_version: str
    provider_identity: ProviderIdentity

    def __post_init__(self) -> None:
        _require_sha256(self.source_alignment_sha256, "source_alignment_sha256")
        _require_sha256(self.request_sha256, "request_sha256")
        _require_non_blank(self.source_language, "source_language")
        _require_non_blank(self.target_language, "target_language")
        _require_non_blank(self.prompt_version, "prompt_version")
        _require_sha256(self.prompt_sha256, "prompt_sha256")
        if self.glossary_sha256 is not None:
            _require_sha256(self.glossary_sha256, "glossary_sha256")
        _require_non_blank(self.response_schema_version, "response_schema_version")
        if not isinstance(self.provider_identity, ProviderIdentity):
            raise ValueError("provider_identity must be a ProviderIdentity")

    @classmethod
    def from_request(
        cls,
        *,
        source_alignment_sha256: str,
        request: TranslationRequest,
        prompt_version: str,
        prompt_sha256: str,
        glossary_sha256: str | None,
        provider_identity: ProviderIdentity,
        response_schema_version: str = RESPONSE_SCHEMA_VERSION,
    ) -> "CheckpointCacheKeyInput":
        if not isinstance(request, TranslationRequest):
            raise ValueError("request must be a TranslationRequest")
        return cls(
            source_alignment_sha256=source_alignment_sha256,
            request_sha256=request.checksum(),
            source_language=request.source_language,
            target_language=request.target_language,
            prompt_version=prompt_version,
            prompt_sha256=prompt_sha256,
            glossary_sha256=glossary_sha256,
            response_schema_version=response_schema_version,
            provider_identity=provider_identity,
        )

    def to_dict(self) -> dict[str, Any]:
        identity = self.provider_identity.to_dict()
        return {
            "source_alignment_sha256": self.source_alignment_sha256,
            "request_sha256": self.request_sha256,
            "source_language": self.source_language,
            "target_language": self.target_language,
            "prompt_version": self.prompt_version,
            "prompt_sha256": self.prompt_sha256,
            "glossary_sha256": self.glossary_sha256,
            "response_schema_version": self.response_schema_version,
            "provider": identity["provider"],
            "model": identity["model"],
            "generation_parameters": identity["generation_parameters"],
        }

    def cache_key(self) -> str:
        return canonical_json_sha256(self.to_dict())


def compute_checkpoint_cache_key(inputs: CheckpointCacheKeyInput) -> str:
    if not isinstance(inputs, CheckpointCacheKeyInput):
        raise ValueError("inputs must be a CheckpointCacheKeyInput")
    return inputs.cache_key()
