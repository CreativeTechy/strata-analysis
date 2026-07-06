"""Thin client for local OpenAI-compatible chat endpoints."""

from __future__ import annotations

from urllib.parse import urljoin

import requests

import config


def _chat_completions_url() -> str:
    base_url = (config.LOCAL_LLM_BASE_URL or "").strip()
    if not base_url:
        return ""
    if base_url.rstrip("/").endswith("/chat/completions"):
        return base_url.rstrip("/")
    return urljoin(base_url.rstrip("/") + "/", "chat/completions")


def chat_completion(*, messages, model=None, temperature=0.2, max_tokens=512, timeout=60):
    url = _chat_completions_url()
    if not url:
        raise ValueError("LOCAL_LLM_BASE_URL is not configured")

    headers = {"Content-Type": "application/json"}
    if config.LOCAL_LLM_API_KEY:
        headers["Authorization"] = f"Bearer {config.LOCAL_LLM_API_KEY}"

    resp = requests.post(
        url,
        headers=headers,
        json={
            "model": model or config.LOCAL_LLM_MODEL,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    payload = resp.json()
    choices = payload.get("choices") or []
    if not choices:
        raise ValueError("Local LLM returned no choices")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Local LLM returned an empty message")
    return content.strip()
