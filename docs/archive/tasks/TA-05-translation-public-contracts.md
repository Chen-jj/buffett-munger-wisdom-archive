# TA-05 — Publish translation result and manifest contracts

- **Status:** accepted
- **Module:** `archive_core`
- **Decision coverage:** ADR-0002 sections 7, 10–13, 14.1
- **Depends on:** TA-04
- **Depended on by:** TA-06

## Goal

Publish the canonical filenames and strict public DTOs that let translation and
future downstream modules exchange a translation result and its successful
manifest without importing translation internals.

## Exact scope

- Add `ArtifactType.TRANSLATION_RESULT` / `translation_result.json` and
  `ArtifactType.TRANSLATION_MANIFEST` / `translation_manifest.json`.
- Add explicit versioned public DTOs for `translation.result.v1` and
  `translation.manifest.v1`, including their nested section/sentence,
  input/output, translation provenance, generation-parameter, and execution
  values described by ADR-0002.
- Validate exact schema versions, required field types, non-empty translated
  sentence text, section-title nullability, duplicate IDs, source order and full
  coverage against a supplied `SourceAlignmentDTO`.
- Keep result content provider-neutral and free of English source text, timing,
  speaker, model, prompt, usage, and timestamps.
- Keep manifest content auditable and strict: succeeded status, asset/input/output
  evidence, prompt/glossary/provider/model/generation parameters, nullable usage,
  and non-negative execution counts.
- Export contracts through `archive_core.interfaces` and add isolated public
  contract tests.

Primary ownership:

- `src/archive_core/domain/artifacts.py`
- a new `src/archive_core/interfaces/translation.py`
- `src/archive_core/interfaces/__init__.py`
- a new archive-core translation contract test file

## Non-goals

- Do not plan model requests, parse provider responses, or read files.
- Do not define checkpoint schema in `archive_core`; checkpoints are private.
- Do not implement relaxed or heuristic translation-quality checks.
- Do not modify the source alignment contract established by TA-01.

## Acceptance criteria

1. Result and manifest valid examples round-trip with deterministic field order.
2. Unknown versions, extra/missing data, duplicate IDs, invalid nullability, and
   empty sentence translations fail.
3. Alignment-aware validation proves exact section/sentence ID order and
   complete coverage, including empty source titles mapping to null translated
   titles and `sections=[]` mapping to no title translations.
4. Canonical filename tests cover both new artifact types.
5. All offline tests pass.

## Verification

```bash
python -m pytest tests/archive_core/test_translation_contracts.py -q
python -m pytest tests/archive_core/ -q
python -m pytest tests/ -q -m "not live"
```

- **Full offline suite required:** yes
- **Live test:** no
