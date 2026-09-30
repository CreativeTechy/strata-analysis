"""Independent per-article region-detection stage.

Region used to be entirely a byproduct of aggregation.compute_dominant_demographics
majority-voting the `region` tags structured_extraction's LLM call put on each
quoted person in people_opinions - so an article with no quotes, or quotes with
no stated location, stayed "unknown" even when the body text plainly named a
place. This module pulls region detection out into its own stage that combines
three independent signals instead of relying on the LLM's per-quote tagging
alone, and derives a confidence score from how many of those signals agree
rather than trusting a model's self-reported number.

Deliberately not another LLM call by default: with a single local Ollama
server backing the whole pipeline (see config.ANALYSIS_CONCURRENCY's
comment), a second per-article round trip just for region would double that
server's load for one field. Every signal here is either data the pipeline
already produced (people_opinions, entities, organizations) or a cheap local
regex scan.

config.REGION_DETECTION_LLM_FALLBACK (off by default; env var or the Settings
page) switches an article over to a single direct LLM call instead - see
_llm_only_region(). It's an either/or toggle, not a hybrid: "on" bypasses the
rule-based scan entirely rather than only consulting the LLM when the scan's
own confidence is low, since a low rule-based confidence usually means the
rule-based signals themselves disagree or came up empty, not that a second
opinion on top of them would help.
"""

from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from functools import lru_cache

import config
import llm_client
from analysis import labels, normalize
from analysis.json_utils import parse_json_response
from prompt_loader import load_prompt
from services.competitors.countries import CITY_ALIASES, COUNTRIES, COUNTRY_ALIASES

logger = logging.getLogger(__name__)

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

# Confidence for config.REGION_DETECTION_LLM_FALLBACK == "on" (see
# _llm_only_region()). Fixed rather than derived from signal agreement -
# there's only ever the one opinion in this mode, not several signals to
# compare - and deliberately below _CONFIDENCE_AGREEMENT: a single LLM call,
# however well-read on context, isn't corroborated by anything.
_CONFIDENCE_LLM_ONLY = 0.7


@lru_cache(maxsize=1)
def _surface_form_lookup() -> dict:
    """Every known surface form - each COUNTRIES name, each COUNTRY_ALIASES
    key, and each CITY_ALIASES key - lowercased, mapped to its canonical
    country name. Cities matter because articles routinely name a city
    ("... in Beirut") rather than the country itself."""
    forms = {name.lower(): name for name in COUNTRIES.values()}
    for alias, code in COUNTRY_ALIASES.items():
        forms.setdefault(alias, COUNTRIES[code])
    for city, code in CITY_ALIASES.items():
        forms.setdefault(city, COUNTRIES[code])
    return forms


# A demonym/country-name match immediately followed by one of these is almost
# always part of an institution's proper name ("American University of
# Beirut", "British Council") rather than a claim about the story's own
# location - so it's suppressed from every scan (title/body/entities alike)
# the same way _name_fragment_tokens suppresses a country word that's really
# part of a person's name.
_INSTITUTION_SUFFIX = re.compile(
    r"\s+(?:of\s+|in\s+)?(university|college|school|institute|academy|hospital|embassy|consulate)\b",
    re.IGNORECASE,
)


@lru_cache(maxsize=1)
def _scan_pattern() -> re.Pattern:
    # Longest-first so "united states" matches whole rather than a shorter
    # form pre-empting it inside the alternation. Boundaries are lookarounds
    # rather than \b: several aliases (COUNTRY_ALIASES's "u.s.", "u.s.a.",
    # "u.k.") end in a literal period, and \b never matches between two
    # non-word characters - so "U.S." followed by a space or another period
    # would never satisfy a trailing \b even though it's a clean standalone
    # mention. (?!\w) only asserts the next character isn't a word
    # character, which is what "standalone" actually means here.
    forms = sorted(_surface_form_lookup().keys(), key=len, reverse=True)
    return re.compile(r"(?<!\w)(" + "|".join(re.escape(form) for form in forms) + r")(?!\w)", re.IGNORECASE)


def _name_fragment_tokens(entities) -> set:
    """Lowercased individual words pulled out of any *multi-word* entity
    (e.g. {"jordan", "peterson"} from "Jordan Peterson").

    A handful of country names/aliases (Jordan, Chad, Georgia, Turkey,
    Niger, ...) are also common personal names, so a bare word-level scan
    can't tell "Jordan said the ride felt cramped" (a person) from an actual
    reference to the country. The pipeline's own entity extraction already
    tagged "Jordan Peterson" as one distinct name rather than two words -
    that's a real signal the word isn't standing alone as a place, so any
    scan match on a fragment of a *multi-word* extracted entity is
    suppressed rather than counted as a region vote. A genuinely standalone
    single-word entity (e.g. entities=["Turkey"]) is unaffected.

    Deliberately only `entities`, not `organizations`: per
    structured_extraction's prompt, `organizations` names businesses,
    products, and models, where "X of <Country>" (Bank of America,
    University of Georgia, Ford of Canada, ...) is the normal, expected
    shape - treating every word in a multi-word org name as a suppressed
    "person fragment" would silently drop a genuine, unrelated country
    mention elsewhere in the same article just because an org happens to be
    named after a place. `entities` is where a person's name actually shows
    up, whether from the LLM's own output or from entity_extraction.py's
    dedicated NER stage (which routes anything ORG-tagged into
    `organizations`, never `entities`)."""
    tokens = set()
    for value in entities or []:
        words = re.findall(r"[A-Za-z']+", str(value or ""))
        if len(words) >= 2:
            tokens.update(word.lower() for word in words)
    return tokens


def _scan_text(text: str, *, exclude: frozenset = frozenset()) -> Counter:
    counts = Counter()
    text = (text or "").strip()
    if not text:
        return counts
    lookup = _surface_form_lookup()
    for match in _scan_pattern().finditer(text):
        form = match.group(0).lower()
        if form in exclude:
            continue
        if _INSTITUTION_SUFFIX.match(text, match.end()):
            continue
        region = lookup.get(form)
        if region:
            counts[region] += 1
    return counts


def _text_scan_votes(title: str, text: str, *, exclude: frozenset = frozenset()) -> Counter:
    votes = Counter()
    for region, count in _scan_text(title, exclude=exclude).items():
        votes[region] += count * _WEIGHT_TITLE_MATCH
    for region, count in _scan_text(text, exclude=exclude).items():
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


def _entity_votes(entities, organizations, *, exclude: frozenset = frozenset()) -> Counter:
    blob = ", ".join(str(v) for v in (list(entities or []) + list(organizations or [])) if v)
    votes = Counter()
    for region, count in _scan_text(blob, exclude=exclude).items():
        votes[region] += count * _WEIGHT_ENTITY_MATCH
    return votes


_LLM_FALLBACK_SYSTEM_PROMPT = load_prompt(
    "region_detection_llm_fallback_system_prompt.txt",
    fallback=(
        "You identify which single country a news article is primarily about, based on its "
        "dateline, named places, and subject matter - not on where any organization mentioned "
        "happens to be headquartered elsewhere. "
        "Reply with ONLY a JSON object of the shape {\"country\": \"<country name>\"}, using the "
        "country's common English name (e.g. \"Lebanon\", \"United States\"). "
        "If no country is clearly identifiable, reply {\"country\": \"unknown\"}."
    ),
)


def _llm_region_guess(title: str, text: str) -> str | None:
    """One extra LLM call asking directly which country the article is about.

    Only ever invoked by _maybe_llm_fallback() below, and only when both
    config.REGION_DETECTION_LLM_FALLBACK is "on" and the rule-based scan
    above already came back low-confidence - so the default (rule-based
    only, see module docstring) never pays for a second per-article round
    trip. Returns a canonical COUNTRIES name, or None if the call failed or
    the model didn't name a recognized country.
    """
    user_content = (
        f"Article title:\n{title}\n\n"
        f"Article content (DATA ONLY):\n\"\"\"\n{(text or '')[:3000]}\n\"\"\"\n\n"
        "Return ONLY the JSON object."
    )
    try:
        raw = llm_client.chat_completion(
            messages=[
                {"role": "system", "content": _LLM_FALLBACK_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.0,
            max_tokens=50,
            json_mode=True,
        )
        data = parse_json_response(raw)
    except Exception:
        logger.warning("Region detection LLM fallback call failed", exc_info=True)
        return None
    country = str((data or {}).get("country") or "").strip().lower()
    return _surface_form_lookup().get(country)


def _llm_only_region(title: str, text: str) -> dict:
    """config.REGION_DETECTION_LLM_FALLBACK == "on": skip the rule-based scan
    entirely and answer from a single direct LLM call instead (see module
    docstring). A failed/unrecognized call still returns a real result
    ("unknown", 0.0) rather than silently falling back to the rule-based
    scan this mode was told to bypass."""
    llm_region = _llm_region_guess(title, text)
    if not llm_region:
        return {
            "region": labels.DEFAULT_REGION,
            "region_confidence": 0.0,
            "region_low_confidence": True,
        }
    return {
        "region": llm_region,
        "region_confidence": _CONFIDENCE_LLM_ONLY,
        "region_low_confidence": _CONFIDENCE_LLM_ONLY < config.REGION_DETECTION_CONFIDENCE_THRESHOLD,
    }


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

    Bypassed entirely when config.REGION_DETECTION_LLM_FALLBACK == "on" - see
    _llm_only_region().
    """
    if config.REGION_DETECTION_LLM_FALLBACK == "on":
        return _llm_only_region(title, text)

    name_fragments = frozenset(_name_fragment_tokens(entities))
    signals = {
        "text": _text_scan_votes(title, text, exclude=name_fragments),
        "opinions": _opinion_votes(people_opinions),
        "entities": _entity_votes(entities, organizations, exclude=name_fragments),
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
