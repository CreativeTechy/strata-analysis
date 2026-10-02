"""Independent per-article demographics-detection stage.

Wraps aggregation.compute_dominant_demographics (majority vote across
structured_extraction's per-quote gender/age_range tags) as the default, and
adds the same either/or LLM-fallback toggle region_detection.py already has
for region: config.DEMOGRAPHICS_LLM_FALLBACK (off by default; env var or the
Settings page) switches an article over to a single direct LLM call instead
of trusting the per-quote tags - see _llm_only_demographics().

Deliberately not another LLM call by default, same reasoning as
region_detection.py's module docstring: one local Ollama server backs the
whole pipeline, so a second per-article round trip for a field that already
has a free-ish answer (structured_extraction's own people_opinions, already
paid for) isn't free. "on" bypasses the majority vote entirely rather than
only consulting the LLM when the vote comes up "unknown" - a majority-vote
"unknown" usually means the article's quotes themselves gave no signal, not
that a second opinion on top of them would help.
"""

from __future__ import annotations

import config
from analysis import labels, normalize
from analysis.aggregation import compute_dominant_demographics
from analysis.llm_fallback import llm_fallback_guess
from prompt_loader import load_prompt

_LLM_FALLBACK_SYSTEM_PROMPT = load_prompt(
    "demographics_detection_llm_fallback_system_prompt.txt",
    fallback=(
        "You identify the gender and age range of the people an article is actually about - the "
        "subjects/sources quoted or described, not the journalist who wrote it. "
        "Reply with ONLY a JSON object of the shape "
        "{\"gender\": \"male|female|unknown\", \"age_range\": "
        "\"under_18|18-24|25-34|35-44|45-54|55-64|65_plus|unknown\"}. "
        "Only answer male/female or a specific age bucket when the article gives a clear, explicit "
        "signal (a pronoun, a stated age, a title) - never infer from a name, a job title, or "
        "stereotype. If the article covers several people with no single dominant gender or age "
        "group, or gives no such signal at all, reply \"unknown\" for that field."
    ),
)


def _llm_demographics_guess(title: str, text: str) -> dict | None:
    """One extra LLM call asking directly for the article's dominant
    gender/age_range. Only ever invoked by _llm_only_demographics() below,
    when config.DEMOGRAPHICS_LLM_FALLBACK is "on" - so the default (majority
    vote over structured_extraction's own per-quote tags, already paid for)
    never pays for a second per-article round trip. Returns a dict with
    normalized gender/age_range, or None if the response was unusable.

    Delegates the actual call/parse/error-handling to
    analysis.llm_fallback.llm_fallback_guess() - same as
    region_detection.py's _llm_region_guess() - so a provider failure
    propagates up through analyze_article() rather than this one field
    quietly reporting "unknown" while the real problem goes unnoticed. Only
    the response's own shape is this function's problem.
    """
    data = llm_fallback_guess(
        system_prompt=_LLM_FALLBACK_SYSTEM_PROMPT,
        title=title,
        text=text,
        log_label="Demographics detection",
    )
    if data is None:
        return None
    return {
        "gender": normalize.normalize_gender(data.get("gender")),
        "age_range": normalize.normalize_age_range(data.get("age_range")),
    }


def _llm_only_demographics(title: str, text: str) -> dict:
    """config.DEMOGRAPHICS_LLM_FALLBACK == "on": skip the majority vote
    entirely and answer from a single direct LLM call instead (see module
    docstring). A failed/unusable call still returns a real result
    ("unknown"/"unknown") rather than silently falling back to the
    majority vote this mode was told to bypass."""
    guess = _llm_demographics_guess(title, text)
    if guess is None:
        return {"gender": labels.DEFAULT_GENDER, "age_range": labels.DEFAULT_AGE_RANGE}
    return guess


def detect_demographics(*, title: str = "", text: str = "", people_opinions=None) -> dict:
    """Per-article gender/age_range - majority vote over
    structured_extraction's per-quote tags by default (see
    aggregation.compute_dominant_demographics), or a single direct LLM call
    when config.DEMOGRAPHICS_LLM_FALLBACK == "on" (see
    _llm_only_demographics())."""
    if config.DEMOGRAPHICS_LLM_FALLBACK == "on":
        return _llm_only_demographics(title, text)
    return compute_dominant_demographics(people_opinions)
