"""Lightweight embedding helpers used by the event and article pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from math import sqrt

import config


@lru_cache(maxsize=2)
def _load_model(model_name: str | None = None):
    try:
        from sentence_transformers import SentenceTransformer
    except Exception:
        return None

    resolved_name = model_name or config.EMBEDDING_MODEL
    try:
        return SentenceTransformer(resolved_name, device=config.EMBEDDING_DEVICE)
    except Exception:
        return None


def cosine_similarity(left, right) -> float:
    try:
        left_values = [float(value) for value in left]
        right_values = [float(value) for value in right]
    except Exception:
        return 0.0

    if not left_values or not right_values or len(left_values) != len(right_values):
        return 0.0

    numerator = sum(l * r for l, r in zip(left_values, right_values))
    left_norm = sqrt(sum(value * value for value in left_values))
    right_norm = sqrt(sum(value * value for value in right_values))
    if not left_norm or not right_norm:
        return 0.0
    return numerator / (left_norm * right_norm)


def get_embedding(text: str, role: str | None = None):
    payload = (text or "").strip()
    if not payload:
        return {}

    model = _load_model()
    if model is None:
        return {}

    try:
        vector = model.encode(payload, normalize_embeddings=True)
        if hasattr(vector, "tolist"):
            vector = vector.tolist()
        embedding_json = [float(value) for value in vector]
        return {
            "embedding_json": embedding_json,
            "embedding_model": config.EMBEDDING_MODEL,
            "embedding_source": role or "local",
            "embedded_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        return {}


def build_event_embedding_text(event):
    if not isinstance(event, dict):
        return ""

    parts = []
    for key in ("name", "description", "location", "target_audience"):
        value = str(event.get(key) or "").strip()
        if value:
            parts.append(value)

    for key in ("hashtags", "keywords", "usernames"):
        values = event.get(key) or []
        if isinstance(values, str):
            values = [values]
        cleaned = [str(value).strip() for value in values if str(value).strip()]
        if cleaned:
            parts.append(" ".join(cleaned))

    return "\n".join(parts).strip()

