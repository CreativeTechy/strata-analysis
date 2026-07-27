"""Dedicated sentiment classifier for article `overall_sentiment`.

This is the ONLY source of article sentiment - the LLM used for the rest of
enrichment (summary, topic, category, tones, feedback lists, ...) is never
consulted for sentiment, and never overrides or backfills it. Sentiment is a
narrow, well-studied classification task a small dedicated model handles
reliably and cheaply, so it's pulled out into its own path rather than
trusted to the shared enrichment prompt.

Model: `SENTIMENT_CLASSIFIER_MODEL` (default
"cardiffnlp/twitter-roberta-base-sentiment-latest"), run on
`SENTIMENT_CLASSIFIER_DEVICE` ("cpu" or "cuda"/"cuda:0"). That model is
3-class (positive/negative/neutral) and can't express "mixed" - rather than
force a "mixed" verdict out of logic that isn't there, this simply never
returns "mixed".

`transformers` is already a transitive dependency of sentence-transformers
(see requirements.txt), so this normally requires no new install. If it's
missing, misconfigured, or the model fails to load or errors at inference
time, classify_sentiment() returns None - callers (enrich.py) must treat
that as "no result" and fall back to a deterministic "neutral" plus logging,
never to the LLM.
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


def _resolve_device():
    """Map SENTIMENT_CLASSIFIER_DEVICE to the int/str transformers.pipeline expects."""
    device = (config.SENTIMENT_CLASSIFIER_DEVICE or "cpu").strip().lower()
    if not device.startswith("cuda"):
        return -1
    parts = device.split(":", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return int(parts[1])
    return 0


@lru_cache(maxsize=1)
def _load_pipeline(model_name: str, device_setting: str):
    try:
        from transformers import pipeline
    except Exception:
        logger.warning(
            "The `transformers` package isn't installed; sentiment will "
            "default to neutral."
        )
        return None
    try:
        return pipeline("sentiment-analysis", model=model_name, device=_resolve_device())
    except Exception:
        logger.exception(
            "Failed to load sentiment classifier model '%s' on device '%s'",
            model_name,
            device_setting,
        )
        return None


def classify_sentiment(text: str):
    """Return {"label": "positive"|"negative"|"neutral", "score": float}, or
    None if the classifier is unavailable, misconfigured, or failed to
    produce a usable label - callers must treat None as "no result" and
    default sentiment to "neutral" (with logging), never fall back to the
    LLM.
    """
    model_name = (config.SENTIMENT_CLASSIFIER_MODEL or "").strip()
    if not model_name:
        logger.warning("SENTIMENT_CLASSIFIER_MODEL is empty; sentiment will default to neutral.")
        return None

    text = (text or "").strip()
    if not text:
        return None

    classifier = _load_pipeline(model_name, config.SENTIMENT_CLASSIFIER_DEVICE or "cpu")
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
