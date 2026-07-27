"""Source-language detection stage.

Detects the article's source language as metadata (source_language,
source_language_confidence on the articles table) - it never translates or
rewrites the stored text, and every other stage's model here is already
multilingual-capable (mDeBERTa, the multilingual sentence-transformers
embedding model, and Qwen2.5-7B-Instruct all handle non-English input
directly). Lazy-loaded and reused like every other stage.
"""

from __future__ import annotations

import logging
from functools import lru_cache

import config
from analysis.model_utils import resolve_device_index

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _load_pipeline(model_name: str, device_setting: str):
    try:
        from transformers import pipeline
    except Exception:
        logger.warning("`transformers` isn't installed; language detection will return unknown.")
        return None
    try:
        return pipeline("text-classification", model=model_name, device=resolve_device_index(device_setting))
    except Exception:
        logger.exception(
            "Failed to load language detection model '%s' on device '%s'", model_name, device_setting
        )
        return None


def _get_pipeline():
    model_name = (config.LANGUAGE_DETECTION_MODEL or "").strip()
    if not model_name:
        logger.warning("LANGUAGE_DETECTION_MODEL is empty; language detection is disabled.")
        return None
    return _load_pipeline(model_name, config.LANGUAGE_DETECTION_DEVICE or "cpu")


def detect_language(text: str) -> dict:
    """Return {"language", "score", "low_confidence"}.

    Unlike sentiment/tone/category, there is no safe default language to
    fall back to - `language` is None (never a fabricated code) whenever
    detection is unavailable, fails, or returns nothing usable. Callers
    must store NULL in that case, not a guessed value.
    """
    text = (text or "").strip()
    if not text:
        return {"language": None, "score": 0.0, "low_confidence": True}

    classifier = _get_pipeline()
    if classifier is None:
        return {"language": None, "score": 0.0, "low_confidence": True}

    try:
        result = classifier(text[:1000])[0]
    except Exception:
        logger.exception("Language detection inference failed")
        return {"language": None, "score": 0.0, "low_confidence": True}

    label = (result.get("label") or "").strip().lower()
    try:
        score = float(result.get("score", 0.0))
    except Exception:
        score = 0.0

    if not label:
        return {"language": None, "score": score, "low_confidence": True}
    if score < config.LANGUAGE_DETECTION_CONFIDENCE_THRESHOLD:
        return {"language": label, "score": score, "low_confidence": True}
    return {"language": label, "score": score, "low_confidence": False}
