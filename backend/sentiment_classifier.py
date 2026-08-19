"""Dedicated sentiment classifier for article `overall_sentiment`.

This is the ONLY source of article sentiment - the LLM used for the rest of
enrichment (summary, topic, category, tones, feedback lists, ...) is never
consulted for sentiment, and never overrides or backfills it. Sentiment is a
narrow, well-studied classification task a small dedicated model handles
reliably and cheaply, so it's pulled out into its own path rather than
trusted to the shared enrichment prompt.

Model: `SENTIMENT_CLASSIFIER_MODEL` (default
"cardiffnlp/twitter-roberta-base-sentiment-latest"). That model is 3-class
(positive/negative/neutral) and can't express "mixed" - rather than force a
"mixed" verdict out of logic that isn't there, this simply never returns
"mixed".

`SENTIMENT_CLASSIFIER_PROVIDER` picks how the model actually runs: "local"
(default) loads it in-process via `transformers.pipeline` on
`SENTIMENT_CLASSIFIER_DEVICE` ("cpu" or "cuda"/"cuda:0"); "hf_api" instead
calls it through Hugging Face's hosted Inference API (see
hf_inference_client.py), which needs no local `transformers`/torch install
but adds a network round trip and depends on HF's own availability/rate
limits. If the classifier is unavailable, misconfigured, or the model fails
to load/call or errors at inference time, classify_sentiment() returns
None - callers (enrich.py) must treat that as "no result" and fall back to
a deterministic "neutral" plus logging, never to the LLM.
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

    Runs locally (transformers.pipeline) or via HF's hosted Inference API,
    per config.SENTIMENT_CLASSIFIER_PROVIDER - see hf_inference_client.py.
    """
    model_name = (config.SENTIMENT_CLASSIFIER_MODEL or "").strip()
    if not model_name:
        logger.warning("SENTIMENT_CLASSIFIER_MODEL is empty; sentiment will default to neutral.")
        return None

    text = (text or "").strip()
    if not text:
        return None

    provider = (config.SENTIMENT_CLASSIFIER_PROVIDER or "local").strip().lower()
    print(f"[sentiment_classifier] provider={provider} model={model_name}", flush=True)
    if provider == "hf_api":
        return _classify_via_hf_api(model_name, text[:512])
    return _classify_via_local_pipeline(model_name, text[:512])


def _classify_via_local_pipeline(model_name: str, text: str):
    classifier = _load_pipeline(model_name, config.SENTIMENT_CLASSIFIER_DEVICE or "cpu")
    if classifier is None:
        return None

    try:
        # Character-sliced input (see classify_sentiment's text[:512]) can
        # still overflow the model's max token length for scripts where the
        # tokenizer needs more tokens per character than English does (CJK,
        # Thai, Arabic...) - truncation=True is the backstop so that
        # overflow degrades to a truncated-but-valid input instead of a
        # tokenizer/model error.
        result = classifier(text, tokenizer_kwargs={"truncation": True})[0]
    except Exception:
        logger.exception("Sentiment classifier inference failed")
        return None

    return _normalize_label_score(result.get("label"), result.get("score"))


def _classify_via_hf_api(model_name: str, text: str):
    try:
        from hf_inference_client import classify_text
    except Exception:
        logger.exception("hf_inference_client import failed")
        return None

    # HFInferenceError (bad token, insufficient quota, rate limit, outage...)
    # is deliberately NOT caught here - it means the provider call itself
    # never produced a usable answer, and every other article would fail the
    # exact same way. It propagates through analysis/sentiment.py's
    # _safe_classify to enrich.enrich_article(), which the pipeline treats
    # as fatal - see services/articles/enrich.py and scraper/pipelines.py.
    results = classify_text(model_name, text)

    if not results:
        return None

    top = max(results, key=lambda item: item.get("score") or 0.0)
    return _normalize_label_score(top.get("label"), top.get("score"))


def _normalize_label_score(raw_label, raw_score):
    label = (raw_label or "").strip().lower()
    label = _LABEL_ALIASES.get(label, label)
    if label not in ("positive", "negative", "neutral"):
        return None

    try:
        score = float(raw_score)
    except (TypeError, ValueError):
        score = 0.0

    return {"label": label, "score": score}
