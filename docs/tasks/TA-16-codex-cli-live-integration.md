# TA-16 — Run the gated Codex CLI ChatGPT translation integration

- **Status:** accepted
- **Module:** translation live test and final authoritative status
- **Decision coverage:** ADR-0005 sections 11.3 and 12 step 8; ADR-0002 live completion
- **Depends on:** TA-15
- **Depended on by:** final technical-lead acceptance
- **Gate:** live; explicit opt-in and authenticated ChatGPT/Codex entitlement

## Goal

Use the production Codex provider and composition to prove real two-section
translation, public provenance/checksums, human quality, and zero-call formal
reuse without using the OpenAI Responses live provider.

## Exact scope

- Convert the existing translation live integration in place to a Codex-only
  test gated by `RUN_CODEX_CLI_TRANSLATION_INTEGRATION=1`. Remove the obsolete
  paid-OpenAI gate from executable test behavior while preserving the OpenAI
  production adapter and offline mock coverage.
- Require a supported local Codex CLI and preflight-confirmed ChatGPT login. The
  test must not call `codex login`, change global auth, or require/pass an OpenAI
  API key; the production child environment must omit `OPENAI_API_KEY` even if
  the parent happens to define it.
- Reuse TA-10's small canonical two-section fixture with titles, 2–3 sentences
  per section, finance terminology, a number, negation, and proper nouns. Invoke
  the production configuration/composition with `codex-cli-chatgpt`.
- Assert complete ordered non-empty title/sentence coverage, public path/size/
  checksum chain, exactly two logical section requests, null token usage/request
  IDs where unavailable, and the full fixed Codex provider identity including
  actual CLI version.
- Immediately run the same command again and prove formal result/manifest reuse,
  unchanged checksum, zero provider/process calls, zero attempts, and no second
  use of ChatGPT quota.
- Print or preserve artifacts only in an isolated temporary/gitignored workspace
  long enough for human inspection. Record whether the title, financial terms,
  number, negation, and proper nouns are reasonable; never commit model output or
  turn exact Chinese phrasing into a brittle assertion.
- After a successful observed run, update ADR-0002, ADR-0005, root/module current
  status, timestamps, and task status. If prerequisites or the real call fail,
  leave live-success wording unchanged and report the exact blocker; do not
  weaken preflight, switch model/provider, or fall back to OpenAI.

## Non-goals

- Do not run the OpenAI live test, use the long CNBC/WhisperX fixture, assert
  exact Chinese wording/token counts, store credentials/output in git, or alter
  production semantics to make a nondeterministic response pass.

## Acceptance criteria

1. Default offline pytest skips all real Codex/network work and the full offline
   suite passes before the live call.
2. Preflight proves supported Codex CLI plus ChatGPT login and the child process
   has no OpenAI API credential.
3. One gated real run publishes a valid two-section pair with correct Codex
   identity, coverage/order, checksum/config evidence, and no mixed provider.
4. Immediate second execution performs zero provider/process calls and reuses
   byte-identical canonical output.
5. Human inspection records reasonable handling of every requested quality
   signal, and authoritative docs claim only what was actually observed.

## Verification

```bash
python -m pytest tests/ -q -m "not live"

# LIVE GATE — uses the current ChatGPT/Codex login, never OPENAI_API_KEY
env -u OPENAI_API_KEY RUN_CODEX_CLI_TRANSLATION_INTEGRATION=1 \
  .venv/bin/python -m pytest tests/translation/test_integration_live.py -q -s

python -m pytest tests/ -q -m "not live"
git diff --check
```

- **Full offline suite required:** yes, before and after live
- **Live test:** required and explicitly gated
