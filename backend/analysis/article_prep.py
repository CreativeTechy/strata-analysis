"""Article preparation stage: normalize/sanitize/chunk text for model input.

Nothing here ever mutates the article's stored `text`/`title` - it only
produces derived, model-facing copies. Callers that persist articles must
keep using the original `article["text"]`.
"""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlparse

import config

_SOCIAL_DOMAINS = {"x.com", "twitter.com", "reddit.com", "t.me", "telegram.me"}

# Chat-template control tokens (ChatML-style, used by many instruct models,
# including the LLM provider behind structured extraction). If scraped
# content contains these literally, it can try
# to fake a role boundary and smuggle in new "instructions" once the text is
# dropped into a chat prompt. They're stripped from the model-facing copy
# only - never from the stored article text.
_CHAT_CONTROL_TOKENS = re.compile(r"<\|[a-zA-Z0-9_\-]{1,32}\|>")

# Lines that look like they're trying to open a new role turn or a system-ish
# directive block inside what should be inert article content.
_ROLE_MARKER_LINE = re.compile(
    r"^\s*(system|assistant|user|developer|tool)\s*:\s*",
    re.IGNORECASE,
)
_INSTRUCTION_OVERRIDE_PHRASES = re.compile(
    r"\b(ignore (?:(?:all|any|the)\s+)?(?:previous|prior|above)\s+instructions?|"
    r"disregard (?:(?:all|any|the)\s+)?(?:previous|prior|above)\s+instructions?|"
    r"new instructions?\s*:|you are now|act as (?:a|an)\s|jailbreak)\b",
    re.IGNORECASE,
)


def normalize_text(value: str | None) -> str:
    """Unicode-normalize and collapse whitespace. Safe to run on any text."""
    text = unicodedata.normalize("NFKC", str(value or ""))
    return " ".join(text.split())


def is_social_post(article: dict) -> bool:
    """True for scraped X/Twitter/Reddit/Telegram posts, which are short and get lighter handling."""
    if not isinstance(article, dict):
        return False
    url_host = urlparse(article.get("url") or "").netloc.lower()
    if url_host.startswith("www."):
        url_host = url_host[4:]
    if url_host in _SOCIAL_DOMAINS:
        return True
    source_host = (article.get("source") or "").split("/")[0].strip().lower()
    return source_host in _SOCIAL_DOMAINS


def sanitize_for_prompt(text: str) -> str:
    """Neutralize prompt-injection vectors in scraped content before it is
    interpolated into an instruction-following model's prompt.

    This is defense in depth, not content moderation: it doesn't try to
    detect and block "bad" content, only to stop scraped text from being
    able to fake chat-template control tokens or role headers and hijack the
    turn structure. Legitimate article text is left readable.
    """
    text = _CHAT_CONTROL_TOKENS.sub(" ", text)

    cleaned_lines = []
    for line in text.splitlines():
        line = _ROLE_MARKER_LINE.sub(lambda m: m.group(0).replace(":", " -"), line)
        cleaned_lines.append(line)
    text = "\n".join(cleaned_lines)

    # Don't strip phrases like "ignore previous instructions" out of the
    # text (that would corrupt legitimate quotes/discussion of prompt
    # injection itself) - just flag-neutral-wrap them so a model reading the
    # DATA block sees them as quoted content, not directives, by breaking up
    # the exact phrase the model pattern-matches on for compliance.
    text = _INSTRUCTION_OVERRIDE_PHRASES.sub(lambda m: f"[quoted: {m.group(0)}]", text)

    return text


def prepare_text_for_model(text: str, *, max_chars: int | None = None) -> str:
    """Normalize + sanitize + hard-truncate. The standard prep for any stage
    that hands article text to a model."""
    max_chars = config.ANALYSIS_MAX_INPUT_CHARS if max_chars is None else max_chars
    cleaned = normalize_text(text)
    cleaned = sanitize_for_prompt(cleaned)
    return cleaned[:max_chars] if max_chars else cleaned


def chunk_text(text: str, *, chunk_size: int | None = None, overlap: int | None = None) -> list[str]:
    """Split text into overlapping chunks on whitespace boundaries.

    Used by stages whose model has a limited context window. Returns a
    single-element list (the whole text) when it already fits in one chunk.
    """
    chunk_size = config.ANALYSIS_CHUNK_SIZE_CHARS if chunk_size is None else chunk_size
    overlap = config.ANALYSIS_CHUNK_OVERLAP_CHARS if overlap is None else overlap
    chunk_size = max(1, chunk_size)
    overlap = max(0, min(overlap, chunk_size - 1))

    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    length = len(text)
    step = chunk_size - overlap
    while start < length:
        end = min(start + chunk_size, length)
        if end < length:
            # Prefer to break on a whitespace boundary near the target end
            # so words aren't split mid-token for the model.
            boundary = text.rfind(" ", start + 1, end)
            if boundary != -1 and boundary > start:
                end = boundary
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= length:
            break
        start += step if step > 0 else chunk_size

    return chunks


def prepare_article(article: dict) -> dict:
    """Return the derived, model-facing view of an article used by every
    downstream stage. `text`/`title` here are normalized+sanitized copies;
    the original `article` dict is left untouched."""
    title = normalize_text(article.get("title", ""))
    raw_text = article.get("text", "") or ""
    model_text = prepare_text_for_model(raw_text)
    return {
        "title": title,
        "text": model_text,
        "chunks": chunk_text(model_text),
        "is_social": is_social_post(article),
    }
