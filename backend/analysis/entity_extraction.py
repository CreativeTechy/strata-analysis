"""Optional dedicated entity-extraction stage.

Off by default (config.ENTITY_EXTRACTION_MODEL empty) - structured_extraction.py
already produces `organizations`/`entities` as part of its JSON output, which
is good enough for most sources. When a dedicated NER model is configured
here, its output *replaces* the structured-extraction fields for those two
lists; when disabled, extract_entities() returns None and callers must keep
whatever structured_extraction.py already gave them rather than treating
None as "no entities found".
"""

from __future__ import annotations

import logging
from functools import lru_cache

import config
from analysis.model_utils import resolve_device_index

logger = logging.getLogger(__name__)

_ORG_TAGS = {"ORG"}


def is_enabled() -> bool:
    return bool((config.ENTITY_EXTRACTION_MODEL or "").strip())


@lru_cache(maxsize=1)
def _load_pipeline(model_name: str, device_setting: str):
    try:
        from transformers import pipeline
    except Exception:
        logger.warning("`transformers` isn't installed; entity extraction is disabled.")
        return None
    try:
        return pipeline(
            "ner",
            model=model_name,
            device=resolve_device_index(device_setting),
            aggregation_strategy="simple",
        )
    except Exception:
        logger.exception(
            "Failed to load entity extraction model '%s' on device '%s'", model_name, device_setting
        )
        return None


def _get_pipeline():
    if not is_enabled():
        return None
    return _load_pipeline(config.ENTITY_EXTRACTION_MODEL.strip(), config.ENTITY_EXTRACTION_DEVICE or "cpu")


def extract_entities(text: str) -> dict | None:
    """Return {"organizations": [...], "entities": [...]}, or None when the
    stage is disabled, unavailable, or inference fails."""
    text = (text or "").strip()
    if not text:
        return None
    ner = _get_pipeline()
    if ner is None:
        return None

    try:
        results = ner(text[:2000])
    except Exception:
        logger.exception("Entity extraction inference failed")
        return None

    threshold = config.ENTITY_EXTRACTION_CONFIDENCE_THRESHOLD
    organizations = []
    entities = []
    seen_orgs = set()
    seen_entities = set()
    for item in results or []:
        try:
            score = float(item.get("score", 0.0))
        except Exception:
            score = 0.0
        if score < threshold:
            continue
        word = (item.get("word") or "").strip()
        if not word:
            continue
        group = (item.get("entity_group") or item.get("entity") or "").upper()
        key = word.lower()
        if group in _ORG_TAGS:
            if key not in seen_orgs:
                seen_orgs.add(key)
                organizations.append(word)
        else:
            if key not in seen_entities:
                seen_entities.add(key)
                entities.append(word)

    return {"organizations": organizations, "entities": entities}
