"""Thin client for the configured chat LLM provider (OpenAI or DeepSeek).

`config.LLM_PROVIDER` picks the active provider; this module is the only
place that knows the difference between OpenAI's Responses API and the
OpenAI-compatible chat-completions shape DeepSeek (and similar providers)
use. Every caller goes through the single `chat_completion(...)` entry point
below and never sees which provider or API shape actually served the
request.
"""

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


def _split_instructions(messages):
    """Split chat-style messages into Responses `instructions` + `input`.

    The Responses API has no "system" role in `input`; system/developer
    messages become the top-level `instructions` string instead, in the
    order they appeared. Everything else is passed through as-is - the
    Responses API accepts the same simple {"role", "content"} shape chat
    completions used for user/assistant turns.
    """
    instructions_parts = []
    input_items = []
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if role in ("system", "developer"):
            if content:
                instructions_parts.append(content)
        else:
            input_items.append({"role": role, "content": content})
    instructions = "\n\n".join(instructions_parts) if instructions_parts else None
    return instructions, input_items


def _extract_output_text_responses(payload) -> str:
    """Extract text from an OpenAI Responses API payload."""
    status = payload.get("status", "unknown")
    output = payload.get("output") or []

    texts = []
    refusal = None
    for item in output:
        if item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            content_type = content.get("type")
            if content_type == "output_text":
                text = content.get("text")
                if text:
                    texts.append(text)
            elif content_type == "refusal":
                refusal = content.get("refusal")

    joined = "\n".join(text.strip() for text in texts if text and text.strip()).strip()
    if joined:
        return joined

    # The provider accepted the request (2xx) but sent back nothing usable -
    # a refusal, a response cut short by the token budget, or a
    # reasoning model burning its whole budget on hidden reasoning before it
    # could write any visible content all look like this. Surface the
    # incomplete reason/refusal so the caller's log line says *why*, and so
    # it can pick a retry strategy.
    incomplete_reason = (payload.get("incomplete_details") or {}).get("reason", "unknown")
    if refusal:
        raise LLMInvalidResponseError(
            f"LLM refused the request (status={status}): {refusal}",
            finish_reason=incomplete_reason,
        )
    raise LLMInvalidResponseError(
        f"LLM returned an empty response (status={status}, incomplete_reason={incomplete_reason})",
        finish_reason=incomplete_reason,
    )


def _extract_output_text_chat_completions(payload) -> str:
    """Extract text from an OpenAI-compatible chat-completions payload (DeepSeek et al.)."""
    choices = payload.get("choices") or []
    if not choices:
        raise LLMInvalidResponseError("LLM returned no choices", finish_reason="unknown")

    choice = choices[0]
    finish_reason = choice.get("finish_reason") or "unknown"
    message = choice.get("message") or {}
    text = (message.get("content") or "").strip()
    if text:
        return text

    # Normalize to the same finish_reason vocabulary _post()'s retry logic
    # already understands for the Responses API ("max_output_tokens" means
    # "give it more room and retry").
    normalized_reason = "max_output_tokens" if finish_reason == "length" else finish_reason
    raise LLMInvalidResponseError(
        f"LLM returned an empty response (finish_reason={finish_reason})",
        finish_reason=normalized_reason,
    )


def _extract_output_text(payload) -> str:
    if config.LLM_API_STYLE == "chat_completions":
        return _extract_output_text_chat_completions(payload)
    return _extract_output_text_responses(payload)


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
                "Authorization": f"Bearer {config.LLM_API_KEY}",
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
        payload = resp.json()
    except ValueError as exc:
        raise LLMInvalidResponseError(f"Non-JSON response from LLM: {exc}") from exc

    # The Responses API can return 2xx with status="failed" (e.g. a
    # provider-side error surfaced mid-request) - treat that the same as an
    # HTTP error rather than trying to extract text from it.
    if payload.get("status") == "failed":
        error = payload.get("error") or {}
        raise LLMError(f"LLM response failed: {error.get('message') or error}")

    return payload


def _build_request_body(*, messages, model, temperature, max_tokens):
    """Build the provider-appropriate request body for the same logical inputs.

    This is the one place that adapts to the active provider's payload shape
    - callers always pass the same messages/temperature/max_tokens/timeout
    regardless of which provider is configured.
    """
    if config.LLM_API_STYLE == "chat_completions":
        return {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

    # "responses" style (OpenAI Responses API): no system role in `input`,
    # system/developer messages become the top-level `instructions` string.
    instructions, input_items = _split_instructions(messages)
    body = {
        "model": model,
        "input": input_items,
        "temperature": temperature,
        "max_output_tokens": max_tokens,
    }
    if instructions:
        body["instructions"] = instructions
    return body


def _max_tokens_key():
    return "max_tokens" if config.LLM_API_STYLE == "chat_completions" else "max_output_tokens"


def chat_completion(*, messages, model=None, temperature=0.2, max_tokens=512, timeout=60):
    url = (config.LLM_CHAT_BASE_URL or "").strip()
    if not config.LLM_API_KEY or not url:
        raise LLMConfigError(f"{config.LLM_API_KEY_ENV_NAME} is not configured")

    body = _build_request_body(
        messages=messages,
        model=model or config.LLM_CHAT_MODEL,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    try:
        payload = _post(url, body, timeout)
    except LLMBadRequestError as exc:
        # Some models only accept the default temperature (1) and reject any
        # other value - drop it and retry once rather than failing outright.
        if "temperature" in (exc.detail or "").lower():
            body = {k: v for k, v in body.items() if k != "temperature"}
            payload = _post(url, body, timeout)
        else:
            raise

    try:
        return _extract_output_text(payload)
    except LLMInvalidResponseError as exc:
        retry_body = body
        max_tokens_key = _max_tokens_key()
        if exc.finish_reason == "max_output_tokens":
            # The model spent its entire token budget on hidden reasoning (or
            # hit the length cap) and never got to write visible content -
            # retrying with the same budget would just hit the same wall.
            # Give it more room instead.
            current = int(body.get(max_tokens_key) or max_tokens)
            retry_body = {**body, max_tokens_key: min(current * 2, 4000)}
            print(
                f"llm_client: empty response from truncation ({exc.detail}); "
                f"retrying once with {max_tokens_key}={retry_body[max_tokens_key]}"
            )
        else:
            # Otherwise treat it as a transient glitch (stray refusal turn)
            # and retry once with the same request.
            print(f"llm_client: empty/invalid response ({exc.detail}); retrying once")
        payload = _post(url, retry_body, timeout)
        return _extract_output_text(payload)
