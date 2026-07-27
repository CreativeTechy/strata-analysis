"""Unified orchestration for the modular analysis pipeline.

Runs, per article: article_prep -> structured_extraction -> sentiment ->
classification (category + writer_tone + article_tone) -> language ->
entity_extraction (optional) -> embeddings. Results are folded into the same
article dict shape the old single-LLM enrich_article() used to return (see
enrich.DEFAULT_ENRICHMENT), plus the additional per-stage metadata
(scores/confidences/model ids/processing status) the persistence layer
needs - so store.py can write it straight into the columns added for the
analysis pipeline without any further translation.

Each stage already applies its own low-confidence/unavailable fallback
(neutral sentiment, general_article/neutral tone, [] feedback lists).
analyze_article() ALWAYS returns a dict, never None: if structured
extraction itself fails outright (no valid JSON even after the correction
retry), there is no trustworthy summary/feedback to report, so the result
carries neutral/empty content fields but analysis_status="failed" and
analysis_error set to why - the caller (enrich.py) stores that as a real,
queryable failure state instead of silently guessing at content. A bare
exception escaping every stage's own handling is the only case this
doesn't catch; enrich.enrich_article() still guards for that.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import config
from analysis import article_prep, classification, entity_extraction, language, structured_extraction
from analysis.aggregation import compute_overall_tone
from analysis.sentiment import classify_article_sentiment
from embeddings import build_article_embedding_text, get_embedding

logger = logging.getLogger(__name__)

PIPELINE_VERSION = "analysis-pipeline/1"

_EMPTY_EMBEDDING_FIELDS = {
    "embedding_json": [],
    "embedding_model": "",
    "embedding_source": "",
    "embedded_at": "",
}

# Used to fill `extracted` when structured extraction fails outright, so the
# rest of analyze_article() (which reads from `extracted`) doesn't need a
# separate code path for the failure case.
_NEUTRAL_EXTRACTED = {
    "topic": "",
    "summary": "",
    "relevance_score": 0,
    "people_opinions": [],
    "frequent_ideas": [],
    **{field: [] for field in structured_extraction.LIST_FIELDS},
}


def describe_models() -> str:
    """Compact "stage=model;stage=model" label stored in analysis_model,
    since the schema has one text column for what used to be one model.
    Per-stage model identifiers are also stored in their own columns
    (sentiment_model/classification_model/extraction_model/embedding_model)
    for querying - this stays for backward compatibility with rows/readers
    written before those columns existed."""
    return (
        f"sentiment={config.SENTIMENT_CLASSIFIER_MODEL or 'unavailable'}"
        f";classification={config.CLASSIFICATION_MODEL or 'unavailable'}"
        f";extraction={config.STRUCTURED_EXTRACTION_MODEL or 'unavailable'}"
        f";embedding={config.EMBEDDING_MODEL or 'unavailable'}"
    )


def analyze_article(article: dict, *, project_context: str = "") -> dict:
    title = article.get("title", "")
    started_at = datetime.now(timezone.utc).isoformat()

    prepared = article_prep.prepare_article(article)
    model_title = prepared["title"] or title
    model_text = prepared["text"]

    extraction = structured_extraction.extract_structured_data(
        model_title, model_text, project_context=project_context
    )
    if extraction.failed:
        logger.warning("Structured extraction failed for '%s...': %s", title[:50], extraction.reason)
        analysis_status = "failed"
        analysis_error = extraction.reason
        extracted = dict(_NEUTRAL_EXTRACTED)
    else:
        analysis_status = "success"
        analysis_error = None
        extracted = extraction.data

    sentiment_result = classify_article_sentiment(
        "\n".join(part for part in (model_title, extracted.get("summary"), model_text) if part)
    )
    category_result = classification.classify_category(model_text)
    writer_tone_result = classification.classify_writer_tone(model_text)
    article_tone_result = classification.classify_article_tone(model_text)
    language_result = language.detect_language(model_text)

    for stage_name, stage_result in (
        ("sentiment", sentiment_result),
        ("category", category_result),
        ("writer_tone", writer_tone_result),
        ("article_tone", article_tone_result),
        ("language", language_result),
    ):
        if stage_result.get("low_confidence"):
            logger.info(
                "Low-confidence %s for '%s...': label=%r (raw=%r, score=%.3f)",
                stage_name, title[:50], stage_result.get("label"),
                stage_result.get("raw_label"), stage_result.get("score", 0.0),
            )

    organizations = extracted.get("organizations") or []
    entities = extracted.get("entities") or []
    entities_override = entity_extraction.extract_entities(model_text)
    if entities_override is not None:
        organizations = entities_override.get("organizations") or organizations
        entities = entities_override.get("entities") or entities

    writer_tone = writer_tone_result["label"]
    article_tone = article_tone_result["label"]
    overall_tone = compute_overall_tone(article_tone, writer_tone)

    insight_json = {
        "topic": extracted.get("topic", ""),
        "article_category": category_result["label"],
        "overall_sentiment": sentiment_result["label"],
        "writer_tone": writer_tone,
        "article_tone": article_tone,
        "overall_tone": overall_tone,
        "summary": extracted.get("summary", ""),
        "positive_feedback": extracted.get("positive_feedback", []),
        "negative_feedback": extracted.get("negative_feedback", []),
        "nice_to_have_features": extracted.get("nice_to_have_features", []),
        "complaints": extracted.get("complaints", []),
        "great_features": extracted.get("great_features", []),
        "comfort_issues": extracted.get("comfort_issues", []),
        "performance_feedback": extracted.get("performance_feedback", []),
        "price_value_feedback": extracted.get("price_value_feedback", []),
        "maintenance_reliability_feedback": extracted.get("maintenance_reliability_feedback", []),
        "technology_feedback": extracted.get("technology_feedback", []),
        "safety_feedback": extracted.get("safety_feedback", []),
        "people_opinions": extracted.get("people_opinions", []),
        "frequent_ideas": extracted.get("frequent_ideas", []),
    }

    result = {
        **insight_json,
        "entities": entities,
        "organizations": organizations,
        "topics": extracted.get("topics", []),
        "key_points": extracted.get("key_points", []),
        "risks": extracted.get("risks", []),
        "opportunities": extracted.get("opportunities", []),
        "car_models": entities,
        "brands": organizations,
        "sentiment": sentiment_result["label"],
        "category": category_result["label"],
        "relevance_score": extracted.get("relevance_score", 0),
        "analysis_model": describe_models(),
        "analysis_prompt_version": PIPELINE_VERSION,
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "insight_json": insight_json,
        **_EMPTY_EMBEDDING_FIELDS,
        # --- per-stage metadata for the persistence layer ---
        "sentiment_score": float(sentiment_result.get("score", 0.0)),
        "sentiment_low_confidence": bool(sentiment_result.get("low_confidence")),
        "sentiment_model": config.SENTIMENT_CLASSIFIER_MODEL or None,
        "category_confidence": float(category_result.get("score", 0.0)),
        "writer_tone_confidence": float(writer_tone_result.get("score", 0.0)),
        "article_tone_confidence": float(article_tone_result.get("score", 0.0)),
        "classification_model": config.CLASSIFICATION_MODEL or None,
        "extraction_model": config.STRUCTURED_EXTRACTION_MODEL or None,
        "analysis_pipeline_version": PIPELINE_VERSION,
        "source_language": language_result.get("language"),
        "source_language_confidence": float(language_result.get("score", 0.0)),
        "analysis_status": analysis_status,
        "analysis_error": analysis_error,
        "analysis_started_at": started_at,
        "analysis_finished_at": datetime.now(timezone.utc).isoformat(),
        "analysis_attempt_count": extraction.attempts,
    }

    embedding_text = build_article_embedding_text(article, result)
    embedding = get_embedding(embedding_text)
    if embedding:
        result.update(embedding)

    return result
