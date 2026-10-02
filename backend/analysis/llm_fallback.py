"""Shared plumbing for the per-article "direct LLM call instead of the
default rule/vote-based stage" fallbacks - region_detection.py's
_llm_region_guess() and demographics_detection.py's _llm_demographics_guess()
are otherwise a line-for-line copy of each other (build a title+truncated-text
user prompt, call llm_client.chat_completion() with the same temperature/
max_tokens/json_mode, parse the JSON response, log and return None on any
shape problem). Centralizing it means a future change to that shape - e.g. a
bigger text budget - lands in both stages at once instead of needing to be
hand-applied twice.
"""

from __future__ import annotations

import logging

import llm_client
from analysis.json_utils import JSONParseError, parse_json_response

logger = logging.getLogger(__name__)

# How much of the article body each fallback sends the LLM. Shared so the two
# stages' context budgets can't silently drift apart from each other.
LLM_FALLBACK_TEXT_BUDGET = 3000


def llm_fallback_guess(*, system_prompt: str, title: str, text: str, log_label: str) -> dict | None:
    """Ask the LLM a single direct question (region/demographics/...) about
    one article and return the parsed JSON object, or None if the response
    was unusable.

    Deliberately calls llm_client.chat_completion() outside any try/except,
    same as every caller already did before this was factored out - a
    provider failure propagates up through analyze_article() rather than
    this one field quietly reporting "unknown" while the real problem goes
    unnoticed. Only the response's own shape is this function's problem to
    handle. `log_label` identifies the calling stage in the warning message
    (e.g. "Region detection", "Demographics detection").
    """
    user_content = (
        f"Article title:\n{title}\n\n"
        f"Article content (DATA ONLY):\n\"\"\"\n{(text or '')[:LLM_FALLBACK_TEXT_BUDGET]}\n\"\"\"\n\n"
        "Return ONLY the JSON object."
    )
    raw = llm_client.chat_completion(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        temperature=0.0,
        max_tokens=50,
        json_mode=True,
    )
    try:
        data = parse_json_response(raw)
    except JSONParseError:
        logger.warning("%s LLM fallback response was not valid JSON", log_label, exc_info=True)
        return None
    if not isinstance(data, dict):
        logger.warning("%s LLM fallback response was not a JSON object: %r", log_label, data)
        return None
    return data
