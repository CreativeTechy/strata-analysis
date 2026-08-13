"""Zero-shot category + tone classification stage
(MoritzLaurer/mDeBERTa-v3-base-mnli-xnli by default).

Runs as a `transformers` zero-shot-classification pipeline, lazy-loaded and
reused across articles - or, when `config.CLASSIFICATION_PROVIDER` is
"hf_api" instead of the default "local", as calls to Hugging Face's hosted
Inference API (see hf_inference_client.py), trading the local torch/
transformers install for a network round trip per chunk. Category,
writer_tone, and article_tone are three independent zero-shot calls against
the same model/text, since each asks a different question of it
(writer_tone and article_tone are deliberately never conflated here - that
only happens later, deterministically, in enrich.py's _compute_overall_tone).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from functools import lru_cache

import config
from analysis import labels
from analysis.article_prep import chunk_text
from analysis.model_utils import resolve_device_index

logger = logging.getLogger(__name__)

_CATEGORY_TEMPLATE = "This text is {}."
_WRITER_TONE_TEMPLATE = "The writer's tone in this text is {}."
_ARTICLE_TONE_TEMPLATE = "The overall tone of the subject matter in this article is {}."


@lru_cache(maxsize=1)
def _load_pipeline(model_name: str, device_setting: str):
    try:
        from transformers import pipeline
    except Exception:
        logger.warning("`transformers` isn't installed; classification will fall back to defaults.")
        return None
    try:
        return pipeline(
            "zero-shot-classification",
            model=model_name,
            device=resolve_device_index(device_setting),
        )
    except Exception:
        logger.exception(
            "Failed to load classification model '%s' on device '%s'", model_name, device_setting
        )
        return None


def _get_pipeline():
    model_name = (config.CLASSIFICATION_MODEL or "").strip()
    if not model_name:
        logger.warning("CLASSIFICATION_MODEL is empty; classification will fall back to defaults.")
        return None
    return _load_pipeline(model_name, config.CLASSIFICATION_DEVICE or "cpu")


def _classify_one_via_local_pipeline(chunk, candidate_labels, hypothesis_template):
    classifier = _get_pipeline()
    if classifier is None:
        return None
    try:
        result = classifier(
            chunk,
            candidate_labels,
            hypothesis_template=hypothesis_template,
            multi_label=False,
        )
    except Exception:
        logger.exception("Zero-shot classification inference failed")
        return None
    result_labels = result.get("labels") or []
    result_scores = result.get("scores") or []
    if not result_labels or not result_scores:
        return None
    return {"label": result_labels[0], "score": result_scores[0]}


def _classify_one_via_hf_api(chunk, candidate_labels, hypothesis_template):
    model_name = (config.CLASSIFICATION_MODEL or "").strip()
    if not model_name:
        logger.warning("CLASSIFICATION_MODEL is empty; classification will fall back to defaults.")
        return None
    try:
        from hf_inference_client import classify_zero_shot
    except Exception:
        logger.exception("hf_inference_client import failed")
        return None
    # HFInferenceError (bad token, insufficient quota, rate limit, outage...)
    # is deliberately NOT caught here - it means the provider call itself
    # never produced a usable answer, and every other chunk/article would
    # fail the exact same way. It propagates to enrich.enrich_article(),
    # which the pipeline treats as fatal - see services/articles/enrich.py
    # and scraper/pipelines.py.
    result = classify_zero_shot(model_name, chunk, candidate_labels, hypothesis_template)
    result_labels = result.get("labels") or []
    result_scores = result.get("scores") or []
    if not result_labels or not result_scores:
        return None
    return {"label": result_labels[0], "score": result_scores[0]}


def _classify_one(chunk, candidate_labels, hypothesis_template):
    provider = (config.CLASSIFICATION_PROVIDER or "local").strip().lower()
    print(f"[classification] provider={provider} model={config.CLASSIFICATION_MODEL}", flush=True)
    if provider == "hf_api":
        return _classify_one_via_hf_api(chunk, candidate_labels, hypothesis_template)
    return _classify_one_via_local_pipeline(chunk, candidate_labels, hypothesis_template)


def _classify_chunks(chunks, candidate_labels, hypothesis_template):
    score_by_label = defaultdict(float)
    count_by_label = defaultdict(int)
    for chunk in chunks:
        chunk = (chunk or "").strip()
        if not chunk:
            continue
        result = _classify_one(chunk, candidate_labels, hypothesis_template)
        if not result:
            continue
        score_by_label[result["label"]] += result["score"]
        count_by_label[result["label"]] += 1

    if not score_by_label:
        return None

    best_label = max(score_by_label, key=lambda label: score_by_label[label])
    avg_score = score_by_label[best_label] / max(1, count_by_label[best_label])
    return {"label": best_label, "score": avg_score}


def _classify(text: str, candidate_labels: list[str], hypothesis_template: str, default_label: str) -> dict:
    """Return {"label", "score", "low_confidence"[, "raw_label"]}.

    `label` is always a valid candidate (falls back to `default_label` when
    the model is unavailable or its top score is below
    config.CLASSIFICATION_CONFIDENCE_THRESHOLD) - callers never see None or
    an out-of-vocabulary label.
    """
    chunks = chunk_text(text) if text else []
    if not chunks and text:
        chunks = [text]
    result = _classify_chunks(chunks, candidate_labels, hypothesis_template)

    if result is None:
        return {"label": default_label, "score": 0.0, "low_confidence": True}
    if result["score"] < config.CLASSIFICATION_CONFIDENCE_THRESHOLD:
        return {
            "label": default_label,
            "score": result["score"],
            "low_confidence": True,
            "raw_label": result["label"],
        }
    return {"label": result["label"], "score": result["score"], "low_confidence": False}


def classify_category(text: str) -> dict:
    hypothesis_labels = labels.CATEGORY_HYPOTHESIS_LABELS
    reverse = {phrase: key for key, phrase in hypothesis_labels.items()}
    default_phrase = hypothesis_labels[labels.DEFAULT_CATEGORY]

    result = _classify(text, list(hypothesis_labels.values()), _CATEGORY_TEMPLATE, default_phrase)
    result["label"] = reverse.get(result["label"], labels.DEFAULT_CATEGORY)
    if "raw_label" in result:
        result["raw_label"] = reverse.get(result["raw_label"], result["raw_label"])
    return result


def classify_writer_tone(text: str) -> dict:
    return _classify(text, list(labels.VALID_TONES), _WRITER_TONE_TEMPLATE, labels.DEFAULT_TONE)


def classify_article_tone(text: str) -> dict:
    return _classify(text, list(labels.VALID_TONES), _ARTICLE_TONE_TEMPLATE, labels.DEFAULT_TONE)
