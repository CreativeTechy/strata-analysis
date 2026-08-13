"""Sentiment stage: thin wrapper around sentiment_classifier.py.

sentiment_classifier.py already implements the lazy-loaded HF pipeline
(cardiffnlp/twitter-roberta-base-sentiment-latest by default) and is kept
as-is - this module just adds chunking for long text and a confidence
threshold with an explicit low-confidence fallback, so callers get one
clear result shape instead of reimplementing that logic themselves.
"""

from __future__ import annotations

from collections import defaultdict

import config
from analysis.article_prep import chunk_text as _chunk_text
from hf_inference_client import HFInferenceError
from sentiment_classifier import classify_sentiment

_ALLOWED_LABELS = {"positive", "negative", "neutral"}


def classify_article_sentiment(text: str) -> dict:
    """Return {"label", "score", "low_confidence", "raw_label"}.

    `label` is always one of positive/negative/neutral - it is downgraded to
    "neutral" (with `low_confidence=True`) when the classifier is unavailable,
    returns an unusable label, or its confidence is below
    config.SENTIMENT_CONFIDENCE_THRESHOLD. `raw_label`/`score` preserve what
    the classifier actually said for logging, even when downgraded.
    """
    text = (text or "").strip()
    if not text:
        return {"label": "neutral", "score": 0.0, "low_confidence": True, "raw_label": None}

    chunks = _chunk_text(text) or [text]
    # Sentiment only needs one representative pass for short/medium articles;
    # only chunk when the text is long enough that classify_sentiment's own
    # 512-char truncation would otherwise only ever see the opening chunk.
    if len(chunks) == 1:
        result = _safe_classify(chunks[0])
        return _to_result(result)

    score_by_label = defaultdict(float)
    count_by_label = defaultdict(int)
    for chunk in chunks:
        result = _safe_classify(chunk)
        if not result:
            continue
        score_by_label[result["label"]] += result["score"]
        count_by_label[result["label"]] += 1

    if not score_by_label:
        return _to_result(None)

    best_label = max(score_by_label, key=lambda label: score_by_label[label])
    avg_score = score_by_label[best_label] / max(1, count_by_label[best_label])
    return _to_result({"label": best_label, "score": avg_score})


def _safe_classify(text: str):
    try:
        return classify_sentiment(text)
    except HFInferenceError:
        raise
    except Exception:
        return None


def _to_result(result) -> dict:
    label = result.get("label") if result else None
    score = float(result.get("score", 0.0)) if result else 0.0

    if label not in _ALLOWED_LABELS:
        return {"label": "neutral", "score": 0.0, "low_confidence": True, "raw_label": label}

    if score < config.SENTIMENT_CONFIDENCE_THRESHOLD:
        return {"label": "neutral", "score": score, "low_confidence": True, "raw_label": label}

    return {"label": label, "score": score, "low_confidence": False, "raw_label": label}
