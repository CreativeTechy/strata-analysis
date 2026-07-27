"""Pure value-normalization helpers shared across analysis stages.

Extracted from enrich.py so structured_extraction.py and aggregation.py can
reuse the exact same feedback-list/people-opinion/frequent-idea normalization
instead of a second copy drifting out of sync.
"""

from __future__ import annotations

import re

from analysis import labels

VALID_CATEGORIES = set(labels.VALID_CATEGORIES)
VALID_TONES = set(labels.VALID_TONES)
VALID_SENTIMENTS = {"positive", "negative", "mixed", "neutral"}


def as_text(value) -> str:
    return str(value).strip() if value is not None else ""


def as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        items = value
    elif isinstance(value, str):
        items = [part.strip() for part in value.replace("\n", ",").split(",")]
    else:
        items = [value]
    cleaned = []
    for item in items:
        text = str(item).strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def normalize_category(value) -> str:
    category = as_text(value).lower()
    return category if category in VALID_CATEGORIES else labels.DEFAULT_CATEGORY


def normalize_tone(value) -> str:
    tone = as_text(value).lower()
    return tone if tone in VALID_TONES else labels.DEFAULT_TONE


def normalize_sentiment(value) -> str:
    """Map a raw sentiment label to one of VALID_SENTIMENTS.

    Used for per-item fields (people_opinions, frequent_ideas/feedback
    entries) - never for the article-level overall_sentiment/sentiment,
    which comes solely from analysis/sentiment.py.
    """
    sentiment = as_text(value).lower().strip()
    if sentiment in VALID_SENTIMENTS:
        return sentiment
    if not sentiment:
        return "neutral"

    words = set(re.findall(r"[a-z]+", sentiment))
    has_positive = "positive" in words or "positives" in words
    has_negative = "negative" in words or "negatives" in words
    has_mixed = "mixed" in words or "ambivalent" in words or "ambiguous" in words

    if has_mixed or (has_positive and has_negative):
        return "mixed"
    if has_positive:
        return "positive"
    if has_negative:
        return "negative"
    return "neutral"


def normalize_feedback_list(value) -> list:
    return as_list(value)


def coerce_frequency_estimate(value) -> int:
    try:
        return max(1, int(float(value)))
    except Exception:
        return 1


def normalize_relevance_score(value):
    try:
        score = float(value)
    except Exception:
        return 0
    return max(0, min(score, 10))


def normalize_people_opinions(value) -> list:
    opinions = []
    if not isinstance(value, list):
        return opinions
    for item in value:
        if not isinstance(item, dict):
            text = as_text(item)
            if text:
                opinions.append({"opinion": text, "sentiment": "neutral", "category": ""})
            continue
        opinion = as_text(item.get("opinion"))
        if not opinion:
            continue
        opinions.append({
            "opinion": opinion,
            "sentiment": normalize_sentiment(item.get("sentiment")),
            "category": as_text(item.get("category")),
        })
    deduped = []
    seen = set()
    for item in opinions:
        key = (item["opinion"].lower(), item["sentiment"], item["category"].lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


_FREQUENT_IDEA_TYPES = {"complaint", "praise", "suggestion", "issue"}


def normalize_frequent_ideas(value) -> list:
    ideas = []
    if not isinstance(value, list):
        return ideas
    for item in value:
        if isinstance(item, dict):
            idea = as_text(item.get("idea"))
            if not idea:
                continue
            type_value = as_text(item.get("type")).lower()
            ideas.append({
                "idea": idea,
                "type": type_value if type_value in _FREQUENT_IDEA_TYPES else "issue",
                "category": as_text(item.get("category")),
                "frequency_estimate": coerce_frequency_estimate(item.get("frequency_estimate", 1)),
            })
        else:
            idea = as_text(item)
            if idea:
                ideas.append({"idea": idea, "type": "issue", "category": "", "frequency_estimate": 1})
    deduped = []
    seen = set()
    for item in ideas:
        key = (item["idea"].lower(), item["type"], item["category"].lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped
