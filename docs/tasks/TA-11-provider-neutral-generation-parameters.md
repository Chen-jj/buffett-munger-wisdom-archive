# TA-11 — Generalize translation generation parameters

- **Status:** accepted
- **Module:** `archive_core` public translation contract and translation provenance
- **Decision coverage:** ADR-0005 section 4; section 11.2 application/contract checks
- **Depends on:** TA-09; TA-10 is superseded and is not a dependency
- **Depended on by:** TA-12

## Goal

Remove the public manifest's accidental OpenAI-only parameter shape so both
accepted providers can publish truthful, deterministic provenance without
changing the `translation.manifest.v1` schema or the existing provider port.

## Exact scope

- Change `TranslationGenerationParametersDTO` from four fixed OpenAI fields to
  a provider-neutral JSON object value used by `TranslationProvenanceDTO`.
- Require every object key, including nested keys, to be a non-empty string and
  accept only finite JSON values: null, booleans, strings, integers, finite
  floats, arrays, and objects. Reject bytes, sets, arbitrary objects, NaN, and
  infinities.
- Prevent caller mutation from changing an already-validated DTO, and return
  plain JSON containers from serialization.
- Keep deterministic round-trip/serialization behavior. The existing OpenAI
  provider must still publish exactly its accepted four keys and values, in the
  existing manifest byte order; do not add an old-DTO compatibility shim.
- Pass the complete mapping unchanged through workflow provenance, formal
  manifest comparison, and cache identity. Prove that any Codex identity field
  change changes the cache key.
- Add focused public-contract, domain/cache, and application tests. Preserve the
  existing OpenAI adapter and all of its tests.

## Non-goals

- Do not implement Codex CLI process execution or configuration.
- Do not change `TranslationProvider`, `ProviderCall`, `ProviderResponse`,
  result schema, retry policy, checkpoints, or publication semantics.
- Do not bump the manifest schema or accept legacy invalid shapes.

## Acceptance criteria

1. Arbitrary valid nested JSON mappings round-trip without mutation or loss;
   empty/non-string keys and non-finite/non-JSON values fail.
2. Existing OpenAI manifest bytes and semantics remain unchanged.
3. Codex-shaped parameters can enter a manifest, and every identity field is
   represented in cache-key input.
4. No provider-specific field is required by the public DTO.
5. The complete offline suite passes.

## Verification

```bash
python -m pytest tests/archive_core/test_translation_contracts.py -q
python -m pytest tests/translation/test_translation_domain.py \
  tests/translation/test_translation_application.py -q
python -m pytest tests/ -q -m "not live"
git diff --check
```

- **Full offline suite required:** yes
- **Live test:** no
