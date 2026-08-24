"""AI helpers for project metadata drafting.

Suggests the target audience and the topics of interest (keywords) a project
should track, from the name and description the user typed. Keywords are what
the Reports page charts existence over, so a good set here is what makes that
chart say anything - and nothing here reaches the network beyond the
configured LLM.
"""

from __future__ import annotations

import json
import re
from collections import Counter

import config
from llm_client import chat_completion

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "have",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "with",
    "your",
    "their",
    "our",
    "will",
    "about",
    "into",
    "over",
    "after",
    "before",
    "more",
    "than",
    "than",
}


def _clean_text(value):
    return " ".join(str(value or "").strip().split())


def _extract_json_blob(text):
    raw = _clean_text(text)
    if not raw:
        return ""
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        if raw.endswith("```"):
            raw = raw[:-3]
    raw = raw.strip()
    if raw:
        return raw
    match = re.search(r"\{.*\}", text or "", re.S)
    return match.group(0).strip() if match else ""


def _normalize_items(values, prefix="#", limit=6):
    if isinstance(values, str):
        values = [part.strip() for part in re.split(r"[\n,]", values)]
    elif not isinstance(values, list):
        values = [values]

    cleaned = []
    seen = set()
    for value in values:
        text = _clean_text(value)
        if not text:
            continue
        if prefix and text.startswith(prefix):
            text = text[len(prefix):].strip()
        text = re.sub(r"\s+", " ", text)
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(f"{prefix}{text}" if prefix else text)
        if len(cleaned) >= limit:
            break
    return cleaned


def _keyword_candidates(name, description):
    text = f"{name} {description}".lower()
    words = re.findall(r"[a-z0-9][a-z0-9&+-]{2,}", text)
    counts = Counter(
        word for word in words
        if word not in STOPWORDS and not word.isdigit()
    )
    return [word for word, _ in counts.most_common(12)]


def _fallback_metadata(name, description):
    """Used when no LLM is reachable: a frequency count over the text the user
    already typed. Weak, but better than leaving them with an empty form and a
    silent failure."""
    keywords = _keyword_candidates(name, description)
    target_audience = ""
    if keywords:
        target_audience = f"People interested in {keywords[0].replace('-', ' ')} and related updates"
    elif name:
        target_audience = f"People following {name}"
    else:
        target_audience = "Readers and professionals tracking the topic"
    return {
        "target_audience": target_audience,
        "keywords": [word.replace("-", " ") for word in keywords[:6]],
        "source": "heuristic",
    }


def suggest_project_metadata(name, description):
    """Return a suggested target audience and topic keywords for a project."""
    name = _clean_text(name)
    description = _clean_text(description)

    fallback = _fallback_metadata(name, description)
    if not config.LLM_API_KEY or not name:
        return fallback

    prompt = (
        "You are helping craft metadata for an opinion-monitoring workspace.\n"
        "Given the project name and description, return ONLY JSON with this shape:\n"
        '{ "target_audience": "string", "keywords": ["string"] }\n'
        "Rules:\n"
        "- Keywords are the topics this project tracks across the documents it\n"
        "  analyzes, so keep them tightly related to the project.\n"
        "- Return 4 to 8 keywords.\n"
        "- Target audience should be a short plain-English phrase.\n"
        "- Do not include markdown or commentary.\n\n"
        f"Project name: {name}\n"
        f"Project description: {description or '(none)'}\n"
    )

    try:
        content = chat_completion(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=400,
            timeout=35,
        )
        payload = json.loads(_extract_json_blob(content))
        if not isinstance(payload, dict):
            return fallback
    except Exception:
        return fallback

    target_audience = _clean_text(payload.get("target_audience")) or fallback["target_audience"]
    keywords = _normalize_items(payload.get("keywords") or [], prefix="", limit=8)

    return {
        "target_audience": target_audience,
        "keywords": keywords or fallback["keywords"],
        "source": config.LLM_PROVIDER,
    }
