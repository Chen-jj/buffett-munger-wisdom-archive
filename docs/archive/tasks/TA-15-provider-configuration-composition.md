# TA-15 — Add explicit provider configuration and production composition

- **Status:** accepted
- **Module:** translation configuration/composition and authoritative offline status
- **Decision coverage:** ADR-0005 sections 5, 9, 11.2, and 12 steps 5–7
- **Depends on:** TA-14
- **Depended on by:** TA-16

## Goal

Make the execution channel an explicit validated choice, select Codex CLI in the
repository configuration, preserve OpenAI as an opt-in alternative, and close
the ADR-0005 offline verification gate.

## Exact scope

- Require `translation.provider` to be exactly `codex-cli-chatgpt` or
  `openai-responses`; missing or unknown values fail with no implicit default.
- Add translation-owned configuration validation and one production composition
  path usable by the integration runner. The shared YAML loader must remain
  feature-neutral and domain/application must not read global YAML.
- Validate Codex settings as accepted: a single executable name/path (the
  repository configuration uses `codex`, never a wrapper command), model
  `gpt-5.6-sol`, effort `high`, and timeout 1800 seconds. Keep the current OpenAI
  block and production adapter selectable without changing its fixed settings.
- Update `config.yaml` to select `codex-cli-chatgpt` and contain both non-secret
  provider blocks. Never place credentials, auth contents, custom endpoints, or
  wrapper commands in configuration/provenance/logs.
- Prove composition selects exactly one provider, never falls back, and reports
  explicit configuration errors. Add cross-provider formal-artifact conflict
  tests in both directions and full identity/cache-key variation coverage.
- Run the complete offline suite and inspect the diff for secrets. Update root,
  `archive_core`, `translation`, and `infrastructure` module guides plus ADR
  implementation wording only to report observed offline implementation; leave
  Codex live acceptance pending TA-16.

## Non-goals

- Do not remove the OpenAI adapter, run either real provider, add a general CLI
  entry point, or add automatic provider/model fallback.
- Do not claim ChatGPT entitlement, live translation quality, or live reuse
  before TA-16 succeeds.

## Acceptance criteria

1. Missing/unknown provider and invalid fixed settings fail before model work;
   valid configuration constructs exactly the selected adapter.
2. Repository configuration explicitly selects Codex CLI while retaining the
   complete non-secret OpenAI alternative.
3. Offline tests prove no fallback/mixing and symmetric cross-provider artifact
   conflicts; all existing OpenAI mock tests continue to pass.
4. Authoritative docs distinguish offline-complete from still-pending Codex live
   acceptance and contain no claim that TA-10 succeeded.
5. The full offline suite and whitespace/secret review pass.

## Verification

```bash
python -m pytest tests/translation/ -q -m "not live"
python -m pytest tests/ -q -m "not live"
git diff --check
git diff -- config.yaml AGENTS.md src/archive_core/AGENTS.md \
  src/infrastructure/AGENTS.md src/translation/AGENTS.md \
  docs/archive/decisions/0002-translation-sentence-units.md \
  docs/archive/decisions/0005-translation-codex-cli-chatgpt-provider.md
```

- **Full offline suite required:** yes
- **Live test:** no; Codex CLI live remains pending TA-16
