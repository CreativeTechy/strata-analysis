"""Evidence workspace generation and reads.

The first release is deliberately conservative: it derives claims from stored
analysis key points, validates every cited passage against the frozen article
body, collapses repeated origins, and only calls a claim supported when two
distinct origins make the same normalized claim. It never fetches the web.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from urllib.parse import urlparse

import db
from psycopg.types.json import Jsonb

RULES_VERSION = "evidence-v1"
ASSESSMENTS = {
    "supported", "contradicted", "mixed_evidence", "insufficient_evidence", "not_yet_verifiable",
}
_STOP = {"about", "after", "again", "against", "also", "because", "been", "before", "being", "between",
         "could", "from", "have", "into", "more", "most", "other", "over", "said", "than", "that", "their",
         "there", "these", "they", "this", "through", "under", "very", "what", "when", "where", "which",
         "while", "with", "would"}
_FORECAST = re.compile(r"\b(will|expects?|forecast|projected|plans?|aims?|next (?:month|quarter|year))\b", re.I)
_OPINION = re.compile(r"\b(think|believe|feel|in my view|should|best|worst)\b", re.I)
_CAUSAL = re.compile(r"\b(because|caused|causes|led to|resulted in|due to|drives?)\b", re.I)
_ATTRIBUTED = re.compile(r"\b(said|stated|announced|according to|reported|claimed)\b", re.I)
_NEGATION = re.compile(r"\b(no|not|never|didn't|doesn't|won't|without|declined|decreased|fell|lower)\b", re.I)
_DATE = re.compile(r"\b(?:20\d{2}(?:-\d{2}(?:-\d{2})?)?|(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+(?:20\d{2}|\d{1,2}(?:,?\s+20\d{2})?))\b", re.I)
_QUANTITY = re.compile(r"(?:[$£€]\s?\d[\d,.]*|\b\d+(?:\.\d+)?\s?(?:%|percent|million|billion|trillion|tonnes?|tons?|barrels?|bpd|days?|months?|years?)\b)", re.I)


def _words(value: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", str(value or "").lower()) if len(w) > 2 and w not in _STOP]


def _fingerprint(topic: str, claim: str) -> str:
    # Sorted content words group exact/reordered repeats while keeping topic
    # context. Negation is omitted from the identity and retained as polarity,
    # allowing an otherwise equivalent opposing statement to be attached as a
    # contradiction.
    words = [w for w in _words(claim) if w not in {
        "not", "never", "without", "lower", "higher", "declined", "decreased", "fell", "increased", "rose",
    }]
    basis = f"{topic.lower()}|{' '.join(sorted(set(words))[:24])}"
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
    value = "\n".join(str(row.get(k) or "") for k in ("title", "summary", "text"))
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", value) if len(part.strip()) >= 20]


def _best_passage(row: dict, claim: str) -> str:
    wanted = set(_words(claim))
    choices = _sentences(row)
    if not choices:
        return str(row.get("title") or "")[:600]
    return max(choices, key=lambda text: len(wanted.intersection(_words(text))))[:1200]


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


def capture_run_snapshot(run_id: str, project_id: int) -> int:
    """Freeze all articles eligible as evidence at the start of a run."""
    row = db.execute(
        """
        insert into evidence_run_articles (run_id, project_id, article_id, content_hash, source_snapshot)
        select %s, %s, a.id, a.content_hash,
               jsonb_build_object(
                   'source', a.source, 'source_url', a.source_url, 'url', a.url,
                   'title', a.title, 'summary', a.summary, 'text', a.text,
                   'author', a.author, 'published_at', a.published_at,
                   'story_id', a.story_id, 'provenance', a.source_provenance,
                   'topics', coalesce(a.topics, '[]'::jsonb),
                   'key_points', coalesce(a.key_points, '[]'::jsonb),
                   'entities', coalesce(a.entities, '[]'::jsonb),
                   'organizations', coalesce(a.organizations, '[]'::jsonb)
               )
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
               era.source_snapshot->>'summary' as summary,
               era.source_snapshot->>'text' as text,
               era.source_snapshot->>'author' as author,
               era.source_snapshot->>'published_at' as published_at,
               era.content_hash,
               nullif(era.source_snapshot->>'story_id', '')::bigint as story_id,
               coalesce(era.source_snapshot->'provenance', '{}'::jsonb) as source_provenance,
               coalesce(era.source_snapshot->'topics', '[]'::jsonb) as topics,
               coalesce(era.source_snapshot->'key_points', '[]'::jsonb) as key_points,
               coalesce(era.source_snapshot->'entities', '[]'::jsonb) as entities,
               coalesce(era.source_snapshot->'organizations', '[]'::jsonb) as organizations
        from evidence_run_articles era
        where era.run_id = %s order by era.article_id
        """, (str(run_id),),
    ) or []


def _generate_for_run(run_id: str, project_id: int) -> dict:
    """Idempotently rebuild a run's claims from its frozen article snapshot."""
    rows = _snapshot_rows(run_id)
    grouped: dict[str, dict] = {}
    for row in rows:
        for topic, text in _claim_candidates(row):
            fingerprint = _fingerprint(topic, text)
            group = grouped.setdefault(fingerprint, {"topic": topic, "claim": text, "type": _claim_type(text), "items": []})
            group["items"].append((row, bool(_NEGATION.search(text))))

    created = 0
    for fingerprint, group in grouped.items():
        items = group["items"]
        origins = {_origin(row) for row, _ in items}
        focal_negative = items[0][1]
        supporting = [(row, neg) for row, neg in items if neg == focal_negative]
        contradicting = [(row, neg) for row, neg in items if neg != focal_negative]
        supporting_origins = {_origin(row) for row, _ in supporting}
        contradicting_origins = {_origin(row) for row, _ in contradicting}
        claim_type = group["type"]
        assessment, explanation = _assessment(claim_type, supporting_origins, contradicting_origins)
        source_row = items[0][0]
        dates = list(dict.fromkeys(_DATE.findall(group["claim"])))
        quantities = list(dict.fromkeys(_QUANTITY.findall(group["claim"])))
        claim = db.execute(
            """
            insert into evidence_claims
                (project_id, run_id, source_article_id, fingerprint, claim_text, claim_type, topic,
                 entities, time_scope, dates, quantities, assessment, explanation, limitations, supporting_count,
                 contradicting_count, contextual_count, distinct_origins, rules_version)
            values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0,%s,%s)
            on conflict (run_id, fingerprint) do update set
                project_id = excluded.project_id,
                source_article_id = excluded.source_article_id,
                claim_text = excluded.claim_text,
                claim_type = excluded.claim_type,
                topic = excluded.topic,
                entities = excluded.entities,
                time_scope = excluded.time_scope,
                dates = excluded.dates,
                quantities = excluded.quantities,
                assessment = excluded.assessment,
                explanation = excluded.explanation,
                limitations = excluded.limitations,
                supporting_count = excluded.supporting_count,
                contradicting_count = excluded.contradicting_count,
                contextual_count = excluded.contextual_count,
                distinct_origins = excluded.distinct_origins,
                rules_version = excluded.rules_version,
                processing_status = 'success',
                processing_error = null
            returning id
            """,
            (int(project_id), str(run_id), int(source_row["id"]), fingerprint, group["claim"], claim_type,
             group["topic"], Jsonb((source_row.get("entities") or []) + (source_row.get("organizations") or [])),
             dates[0] if dates else None, Jsonb(dates), Jsonb(quantities),
             assessment, explanation, "Assessment is limited to the material imported before this run started.",
             len(supporting), len(contradicting), len(origins), RULES_VERSION),
        )
        claim_id = int(claim["id"])
        # Replace generated citations while preserving the claim row and its
        # immutable analyst review history across retries.
        db.execute("delete from evidence_items where claim_id = %s", (claim_id,))
        for row, negative_polarity in items:
            relationship = "supporting" if negative_polarity == focal_negative else "contradicting"
            passage = _best_passage(row, group["claim"])
            haystack = "\n".join(str(row.get(k) or "") for k in ("title", "summary", "text"))
            valid = bool(passage and passage in haystack)
            snapshot = {
                "title": row.get("title"), "source": row.get("source"), "url": row.get("url"),
                "source_url": row.get("source_url"), "author": row.get("author"),
                "published_at": row.get("published_at").isoformat() if hasattr(row.get("published_at"), "isoformat") else row.get("published_at"),
                "provenance": row.get("source_provenance") or {},
            }
            db.execute(
                """insert into evidence_items
                   (claim_id, article_id, relationship, passage, citation_valid, origin_key, source_snapshot)
                   values (%s,%s,%s,%s,%s,%s,%s)
                   on conflict (claim_id, article_id, relationship) do nothing""",
                (claim_id, int(row["id"]), relationship, passage, valid, _origin(row), Jsonb(snapshot)),
            )
        created += 1
    return {"claims": created, "articles": len(rows)}


def generate_for_run(run_id: str, project_id: int) -> dict:
    """Generate evidence and persist a retryable run-stage status."""
    db.execute(
        """insert into evidence_run_status
               (run_id, project_id, status, rules_version, started_at, error)
           values (%s,%s,'running',%s,now(),null)
           on conflict (run_id) do update set status='running', error=null,
               rules_version=excluded.rules_version, started_at=now(), finished_at=null""",
        (str(run_id), int(project_id), RULES_VERSION),
    )
    try:
        result = _generate_for_run(run_id, project_id)
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


def list_workspace(project_id: int, run_id: str | None = None, topic: str | None = None) -> dict:
    runs = db.fetch_all(
        """select pr.id, pr.status, pr.created_at, pr.finished_at,
                  (select count(*)::int from evidence_claims ec where ec.run_id=pr.id) as claim_count,
                  ers.status as evidence_status, ers.error as evidence_error,
                  ers.rules_version, ers.started_at as evidence_started_at,
                  ers.finished_at as evidence_finished_at
           from pipeline_runs pr left join evidence_run_status ers on ers.run_id=pr.id
           where pr.project_id = %s and pr.pipeline = 'analysis'
           order by pr.created_at desc""", (int(project_id),),
    ) or []
    selected = str(run_id) if run_id else (str(runs[0]["id"]) if runs else None)
    if not selected:
        return {"runs": [], "selected_run_id": None, "topics": [], "overview": {}, "claims": []}
    params: list = [int(project_id), selected]
    topic_sql = ""
    if topic:
        topic_sql = "and ec.topic = %s"
        params.append(str(topic))
    claims = db.fetch_all(
        f"""select ec.*, a.title as source_title,
                   coalesce((select er.decision from evidence_reviews er where er.claim_id=ec.id order by er.created_at desc limit 1), '') as review_decision,
                   (select count(*)::int from evidence_reviews er where er.claim_id=ec.id) as review_count
              from evidence_claims ec left join articles a on a.id=ec.source_article_id
             where ec.project_id=%s and ec.run_id=%s {topic_sql}
             order by ec.topic, ec.created_at desc""", tuple(params),
    ) or []
    topics = db.fetch_all("select topic, count(*)::int as count from evidence_claims where project_id=%s and run_id=%s group by topic order by topic", (int(project_id), selected)) or []
    counts = Counter(row.get("review_decision") or row["assessment"] for row in claims)
    origin_params: list = [int(project_id), selected]
    origin_topic_sql = ""
    if topic:
        origin_topic_sql = "and ec.topic = %s"
        origin_params.append(str(topic))
    origins = db.fetch_one(
        f"""select count(distinct ei.origin_key)::int as known_origins,
                  count(*) filter (where coalesce(
                      (select epr.status from evidence_provenance_reviews epr
                        where epr.project_id=ec.project_id and epr.article_id=ei.article_id
                        order by epr.created_at desc limit 1),
                      ei.source_snapshot->'provenance'->>'verification_status',
                      'unassessed')='unassessed')::int as unassessed_items
             from evidence_items ei join evidence_claims ec on ec.id=ei.claim_id
            where ec.project_id=%s and ec.run_id=%s {origin_topic_sql}""", tuple(origin_params),
    ) or {}
    return {"runs": runs, "selected_run_id": selected, "topics": topics,
            "overview": {"total_claims": len(claims), "assessment_counts": dict(counts), **origins}, "claims": claims}


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
                  supporting_count, contradicting_count, distinct_origins, rules_version
             from evidence_claims
            where project_id=%s and run_id in (%s,%s)""",
        (int(project_id), str(base_run_id), str(target_run_id)),
    ) or []
    by_run = {str(base_run_id): {}, str(target_run_id): {}}
    for claim in claims:
        by_run[str(claim["run_id"])][claim["fingerprint"]] = claim

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
            evidence_changed = any(before[key] != after[key] for key in (
                "supporting_count", "contradicting_count", "distinct_origins",
            ))
            rules_changed = before["rules_version"] != after["rules_version"]
            if assessment_changed and evidence_changed:
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
    claim = db.fetch_one("select * from evidence_claims where id=%s and project_id=%s", (int(claim_id), int(project_id)))
    if not claim: return None
    claim["evidence"] = db.fetch_all(
        """select ei.*, a.source_provenance as current_provenance,
                  (select jsonb_build_object('status', epr.status, 'reason', epr.reason,
                                              'reviewer_name', epr.reviewer_name, 'created_at', epr.created_at)
                     from evidence_provenance_reviews epr
                    where epr.project_id=%s and epr.article_id=ei.article_id
                    order by epr.created_at desc limit 1) as provenance_review
             from evidence_items ei left join articles a on a.id=ei.article_id
            where ei.claim_id=%s order by ei.relationship, ei.id""",
        (int(project_id), int(claim_id)),
    ) or []
    claim["reviews"] = db.fetch_all("select * from evidence_reviews where claim_id=%s order by created_at desc", (int(claim_id),)) or []
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
