from __future__ import annotations

import logging

from huggingface_hub import InferenceClient
from huggingface_hub.errors import HfHubHTTPError, InferenceTimeoutError

import config

logger = logging.getLogger(__name__)


class HFInferenceError(Exception):
    """Base class for HF Inference API failures - auth, network, timeout, an
    unexpected response shape, or the account being out of quota.

    Carries the same `code`/`user_message` shape as llm_client.LLMError so
    callers that treat "the AI provider call failed" as fatal (see
    services/articles/enrich.py, scraper/pipelines.py) can build one clear
    message regardless of which provider (chat LLM or HF) actually failed.
    `detail` holds the raw provider/exception text for server-side logs
    only - never send it to the client.
    """

    code = "hf_inference_error"
    user_message = "The Hugging Face Inference API call failed. Please try again."

    def __init__(self, detail="", *, code=None, user_message=None):
        super().__init__(detail or self.user_message)
        self.detail = detail
        if code is not None:
            self.code = code
        if user_message is not None:
            self.user_message = user_message


class HFConfigError(HFInferenceError):
    code = "hf_config_error"
    user_message = "The Hugging Face Inference API isn't configured (missing HF_API_TOKEN/HF_TOKEN). Please contact your administrator."


class HFAuthError(HFInferenceError):
    code = "hf_auth_error"
    user_message = "Hugging Face rejected the configured API token. Please check HF_API_TOKEN/HF_TOKEN."


class HFQuotaError(HFInferenceError):
    code = "hf_quota_exceeded"
    user_message = "The Hugging Face account is out of Inference API credit or has hit its usage quota. Top up billing and try again."


class HFRateLimitError(HFInferenceError):
    code = "hf_rate_limited"
    user_message = "Hugging Face Inference API is rate-limiting requests. Please wait a moment and try again."


class HFTimeoutError(HFInferenceError):
    code = "hf_timeout"
    user_message = "The Hugging Face Inference API call timed out. Please try again."


class HFUnavailableError(HFInferenceError):
    code = "hf_unavailable"
    user_message = "The Hugging Face Inference API is temporarily unavailable. Please try again shortly."


def _wrap_http_error(exc: HfHubHTTPError, model: str, action: str) -> HFInferenceError:
    status = getattr(exc.response, "status_code", None)
    status = status if isinstance(status, int) else None
    detail = f"HF Inference API {action} call failed for '{model}' (status={status}): {exc}"
    if status in (401, 403):
        return HFAuthError(detail)
    if status == 402:
        return HFQuotaError(detail)
    if status == 429:
        return HFRateLimitError(detail)
    if status is not None and status >= 500:
        return HFUnavailableError(detail)
    return HFInferenceError(detail)


def _client(timeout: float | None = None) -> InferenceClient:
    token = (config.HF_API_TOKEN or "").strip()
    if not token:
        raise HFConfigError("HF_API_TOKEN (or HF_TOKEN) is not configured")

    base_url = (config.HF_API_BASE_URL or "").strip()
    if base_url:
        return InferenceClient(base_url=base_url, token=token, timeout=timeout or config.HF_API_TIMEOUT_SECONDS)
    return InferenceClient(
        provider="hf-inference", token=token, timeout=timeout or config.HF_API_TIMEOUT_SECONDS
    )


def classify_text(model: str, text: str, timeout: float | None = None) -> list[dict]:
    """Run a text-classification model (e.g. a sentiment model) on `text`.

    Returns a list of {"label", "score"} dicts, best-first. Raises a
    specific HFInferenceError subclass on any failure - see the classes
    above.
    """
    client = _client(timeout)
    try:
        results = client.text_classification(text, model=model)
    except HfHubHTTPError as exc:
        raise _wrap_http_error(exc, model, "text-classification") from exc
    except InferenceTimeoutError as exc:
        raise HFTimeoutError(f"HF Inference API text-classification call timed out for '{model}': {exc}") from exc
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
    returns. Raises a specific HFInferenceError subclass on any failure.
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
    except HfHubHTTPError as exc:
        raise _wrap_http_error(exc, model, "zero-shot-classification") from exc
    except InferenceTimeoutError as exc:
        raise HFTimeoutError(f"HF Inference API zero-shot-classification call timed out for '{model}': {exc}") from exc
    if not results:
        raise HFInferenceError(f"Empty zero-shot-classification response for '{model}'")
    return {"labels": [item.label for item in results], "scores": [item.score for item in results]}
