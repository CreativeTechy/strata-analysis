from __future__ import annotations

import logging

from huggingface_hub import InferenceClient
from huggingface_hub.errors import HfHubHTTPError, InferenceTimeoutError

import config

logger = logging.getLogger(__name__)


class HFInferenceError(Exception):
    """Raised for any HF Inference API failure - auth, network, timeout, or
    an unexpected response shape. Callers treat this the same as "no result"."""


def _client(timeout: float | None = None) -> InferenceClient:
    token = (config.HF_API_TOKEN or "").strip()
    if not token:
        raise HFInferenceError("HF_API_TOKEN (or HF_TOKEN) is not configured")

    base_url = (config.HF_API_BASE_URL or "").strip()
    if base_url:
        return InferenceClient(base_url=base_url, token=token, timeout=timeout or config.HF_API_TIMEOUT_SECONDS)
    return InferenceClient(
        provider="hf-inference", token=token, timeout=timeout or config.HF_API_TIMEOUT_SECONDS
    )


def classify_text(model: str, text: str, timeout: float | None = None) -> list[dict]:
    """Run a text-classification model (e.g. a sentiment model) on `text`.

    Returns a list of {"label", "score"} dicts, best-first. Raises
    HFInferenceError on any failure.
    """
    client = _client(timeout)
    try:
        results = client.text_classification(text, model=model)
    except (HfHubHTTPError, InferenceTimeoutError) as exc:
        raise HFInferenceError(
            f"HF Inference API text-classification call failed for '{model}': {exc}"
        ) from exc
    return [{"label": item.label, "score": item.score} for item in results]


def classify_zero_shot(
    model: str,
    text: str,
    candidate_labels: list[str],
    hypothesis_template: str,
    timeout: float | None = None,
) -> dict:
    """Run a zero-shot-classification model on `text` against `candidate_labels`.

    Returns {"labels": [...], "scores": [...]}, best-first - the same shape
    a local `transformers.pipeline("zero-shot-classification")` call
    returns. Raises HFInferenceError on any failure.
    """
    client = _client(timeout)
    try:
        results = client.zero_shot_classification(
            text,
            candidate_labels,
            model=model,
            hypothesis_template=hypothesis_template,
            multi_label=False,
        )
    except (HfHubHTTPError, InferenceTimeoutError) as exc:
        raise HFInferenceError(
            f"HF Inference API zero-shot-classification call failed for '{model}': {exc}"
        ) from exc
    if not results:
        raise HFInferenceError(f"Empty zero-shot-classification response for '{model}'")
    return {"labels": [item.label for item in results], "scores": [item.score for item in results]}
