"""Evidence workspace generation and reads.

The first release is deliberately conservative: it derives claims from stored
analysis key points, validates every cited passage against the frozen article
body, collapses repeated origins, and only calls a claim supported when two
distinct origins make the same normalized claim. It never fetches the web.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from urllib.parse import urlparse

import db
import config
from embeddings import cosine_similarity, get_embedding
from llm_client import LLMError, chat_completion
from psycopg.types.json import Jsonb

RULES_VERSION = "evidence-v3"
ASSESSMENTS = {
    "supported", "contradicted", "mixed_evidence", "insufficient_evidence", "not_yet_verifiable",
    "assessment_unavailable",
}
_STOP = {"about", "after", "again", "against", "also", "because", "been", "before", "being", "between",
         "could", "from", "have", "into", "more", "most", "other", "over", "said", "than", "that", "their",
         "there", "these", "they", "this", "through", "under", "very", "what", "when", "where", "which",
         "while", "with", "would"}
_FORECAST = re.compile(r"\b(will|expects?|forecast|projected|plans?|aims?|next (?:month|quarter|year))\b", re.I)
_OPINION = re.compile(r"\b(think|believe|feel|in my view|should|best|worst)\b", re.I)
_CAUSAL = re.compile(r"\b(because|caused|causes|led to|resulted in|due to|drives?)\b", re.I)
_ATTRIBUTED = re.compile(r"\b(said|stated|announced|according to|reported|claimed)\b", re.I)
_NEGATION = re.compile(r"\b(no|not|never|didn't|doesn't|won't|without)\b", re.I)
_UP = re.compile(r"\b(increase[ds]?|increasing|rose|risen|higher|grew|growth|support(?:s|ed)?)\b", re.I)
_DOWN = re.compile(r"\b(decrease[ds]?|decreasing|fell|fallen|lower|decline[ds]?|declining|oppose[ds]?|ban)\b", re.I)
_DATE = re.compile(r"\b(?:20\d{2}(?:-\d{2}(?:-\d{2})?)?|(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+(?:20\d{2}|\d{1,2}(?:,?\s+20\d{2})?))\b", re.I)
_QUANTITY = re.compile(
    r"(?:[$£€]\s?\d[\d,.]*|\b\d[\d,.]*(?:\s?(?:%|percent|million|billion|trillion|tonnes?|tons?|barrels?|bpd|days?|months?|years?))?"
    r"|\b(?:one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:million|billion|trillion)\b)",
    re.I,
)

_CLAIM_EQUIVALENTS = {
    "ev": "vehicle", "evs": "vehicle", "electric": "vehicle", "vehicles": "vehicle",
    "cars": "car", "automobiles": "car", "charging": "charge", "chargers": "charge",
    "registrations": "registered", "registration": "registered", "sales": "sold",
    "costs": "cost", "prices": "price", "publicly": "public", "approximately": "about",
}
_GENERIC_CLAIM_WORDS = {
    "according", "report", "reported", "reports", "says", "source", "uk", "united", "kingdom",
}


def _words(value: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", str(value or "").lower()) if (len(w) > 2 or w.isdigit()) and w not in _STOP]


def _claim_words(value: str) -> set[str]:
    """Content words used as a transparent fallback around semantic matching."""
    words = []
    for word in _words(value):
        word = _CLAIM_EQUIVALENTS.get(word, word)
        if word not in _GENERIC_CLAIM_WORDS:
            words.append(word)
    return set(words)


def _normalized_scopes(value: str) -> tuple[set[str], set[str]]:
    structured = _structured_claim("", value)
    dates = {re.sub(r"\s+", " ", item.lower()).strip() for item in structured["dates"]}
    number_words = {
        "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
        "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
    }
    quantities = {
        re.sub(
            r"[^a-z0-9.%]+", "",
            re.sub(
                r"\b(one|two|three|four|five|six|seven|eight|nine|ten)\b",
                lambda match: number_words[match.group(1).lower()],
                item.lower().replace("percent", "%"),
            ),
        )
        for item in structured["quantities"]
    }
    return dates, quantities


def _scope_compatible(left: str, right: str) -> bool:
    """Reject similar-sounding claims that describe different measured facts."""
    left_dates, left_quantities = _normalized_scopes(left)
    right_dates, right_quantities = _normalized_scopes(right)
    if bool(left_dates) != bool(right_dates):
        return False
    if left_dates and right_dates and left_dates.isdisjoint(right_dates):
        return False
    if bool(left_quantities) != bool(right_quantities):
        return False
    if left_quantities and right_quantities and left_quantities.isdisjoint(right_quantities):
        return False
    return True


def _passage_covers_scope(claim: str, passage: str) -> bool:
    """A passage may add context, but it must contain every claim scope value."""
    claim_dates, claim_quantities = _normalized_scopes(claim)
    passage_dates, passage_quantities = _normalized_scopes(passage)
    return claim_dates.issubset(passage_dates) and claim_quantities.issubset(passage_quantities)


def _lexical_similarity(left: str, right: str) -> float:
    left_words, right_words = _claim_words(left), _claim_words(right)
    if not left_words or not right_words:
        return 0.0
    overlap = len(left_words & right_words)
    return max(
        overlap / len(left_words | right_words),
        overlap / min(len(left_words), len(right_words)),
    )


def _claims_match(left: dict, right: dict, threshold: float | None = None) -> bool:
    """Hybrid paraphrase match with hard safeguards for dates and quantities."""
    if not _scope_compatible(left["claim"], right["claim"]):
        return False
    overlap = len(_claim_words(left["claim"]) & _claim_words(right["claim"]))
    if overlap < 2:
        return False
    lexical = _lexical_similarity(left["claim"], right["claim"])
    semantic = cosine_similarity(left.get("embedding") or [], right.get("embedding") or [])
    minimum = config.EVIDENCE_CLAIM_SIMILARITY_THRESHOLD if threshold is None else threshold
    return lexical >= 0.72 or semantic >= minimum


def _group_claim_candidates(candidates: list[dict]) -> list[dict]:
    """Cluster exact claims and cautious semantic paraphrases across topics."""
    groups: list[dict] = []
    for candidate in candidates:
        exact = next((group for group in groups if group["fingerprint"] == candidate["fingerprint"]), None)
        if exact:
            exact["items"].append(candidate)
            continue
        match = next((group for group in groups if _claims_match(group["canonical"], candidate)), None)
        if match:
            match["items"].append(candidate)
            continue
        groups.append({
            "fingerprint": candidate["fingerprint"],
            "canonical": candidate,
            "items": [candidate],
        })
    return groups


def _direction(value: str) -> str:
    negative = bool(_NEGATION.search(value) or _DOWN.search(value))
    positive = bool(_UP.search(value))
    if negative and positive:
        return "mixed"
    if negative:
        return "negative"
    if positive:
        return "positive"
    return "neutral"


def _structured_claim(topic: str, claim: str) -> dict:
    dates = list(dict.fromkeys(_DATE.findall(claim)))
    quantities = list(dict.fromkeys(_QUANTITY.findall(claim)))
    return {
        "topic": topic,
        "assertion": claim,
        "dates": dates,
        "quantities": quantities,
        "direction": _direction(claim),
        "claim_type": _claim_type(claim),
    }


def _fingerprint(topic: str, claim: str) -> str:
    # Keep dates and quantities in the identity so claims about different
    # periods or values cannot become false contradictions. Direction words
    # are removed only from the matching identity and retained separately.
    words = [w for w in _words(claim) if w not in {
        "not", "never", "without", "lower", "higher", "decline", "declined", "decreasing", "decreased",
        "fell", "fallen", "increase", "increased", "increasing", "rose", "risen", "support", "supports",
        "supported", "oppose", "opposes", "opposed",
    }]
    structured = _structured_claim(topic, claim)
    scope = "|".join(structured["dates"] + structured["quantities"])
    basis = f"{topic.lower()}|{' '.join(sorted(set(words))[:32])}|{scope.lower()}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def _claim_type(text: str) -> str:
    if _FORECAST.search(text): return "forecast"
    if _OPINION.search(text): return "opinion"
    if _CAUSAL.search(text): return "causal_explanation"
    if _ATTRIBUTED.search(text): return "attributed_statement"
    return "factual_assertion"


def _origin(row: dict) -> str:
    provenance = row.get("source_provenance") or {}
    # A deduplicated story is one underlying origin even when several outlets
    # republished it under different hostnames.
    if provenance.get("origin_group"):
        return f"origin:{str(provenance['origin_group']).strip().lower()}"
    if row.get("story_id"):
        return f"story:{row['story_id']}"
    publisher = str(provenance.get("publisher") or "").strip().lower()
    if publisher:
        return f"publisher:{publisher}"
    for value in (provenance.get("original_url"), row.get("url"), row.get("source_url")):
        host = urlparse(str(value or "")).netloc.lower().removeprefix("www.")
        if host:
            return f"host:{host}"
    return f"source:{str(row.get('source') or 'unknown').strip().lower()}"


def _sentences(row: dict) -> list[str]:
    # Evidence quotations come from the frozen document body. Titles and LLM
    # summaries help humans navigate, but are not treated as source passages.
    value = str(row.get("text") or "")
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", value) if len(part.strip()) >= 20]


def _best_passage(row: dict, claim: str) -> str:
    wanted = set(_words(claim))
    choices = _sentences(row)
    if not choices:
        return ""
    return max(choices, key=lambda text: len(wanted.intersection(_words(text))))[:1200]


def _passage_qualification(claim: str, passage: str) -> tuple[bool, float, str]:
    """Check that an exact quote is also a plausible citation for the claim.

    This is deliberately conservative. It does not call word overlap proof of
    entailment; it only lets the passage proceed to the relationship assessor.
    """
    if not passage:
        return False, 0.0, "No exact passage was found in the stored document."
    claim_words, passage_words = _claim_words(claim), _claim_words(passage)
    overlap = len(claim_words & passage_words)
    score = overlap / max(1, min(len(claim_words), len(passage_words)))
    if overlap < 2 or score < 0.35:
        return False, score, "The quotation does not share enough specific meaning with the extracted claim."
    if not _passage_covers_scope(claim, passage):
        return False, score, "The quotation and claim use incompatible dates or quantities."
    return True, score, "The quotation matches the claim scope and contains the claim's key terms."


def _passage_locator(row: dict, passage: str) -> str | None:
    if not passage:
        return None
    sentences = _sentences(row)
    try:
        return f"paragraph {sentences.index(passage) + 1}"
    except ValueError:
        return None


def _claim_candidates(row: dict) -> list[tuple[str, str]]:
    topics = [str(x).strip() for x in (row.get("topics") or []) if str(x).strip()]
    topic = topics[0] if topics else "General"
    points = row.get("key_points") or []
    claims = []
    for point in points[:8]:
        text = str(point.get("point") or point.get("text") or "").strip() if isinstance(point, dict) else str(point).strip()
        if len(text) >= 20:
            claims.append((topic, text[:1000]))
    if not claims:
        fallback = str(row.get("summary") or row.get("title") or "").strip()
        if len(fallback) >= 20:
            claims.append((topic, fallback[:1000]))
    return claims


def _assessment(claim_type: str, supporting_origins: set[str], contradicting_origins: set[str]) -> tuple[str, str]:
    if claim_type == "forecast":
        return "not_yet_verifiable", "The statement concerns a future outcome that this evidence snapshot cannot yet verify."
    if claim_type == "opinion":
        return "insufficient_evidence", "The source expresses an opinion; it is preserved as evidence of that view, not treated as an established fact."
    if len(contradicting_origins) >= 2 and len(supporting_origins) == 1:
        return "contradicted", "Two or more distinct recorded origins conflict with the source claim, while only its own origin supports it."
    if contradicting_origins:
        return "mixed_evidence", "The frozen evidence contains materially similar statements with opposing polarity."
    if len(supporting_origins) >= 2:
        return "supported", f"The same claim appears in {len(supporting_origins)} distinct recorded origins."
    return "insufficient_evidence", "Only one recorded origin supports this claim; independent corroboration is not available in this run."


def _grounded_model_assessment(claim_text: str, claim_type: str, prepared: list[tuple]) -> dict | None:
    """Optionally classify exact passages; return None for a safe rules fallback."""
    if not config.EVIDENCE_LLM_ASSESSMENT:
        return None
    passages = [
        {"article_id": int(row["id"]), "passage": passage}
        for row, _relationship, passage, valid, qualifies, _source_type, _score, _reason in prepared
        if valid and qualifies
    ]
    if not passages:
        return None
    prompt = {
        "claim": claim_text,
        "claim_type": claim_type,
        "passages": passages,
        "instructions": (
            "Classify every passage as supporting, contradicting, or contextual. "
            "A contradiction requires the same subject, geography, metric and time scope. "
            "Return an overall assessment and a short explanation grounded only in these passages."
        ),
    }
    try:
        raw = chat_completion(
            messages=[
                {"role": "system", "content": "Return JSON only with assessment, explanation, and relationships [{article_id, relationship}]. Valid assessments: supported, contradicted, mixed_evidence, insufficient_evidence, not_yet_verifiable, assessment_unavailable."},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            temperature=0, max_tokens=700, json_mode=True,
        )
        result = json.loads(raw)
    except (LLMError, ValueError, TypeError, json.JSONDecodeError):
        return None
    if not isinstance(result, dict) or result.get("assessment") not in ASSESSMENTS or not isinstance(result.get("relationships"), list):
        return None
    allowed_ids = {item["article_id"] for item in passages}
    relationships = {}
    for item in result["relationships"]:
        if isinstance(item, dict) and item.get("article_id") in allowed_ids and item.get("relationship") in {"supporting", "contradicting", "contextual"}:
            relationships[int(item["article_id"])] = item["relationship"]
    if set(relationships) != allowed_ids:
        return None
    return {"assessment": result["assessment"], "explanation": str(result.get("explanation") or "")[:2000], "relationships": relationships}


def capture_run_snapshot(run_id: str, project_id: int) -> int:
    """Freeze source content and the pre-run analysis as separate records."""
    row = db.execute(
        """
        insert into evidence_run_articles
            (run_id, project_id, article_id, content_hash, source_snapshot,
             analysis_snapshot, analysis_source, analysis_status)
        select %s, %s, a.id, a.content_hash,
               jsonb_build_object(
                   'source', a.source, 'source_url', a.source_url, 'url', a.url,
                   'title', a.title, 'text', a.text,
                   'author', a.author, 'published_at', a.published_at,
                   'story_id', a.story_id, 'provenance', a.source_provenance
               ),
               jsonb_build_object(
                   'summary', a.summary,
                   'topics', coalesce(a.topics, '[]'::jsonb),
                   'key_points', coalesce(a.key_points, '[]'::jsonb),
                   'entities', coalesce(a.entities, '[]'::jsonb),
                   'organizations', coalesce(a.organizations, '[]'::jsonb)
               ),
               case when a.analysis_status='success' then 'reused' else 'pending' end,
               coalesce(a.analysis_status, 'pending')
        from articles a join article_projects ap on ap.article_id = a.id
        where ap.project_id = %s
        on conflict (run_id, article_id) do nothing
        returning article_id
        """,
        (str(run_id), int(project_id), int(project_id)),
    )
    # execute returns one row at most; the actual count is read to make retries deterministic.
    count = db.fetch_one("select count(*)::int as count from evidence_run_articles where run_id = %s", (str(run_id),))
    article_count = int((count or {}).get("count") or (1 if row else 0))
    db.execute(
        """insert into evidence_run_status (run_id, project_id, status, article_count, rules_version)
           values (%s,%s,'pending',%s,%s)
           on conflict (run_id) do update set article_count=excluded.article_count,
               rules_version=excluded.rules_version""",
        (str(run_id), int(project_id), article_count, RULES_VERSION),
    )
    return article_count


def _snapshot_rows(run_id: str) -> list[dict]:
    return db.fetch_all(
        """
        select era.article_id as id,
               era.source_snapshot->>'url' as url,
               era.source_snapshot->>'source_url' as source_url,
               era.source_snapshot->>'source' as source,
               era.source_snapshot->>'title' as title,
               coalesce(an.summary, era.analysis_snapshot->>'summary') as summary,
               era.source_snapshot->>'text' as text,
               era.source_snapshot->>'author' as author,
               era.source_snapshot->>'published_at' as published_at,
               era.content_hash,
               nullif(era.source_snapshot->>'story_id', '')::bigint as story_id,
               coalesce(era.source_snapshot->'provenance', '{}'::jsonb) as source_provenance,
               coalesce(an.topics, era.analysis_snapshot->'topics', '[]'::jsonb) as topics,
               coalesce(an.key_points, era.analysis_snapshot->'key_points', '[]'::jsonb) as key_points,
               coalesce(an.entities, era.analysis_snapshot->'entities', '[]'::jsonb) as entities,
               coalesce(an.organizations, era.analysis_snapshot->'organizations', '[]'::jsonb) as organizations,
               case when an.article_id is not null then 'run' else era.analysis_source end as analysis_source,
               case when an.article_id is not null then an.analysis_status else era.analysis_status end as analysis_status,
               coalesce((select epr.status from evidence_provenance_reviews epr
                         where epr.project_id=era.project_id and epr.article_id=era.article_id
                         order by epr.created_at desc limit 1),
                        era.source_snapshot->'provenance'->>'verification_status', 'unassessed') as provenance_status
        from evidence_run_articles era
        left join article_analyses an on an.run_id=era.run_id and an.article_id=era.article_id
        where era.run_id = %s order by era.article_id
        """, (str(run_id),),
    ) or []


def _generate_for_run(run_id: str, project_id: int, generation: int) -> dict:
    """Rebuild claims from frozen content plus this run's analysis snapshot."""
    rows = _snapshot_rows(run_id)
    candidates = []
    embedding_cache: dict[str, list[float]] = {}
    for row in rows:
        if row.get("provenance_status") == "rejected":
            continue
        for topic, claim_text in _claim_candidates(row):
            fingerprint = _fingerprint(topic, claim_text)
            cache_key = claim_text.strip().lower()
            if cache_key not in embedding_cache:
                embedded = get_embedding(claim_text)
                embedding_cache[cache_key] = embedded.get("embedding_json") or []
            candidates.append({
                "row": row,
                "topic": topic,
                "claim": claim_text,
                "type": _claim_type(claim_text),
                "direction": _direction(claim_text),
                "fingerprint": fingerprint,
                "embedding": embedding_cache[cache_key],
            })
    grouped = _group_claim_candidates(candidates)

    db.execute("update evidence_claims set active=false where run_id=%s", (str(run_id),))
    created = 0
    for group in grouped:
        canonical = group["canonical"]
        fingerprint = group["fingerprint"]
        items = group["items"]
        focal_direction = canonical["direction"]
        prepared = []
        for candidate in items:
            row, direction = candidate["row"], candidate["direction"]
            if {direction, focal_direction} == {"positive", "negative"}:
                relationship = "contradicting"
            else:
                relationship = "supporting"
            passage = _best_passage(row, candidate["claim"])
            valid = bool(passage and passage in str(row.get("text") or ""))
            aligned, match_score, qualification_reason = _passage_qualification(candidate["claim"], passage)
            source_type = str((row.get("source_provenance") or {}).get("source_type") or "original document").lower()
            is_summary = "summary" in source_type or "synthetic" in source_type
            qualifies = bool(valid and aligned and not is_summary and row.get("provenance_status") != "rejected")
            prepared.append((row, relationship, passage, valid, qualifies, source_type, match_score, qualification_reason))

        model_result = None
        if canonical["type"] not in {"forecast", "opinion"}:
            model_result = _grounded_model_assessment(canonical["claim"], canonical["type"], prepared)
        if model_result:
            prepared = [
                (row, model_result["relationships"].get(int(row["id"]), relationship) if qualifies else relationship,
                 passage, valid, qualifies, source_type, match_score, qualification_reason)
                for row, relationship, passage, valid, qualifies, source_type, match_score, qualification_reason in prepared
            ]

        support = {_origin(row) for row, rel, _p, _v, ok, _s, _m, _q in prepared if rel == "supporting" and ok}
        conflict = {_origin(row) for row, rel, _p, _v, ok, _s, _m, _q in prepared if rel == "contradicting" and ok}
        context = {_origin(row) for row, rel, _p, _v, ok, _s, _m, _q in prepared if rel == "contextual" and ok}
        all_origins = {_origin(row) for row, _rel, _p, _v, _ok, _s, _m, _q in prepared}
        if model_result:
            assessment, explanation = model_result["assessment"], model_result["explanation"]
        elif not support and not conflict:
            assessment = "assessment_unavailable"
            explanation = "No qualifying original-document passage is available for an automated assessment."
        else:
            assessment, explanation = _assessment(canonical["type"], support, conflict)

        source_row = canonical["row"]
        structured = _structured_claim(canonical["topic"], canonical["claim"])
        structured["matched_claims"] = [item["claim"] for item in items]
        dates, quantities = structured["dates"], structured["quantities"]
        claim = db.execute(
            """insert into evidence_claims
               (project_id,run_id,source_article_id,fingerprint,claim_text,claim_type,topic,entities,
                time_scope,dates,quantities,structured_claim,assessment,explanation,limitations,
                supporting_count,contradicting_count,contextual_count,distinct_origins,
                independent_origin_count,citation_checked_count,model,rules_version,active)
               values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,true)
               on conflict (run_id,fingerprint) do update set
                 source_article_id=excluded.source_article_id, claim_text=excluded.claim_text,
                 claim_type=excluded.claim_type, topic=excluded.topic, entities=excluded.entities,
                 time_scope=excluded.time_scope, dates=excluded.dates, quantities=excluded.quantities,
                 structured_claim=excluded.structured_claim, assessment=excluded.assessment,
                 explanation=excluded.explanation, limitations=excluded.limitations,
                 supporting_count=excluded.supporting_count,
                 contradicting_count=excluded.contradicting_count,
                 contextual_count=excluded.contextual_count,
                 distinct_origins=excluded.distinct_origins,
                 independent_origin_count=excluded.independent_origin_count,
                 citation_checked_count=excluded.citation_checked_count,
                 model=excluded.model, rules_version=excluded.rules_version, active=true,
                 processing_status='success', processing_error=null
               returning id""",
            (int(project_id), str(run_id), int(source_row["id"]), fingerprint, canonical["claim"], canonical["type"],
             canonical["topic"], Jsonb((source_row.get("entities") or []) + (source_row.get("organizations") or [])),
             dates[0] if dates else None, Jsonb(dates), Jsonb(quantities), Jsonb(structured), assessment,
             explanation, "Limited to frozen source material and qualifying exact passages available to this run.",
             len(support), len(conflict), len(context), len(all_origins), len(support | conflict | context),
             sum(1 for _r, _rel, _p, valid, _ok, _s, _m, _q in prepared if valid),
             config.LLM_CHAT_MODEL if model_result else None, RULES_VERSION),
        )
        claim_id = int(claim["id"])
        db.execute("delete from evidence_items where claim_id=%s", (claim_id,))
        for row, relationship, passage, valid, qualifies, source_type, match_score, qualification_reason in prepared:
            snapshot = {
                "title": row.get("title"), "source": row.get("source"), "url": row.get("url"),
                "source_url": row.get("source_url"), "author": row.get("author"),
                "published_at": row.get("published_at").isoformat() if hasattr(row.get("published_at"), "isoformat") else row.get("published_at"),
                "provenance": row.get("source_provenance") or {},
                "analysis_source": row.get("analysis_source"), "analysis_status": row.get("analysis_status"),
                "passage_match_score": round(float(match_score), 3),
                "qualification_reason": qualification_reason,
            }
            db.execute(
                """insert into evidence_items
                   (claim_id,article_id,relationship,passage,citation_valid,origin_key,source_snapshot,
                    quote_source,passage_locator,qualifies)
                   values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   on conflict (claim_id,article_id,relationship) do nothing""",
                (claim_id, int(row["id"]), relationship, passage or "No exact document passage was available.",
                 valid, _origin(row), Jsonb(snapshot), source_type, _passage_locator(row, passage), qualifies),
            )
        db.execute(
            """insert into evidence_assessment_revisions
               (claim_id,generation,assessment,explanation,supporting_count,contradicting_count,
                contextual_count,distinct_origins,rules_version)
               values (%s,%s,%s,%s,%s,%s,%s,%s,%s)
               on conflict (claim_id,generation) do update set
                 assessment=excluded.assessment,explanation=excluded.explanation,
                 supporting_count=excluded.supporting_count,contradicting_count=excluded.contradicting_count,
                 contextual_count=excluded.contextual_count,distinct_origins=excluded.distinct_origins,
                 rules_version=excluded.rules_version""",
            (claim_id, generation, assessment, explanation, len(support), len(conflict), len(context),
             len(all_origins), RULES_VERSION),
        )
        created += 1
    return {"claims": created, "articles": len(rows)}


def generate_for_run(run_id: str, project_id: int) -> dict:
    """Generate evidence and persist a retryable run-stage status."""
    status_row = db.execute(
        """insert into evidence_run_status
               (run_id, project_id, status, rules_version, started_at, error)
           values (%s,%s,'running',%s,now(),null)
           on conflict (run_id) do update set status='running', error=null,
               rules_version=excluded.rules_version, started_at=now(), finished_at=null,
               generation=evidence_run_status.generation+1
           returning generation""",
        (str(run_id), int(project_id), RULES_VERSION),
    )
    try:
        result = _generate_for_run(run_id, project_id, int((status_row or {}).get("generation") or 0))
    except Exception as exc:
        db.execute(
            "update evidence_run_status set status='failed', error=%s, finished_at=now() where run_id=%s",
            (str(exc)[:2000], str(run_id)),
        )
        raise
    db.execute(
        """update evidence_run_status set status='success', error=null,
                  article_count=%s, claim_count=%s, finished_at=now()
             where run_id=%s""",
        (int(result["articles"]), int(result["claims"]), str(run_id)),
    )
    return result


def list_workspace(project_id: int, run_id: str | None = None, topic: str | None = None,
                   search: str | None = None, assessment: str | None = None,
                   claim_type: str | None = None, publisher: str | None = None,
                   review_status: str | None = None, provenance_status: str | None = None,
                   coverage: str | None = None,
                   limit: int = 50, offset: int = 0) -> dict:
    runs = db.fetch_all(
        """with ranked as (
               select pr.*, row_number() over (order by pr.created_at asc) as run_number
               from pipeline_runs pr where pr.project_id=%s and pr.pipeline='analysis'
           )
           select pr.id, pr.status, pr.created_at, pr.finished_at, pr.run_number,
                  (select count(*)::int from evidence_claims ec where ec.run_id=pr.id and ec.active) as claim_count,
                  (select count(*)::int from pipeline_run_documents prd where prd.run_id=pr.id) as document_count,
                  ers.status as evidence_status, ers.error as evidence_error,
                  ers.rules_version, ers.article_count, ers.generation, ers.started_at as evidence_started_at,
                  ers.finished_at as evidence_finished_at
           from ranked pr left join evidence_run_status ers on ers.run_id=pr.id
           order by pr.created_at desc""", (int(project_id),),
    ) or []
    selected = str(run_id) if run_id else (str(runs[0]["id"]) if runs else None)
    if not selected:
        return {"runs": [], "selected_run_id": None, "topics": [], "overview": {}, "claims": []}
    base_params: list = [int(project_id), selected]
    conditions = ["ec.project_id=%s", "ec.run_id=%s", "ec.active=true"]
    if topic:
        conditions.append("ec.topic=%s")
        base_params.append(str(topic))
    overview_where = " and ".join(conditions)
    params = list(base_params)
    if search:
        conditions.append("(ec.claim_text ilike %s or ec.explanation ilike %s)")
        params.extend([f"%{search.strip()}%", f"%{search.strip()}%"])
    if assessment:
        conditions.append("coalesce((select er.decision from evidence_reviews er where er.claim_id=ec.id order by er.created_at desc limit 1),ec.assessment)=%s")
        params.append(assessment)
    if claim_type:
        conditions.append("ec.claim_type=%s")
        params.append(claim_type)
    if publisher:
        conditions.append("exists (select 1 from evidence_items ei where ei.claim_id=ec.id and coalesce(ei.source_snapshot->'provenance'->>'publisher',ei.source_snapshot->>'source')=%s)")
        params.append(publisher)
    if review_status == "reviewed":
        conditions.append("exists (select 1 from evidence_reviews er where er.claim_id=ec.id)")
    elif review_status == "unreviewed":
        conditions.append("not exists (select 1 from evidence_reviews er where er.claim_id=ec.id)")
    elif review_status == "needs_attention":
        conditions.append("(coalesce((select er.decision from evidence_reviews er where er.claim_id=ec.id order by er.created_at desc limit 1),ec.assessment) in ('mixed_evidence','assessment_unavailable') or exists (select 1 from evidence_items ei where ei.claim_id=ec.id and (not ei.citation_valid or not ei.qualifies)))")
    if provenance_status:
        conditions.append("exists (select 1 from evidence_items ei where ei.claim_id=ec.id and coalesce((select epr.status from evidence_provenance_reviews epr where epr.project_id=ec.project_id and epr.article_id=ei.article_id order by epr.created_at desc limit 1),ei.source_snapshot->'provenance'->>'verification_status','unassessed')=%s)")
        params.append(provenance_status)
    if coverage == "single_source":
        conditions.append("ec.independent_origin_count=1")
    elif coverage == "corroborated":
        conditions.append("ec.independent_origin_count>=2")
    elif coverage == "conflicting":
        conditions.append("coalesce((select er.decision from evidence_reviews er where er.claim_id=ec.id order by er.created_at desc limit 1),ec.assessment) in ('contradicted','mixed_evidence')")
    filtered_where = " and ".join(conditions)
    total_row = db.fetch_one(f"select count(*)::int as count from evidence_claims ec where {filtered_where}", tuple(params)) or {}
    page_params = [*params, max(1, min(int(limit), 200)), max(0, int(offset))]
    claims = db.fetch_all(
        f"""select ec.*, a.title as source_title,
                   coalesce((select er.decision from evidence_reviews er where er.claim_id=ec.id order by er.created_at desc limit 1), '') as review_decision,
                   (select count(*)::int from evidence_reviews er where er.claim_id=ec.id) as review_count,
                   (coalesce((select er.decision from evidence_reviews er where er.claim_id=ec.id order by er.created_at desc limit 1),ec.assessment) in ('mixed_evidence','assessment_unavailable')
                    or exists(select 1 from evidence_items ei where ei.claim_id=ec.id and (not ei.citation_valid or not ei.qualifies))) as needs_review
              from evidence_claims ec left join articles a on a.id=ec.source_article_id
             where {filtered_where}
             order by needs_review desc, ec.topic, ec.created_at desc limit %s offset %s""", tuple(page_params),
    ) or []
    topics = db.fetch_all("select topic,count(*)::int as count from evidence_claims where project_id=%s and run_id=%s and active group by topic order by topic", (int(project_id), selected)) or []
    summary_rows = db.fetch_all(
        f"""select ec.assessment, ec.independent_origin_count, ec.citation_checked_count,
                   coalesce((select er.decision from evidence_reviews er where er.claim_id=ec.id order by er.created_at desc limit 1),'') as review_decision,
                   (coalesce((select er.decision from evidence_reviews er where er.claim_id=ec.id order by er.created_at desc limit 1),ec.assessment) in ('mixed_evidence','assessment_unavailable')
                    or exists(select 1 from evidence_items ei where ei.claim_id=ec.id and (not ei.citation_valid or not ei.qualifies))) as needs_review
              from evidence_claims ec where {overview_where}""",
        tuple(base_params),
    ) or []
    counts = Counter(row.get("review_decision") or row["assessment"] for row in summary_rows)
    origins = db.fetch_one(
        f"""select count(distinct ei.origin_key)::int as known_origins,
                  count(*) filter (where coalesce(
                      (select epr.status from evidence_provenance_reviews epr
                        where epr.project_id=ec.project_id and epr.article_id=ei.article_id
                        order by epr.created_at desc limit 1),
                      ei.source_snapshot->'provenance'->>'verification_status',
                      'unassessed')='unassessed')::int as unassessed_items,
                  count(*) filter (where not ei.citation_valid or not ei.qualifies)::int as unqualified_items
             from evidence_items ei join evidence_claims ec on ec.id=ei.claim_id
            where {overview_where}""", tuple(base_params),
    ) or {}
    publishers = db.fetch_all(
        """select distinct coalesce(ei.source_snapshot->'provenance'->>'publisher',ei.source_snapshot->>'source') as publisher
           from evidence_items ei join evidence_claims ec on ec.id=ei.claim_id
           where ec.project_id=%s and ec.run_id=%s and ec.active order by publisher""",
        (int(project_id), selected),
    ) or []

    claim_ids = [int(claim["id"]) for claim in claims]
    matrix_items = db.fetch_all(
        """select ei.claim_id, ei.relationship,
                  coalesce(ei.source_snapshot->'provenance'->>'publisher',ei.source_snapshot->>'source','Unknown source') as publisher,
                  ei.citation_valid, ei.qualifies
             from evidence_items ei
            where ei.claim_id = any(%s)
            order by ei.claim_id, publisher""",
        (claim_ids,),
    ) if claim_ids else []
    matrix_by_claim: dict[int, list[dict]] = defaultdict(list)
    for item in matrix_items or []:
        matrix_by_claim[int(item["claim_id"])].append(item)
    source_matrix = {
        "publishers": [row["publisher"] for row in publishers if row.get("publisher")],
        "rows": [
            {
                "claim_id": int(claim["id"]),
                "claim_text": claim["claim_text"],
                "topic": claim["topic"],
                "assessment": claim.get("review_decision") or claim["assessment"],
                "sources": matrix_by_claim.get(int(claim["id"]), []),
            }
            for claim in claims
        ],
    }
    return {"runs": runs, "selected_run_id": selected, "topics": topics,
            "overview": {
                "total_claims": len(summary_rows),
                "corroborated_claims": sum(1 for row in summary_rows if int(row.get("independent_origin_count") or 0) >= 2),
                "single_source_claims": sum(1 for row in summary_rows if int(row.get("independent_origin_count") or 0) == 1),
                "needs_review_claims": sum(1 for row in summary_rows if row.get("needs_review")),
                "exact_quotes": sum(int(row.get("citation_checked_count") or 0) for row in summary_rows),
                "assessment_counts": dict(counts), **origins,
            },
            "filter_options": {"publishers": [row["publisher"] for row in publishers if row.get("publisher")]},
            "source_matrix": source_matrix,
            "claims": claims, "total_filtered": int(total_row.get("count") or 0),
            "limit": page_params[-2], "offset": page_params[-1]}


def compare_runs(project_id: int, base_run_id: str, target_run_id: str) -> dict | None:
    """Explain evidence changes between two immutable project run snapshots."""
    run_rows = db.fetch_all(
        """select id, created_at from pipeline_runs
            where project_id=%s and pipeline='analysis' and id in (%s,%s)""",
        (int(project_id), str(base_run_id), str(target_run_id)),
    ) or []
    if {str(row["id"]) for row in run_rows} != {str(base_run_id), str(target_run_id)}:
        return None

    claims = db.fetch_all(
        """select id, run_id, fingerprint, claim_text, topic, assessment,
                  supporting_count, contradicting_count, contextual_count, distinct_origins, rules_version,
                  coalesce((select er.decision from evidence_reviews er where er.claim_id=evidence_claims.id order by er.created_at desc limit 1),'') as review_decision
             from evidence_claims
            where project_id=%s and run_id in (%s,%s) and active""",
        (int(project_id), str(base_run_id), str(target_run_id)),
    ) or []
    by_run = {str(base_run_id): {}, str(target_run_id): {}}
    for claim in claims:
        by_run[str(claim["run_id"])][claim["fingerprint"]] = claim
    item_rows = db.fetch_all(
        """select ec.run_id,ec.fingerprint,ei.origin_key,ei.relationship,ei.passage,
                  ei.citation_valid,ei.qualifies
             from evidence_items ei join evidence_claims ec on ec.id=ei.claim_id
            where ec.project_id=%s and ec.run_id in (%s,%s) and ec.active""",
        (int(project_id), str(base_run_id), str(target_run_id)),
    ) or []
    signatures = defaultdict(set)
    for item in item_rows:
        signatures[(str(item["run_id"]), item["fingerprint"])].add(
            (item.get("origin_key"), item.get("relationship"), item.get("passage"),
             bool(item.get("citation_valid")), bool(item.get("qualifies")))
        )

    changes = []
    counts = Counter()
    fingerprints = set(by_run[str(base_run_id)]) | set(by_run[str(target_run_id)])
    for fingerprint in fingerprints:
        before = by_run[str(base_run_id)].get(fingerprint)
        after = by_run[str(target_run_id)].get(fingerprint)
        if before is None:
            change_type = "new_evidence"
            cause = "This claim first appears in material available to the target run."
        elif after is None:
            change_type = "removed_evidence"
            cause = "This claim is absent from the target run's captured evidence set."
        else:
            assessment_changed = before["assessment"] != after["assessment"]
            before_items = signatures[(str(base_run_id), fingerprint)]
            after_items = signatures[(str(target_run_id), fingerprint)]
            evidence_changed = before_items != after_items
            origin_rel_before = {(item[0], item[1]) for item in before_items}
            origin_rel_after = {(item[0], item[1]) for item in after_items}
            source_corrected = evidence_changed and origin_rel_before == origin_rel_after
            rules_changed = before["rules_version"] != after["rules_version"]
            review_changed = before.get("review_decision") != after.get("review_decision")
            if review_changed:
                change_type = "analyst_decision_changed"
                cause = "The latest analyst decision differs between these run-specific claims."
            elif source_corrected:
                change_type = "source_corrected"
                cause = "A stored passage or its citation qualification changed while the recorded origins stayed the same."
            elif assessment_changed and evidence_changed:
                change_type = "assessment_changed"
                cause = (
                    f"Evidence coverage changed from {before['distinct_origins']} to "
                    f"{after['distinct_origins']} recorded origins, changing the assessment."
                )
            elif assessment_changed and rules_changed:
                change_type = "rules_changed"
                cause = "The assessment changed after the evidence rules version changed; this is a processing change, not a reported real-world change."
            elif assessment_changed:
                change_type = "reprocessed"
                cause = "The assessment changed without a recorded evidence-count change; this is shown as reprocessing, not a real-world change."
            elif evidence_changed:
                change_type = "evidence_changed"
                cause = "The supporting, conflicting, or origin counts changed while the assessment label stayed the same."
            else:
                continue
        counts[change_type] += 1
        changes.append({
            "fingerprint": fingerprint,
            "change_type": change_type,
            "cause": cause,
            "claim_text": (after or before)["claim_text"],
            "topic": (after or before)["topic"],
            "base": before,
            "target": after,
        })
    changes.sort(key=lambda item: (item["topic"], item["claim_text"]))
    return {
        "base_run_id": str(base_run_id), "target_run_id": str(target_run_id),
        "counts": dict(counts), "changes": changes,
    }


def get_claim(project_id: int, claim_id: int) -> dict | None:
    claim = db.fetch_one("select * from evidence_claims where id=%s and project_id=%s and active", (int(claim_id), int(project_id)))
    if not claim: return None
    claim["evidence"] = db.fetch_all(
        """select ei.*, a.source_provenance as current_provenance,
                  (select jsonb_build_object('status', epr.status, 'reason', epr.reason,
                                              'reviewer_name', epr.reviewer_name, 'created_at', epr.created_at)
                     from evidence_provenance_reviews epr
                    where epr.project_id=%s and epr.article_id=ei.article_id
                    order by epr.created_at desc limit 1) as provenance_review
             from evidence_items ei left join articles a on a.id=ei.article_id
            where ei.claim_id=%s
            order by case ei.relationship when 'supporting' then 1 when 'contradicting' then 2 else 3 end, ei.id""",
        (int(project_id), int(claim_id)),
    ) or []
    claim["reviews"] = db.fetch_all("select * from evidence_reviews where claim_id=%s order by created_at desc", (int(claim_id),)) or []
    claim["assessment_revisions"] = db.fetch_all(
        "select * from evidence_assessment_revisions where claim_id=%s order by generation desc", (int(claim_id),)
    ) or []
    return claim


def review_claim(project_id: int, claim_id: int, decision: str, reason: str, user: dict) -> dict | None:
    if decision not in ASSESSMENTS or not reason.strip():
        raise ValueError("A valid decision and review reason are required.")
    claim = db.fetch_one("select id from evidence_claims where id=%s and project_id=%s", (int(claim_id), int(project_id)))
    if not claim: return None
    db.execute("insert into evidence_reviews (claim_id, reviewer_id, reviewer_name, decision, reason) values (%s,%s,%s,%s,%s)",
               (int(claim_id), user.get("id"), user.get("username") or user.get("email"), decision, reason.strip()[:2000]))
    return get_claim(project_id, claim_id)


def review_provenance(project_id: int, article_id: int, status: str, reason: str, user: dict) -> dict | None:
    if status not in {"verified", "rejected", "unassessed"} or not reason.strip():
        raise ValueError("A valid provenance status and reason are required.")
    row = db.fetch_one("select a.source_provenance from articles a join article_projects ap on ap.article_id=a.id where a.id=%s and ap.project_id=%s", (int(article_id), int(project_id)))
    if not row: return None
    value = dict(row.get("source_provenance") or {})
    reviewer_name = user.get("username") or user.get("email")
    value.update({"verification_status": status, "verified_by": reviewer_name, "verification_reason": reason.strip()[:1000]})
    db.execute(
        """insert into evidence_provenance_reviews
           (project_id, article_id, reviewer_id, reviewer_name, status, reason)
           values (%s,%s,%s,%s,%s,%s)""",
        (int(project_id), int(article_id), user.get("id"), reviewer_name, status, reason.strip()[:1000]),
    )
    return db.execute("update articles set source_provenance=%s where id=%s returning id, source_provenance", (Jsonb(value), int(article_id)))
