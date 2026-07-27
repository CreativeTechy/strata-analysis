"""Optional dedicated sentiment classifier, used only to double-check
`overall_sentiment` - the rest of the enrichment payload stays LLM-driven.

Disabled by default. Set `SENTIMENT_CLASSIFIER_MODEL` in backend/.env to a
Hugging Face text-classification model id (e.g.
"cardiffnlp/twitter-roberta-base-sentiment-latest") to enable it.

Where this plugs in: enrich.py calls classify_sentiment() only when the LLM's
overall_sentiment came back "neutral", and only promotes it to positive/negative
when the classifier is confident (see SENTIMENT_CLASSIFIER_MIN_SCORE in
config.py). It never overrides a non-neutral LLM sentiment and it can't
produce "mixed" itself, so LLM-detected nuance (mixed, category-driven
negative, etc.) is left alone. This targets the specific failure mode of an
overly-cautious prompt/model defaulting to neutral, without touching anything
else in the pipeline.

`transformers` is already a transitive dependency of sentence-transformers
(see requirements.txt), so enabling this normally requires no new install.
If it's missing, or the model fails to load, this fails soft to None and
enrich.py just keeps the LLM's sentiment - the pipeline never breaks because
of this module.
"""

from __future__ import annotations

import logging
from functools import lru_cache

import config

logger = logging.getLogger(__name__)

# Some 3-class sentiment models expose labels as LABEL_0/1/2 instead of
# human-readable names, depending on how their config.json was authored.
_LABEL_ALIASES = {
    "label_0": "negative",
    "label_1": "neutral",
    "label_2": "positive",
}


@lru_cache(maxsize=1)
def _load_pipeline():
    model_name = (config.SENTIMENT_CLASSIFIER_MODEL or "").strip()
    if not model_name:
        return None
    try:
        from transformers import pipeline
    except Exception:
        logger.warning(
            "SENTIMENT_CLASSIFIER_MODEL=%s is set but the `transformers` package "
            "isn't installed; the dedicated sentiment classifier is disabled.",
            model_name,
        )
        return None
    try:
        return pipeline("sentiment-analysis", model=model_name)
    except Exception:
        logger.exception("Failed to load sentiment classifier model '%s'", model_name)
        return None


def classify_sentiment(text: str):
    """Return {"label": "positive"|"negative"|"neutral", "score": float}, or
    None if the classifier is disabled, unavailable, or failed - callers
    should treat None as "no opinion" and keep whatever sentiment they have.
    """
    text = (text or "").strip()
    if not text:
        return None

    classifier = _load_pipeline()
    if classifier is None:
        return None

    try:
        result = classifier(text[:512])[0]
    except Exception:
        logger.exception("Sentiment classifier inference failed")
        return None

    label = (result.get("label") or "").strip().lower()
    label = _LABEL_ALIASES.get(label, label)
    if label not in ("positive", "negative", "neutral"):
        return None

    try:
        score = float(result.get("score"))
    except Exception:
        score = 0.0

    return {"label": label, "score": score}
