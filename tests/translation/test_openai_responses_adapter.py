from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from unittest.mock import Mock

import httpx2
import openai
import pytest

from translation.domain import (
    PermanentProviderError,
    ProviderCall,
    ProviderStatus,
    TransientProviderError,
    TranslationRequest,
    TranslationRequestItem,
    TranslationRequestSection,
    canonical_json_bytes,
    translation_response_schema,
)
from translation.infrastructure import OpenAIResponsesTranslationProvider


SECRET = "sk-test-do-not-log"
SOURCE_TEXT = "A full private source payload."


def _call() -> ProviderCall:
    return ProviderCall(
        instructions="Translate without logging this full prompt.",
        request=TranslationRequest(
            source_language="en",
            target_language="zh-Hans",
            section=TranslationRequestSection(id="sec1", title="Opening"),
            items=(TranslationRequestItem(id="s1", text=SOURCE_TEXT),),
        ),
        output_schema=translation_response_schema(),
        max_attempts=3,
    )


def _completed_response(*, usage=SimpleNamespace(input_tokens=12, output_tokens=7)):
    return SimpleNamespace(
        id="resp_123",
        status="completed",
        output=(),
        output_text=json.dumps(
            {
                "section": {"id": "sec1", "translated_title": "开场"},
                "items": [{"id": "s1", "translated_text": "完整译文。"}],
            }
        ),
        usage=usage,
    )


@pytest.fixture
def sdk(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    create = Mock(return_value=_completed_response())
    client = SimpleNamespace(responses=SimpleNamespace(create=create))
    constructor = Mock(return_value=client)
    monkeypatch.setattr(openai, "OpenAI", constructor)
    return constructor, create


def test_sends_exact_fixed_responses_payload_and_disables_sdk_retries(sdk):
    constructor, create = sdk

    response = OpenAIResponsesTranslationProvider().translate(_call())

    constructor.assert_called_once_with(
        api_key=SECRET,
        timeout=1800,
        max_retries=0,
    )
    create.assert_called_once_with(
        model="gpt-5.6-sol",
        reasoning={"effort": "high"},
        instructions="Translate without logging this full prompt.",
        input=(
            '{"items":[{"id":"s1","text":"A full private source payload."}],'
            '"section":{"id":"sec1","title":"Opening"},'
            '"source_language":"en","target_language":"zh-Hans"}'
        ),
        text={
            "format": {
                "type": "json_schema",
                "name": "translation_response",
                "strict": True,
                "schema": translation_response_schema(),
            }
        },
        max_output_tokens=128_000,
        store=False,
    )
    sent = create.call_args.kwargs
    assert {
        "temperature",
        "top_p",
        "tools",
        "previous_response_id",
        "base_url",
    }.isdisjoint(sent)
    assert response.status == ProviderStatus.COMPLETED
    assert response.attempt_count == 1
    assert json.loads(canonical_json_bytes(response.output)) == {
        "section": {"id": "sec1", "translated_title": "开场"},
        "items": [{"id": "s1", "translated_text": "完整译文。"}],
    }
    assert response.usage is not None
    assert response.usage.to_dict() == {"input_tokens": 12, "output_tokens": 7}
    assert response.provider_request_id == "resp_123"


def test_missing_credential_is_permanent_configuration_error(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    constructor = Mock()
    monkeypatch.setattr(openai, "OpenAI", constructor)

    with pytest.raises(PermanentProviderError) as caught:
        OpenAIResponsesTranslationProvider()

    assert caught.value.code == "configuration"
    constructor.assert_not_called()


def test_client_configuration_error_is_permanent(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    monkeypatch.setattr(openai, "OpenAI", Mock(side_effect=openai.OpenAIError("bad")))

    with pytest.raises(PermanentProviderError) as caught:
        OpenAIResponsesTranslationProvider()

    assert caught.value.code == "configuration"


def test_refusal_maps_without_exposing_refusal_text(sdk):
    _, create = sdk
    create.return_value = SimpleNamespace(
        id="resp_refused",
        status="completed",
        output=(
            SimpleNamespace(
                type="message",
                content=(SimpleNamespace(type="refusal", refusal="private reason"),),
            ),
        ),
        usage=None,
    )

    response = OpenAIResponsesTranslationProvider().translate(_call())

    assert response.status == ProviderStatus.REFUSED
    assert response.output is None
    assert response.usage is None
    assert response.provider_request_id == "resp_refused"


def test_incomplete_maps_with_nullable_usage_and_request_id(sdk):
    _, create = sdk
    create.return_value = SimpleNamespace(
        id=None,
        status="incomplete",
        output=(),
        usage=None,
    )

    response = OpenAIResponsesTranslationProvider().translate(_call())

    assert response.status == ProviderStatus.INCOMPLETE
    assert response.output is None
    assert response.usage is None
    assert response.provider_request_id is None


def test_explicit_transient_failed_response_is_retryable(sdk):
    _, create = sdk
    create.return_value = SimpleNamespace(
        id="resp_failed",
        status="failed",
        output=(),
        usage=None,
        error=SimpleNamespace(code="temporarily_unavailable"),
    )

    with pytest.raises(TransientProviderError) as caught:
        OpenAIResponsesTranslationProvider().translate(_call())

    assert caught.value.code == "transient"


def _status_error(error_class, status_code, *, code=None, retry_after=None):
    request = httpx2.Request("POST", "https://api.openai.com/v1/responses")
    headers = {} if retry_after is None else {"retry-after": str(retry_after)}
    response = httpx2.Response(
        status_code,
        request=request,
        headers=headers,
    )
    body = None if code is None else {"error": {"code": code}}
    return error_class("private provider message", response=response, body=body)


@pytest.mark.parametrize(
    ("error", "code", "retry_after"),
    [
        (
            openai.APIConnectionError(
                request=httpx2.Request(
                    "POST", "https://api.openai.com/v1/responses"
                )
            ),
            "connection",
            None,
        ),
        (
            openai.APITimeoutError(
                request=httpx2.Request(
                    "POST", "https://api.openai.com/v1/responses"
                )
            ),
            "timeout",
            None,
        ),
        (_status_error(openai.RateLimitError, 429, retry_after=7), "http_429", 7),
        (_status_error(openai.APIStatusError, 408), "http_408", None),
        (_status_error(openai.InternalServerError, 503), "http_503", None),
        (_status_error(openai.APIStatusError, 599), "http_599", None),
        (
            _status_error(openai.BadRequestError, 400, code="server_error"),
            "transient",
            None,
        ),
    ],
)
def test_transient_sdk_errors_are_classified(sdk, error, code, retry_after):
    _, create = sdk
    create.side_effect = error

    with pytest.raises(TransientProviderError) as caught:
        OpenAIResponsesTranslationProvider().translate(_call())

    assert caught.value.code == code
    assert caught.value.retry_after_seconds == retry_after
    assert create.call_count == 1


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (_status_error(openai.AuthenticationError, 401), "authentication"),
        (_status_error(openai.PermissionDeniedError, 403), "permission"),
        (
            _status_error(
                openai.BadRequestError,
                400,
                code="context_length_exceeded",
            ),
            "request_too_large",
        ),
        (_status_error(openai.BadRequestError, 400), "invalid_request"),
        (_status_error(openai.APIStatusError, 409), "provider_error"),
        (_status_error(openai.APIStatusError, 600), "provider_error"),
    ],
)
def test_permanent_sdk_errors_are_classified(sdk, error, code):
    _, create = sdk
    create.side_effect = error

    with pytest.raises(PermanentProviderError) as caught:
        OpenAIResponsesTranslationProvider().translate(_call())

    assert caught.value.code == code
    assert create.call_count == 1


@pytest.mark.parametrize("output_text", ["", "not json", "[]"])
def test_malformed_output_is_permanent(sdk, output_text):
    _, create = sdk
    create.return_value = SimpleNamespace(
        id="resp_bad",
        status="completed",
        output=(),
        output_text=output_text,
        usage=None,
    )

    with pytest.raises(PermanentProviderError) as caught:
        OpenAIResponsesTranslationProvider().translate(_call())

    assert caught.value.code == "malformed_response"


def test_credentials_and_full_payload_are_not_logged(sdk, caplog):
    _, create = sdk
    create.side_effect = _status_error(openai.BadRequestError, 400)

    with caplog.at_level(logging.DEBUG), pytest.raises(PermanentProviderError):
        OpenAIResponsesTranslationProvider().translate(_call())

    logged = caplog.text
    assert SECRET not in logged
    assert SOURCE_TEXT not in logged
    assert "Translate without logging this full prompt." not in logged
