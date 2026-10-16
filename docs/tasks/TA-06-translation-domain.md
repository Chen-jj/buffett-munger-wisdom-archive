# TA-06 — Implement translation domain and request planning

- **Status:** accepted
- **Module:** `translation/domain`
- **Decision coverage:** ADR-0002 sections 4–9, 12–14.1
- **Depends on:** TA-05
- **Depended on by:** TA-07

## Goal

Implement pure provider-neutral translation concepts and deterministic rules for
glossary validation, section/document request planning, response validation, and
checkpoint cache keys.

## Exact scope

- Create the translation package/domain structure and public domain exports.
- Define immutable request items/section, provider identity/call/response/usage,
  provider statuses, and explicit transient/permanent error categories without
  importing the OpenAI SDK.
- Plan one request per complete source section in source order, or one full
  document request when `sections=[]`. Request payloads contain only language,
  section ID/title, and sentence ID/text.
- Define the strict static response JSON schema and deterministic validation for
  exact fields, section ID/null/title rules, item count, ID order/coverage, and
  non-blank translated text.
- Validate `translation.glossary.v1`: non-empty source/target and no one source
  mapping to different targets. Do not add content-inclusion heuristics.
- Add a versioned prompt resource at the exact ADR path and a pure renderer that
  incorporates the fixed rules and optional glossary while treating all source
  text as data.
- Compute canonical JSON checksums/cache keys from every ADR input: complete
  alignment checksum, request checksum, languages, prompt version/checksum,
  optional glossary checksum, response-schema version, provider/model identity,
  and generation parameters.

This task owns new domain files, the prompt resource, and domain tests. It must
not edit later application or provider-adapter files.

## Non-goals

- Do not access manifests, files, environment variables, network, SDK, or sleep.
- Do not estimate tokens, preflight context windows, split a section, merge
  sections, or add provider fallback.
- Do not implement checkpoint persistence, retries, or canonical publication.

## Acceptance criteria

1. Section and no-section planners create the exact request boundaries and never
   leak speaker, timing, words, or provenance.
2. Response tests reject extra/missing/duplicate/reordered IDs, bad title rules,
   blank text, refused, and incomplete outputs.
3. Glossary round-trip and conflict tests pass.
4. Each individual cache-key input named by ADR-0002 changes the resulting key;
   equivalent canonical mappings do not change it due to dictionary order.
5. Domain tests require no network, SDK, filesystem write, or real sleep.

## Verification

```bash
python -m pytest tests/translation/test_translation_domain.py -q
```

- **Full offline suite required:** no; TA-07 owns the workflow-wide gate
- **Live test:** no
