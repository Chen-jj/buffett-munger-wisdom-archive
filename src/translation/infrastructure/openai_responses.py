"""OpenAI Responses API adapter for the v1 translation provider contract."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import os

import openai

from translation.domain import (
    PermanentProviderError,
    ProviderCall,
    ProviderIdentity,
    ProviderResponse,
    ProviderStatus,
    ProviderUsage,
    TransientProviderError,
    canonical_json_bytes,
)


_API_KEY_ENV = "OPENAI_API_KEY"
_MODEL = "gpt-5.6-sol"
_TRANSIENT_ERROR_CODES = frozenset(
    {
        "overloaded",
        "server_error",
        "service_unavailable",
        "temporarily_unavailable",
    }
)
_REQUEST_TOO_LARGE_CODES = frozenset(
    {
        "context_length_exceeded",
        "input_too_large",
        "request_too_large",
    }
)


def _value(value: object, name: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _error_code(error: object) -> str | None:
    for candidate in (
        _value(error, "code"),
        _value(_value(error, "body"), "code"),
        _value(_value(_value(error, "body"), "error"), "code"),
        _value(_value(error, "error"), "code"),
    ):
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


def _retry_after_seconds(error: object) -> float | None:
    response = _value(error, "response")
    headers = _value(response, "headers")
    if not isinstance(headers, Mapping):
        return None
    value = headers.get("retry-after")
    if value is None:
        value = headers.get("Retry-After")
    try:
        seconds = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return seconds if seconds >= 0 else None


def _classify_openai_error(error: openai.OpenAIError) -> Exception:
    if isinstance(error, openai.APITimeoutError):
        return TransientProviderError(
            "OpenAI request timed out",
            code="timeout",
        )
    if isinstance(error, openai.APIConnectionError):
        return TransientProviderError(
            "OpenAI connection failed",
            code="connection",
        )
    if isinstance(error, openai.AuthenticationError):
        return PermanentProviderError(
            "OpenAI authentication failed",
            code="authentication",
        )
    if isinstance(error, openai.PermissionDeniedError):
        return PermanentProviderError(
            "OpenAI permission denied",
            code="permission",
        )

    status_code = _value(error, "status_code")
    provider_code = _error_code(error)
    if isinstance(error, openai.RateLimitError) or status_code == 429:
        return TransientProviderError(
            "OpenAI rate limit exceeded",
            code="http_429",
            retry_after_seconds=_retry_after_seconds(error),
        )
    if status_code == 413 or provider_code in _REQUEST_TOO_LARGE_CODES:
        return PermanentProviderError(
            "OpenAI request is too large",
            code="request_too_large",
        )
    transient_status = isinstance(status_code, int) and (
        status_code == 408 or 500 <= status_code <= 599
    )
    if transient_status or provider_code in _TRANSIENT_ERROR_CODES:
        code = f"http_{status_code}" if transient_status else "transient"
        return TransientProviderError(
            "OpenAI service is temporarily unavailable",
            code=code,
            retry_after_seconds=_retry_after_seconds(error),
        )
    if isinstance(error, (openai.BadRequestError, openai.UnprocessableEntityError)):
        return PermanentProviderError(
            "OpenAI rejected the request",
            code="invalid_request",
        )
    return PermanentProviderError(
        "OpenAI request failed",
        code="provider_error",
    )


def _has_refusal(response: object) -> bool:
    output = _value(response, "output", ())
    if not isinstance(output, Sequence) or isinstance(output, (str, bytes, bytearray)):
        return False
    for item in output:
        content = _value(item, "content", ())
        if not isinstance(content, Sequence) or isinstance(
            content, (str, bytes, bytearray)
        ):
            continue
        if any(_value(block, "type") == "refusal" for block in content):
            return True
    return False


def _output_text(response: object) -> str:
    text = _value(response, "output_text")
    if isinstance(text, str):
        return text

    parts: list[str] = []
    output = _value(response, "output", ())
    if not isinstance(output, Sequence) or isinstance(output, (str, bytes, bytearray)):
        return ""
    for item in output:
        content = _value(item, "content", ())
        if not isinstance(content, Sequence) or isinstance(
            content, (str, bytes, bytearray)
        ):
            continue
        for block in content:
            if _value(block, "type") == "output_text":
                block_text = _value(block, "text")
                if isinstance(block_text, str):
                    parts.append(block_text)
    return "".join(parts)


def _usage(response: object) -> ProviderUsage | None:
    usage = _value(response, "usage")
    if usage is None:
        return None
    try:
        return ProviderUsage(
            input_tokens=_value(usage, "input_tokens"),  # type: ignore[arg-type]
            output_tokens=_value(usage, "output_tokens"),  # type: ignore[arg-type]
        )
    except (TypeError, ValueError) as error:
        raise PermanentProviderError(
            "OpenAI returned malformed usage",
            code="malformed_response",
        ) from error


def _request_id(response: object) -> str | None:
    request_id = _value(response, "id")
    return request_id if isinstance(request_id, str) and request_id.strip() else None


class OpenAIResponsesTranslationProvider:
    """Translate one provider-neutral call with exactly one Responses API call."""

    identity = ProviderIdentity(
        provider="openai-responses",
        model=_MODEL,
        generation_parameters={
            "reasoning_effort": "high",
            "temperature": None,
            "max_output_tokens": 128_000,
            "store": False,
        },
    )

    def __init__(self) -> None:
        api_key = os.environ.get(_API_KEY_ENV)
        if not api_key:
            raise PermanentProviderError(
                f"{_API_KEY_ENV} is not configured",
                code="configuration",
            )
        try:
            self._client = openai.OpenAI(
                api_key=api_key,
                timeout=1800,
                max_retries=0,
            )
        except openai.OpenAIError:
            raise PermanentProviderError(
                "OpenAI client configuration failed",
                code="configuration",
            ) from None

    def translate(self, call: ProviderCall) -> ProviderResponse:
        if not isinstance(call, ProviderCall):
            raise ValueError("call must be a ProviderCall")

        schema = json.loads(canonical_json_bytes(call.output_schema))
        try:
            response = self._client.responses.create(
                model=_MODEL,
                reasoning={"effort": "high"},
                instructions=call.instructions,
                input=call.request.canonical_json(),
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "translation_response",
                        "strict": True,
                        "schema": schema,
                    }
                },
                max_output_tokens=128_000,
                store=False,
            )
        except openai.OpenAIError as error:
            raise _classify_openai_error(error) from None

        usage = _usage(response)
        request_id = _request_id(response)
        if _has_refusal(response):
            return ProviderResponse(
                status=ProviderStatus.REFUSED,
                output=None,
                attempt_count=1,
                usage=usage,
                provider_request_id=request_id,
            )

        status = _value(response, "status")
        if status == "incomplete":
            return ProviderResponse(
                status=ProviderStatus.INCOMPLETE,
                output=None,
                attempt_count=1,
                usage=usage,
                provider_request_id=request_id,
            )
        if status != "completed":
            response_error = _value(response, "error")
            provider_code = _error_code(response_error)
            if provider_code in _TRANSIENT_ERROR_CODES:
                raise TransientProviderError(
                    "OpenAI service is temporarily unavailable",
                    code="transient",
                )
            raise PermanentProviderError(
                "OpenAI returned an unexpected response status",
                code="malformed_response",
            )

        try:
            output = json.loads(_output_text(response))
        except (TypeError, json.JSONDecodeError) as error:
            raise PermanentProviderError(
                "OpenAI returned malformed JSON",
                code="malformed_response",
            ) from error
        if not isinstance(output, Mapping):
            raise PermanentProviderError(
                "OpenAI returned malformed JSON",
                code="malformed_response",
            )
        return ProviderResponse(
            status=ProviderStatus.COMPLETED,
            output=output,
            attempt_count=1,
            usage=usage,
            provider_request_id=request_id,
        )
