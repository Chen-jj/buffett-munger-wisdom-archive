# TA-09 — Align configuration, module guides, and offline status

- **Status:** accepted
- **Module:** repository configuration and documentation
- **Decision coverage:** ADR-0002 sections 6.3, 15 steps 6–7; ADR-0004 status
- **Depends on:** TA-08
- **Depended on by:** TA-10

## Goal

Align the repository's non-secret configuration and authoritative implementation
status with the accepted, offline-tested code before any real OpenAI call.

## Exact scope

- Replace legacy translation YAML keys with exactly the ADR-approved non-secret
  settings: `api_key_env`, model, reasoning effort, max output tokens, and
  timeout. Remove legacy `api_key`, `base_url`, `temperature`, and `batch_size`.
- Confirm `requirements.txt` contains the user's existing exact
  `openai==3.31.0` pin; preserve that uncommitted edit rather than replacing or
  broadening it.
- Rewrite `src/translation/AGENTS.md` to describe source sentences/sections,
  provider-neutral application boundaries, checkpoint/publication rules, and
  offline/live test gates. Remove the obsolete SRT/cue responsibility.
- Update `src/archive_core/AGENTS.md`, `src/transcription/AGENTS.md`, root
  `AGENTS.md`, and accepted ADR status wording only where the now-verified
  implementation changed factual state. Use the current verification timestamp.
- State truthfully that translation has offline coverage and that OpenAI live
  acceptance remains pending TA-10; do not claim live success early.
- Run the complete offline suite and inspect the full diff for secrets and
  unrelated edits.

## Non-goals

- Do not add new business logic or refactor configuration loading.
- Do not add a real API key, endpoint, output artifact, or model response.
- Do not run or edit the live integration test; TA-10 owns it.
- Do not restore deleted legacy pipeline/roadmap files.

## Acceptance criteria

1. `config.yaml` contains no credential value or obsolete translation keys and
   matches the adapter defaults exactly.
2. The OpenAI dependency remains exactly pinned to 3.31.0.
3. Module and root guides accurately describe implemented contracts, tests, and
   still-pending live status; their implementation-state timestamp is current.
4. ADR status text no longer says implemented offline work is wholly pending,
   while still identifying the TA-10 live gate.
5. The full offline suite passes and `git diff --check` is clean.

## Verification

```bash
python -m pytest tests/ -q -m "not live"
git diff --check
git diff -- config.yaml requirements.txt AGENTS.md \
  src/archive_core/AGENTS.md src/transcription/AGENTS.md src/translation/AGENTS.md \
  docs/decisions/0002-translation-sentence-units.md \
  docs/decisions/0004-transcription-source-sections.md
```

- **Full offline suite required:** yes
- **Live test:** no; it remains pending TA-10
