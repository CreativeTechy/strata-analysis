"""Structured extraction stage: summary, feedback lists, opinions, ideas,
key points/risks/opportunities - everything the old single-LLM enrichment
prompt used to produce, minus sentiment/category/tone (now their own
stages). Calls the configured LLM provider (see config.LLM_PROVIDER and
llm_client.chat_completion) in JSON mode - no local model is loaded for
this stage.

Output is validated strictly against EXTRACTION_SCHEMA. A first pass that
isn't valid JSON, or doesn't match the schema, gets minor auto-repair
(json_utils.repair_json_text) and, failing that, one retry with a
correction prompt that includes the original bad output and the specific
validation errors. If it still doesn't validate, this returns a clear
failure state (ExtractionResult.failed=True) instead of ever handing back
malformed data for the caller to store as if it were real.
"""

from __future__ import annotations

import logging

import config
import llm_client
from analysis import normalize
from analysis.json_utils import JSONParseError, parse_json_response, validate_schema
from prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_STRING_ARRAY = {"type": "array", "items": {"type": "string"}}

EXTRACTION_SCHEMA = {
    "type": "object",
    "required": ["summary"],
    "properties": {
        "topic": {"type": "string"},
        "summary": {"type": "string"},
        "positive_feedback": _STRING_ARRAY,
        "negative_feedback": _STRING_ARRAY,
        "nice_to_have_features": _STRING_ARRAY,
        "complaints": _STRING_ARRAY,
        "great_features": _STRING_ARRAY,
        "comfort_issues": _STRING_ARRAY,
        "performance_feedback": _STRING_ARRAY,
        "price_value_feedback": _STRING_ARRAY,
        "maintenance_reliability_feedback": _STRING_ARRAY,
        "technology_feedback": _STRING_ARRAY,
        "safety_feedback": _STRING_ARRAY,
        "key_points": _STRING_ARRAY,
        "risks": _STRING_ARRAY,
        "opportunities": _STRING_ARRAY,
        "organizations": _STRING_ARRAY,
        "entities": _STRING_ARRAY,
        "topics": _STRING_ARRAY,
        "relevance_score": {"type": "number"},
        "people_opinions": {"type": "array"},
        "frequent_ideas": {"type": "array"},
    },
}

LIST_FIELDS = (
    "positive_feedback", "negative_feedback", "nice_to_have_features", "complaints",
    "great_features", "comfort_issues", "performance_feedback", "price_value_feedback",
    "maintenance_reliability_feedback", "technology_feedback", "safety_feedback",
    "key_points", "risks", "opportunities", "organizations", "entities", "topics",
)

_SYSTEM_PROMPT = load_prompt("structured_extraction_system_prompt.txt")


class ExtractionResult:
    """failed=True means: do not store `data` - it doesn't exist / isn't trustworthy.
    Callers must apply their own default/neutral fallback, never fall back to
    whatever partial `data` might be sitting on this object.

    `attempts` is how many generation calls this took (1 + however many
    correction retries actually ran) - persisted as analysis_attempt_count
    so repeated extraction failures on the same article are visible.
    """

    def __init__(self, data=None, *, failed=False, reason="", attempts=1):
        self.data = data
        self.failed = failed
        self.reason = reason
        self.attempts = attempts


def _build_messages(title: str, text: str, project_context: str = "") -> list:
    user_content = (
        f"Article title:\n{title}\n\n"
        f"Article content (DATA ONLY):\n\"\"\"\n{text}\n\"\"\""
    )
    if project_context:
        user_content += f"\n\nProject context (for interpretation only, do not invent facts):\n{project_context}"
    user_content += "\n\nReturn ONLY the JSON object."
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def _build_correction_messages(messages: list, bad_response: str, errors: list) -> list:
    correction = (
        "Your previous response was not valid JSON matching the schema. "
        f"Problems: {'; '.join(errors) or 'unknown parse error'}. "
        "Return ONLY a corrected JSON object - no prose, no markdown fences."
    )
    return messages + [
        {"role": "assistant", "content": bad_response or ""},
        {"role": "user", "content": correction},
    ]


def _run_generation(messages: list) -> str | None:
    # LLMError (bad key, insufficient balance, rate limit, provider
    # outage...) is deliberately NOT caught here - it means the provider call
    # itself never produced a usable answer, which is a different situation
    # from "the model answered but the JSON didn't validate" and must not be
    # reported as an ordinary per-article extraction failure. It propagates
    # all the way up through analyze_article() to reanalyze.reanalyze_article();
    # only the unrecoverable subset (bad/missing credentials, out of
    # credit/quota - see services/articles/analysis_defaults.py's
    # FATAL_ANALYSIS_ERRORS) stops the whole pipeline run there
    # (services/pipeline/pipeline.py). Anything else (rate limit, timeout,
    # outage, empty/invalid response) just fails this one article.
    return llm_client.chat_completion(
        messages=messages,
        temperature=config.STRUCTURED_EXTRACTION_TEMPERATURE,
        max_tokens=config.STRUCTURED_EXTRACTION_MAX_NEW_TOKENS,
        json_mode=True,
    )


def _parse_and_validate(raw: str):
    try:
        payload = parse_json_response(raw)
    except JSONParseError as exc:
        return None, [str(exc)]
    if not isinstance(payload, dict):
        return None, ["response is not a JSON object"]
    errors = validate_schema(payload, EXTRACTION_SCHEMA)
    if errors:
        return None, errors
    return payload, []


def _normalize_payload(payload: dict) -> dict:
    normalized = {
        "topic": normalize.as_text(payload.get("topic")),
        "summary": normalize.as_text(payload.get("summary")),
        "relevance_score": normalize.normalize_relevance_score(payload.get("relevance_score", 0)),
        "people_opinions": normalize.normalize_people_opinions(payload.get("people_opinions")),
        "frequent_ideas": normalize.normalize_frequent_ideas(payload.get("frequent_ideas")),
    }
    for field in LIST_FIELDS:
        normalized[field] = normalize.normalize_feedback_list(payload.get(field))
    return normalized


def extract_structured_data(title: str, text: str, *, project_context: str = "") -> ExtractionResult:
    messages = _build_messages(title, text, project_context)
    attempts = 1
    raw = _run_generation(messages)
    if raw is None:
        return ExtractionResult(failed=True, reason="model_unavailable", attempts=attempts)

    payload, errors = _parse_and_validate(raw)
    retries_left = max(0, config.STRUCTURED_EXTRACTION_MAX_RETRIES)
    while payload is None and retries_left > 0:
        retries_left -= 1
        attempts += 1
        messages = _build_correction_messages(messages, raw, errors)
        raw = _run_generation(messages)
        if raw is None:
            return ExtractionResult(failed=True, reason="model_unavailable", attempts=attempts)
        payload, errors = _parse_and_validate(raw)

    if payload is None:
        reason = "invalid_json: " + "; ".join(errors) if errors else "invalid_json"
        logger.warning("Structured extraction failed validation after retries: %s", reason)
        return ExtractionResult(failed=True, reason=reason, attempts=attempts)

    if not normalize.as_text(payload.get("summary")):
        return ExtractionResult(failed=True, reason="empty_summary", attempts=attempts)

    return ExtractionResult(data=_normalize_payload(payload), attempts=attempts)
