"""Pure value-normalization helpers shared across analysis stages.

Kept separate so structured_extraction.py and aggregation.py can
reuse the exact same feedback-list/people-opinion/frequent-idea normalization
instead of a second copy drifting out of sync.
"""

from __future__ import annotations

import re

from analysis import labels
from services.competitors.countries import COUNTRIES, resolve_country_alias

VALID_CATEGORIES = set(labels.VALID_CATEGORIES)
VALID_TONES = set(labels.VALID_TONES)
VALID_SENTIMENTS = {"positive", "negative", "mixed", "neutral"}
VALID_GENDERS = set(labels.VALID_GENDERS)
VALID_AGE_RANGES = set(labels.VALID_AGE_RANGES)
_COUNTRY_NAMES_BY_LOWER = {name.lower(): name for name in COUNTRIES.values()}


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


def normalize_gender(value) -> str:
    gender = as_text(value).lower()
    if gender in VALID_GENDERS:
        return gender
    return labels.GENDER_ALIASES.get(gender, labels.DEFAULT_GENDER)


def normalize_age_range(value) -> str:
    age_range = as_text(value).lower().replace(" ", "")
    return age_range if age_range in VALID_AGE_RANGES else labels.DEFAULT_AGE_RANGE


def normalize_region(value) -> str:
    """Best-effort canonicalization: a known country name/code matches to its
    canonical form (see services/competitors/countries.py, already used the
    same way for competitor target countries), and a common abbreviation/
    demonym (COUNTRY_ALIASES - "USA", "American", "UK", "British", ...)
    resolves to that same canonical form so free-text model output doesn't
    fragment into near-duplicates. Anything else is passed through as
    trimmed free text (city, "Middle East", ...) rather than forced into the
    closed country list, since a quoted person's region isn't always a
    country. Blank stays "unknown"."""
    text = as_text(value)
    if not text:
        return labels.DEFAULT_REGION
    lowered = text.lower()
    if lowered == labels.DEFAULT_REGION:
        return labels.DEFAULT_REGION
    if lowered in _COUNTRY_NAMES_BY_LOWER:
        return _COUNTRY_NAMES_BY_LOWER[lowered]
    upper = text.upper()
    if upper in COUNTRIES:
        return COUNTRIES[upper]
    alias_code = resolve_country_alias(text)
    if alias_code:
        return COUNTRIES[alias_code]
    return text


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


_GENDER_EVIDENCE_MAX_LEN = 160


def normalize_gender_evidence(value, gender: str) -> str:
    """The exact word/phrase the model says it relied on for `gender` (see
    structured_extraction_system_prompt.txt) - kept as an audit trail so a
    "male"/"female" call can be checked against real wording instead of
    trusted blind, and so a low-effort or hallucinated call (gender set but
    no real evidence quoted) is visible as an empty string rather than
    indistinguishable from a well-evidenced one. Dropped whenever gender
    itself resolved to "unknown" - evidence for a value that didn't survive
    normalize_gender is not meaningful and would just be noise (or, worse,
    the model's guess from a name) sitting on a row that claims no signal."""
    if gender == labels.DEFAULT_GENDER:
        return ""
    return as_text(value)[:_GENDER_EVIDENCE_MAX_LEN]


def normalize_people_opinions(value) -> list:
    opinions = []
    if not isinstance(value, list):
        return opinions
    for item in value:
        if not isinstance(item, dict):
            text = as_text(item)
            if text:
                opinions.append({
                    "opinion": text,
                    "sentiment": "neutral",
                    "category": "",
                    "gender": labels.DEFAULT_GENDER,
                    "gender_evidence": "",
                    "age_range": labels.DEFAULT_AGE_RANGE,
                    "region": labels.DEFAULT_REGION,
                    "segment": labels.DEFAULT_SEGMENT,
                })
            continue
        opinion = as_text(item.get("opinion"))
        if not opinion:
            continue
        gender = normalize_gender(item.get("gender"))
        opinions.append({
            "opinion": opinion,
            "sentiment": normalize_sentiment(item.get("sentiment")),
            "category": as_text(item.get("category")),
            "gender": gender,
            "gender_evidence": normalize_gender_evidence(item.get("gender_evidence"), gender),
            "age_range": normalize_age_range(item.get("age_range")),
            "region": normalize_region(item.get("region")),
            "segment": as_text(item.get("segment")) or labels.DEFAULT_SEGMENT,
        })
    deduped = []
    seen = set()
    for item in opinions:
        # Includes gender/age_range/region/segment so two different quoted
        # people who happen to share the same short opinion/sentiment/category
        # aren't collapsed into one row and lose a demographic.
        key = (
            item["opinion"].lower(), item["sentiment"], item["category"].lower(),
            item["gender"], item["age_range"], item["region"].lower(), item["segment"].lower(),
        )
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
                "value": as_text(item.get("value")),
            })
        else:
            idea = as_text(item)
            if idea:
                ideas.append({"idea": idea, "type": "issue", "category": "", "frequency_estimate": 1, "value": ""})
    deduped = []
    seen = set()
    for item in ideas:
        # value is deliberately excluded from the key: two occurrences of the
        # same idea with different stated values are still one idea for
        # per-article dedup purposes (idea_clustering.py is where different
        # values across different *articles* matter), so the first value seen
        # on this article wins rather than spawning a near-duplicate entry.
        key = (item["idea"].lower(), item["type"], item["category"].lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped
