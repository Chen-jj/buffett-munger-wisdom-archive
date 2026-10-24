# TA-08 — Implement the OpenAI Responses provider adapter

- **Status:** accepted
- **Module:** `translation/infrastructure`
- **Decision coverage:** ADR-0002 sections 6.2–6.3, 8.2, 14.3, 15 step 5
- **Depends on:** TA-07
- **Depended on by:** TA-09

## Goal

Implement the single v1 production provider adapter against OpenAI Responses
API while keeping application code SDK-independent and unit tests fully offline.

## Exact scope

- Implement `OpenAIResponsesTranslationProvider` using `openai==3.31.0` and
  credentials read only from the configured `OPENAI_API_KEY` environment name.
- Configure client timeout to 1800 seconds and disable SDK implicit retries.
- Submit exactly: model `gpt-5.6-sol`, reasoning effort `high`, canonical request
  JSON as input, strict static JSON Schema response format,
  `max_output_tokens=128000`, and `store=false`.
- Do not send temperature, top_p, tools, previous response ID, API key in logs,
  or any custom base URL.
- Parse completed structured output into the provider-neutral response and map
  refused/incomplete, nullable usage, and optional request ID.
- Classify connection/timeout/429/5xx/explicit transient errors as transient;
  authentication/permission/config/request-too-large and malformed output as
  permanent. The adapter/application boundary must preserve one owner for the
  total attempt count and never stack SDK retries.
- Mock the SDK in every test and assert the exact outbound call and mappings.

This task owns the new OpenAI adapter and its isolated test file. Any package
export adjustment must be minimal and coordinated after TA-07 is accepted.

## Non-goals

- Do not make a real API call or add the live integration test; TA-10 owns it.
- Do not implement alternate/custom endpoints, compatible providers, or model
  fallback.
- Do not modify translation workflow/checkpoint semantics to fit SDK objects.
- Do not read translation settings from global YAML inside domain/application.

## Acceptance criteria

1. Mock assertions prove every required parameter and prove all forbidden
   parameters are absent.
2. SDK implicit retries are zero and `max_attempts` remains the workflow's total
   logical-call limit.
3. Completed/refused/incomplete, usage, request ID, and all error categories map
   to provider-neutral types correctly.
4. Tests prove no credential or full payload is logged.
5. All offline tests pass without network access.

## Verification

```bash
python -m pytest tests/translation/test_openai_responses_adapter.py -q
python -m pytest tests/translation/ -q -m "not live"
python -m pytest tests/ -q -m "not live"
```

- **Full offline suite required:** yes
- **Live test:** no
