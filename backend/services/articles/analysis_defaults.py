"""Neutral analysis defaults and the provider-failure contract.

Two things every analysis caller needs and neither `analysis/` nor
`reanalyze.py` should own:

* `DEFAULT_ENRICHMENT` - a complete, neutral article-analysis dict. Several
  `articles` columns are not-null with no python-side default, so a caller
  writing an article that has not been analyzed yet (a document candidate
  being materialized) starts from this rather than a bare dict.
* `FATAL_ANALYSIS_ERRORS` - the provider failures that mean "stop, everything
  else will fail identically" rather than "this article failed".
"""

from analysis.orchestrator import PIPELINE_VERSION, describe_models
from hf_inference_client import HFAuthError, HFConfigError, HFQuotaError
from llm_client import (
    LLMAuthError, LLMConfigError, LLMConnectionError, LLMEndpointNotFoundError,
    LLMQuotaError,
)

# Only the AI provider failures that mean the provider is unusable outright
# - missing/invalid credentials, the account being out of credit/quota, or
# the endpoint being flat-out unreachable (DNS/connection failure, or a 404 -
# every call here uses the same URL, so a 404 is never article-specific, it
# means the configured base URL/tunnel itself is wrong or offline, e.g. an
# expired ngrok tunnel in front of a local Ollama) - stop the whole pipeline:
# every remaining article would fail the exact same way, so grinding through
# the rest of the run would just be doomed calls. Everything else an AI
# provider call can raise (rate limit, timeout, a reachable server's own 5xx,
# a bad request, or a response with no usable content - see
# llm_client.LLMInvalidResponseError/HFInferenceError's other subclasses) is
# a one-off failure of *this* article's call, not proof the provider itself
# is broken, so it is NOT included here - reanalyze_article() records that
# single article as failed and the run keeps going. Both the LLM and the
# Hugging Face client raise into this tuple, so either provider type stops a
# run the same way.
#
# This matters more here than it did in the crawler this was forked from: with
# LLM_PROVIDER=ollama the single most common failure is "the local model server
# isn't running", which is exactly LLMConnectionError - and a run that reported
# 400 individually-failed articles instead of "the model host is unreachable"
# would be telling the operator nothing.
FATAL_ANALYSIS_ERRORS = (
    LLMConfigError, LLMAuthError, LLMQuotaError, LLMConnectionError, LLMEndpointNotFoundError,
    HFConfigError, HFAuthError, HFQuotaError,
)

# The neutral fallback used when the analysis pipeline crashed somewhere no
# stage's own error handling caught, and as the starting point for an article
# materialized out of a document (which has no analysis yet - see
# services/projects/project_document_articles.py).
# In the ordinary "structured extraction failed validation" case,
# analyze_article() already returns neutral content plus a real
# analysis_status="failed"/analysis_error - this is the last-resort fallback
# below that.
DEFAULT_ENRICHMENT = {
    "topic": "",
    "article_category": "general_article",
    "overall_sentiment": "neutral",
    "writer_tone": "neutral",
    "article_tone": "neutral",
    "overall_tone": "neutral",
    "region": "unknown",
    "gender": "unknown",
    "age_range": "unknown",
    "summary": "",
    "positive_feedback": [],
    "negative_feedback": [],
    "nice_to_have_features": [],
    "complaints": [],
    "great_features": [],
    "comfort_issues": [],
    "performance_feedback": [],
    "price_value_feedback": [],
    "maintenance_reliability_feedback": [],
    "technology_feedback": [],
    "safety_feedback": [],
    "people_opinions": [],
    "frequent_ideas": [],
    "entities": [],
    "organizations": [],
    "topics": [],
    "key_points": [],
    "risks": [],
    "opportunities": [],
    "car_models": [],
    "brands": [],
    "sentiment": "neutral",
    "category": "general_article",
    "relevance_score": 0,
    "analysis_model": describe_models(),
    "analysis_prompt_version": PIPELINE_VERSION,
    "analyzed_at": "",
    "insight_json": {},
    "embedding_json": [],
    "embedding_model": "",
    "embedding_source": "",
    "embedded_at": "",
    "sentiment_score": 0.0,
    "sentiment_low_confidence": True,
    "sentiment_model": None,
    "category_confidence": 0.0,
    "writer_tone_confidence": 0.0,
    "article_tone_confidence": 0.0,
    "classification_model": None,
    "extraction_model": None,
    "analysis_pipeline_version": PIPELINE_VERSION,
    "source_language": None,
    "source_language_confidence": 0.0,
    "analysis_status": "failed",
    "analysis_error": "pipeline_crashed",
    "analysis_started_at": None,
    "analysis_finished_at": None,
    "analysis_attempt_count": 0,
}
