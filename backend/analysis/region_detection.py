"""Independent per-article region-detection stage.

Region used to be entirely a byproduct of aggregation.compute_dominant_demographics
majority-voting the `region` tags structured_extraction's LLM call put on each
quoted person in people_opinions - so an article with no quotes, or quotes with
no stated location, stayed "unknown" even when the body text plainly named a
place. This module pulls region detection out into its own stage that combines
three independent signals instead of relying on the LLM's per-quote tagging
alone, and derives a confidence score from how many of those signals agree
rather than trusting a model's self-reported number.

Deliberately not another LLM call: with a single local Ollama server backing
the whole pipeline (see config.ANALYSIS_CONCURRENCY's comment), a second
per-article round trip just for region would double that server's load for
one field. Every signal here is either data the pipeline already produced
(people_opinions, entities, organizations) or a cheap local regex scan.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from functools import lru_cache

import config
from analysis import labels, normalize
from services.competitors.countries import COUNTRIES, COUNTRY_ALIASES

# A title mention outweighs a body mention (a story's headline names what
# it's about); an already-recognized entity/organization name outweighs an
# incidental body-text word match, since it's not just any word - the
# pipeline already picked it out as a distinct name.
_WEIGHT_TITLE_MATCH = 1.2
_WEIGHT_TEXT_MATCH = 0.6
_WEIGHT_OPINION_VOTE = 1.0
_WEIGHT_ENTITY_MATCH = 0.9

# Confidence bands, keyed off how many of the (up to 3) signal types agree on
# the winning region - see detect_region()'s docstring.
_CONFIDENCE_AGREEMENT = 0.9
_CONFIDENCE_SINGLE_SIGNAL = 0.55
_CONFIDENCE_CONFLICT = 0.35


@lru_cache(maxsize=1)
def _surface_form_lookup() -> dict:
    """Every known surface form - each COUNTRIES name and each COUNTRY_ALIASES
    key - lowercased, mapped to its canonical country name."""
    forms = {name.lower(): name for name in COUNTRIES.values()}
    for alias, code in COUNTRY_ALIASES.items():
        forms.setdefault(alias, COUNTRIES[code])
    return forms


@lru_cache(maxsize=1)
def _scan_pattern() -> re.Pattern:
    # Longest-first so "united states" matches whole rather than a shorter
    # form pre-empting it inside the alternation.
    forms = sorted(_surface_form_lookup().keys(), key=len, reverse=True)
    return re.compile(r"\b(" + "|".join(re.escape(form) for form in forms) + r")\b", re.IGNORECASE)


def _scan_text(text: str) -> Counter:
    counts = Counter()
    text = (text or "").strip()
    if not text:
        return counts
    lookup = _surface_form_lookup()
    for match in _scan_pattern().finditer(text):
        region = lookup.get(match.group(0).lower())
        if region:
            counts[region] += 1
    return counts


def _text_scan_votes(title: str, text: str) -> Counter:
    votes = Counter()
    for region, count in _scan_text(title).items():
        votes[region] += count * _WEIGHT_TITLE_MATCH
    for region, count in _scan_text(text).items():
        votes[region] += count * _WEIGHT_TEXT_MATCH
    return votes


def _opinion_votes(people_opinions) -> Counter:
    votes = Counter()
    for item in people_opinions or []:
        if not isinstance(item, dict):
            continue
        region = normalize.normalize_region(item.get("region"))
        if region and region.lower() != labels.DEFAULT_REGION:
            votes[region] += _WEIGHT_OPINION_VOTE
    return votes


def _entity_votes(entities, organizations) -> Counter:
    blob = ", ".join(str(v) for v in (list(entities or []) + list(organizations or [])) if v)
    votes = Counter()
    for region, count in _scan_text(blob).items():
        votes[region] += count * _WEIGHT_ENTITY_MATCH
    return votes


def detect_region(
    *, title: str = "", text: str = "", people_opinions=None, entities=None, organizations=None,
) -> dict:
    """Deterministic per-article region guess with a confidence score.

    Combines up to three independent signal types - a title+body text scan
    against the country/alias tables, the per-quote region votes structured
    extraction already tagged, and a scan of the already-extracted entities/
    organizations - then reports the highest-scoring region overall.

    Confidence reflects how many *distinct signal types* agree on that
    region, not a model's self-reported number:
      - 2+ signal types agree on the winning region -> high confidence
      - exactly 1 signal type fired at all -> medium confidence
      - 2+ signal types fired but disagree -> low confidence on the winner
      - nothing fired -> "unknown", 0.0 confidence

    Runs even when structured extraction failed outright (people_opinions/
    entities/organizations empty) - the text scan alone still gives a real,
    if lower-confidence, answer.
    """
    signals = {
        "text": _text_scan_votes(title, text),
        "opinions": _opinion_votes(people_opinions),
        "entities": _entity_votes(entities, organizations),
    }

    scores: defaultdict = defaultdict(float)
    top_region_by_signal = {}
    for name, votes in signals.items():
        if not votes:
            continue
        for region, weight in votes.items():
            scores[region] += weight
        top_region_by_signal[name] = votes.most_common(1)[0][0]

    if not scores:
        return {
            "region": labels.DEFAULT_REGION,
            "region_confidence": 0.0,
            "region_low_confidence": True,
        }

    winner = max(scores, key=lambda region: scores[region])
    agreeing_signals = sum(1 for top in top_region_by_signal.values() if top == winner)
    fired_signals = len(top_region_by_signal)

    if agreeing_signals >= 2:
        confidence = _CONFIDENCE_AGREEMENT
    elif fired_signals == 1:
        confidence = _CONFIDENCE_SINGLE_SIGNAL
    else:
        confidence = _CONFIDENCE_CONFLICT

    return {
        "region": winner,
        "region_confidence": confidence,
        "region_low_confidence": confidence < config.REGION_DETECTION_CONFIDENCE_THRESHOLD,
    }
