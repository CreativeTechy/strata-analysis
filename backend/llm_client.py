"""Thin client for the DeepSeek chat completions API."""

from __future__ import annotations

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


def chat_completion(*, messages, model=None, temperature=0.2, max_tokens=512, timeout=60):
    url = (config.DEEPSEEK_CHAT_BASE_URL or "").strip()
    if not config.DEEPSEEK_API_KEY or not url:
        raise ValueError("DEEPSEEK_API_KEY is not configured")

    resp = requests.post(
        url,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.DEEPSEEK_API_KEY}",
        },
        json={
            "model": model or config.DEEPSEEK_CHAT_MODEL,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    return _extract_chat_content(resp.json())
