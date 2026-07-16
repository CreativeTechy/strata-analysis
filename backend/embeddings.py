"""Shared embedding helpers for articles and projects."""

from __future__ import annotations

import logging
import math
from functools import lru_cache
from datetime import datetime, timezone

import config
try:
    from sentence_transformers import SentenceTransformer
except Exception:  # pragma: no cover - handled at runtime
    SentenceTransformer = None

logger = logging.getLogger(__name__)


def _clean_text(value) -> str:
    return " ".join(str(value or "").strip().split())


def _coerce_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [part.strip() for part in value.replace("\n", ",").split(",")]
    return [value]


def _dedupe_texts(values):
    cleaned = []
    seen = set()
    for value in values or []:
        text = _clean_text(value)
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
    return cleaned


def build_article_embedding_text(article: dict, enrichment: dict | None = None) -> str:
    enrichment = enrichment or {}
    parts = []
    for value in (
        article.get("title"),
        enrichment.get("summary"),
        article.get("summary"),
        enrichment.get("topic"),
        article.get("source_url"),
        article.get("source"),
        article.get("author"),
    ):
        text = _clean_text(value)
        if text:
            parts.append(text)

    list_fields = (
        article.get("organizations"),
        article.get("entities"),
        article.get("topics"),
        article.get("key_points"),
        article.get("risks"),
        article.get("opportunities"),
        article.get("brands"),
        article.get("car_models"),
        enrichment.get("organizations"),
        enrichment.get("entities"),
        enrichment.get("topics"),
        enrichment.get("key_points"),
        enrichment.get("risks"),
        enrichment.get("opportunities"),
    )
    for values in list_fields:
        parts.extend(_dedupe_texts(_coerce_list(values)))

    return "\n".join(part for part in parts if part)[:12000]


def build_project_embedding_text(project: dict) -> str:
    parts = []
    for value in (
        project.get("name"),
        project.get("description"),
        project.get("location"),
        project.get("location_type"),
        project.get("target_audience"),
    ):
        text = _clean_text(value)
        if text:
            parts.append(text)

    list_fields = (
        project.get("hashtags"),
        project.get("keywords"),
        project.get("usernames"),
    )
    for values in list_fields:
        parts.extend(_dedupe_texts(_coerce_list(values)))

    return "\n".join(part for part in parts if part)[:8000]


def _normalize_vector(vector):
    if not isinstance(vector, list):
        return []
    cleaned = []
    for value in vector:
        try:
            cleaned.append(float(value))
        except Exception:
            continue
    return cleaned


@lru_cache(maxsize=1)
def _load_model():
    if SentenceTransformer is None:
        logger.error(
            "sentence-transformers is not installed; embeddings are disabled. "
            "Install backend/requirements.txt in the runtime image."
        )
        return None
    try:
        return SentenceTransformer(
            config.EMBEDDING_MODEL,
            device=config.EMBEDDING_DEVICE or "cpu",
        )
    except Exception:
        logger.exception(
            "Failed to load embedding model '%s' on device '%s'",
            config.EMBEDDING_MODEL,
            config.EMBEDDING_DEVICE or "cpu",
        )
        return None


def get_embedding(text: str, *, role: str = "passage") -> dict:
    text = _clean_text(text)
    if not text:
        return {}

    try:
        model = _load_model()
        if model is None:
            logger.error(
                "Skipping embedding generation because no embedding model could be loaded "
                "(model=%s, device=%s).",
                config.EMBEDDING_MODEL,
                config.EMBEDDING_DEVICE or "cpu",
            )
            return {}
        prepared_text = text
        model_name = (config.EMBEDDING_MODEL or "").lower()
        if "e5" in model_name and not prepared_text.lower().startswith(("query:", "passage:")):
            prefix = "query" if role == "query" else "passage"
            prepared_text = f"{prefix}: {prepared_text}"
        embedding = model.encode(
            prepared_text,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        ).tolist()
        embedding = _normalize_vector(embedding)
        if not embedding:
            logger.error(
                "Embedding model '%s' returned an empty vector for role '%s'.",
                config.EMBEDDING_MODEL,
                role,
            )
            return {}
        return {
            "embedding_json": embedding,
            "embedding_model": config.EMBEDDING_MODEL,
            "embedding_source": "sentence-transformers",
            "embedded_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        logger.exception(
            "Embedding generation failed for model '%s' and role '%s'",
            config.EMBEDDING_MODEL,
            role,
        )
        return {}


def cosine_similarity(a, b) -> float:
    vector_a = _normalize_vector(a)
    vector_b = _normalize_vector(b)
    if not vector_a or not vector_b or len(vector_a) != len(vector_b):
        return 0.0

    dot_product = sum(x * y for x, y in zip(vector_a, vector_b))
    magnitude_a = math.sqrt(sum(x * x for x in vector_a))
    magnitude_b = math.sqrt(sum(y * y for y in vector_b))
    if not magnitude_a or not magnitude_b:
        return 0.0

    score = dot_product / (magnitude_a * magnitude_b)
    if score != score:
        return 0.0
    return max(-1.0, min(1.0, score))
