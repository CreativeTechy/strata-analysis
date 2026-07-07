"""Thin client for local OpenAI-compatible chat endpoints."""

from __future__ import annotations

from urllib.parse import urljoin

import requests

import config


def _extract_chat_content(payload) -> str:
    choices = payload.get("choices") or []
    if not choices:
        raise ValueError("LLM returned no choices")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("LLM returned an empty message")
    return content.strip()


def _post_chat_completion(*, url: str, headers: dict, messages, model: str, temperature: float, max_tokens: int, timeout: int) -> str:
    resp = requests.post(
        url,
        headers=headers,
        json={
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    payload = resp.json()
    return _extract_chat_content(payload)


def _chat_completions_url() -> str:
    base_url = (config.LOCAL_LLM_BASE_URL or "").strip()
    if not base_url:
        return ""
    if base_url.rstrip("/").endswith("/chat/completions"):
        return base_url.rstrip("/")
    return urljoin(base_url.rstrip("/") + "/", "chat/completions")


def _deepseek_chat_completions_url() -> str:
    return (config.DEEPSEEK_CHAT_BASE_URL or "").strip()


def chat_completion(*, messages, model=None, temperature=0.2, max_tokens=512, timeout=60):
    url = _chat_completions_url()
    if not url:
        local_error = ValueError("LOCAL_LLM_BASE_URL is not configured")
        url = ""
    else:
        local_error = None

    headers = {"Content-Type": "application/json"}
    if config.LOCAL_LLM_API_KEY:
        headers["Authorization"] = f"Bearer {config.LOCAL_LLM_API_KEY}"

    if url:
        try:
            return _post_chat_completion(
                url=url,
                headers=headers,
                messages=messages,
                model=model or config.LOCAL_LLM_MODEL,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
            )
        except Exception as exc:
            local_error = exc

    deepseek_url = _deepseek_chat_completions_url()
    if config.DEEPSEEK_API_KEY and deepseek_url:
        deepseek_headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.DEEPSEEK_API_KEY}",
        }
        try:
            return _post_chat_completion(
                url=deepseek_url,
                headers=deepseek_headers,
                messages=messages,
                model=config.DEEPSEEK_CHAT_MODEL,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
            )
        except Exception as exc:
            if local_error is not None:
                raise ValueError(f"Local LLM failed and DeepSeek fallback also failed: {local_error}; {exc}") from exc
            raise

    if local_error is not None:
        raise local_error
    raise ValueError("No LLM endpoint is configured")
