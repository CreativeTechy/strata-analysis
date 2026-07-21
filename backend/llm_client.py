"""Thin client for the configured OpenAI-compatible chat completions API."""

from __future__ import annotations

import requests

import config


class LLMError(Exception):
    """Base class for user-facing LLM failures.

    Carries a stable, machine-readable `code` and a short, provider-neutral
    `user_message` safe to show in the UI. `detail` holds the raw
    provider/exception text for server-side logs only - never send it to
    the client.
    """

    code = "llm_provider_error"
    user_message = "The assistant hit an unexpected error. Please try again."

    def __init__(self, detail="", *, code=None, user_message=None):
        super().__init__(detail or self.user_message)
        self.detail = detail
        if code is not None:
            self.code = code
        if user_message is not None:
            self.user_message = user_message


class LLMConfigError(LLMError):
    code = "llm_config_error"
    user_message = "The AI assistant isn't set up yet. Please contact your administrator."


class LLMAuthError(LLMError):
    code = "llm_auth_error"
    user_message = "The AI assistant isn't configured correctly. Please contact your administrator."


class LLMRateLimitError(LLMError):
    code = "llm_rate_limited"
    user_message = "The assistant is busy right now. Please wait a moment and try again."


class LLMTimeoutError(LLMError):
    code = "llm_timeout"
    user_message = "The assistant took too long to respond. Please try again."


class LLMUnavailableError(LLMError):
    code = "llm_unavailable"
    user_message = "The assistant service is temporarily unavailable. Please try again shortly."


class LLMBadRequestError(LLMError):
    code = "llm_bad_request"
    user_message = "That request couldn't be processed. Try rephrasing your question."


class LLMInvalidResponseError(LLMError):
    code = "llm_invalid_response"
    user_message = "The assistant couldn't produce a usable answer. Try rephrasing your question."

    def __init__(self, detail="", *, code=None, user_message=None, finish_reason=None):
        super().__init__(detail, code=code, user_message=user_message)
        self.finish_reason = finish_reason


def _extract_chat_content(payload) -> str:
    choices = payload.get("choices") or []
    if not choices:
        raise LLMInvalidResponseError("LLM returned no choices")
    choice = choices[0]
    message = choice.get("message") or {}
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()

    # The provider accepted the request (2xx) but sent back nothing usable -
    # a refusal, a tool-call-only turn, a content-filtered response, or a
    # reasoning model burning its whole token budget on hidden reasoning
    # before it could write any visible content (finish_reason="length" with
    # an empty message) all look like this. Surface finish_reason/refusal so
    # the caller's log line says *why*, and so it can pick a retry strategy.
    finish_reason = choice.get("finish_reason", "unknown")
    refusal = message.get("refusal")
    if refusal:
        raise LLMInvalidResponseError(
            f"LLM refused the request (finish_reason={finish_reason}): {refusal}",
            finish_reason=finish_reason,
        )
    raise LLMInvalidResponseError(
        f"LLM returned an empty message (finish_reason={finish_reason}, "
        f"message_keys={sorted(message.keys())})",
        finish_reason=finish_reason,
    )


def _error_message(resp) -> str:
    try:
        detail = (resp.json().get("error") or {}).get("message", "")
    except ValueError:
        detail = ""
    return detail or (resp.text or "")[:500]


def _raise_for_status(resp):
    message = _error_message(resp)
    detail = f"{resp.status_code} error for url: {resp.url} - {message}"
    status = resp.status_code
    if status in (401, 403):
        raise LLMAuthError(detail)
    if status == 429:
        raise LLMRateLimitError(detail)
    if status in (400, 422):
        raise LLMBadRequestError(detail)
    if status >= 500:
        raise LLMUnavailableError(detail)
    raise LLMError(detail)


def _post(url, body, timeout):
    try:
        resp = requests.post(
            url,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {config.OPENAI_API_KEY}",
            },
            json=body,
            timeout=timeout,
        )
    except requests.Timeout as exc:
        raise LLMTimeoutError(str(exc)) from exc
    except requests.ConnectionError as exc:
        raise LLMUnavailableError(str(exc)) from exc
    except requests.RequestException as exc:
        raise LLMUnavailableError(str(exc)) from exc

    if not resp.ok:
        _raise_for_status(resp)

    try:
        return resp.json()
    except ValueError as exc:
        raise LLMInvalidResponseError(f"Non-JSON response from LLM: {exc}") from exc


def chat_completion(*, messages, model=None, temperature=0.2, max_tokens=512, timeout=60):
    url = (config.OPENAI_CHAT_BASE_URL or "").strip()
    if not config.OPENAI_API_KEY or not url:
        raise LLMConfigError("OPENAI_API_KEY is not configured")

    # max_completion_tokens is the current OpenAI chat-completions parameter;
    # some models (e.g. reasoning models) reject the legacy max_tokens name.
    body = {
        "model": model or config.OPENAI_CHAT_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_completion_tokens": max_tokens,
    }

    try:
        payload = _post(url, body, timeout)
    except LLMBadRequestError as exc:
        # Some models only accept the default temperature (1) and reject any
        # other value - drop it and retry once rather than failing outright.
        if "temperature" in (exc.detail or "").lower():
            body.pop("temperature", None)
            payload = _post(url, body, timeout)
        else:
            raise

    try:
        return _extract_chat_content(payload)
    except LLMInvalidResponseError as exc:
        retry_body = body
        if exc.finish_reason == "length":
            # The model spent its entire max_completion_tokens budget on
            # hidden reasoning and never got to write visible content -
            # retrying with the same budget would just hit the same wall.
            # Give it more room instead.
            current = int(body.get("max_completion_tokens") or max_tokens)
            retry_body = {**body, "max_completion_tokens": min(current * 2, 4000)}
            print(
                f"llm_client: empty response from truncation ({exc.detail}); "
                f"retrying once with max_completion_tokens={retry_body['max_completion_tokens']}"
            )
        else:
            # Otherwise treat it as a transient glitch (stray tool-call/refusal
            # turn) and retry once with the same request.
            print(f"llm_client: empty/invalid response ({exc.detail}); retrying once")
        payload = _post(url, retry_body, timeout)
        return _extract_chat_content(payload)
