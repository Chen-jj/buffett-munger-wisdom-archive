# TA-10 — Run the gated OpenAI translation integration

- **Status:** superseded
- **Module:** translation live tests and final status documentation
- **Decision coverage:** ADR-0002 sections 14.4 and 15 step 7
- **Depends on:** TA-09
- **Depended on by:** none; superseded by TA-16
- **Gate:** live; paid external API and explicit opt-in

## Supersession

ADR-0005 replaced this uncompleted OpenAI live acceptance with TA-16's Codex
CLI/ChatGPT live acceptance. Preserve the OpenAI Responses production adapter
and its offline tests, but do not run this paid-API gate. This task was not
accepted; its historical scope remains below for traceability.

## Goal

Add and explicitly run the smallest real OpenAI Responses integration that
proves section-aware translation, public artifacts, and second-run formal result
reuse without asserting nondeterministic wording.

## Exact scope

- Add a test marked `live` that skips unless both
  `RUN_TRANSLATION_INTEGRATION=1` and `OPENAI_API_KEY` are present.
- Build a canonical synthetic transcription workspace and successful manifest
  for a small two-section English alignment. Each section has 2–3 complete
  sentences; the sample includes a title, financial terminology, a number,
  negation, and a proper noun.
- Invoke the production composition with the fixed OpenAI provider/model
  settings. Assert two section requests indirectly through manifest execution
  evidence and complete title/sentence ID order/coverage/non-empty output.
- Assert the public result and manifest path/size/SHA-256 chain and fixed
  provider/model/generation parameters.
- Run a second time with identical inputs and assert formal-result `reused`, zero
  provider calls/token usage for that execution, and unchanged canonical
  checksum. The test must not make a second paid API request.
- Do not assert exact Chinese wording. Preserve generated artifacts only in an
  isolated gitignored/temp workspace for human quality inspection when useful.
- After a successful live run, update root and translation module current-state
  facts and verification timestamps, and remove any “live pending” wording from
  the two ADR implementation statuses. If the gate cannot run, leave those facts
  unchanged and report the task blocked.

## Non-goals

- Do not use the long CNBC/WhisperX fixture for this translation API test.
- Do not run live by default, store provider responses in git, or expose the key.
- Do not assert token counts are always present or exact translated phrases.
- Do not change production behavior merely to accommodate nondeterministic text.

## Acceptance criteria

1. The test is absent from default offline execution and clearly documents its
   paid/API prerequisites.
2. The full offline suite passes before the live call.
3. A gated real run produces valid two-section result/manifest artifacts with
   complete ordered non-empty translations and correct checksum/config evidence.
4. The immediate second execution reuses the formal pair and makes no provider
   call.
5. Human inspection records whether title, finance terms, number, negation, and
   proper noun are reasonable, without turning those observations into brittle
   string gates.
6. Final authoritative documentation reports only actually observed live status.

## Verification

```bash
python -m pytest tests/ -q -m "not live"

# LIVE GATE — requires an intentionally supplied paid credential
RUN_TRANSLATION_INTEGRATION=1 OPENAI_API_KEY="${OPENAI_API_KEY}" \
  .venv/bin/python -m pytest tests/translation/test_integration_live.py -q -s

git diff --check
```

- **Full offline suite required:** yes, before live
- **Live test:** required and explicitly gated
