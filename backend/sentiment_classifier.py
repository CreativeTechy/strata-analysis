"""Dedicated sentiment classifier for article `overall_sentiment`.

Why a separate classifier instead of the LLM: the enrichment LLM call is one
prompt producing the whole payload (summary, topic, category, tones, feedback
lists, ...), and it tends to hedge sentiment toward "neutral". Sentiment is
also a narrow, well-studied classification task a small dedicated model
handles reliably and cheaply, so it's pulled out into its own path rather
than reworking the shared enrichment prompt. Everything else in the payload
still comes from that one LLM call, untouched.

Toggle: set `ENABLE_SENTIMENT_CLASSIFIER=true` in backend/.env to switch
article sentiment over to this classifier; leave it false/unset (the
default) to keep the existing LLM-based sentiment. This is a plain env
lookup read fresh from `config` on every call, so flipping it in .env and
restarting the process is enough - no code change needed.

Model: `SENTIMENT_CLASSIFIER_MODEL` (default
"cardiffnlp/twitter-roberta-base-sentiment-latest"), run on
`SENTIMENT_CLASSIFIER_DEVICE` ("cpu" or "cuda"/"cuda:0"). That model is
3-class (positive/negative/neutral) and can't express "mixed" - rather than
force a "mixed" verdict out of logic that isn't there, this simply never
returns "mixed"; enrich.py falls back to the LLM's own sentiment (which can
say "mixed") whenever the classifier has nothing usable to say.

`transformers` is already a transitive dependency of sentence-transformers
(see requirements.txt), so enabling this normally requires no new install.
If it's missing, disabled, or the model fails to load or errors at
inference time, classify_sentiment() returns None and enrich.py keeps
whatever sentiment it already had - this module can never crash the
pipeline or leave a field unset.
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
            "ENABLE_SENTIMENT_CLASSIFIER is set but the `transformers` package "
            "isn't installed; falling back to the LLM's sentiment."
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
    None if the classifier is disabled, unavailable, misconfigured, or
    failed to produce a usable label - callers should treat None as "no
    opinion" and keep whatever sentiment they already have.
    """
    if not config.ENABLE_SENTIMENT_CLASSIFIER:
        return None

    model_name = (config.SENTIMENT_CLASSIFIER_MODEL or "").strip()
    if not model_name:
        logger.warning("ENABLE_SENTIMENT_CLASSIFIER is set but SENTIMENT_CLASSIFIER_MODEL is empty.")
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
