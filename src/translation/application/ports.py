"""Provider-neutral ports used by the translation workflow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol

from translation.domain import (
    ProviderCall,
    ProviderIdentity,
    ProviderResponse,
    TranslationGlossary,
)


class TranslationProvider(Protocol):
    @property
    def identity(self) -> ProviderIdentity: ...

    def translate(self, call: ProviderCall) -> ProviderResponse: ...


class ChecksumService(Protocol):
    def sha256(self, path: str) -> str: ...


class TranslationArtifactStore(Protocol):
    def exists(self, path: str) -> bool: ...

    def size(self, path: str) -> int: ...

    def read_json(self, path: str) -> Mapping[str, Any]: ...

    def publish_json_pair(
        self,
        result_path: str,
        result_data: Mapping[str, Any],
        manifest_path: str,
        manifest_factory: Callable[[int, str], Mapping[str, Any]],
        *,
        overwrite: bool,
    ) -> tuple[int, str]: ...


@dataclass(frozen=True)
class PromptResource:
    version: str
    text: str
    sha256: str


class PromptLoader(Protocol):
    def load(self) -> PromptResource: ...


@dataclass(frozen=True)
class GlossaryResource:
    glossary: TranslationGlossary
    sha256: str


class GlossaryLoader(Protocol):
    def load(self, path: str) -> GlossaryResource: ...


class CheckpointStore(Protocol):
    def exists(self, cache_key: str) -> bool: ...

    def read(self, cache_key: str) -> Mapping[str, Any]: ...

    def write(
        self, cache_key: str, data: Mapping[str, Any], *, overwrite: bool
    ) -> None: ...


class Sleeper(Protocol):
    def sleep(self, seconds: float) -> None: ...


class Clock(Protocol):
    def now_utc(self) -> str: ...


class MetadataLogger(Protocol):
    def log(self, event: str, metadata: Mapping[str, object]) -> None: ...
