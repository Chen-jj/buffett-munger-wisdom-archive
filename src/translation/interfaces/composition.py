"""Public local composition; providers are constructed lazily on execution."""

from pathlib import Path


def build_translation_handler(*, output_root="output", config_path=None, provider=None,
                              artifacts=None, checksum=None, prompts=None, glossaries=None,
                              checkpoints=None, sleeper=None, clock=None, logger=None):
    from infrastructure.infrastructure.config import load_yaml_config
    from translation.application import TranslationWorkflow
    from translation.infrastructure import (
        LocalCheckpointStore, LocalChecksumService, LocalGlossaryLoader, LocalPromptLoader,
        LocalTranslationArtifactStore, NullMetadataLogger, SystemClock, SystemSleeper,
        build_translation_provider,
    )
    from .workflow import TranslationCommandHandler

    class ConfiguredProvider:
        def __init__(self):
            from translation.domain import canonical_json_sha256
            config = load_yaml_config(config_path)
            self.configuration_sha256 = canonical_json_sha256(config["translation"])
            self._provider = None

        def _get(self):
            if self._provider is None:
                self._provider = build_translation_provider(load_yaml_config(config_path))
            return self._provider

        @property
        def identity(self):
            return self._get().identity

        def translate(self, call):
            return self._get().translate(call)

    return TranslationCommandHandler(TranslationWorkflow(
        output_root=output_root, provider=provider or ConfiguredProvider(),
        artifacts=artifacts or LocalTranslationArtifactStore(),
        checksum=checksum or LocalChecksumService(), prompts=prompts or LocalPromptLoader(),
        glossaries=glossaries or LocalGlossaryLoader(),
        checkpoints=checkpoints or LocalCheckpointStore(str(Path(output_root) / "translation_checkpoints")),
        sleeper=sleeper or SystemSleeper(), clock=clock or SystemClock(),
        logger=logger or NullMetadataLogger(),
        default_glossary_path=str(Path(__file__).parents[1] / "application" / "translation_glossary_v1.json"),
    ))


def build_bilingual_postprocessing_handler(*, output_root="output", config_path=None, provider=None,
                                            artifacts=None, checksum=None, checkpoints=None,
                                            glossaries=None, clock=None):
    from translation.application.postprocessing import BilingualPostprocessingWorkflow
    from .workflow import BilingualPostprocessingCommandHandler
    initial = build_translation_handler(output_root=output_root, config_path=config_path,
        provider=provider, artifacts=artifacts, checksum=checksum, checkpoints=checkpoints,
        glossaries=glossaries, clock=clock).workflow
    return BilingualPostprocessingCommandHandler(BilingualPostprocessingWorkflow(
        output_root=output_root, provider=initial.provider, artifacts=initial.artifacts,
        checksum=initial.checksum, checkpoints=initial.checkpoints,
        glossaries=initial.glossaries, clock=initial.clock, default_glossary_path=initial.default_glossary_path))
