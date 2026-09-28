"""Fast, cached article-to-project relevance screening.

Runs in the pipeline's `prepare` stage, before the expensive per-article
analysis (backend/analysis/orchestrator.py - one or more LLM calls plus
three separate zero-shot classification passes) and before evidence
generation. Local sentence-transformer embeddings (the same model
backend/embeddings.py already loads for search/clustering/evidence, so this
adds no new model or network dependency) handle the clear matches and clear
misses; only the middle band reaches the configured chat LLM, batched, since
that's the only step here with a real per-call cost.

Whether the source *text itself* is usable (a login wall, cookie notice, or
access-denied page saved in place of the real article) is a separate concern
from scope relevance and is not this module's job - see
services/evidence/workspace.py's own `_content_quality`, which already
screens that at the evidence-generation stage.

The decision is cached per (article, project) in article_projects, keyed by
content hash + project scope hash + rules version, so a project's scope or
an article's text changing is what invalidates the cache - not time. Missing
models, malformed LLM responses, and any other failure fail open as
``needs_review`` rather than silently discarding material a human never saw.
A manual override always wins over any automatic decision, in either
direction.

`screen_project_articles`'s `article_ids` restricts screening to one run's
candidate set (see services/pipeline/pipeline.py's `_select_articles`) rather
than every article the project has ever held - a pending-only run only pays
to screen the articles it might actually analyze, and a run's screened/
included/excluded counters describe that run's own selection instead of the
project's entire history.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Callable

import config
import db
from embeddings import build_project_embedding_text, cosine_similarity, get_embeddings
from llm_client import LLMError, chat_completion
from psycopg.types.json import Jsonb
from services.projects.projects_store import get_project, persist_project_embedding_for_id

logger = logging.getLogger(__name__)

# Bumped because what gets *persisted* as a cache-valid decision changed
# (see _OUTAGE_SOURCES below) - forces every existing cached decision to be
# re-evaluated once, rather than leaving pre-fix outage artifacts stuck as
# "cache" hits forever.
RULES_VERSION = "article-relevance-v4"
DECISIONS = {"accepted", "excluded", "needs_review"}
OVERRIDE_DECISIONS = {"include", "exclude"}

# Sources produced by a failure fallback (the embedding model couldn't load,
# or the borderline LLM call errored/timed out/returned malformed JSON) as
# opposed to a genuine scored answer. These are never persisted as a cached
# decision (see screen_project_articles's final loop) and never treated as a
# real "uncertain" LLM answer - an outage must not permanently disable
# screening for whatever it touched.
_OUTAGE_SOURCES = {"fallback", "llm_unavailable"}


class ScreeningCancelled(Exception):
    """Raised when `should_cancel` reports the run was stopped mid-screening -
    embedding and the borderline LLM batches are the only slow steps here, so
    that's where this is checked (see _article_vectors and the borderline
    loop in screen_project_articles)."""


def _rules_version() -> str:
    """Cache key includes tunable thresholds so calibration never goes stale."""
    return (
        f"{RULES_VERSION}:accept={config.ARTICLE_RELEVANCE_ACCEPT_THRESHOLD:.4f}:"
        f"exclude={config.ARTICLE_RELEVANCE_EXCLUDE_THRESHOLD:.4f}"
    )


def current_rules_version() -> str:
    """Public wrapper around _rules_version() for callers outside this module
    (pipeline.py's enforce-mode candidate filter) that need to tell a still-
    valid cached decision apart from one whose calibration has since changed,
    without duplicating the threshold-hashing logic."""
    return _rules_version()


def _hash_text(value: str) -> str:
    normalized = " ".join(str(value or "").split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _article_text(row: dict) -> str:
    title = " ".join(str(row.get("title") or "").split())
    body = " ".join(str(row.get("text") or "").split())
    return "\n".join(part for part in (title, body) if part)[:12000]


def _content_hash(row: dict) -> str:
    return str(row.get("content_hash") or "").strip() or _hash_text(_article_text(row))


def _scope_hash(project: dict) -> str:
    return _hash_text(build_project_embedding_text(project))


def _project_vector(project: dict) -> list[float]:
    vector = project.get("embedding_json") or []
    source = str(project.get("embedding_source") or "")
    if vector and project.get("embedding_model") == config.EMBEDDING_MODEL and source.endswith(":query"):
        return vector
    refreshed = persist_project_embedding_for_id(int(project["id"])) or {}
    return refreshed.get("embedding_json") or []


def _article_vectors(rows: list[dict], should_cancel: Callable[[], bool] | None = None) -> dict[int, list[float]]:
    """Load cached vectors and embed all missing articles in batches."""
    vectors: dict[int, list[float]] = {}
    missing = []
    for row in rows:
        article_id = int(row["id"])
        vector = row.get("embedding_json") or []
        source = str(row.get("embedding_source") or "")
        if (vector and row.get("embedding_model") == config.EMBEDDING_MODEL
                and source.endswith(":passage") and not row.get("_force_reembed")):
            vectors[article_id] = vector
        else:
            missing.append(row)

    for start in range(0, len(missing), 128):
        if should_cancel and should_cancel():
            raise ScreeningCancelled()
        batch = missing[start:start + 128]
        embedded = get_embeddings([_article_text(row) for row in batch], role="passage")
        writes = []
        for row, result in zip(batch, embedded):
            vector = result.get("embedding_json") or []
            if not vector:
                continue
            article_id = int(row["id"])
            vectors[article_id] = vector
            writes.append((Jsonb(vector), result.get("embedding_model"), result.get("embedding_source"),
                           result.get("embedded_at"), article_id))
        if writes:
            with db.transaction() as cur:
                cur.executemany(
                    """update articles set embedding_json=%s,embedding_model=%s,
                              embedding_source=%s,embedded_at=%s where id=%s""",
                    writes,
                )
    return vectors


def _validate_llm_results(payload, expected_ids: set[int]) -> dict[int, dict] | None:
    items = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return None
    parsed = {}
    for item in items:
        if not isinstance(item, dict):
            return None
        try:
            article_id = int(item.get("id"))
            score = float(item.get("score", 0))
        except (TypeError, ValueError):
            return None
        label = str(item.get("relevance") or "").strip().lower()
        if article_id not in expected_ids or label not in {"relevant", "contextual", "unrelated", "uncertain"}:
            return None
        parsed[article_id] = {
            "relevance": label,
            "score": max(0.0, min(1.0, score)),
            "explanation": str(item.get("explanation") or "").strip()[:1000],
        }
    return parsed if set(parsed) == expected_ids else None


def _classify_borderline(project: dict, rows: list[dict]) -> dict[int, dict]:
    if not rows:
        return {}
    prompt = {
        "project": {
            "title": project.get("name"),
            "description": project.get("description"),
            "location": project.get("location"),
            "keywords": project.get("keywords") or [],
        },
        "articles": [
            {"id": int(row["id"]), "title": row.get("title"), "excerpt": str(row.get("text") or "")[:800]}
            for row in rows
        ],
        "instructions": (
            "Classify whether each article is relevant to the project's actual research scope. "
            "Shared geography or a broad keyword alone is insufficient. Use contextual only for "
            "concrete causes, effects, actors, or measurements connected to the project."
        ),
    }
    try:
        raw = chat_completion(
            messages=[
                {"role": "system", "content": (
                    "Return JSON only: {results:[{id,relevance,score,explanation}]}. "
                    "relevance must be relevant, contextual, unrelated, or uncertain."
                )},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            temperature=0,
            max_tokens=max(600, len(rows) * 70),
            json_mode=True,
        )
        parsed = _validate_llm_results(json.loads(raw), {int(row["id"]) for row in rows})
        if parsed is not None:
            return parsed
    except (LLMError, TypeError, ValueError, json.JSONDecodeError):
        logger.exception("Borderline article relevance classification failed.")
    return {
        int(row["id"]): {
            "relevance": "uncertain", "score": 0.0,
            "explanation": "The lightweight relevance check was unavailable; included for review.",
            # Distinguishes "the call itself failed" from a genuine LLM answer
            # of "uncertain" - screen_project_articles reads this to keep an
            # outage from being cached as if it were a real decision.
            "unavailable": True,
        }
        for row in rows
    }


def _decision_from_label(label: str) -> str:
    if label in {"relevant", "contextual"}:
        return "accepted"
    if label == "unrelated":
        return "excluded"
    return "needs_review"


def _persist_screening(project_id: int, row: dict, result: dict) -> None:
    db.execute(
        """update article_projects set similarity_score=%s,relevance_decision=%s,
                  relevance_explanation=%s,relevance_source=%s,relevance_scope_hash=%s,
                  relevance_content_hash=%s,relevance_model=%s,relevance_rules_version=%s,
                  relevance_screened_at=now()
             where project_id=%s and article_id=%s""",
        (result.get("similarity_score"), result["decision"], result.get("explanation"),
         result.get("source"), result["scope_hash"], result["content_hash"],
         config.EMBEDDING_MODEL, result["rules_version"],
         int(project_id), int(row["id"])),
    )


def _record_run_screenings(run_id: str, project_id: int, results: list[dict]) -> None:
    if not results:
        return
    with db.transaction() as cur:
        cur.executemany(
            """insert into pipeline_run_article_screenings
                   (run_id,project_id,article_id,decision,included,similarity_score,
                    decision_source,explanation,scope_hash,content_hash,rules_version,model)
               values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               on conflict (run_id,article_id) do update set
                   decision=excluded.decision,included=excluded.included,
                   similarity_score=excluded.similarity_score,
                   decision_source=excluded.decision_source,explanation=excluded.explanation""",
            [
                (run_id, int(project_id), item["article_id"], item["decision"], item["included"],
                 item.get("similarity_score"), item.get("source"), item.get("explanation"),
                 item["scope_hash"], item["content_hash"], item["rules_version"], config.EMBEDDING_MODEL)
                for item in results
            ],
        )


def screen_project_articles(
    project_id: int, run_id: str, mode: str | None = None, article_ids: list[int] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> dict:
    """`article_ids`, when not None, restricts screening to that specific set
    (a run's own candidate articles) rather than everything article_projects
    links to this project. An empty list means "nothing to screen" - a run
    with no candidate articles skips the query entirely, the same way
    services/pipeline/pipeline.py's `_select_articles` treats an empty
    relevance filter.

    `should_cancel`, when given, is checked between the embedding batches and
    between the borderline LLM batches - the only steps slow enough that a
    stop request needs to land inside them rather than waiting for the whole
    call to finish. Raises ScreeningCancelled rather than returning early, so
    a stop can't be silently swallowed as "screening produced nothing"."""
    mode = str(mode or config.ARTICLE_RELEVANCE_SCREENING_MODE).strip().lower()
    if mode not in {"off", "observe", "enforce"}:
        mode = "observe"
    if article_ids is not None and not article_ids:
        return {"mode": mode, "results": [], "included_ids": [], "screened": 0,
                "included": 0, "excluded": 0, "needs_review": 0}
    id_filter = ""
    params: list = [int(project_id)]
    if article_ids is not None:
        id_filter = "and a.id = any(%s)"
        params.append([int(article_id) for article_id in article_ids])
    rows = db.fetch_all(
        f"""select a.id,a.title,a.text,a.content_hash,a.embedding_json,a.embedding_model,
                  a.embedding_source,ap.similarity_score,ap.relevance_decision,
                  ap.relevance_explanation,ap.relevance_source,ap.relevance_scope_hash,
                  ap.relevance_content_hash,ap.relevance_model,ap.relevance_rules_version,
                  ap.manual_relevance_override,ap.manual_relevance_reason
             from articles a join article_projects ap on ap.article_id=a.id
            where ap.project_id=%s {id_filter} order by a.id""",
        tuple(params),
    ) or []
    if not rows:
        return {"mode": mode, "results": [], "included_ids": [], "screened": 0,
                "included": 0, "excluded": 0, "needs_review": 0}

    project = get_project(project_id) or {}
    scope_digest = _scope_hash(project)
    rules_version = _rules_version()
    project_vector = _project_vector(project) if mode != "off" and project.get("id") else []
    results, pending, borderline = [], [], []
    for row in rows:
        article_id = int(row["id"])
        content_digest = _content_hash(row)
        override = str(row.get("manual_relevance_override") or "").strip().lower()
        common = {"article_id": article_id, "scope_hash": scope_digest,
                  "content_hash": content_digest, "rules_version": rules_version}
        if override in OVERRIDE_DECISIONS:
            results.append({**common, "decision": "accepted" if override == "include" else "excluded",
                            "similarity_score": row.get("similarity_score"), "source": "manual",
                            "explanation": row.get("manual_relevance_reason") or "Manual relevance override."})
            continue
        if mode == "off":
            results.append({**common, "decision": "accepted", "similarity_score": None,
                            "source": "screening_off", "explanation": "Article relevance screening is disabled."})
            continue

        cache_valid = (
            row.get("relevance_scope_hash") == scope_digest
            and row.get("relevance_content_hash") == content_digest
            and row.get("relevance_model") == config.EMBEDDING_MODEL
            and row.get("relevance_rules_version") == rules_version
            and row.get("relevance_decision") in DECISIONS
        )
        if cache_valid:
            results.append({**common, "decision": row["relevance_decision"],
                            "similarity_score": row.get("similarity_score"), "source": "cache",
                            "explanation": row.get("relevance_explanation") or "Cached screening decision."})
            continue
        pending_row = dict(row)
        pending_row["_force_reembed"] = bool(
            row.get("relevance_content_hash")
            and row.get("relevance_content_hash") != content_digest
        )
        pending.append((pending_row, common))

    article_vectors = (
        _article_vectors([row for row, _common in pending], should_cancel=should_cancel)
        if pending and project_vector else {}
    )
    for row, common in pending:
        article_vector = article_vectors.get(int(row["id"])) or []
        if not project_vector or not article_vector:
            results.append({**common, "decision": "needs_review", "similarity_score": None,
                            "source": "fallback", "explanation": "Embedding unavailable; included for review."})
            continue
        similarity = cosine_similarity(project_vector, article_vector)
        if similarity >= config.ARTICLE_RELEVANCE_ACCEPT_THRESHOLD:
            results.append({**common, "decision": "accepted", "similarity_score": similarity,
                            "source": "embedding", "explanation": "Embedding similarity is above the acceptance threshold."})
        elif similarity <= config.ARTICLE_RELEVANCE_EXCLUDE_THRESHOLD:
            results.append({**common, "decision": "excluded", "similarity_score": similarity,
                            "source": "embedding", "explanation": "Embedding similarity is below the exclusion threshold."})
        else:
            borderline.append((row, common, similarity))

    batch_size = config.ARTICLE_RELEVANCE_BATCH_SIZE
    for start in range(0, len(borderline), batch_size):
        if should_cancel and should_cancel():
            raise ScreeningCancelled()
        batch = borderline[start:start + batch_size]
        classified = _classify_borderline(project, [item[0] for item in batch])
        for row, common, similarity in batch:
            answer = classified[int(row["id"])]
            # An outage (LLMError, timeout, malformed JSON) falls back to
            # "uncertain" the same way a genuine ambiguous answer would - tag
            # it separately so it isn't cached as if the LLM had actually
            # weighed in (see _OUTAGE_SOURCES below).
            source = "llm_unavailable" if answer.get("unavailable") else "llm"
            results.append({**common, "decision": _decision_from_label(answer["relevance"]),
                            "similarity_score": similarity, "source": source,
                            "explanation": answer.get("explanation") or "Borderline semantic match."})

    results.sort(key=lambda item: item["article_id"])
    rows_by_id = {int(row["id"]): row for row in rows}
    for item in results:
        row = rows_by_id[item["article_id"]]
        # Cache and manual/off decisions don't need rewriting, and an outage
        # fallback (fallback/llm_unavailable) must never be written as a
        # cache-valid decision - it isn't a real answer, and persisting it
        # would permanently stop this article from being re-screened once
        # the model or LLM is working again (cache_valid above doesn't look
        # at source, only at decision/hash/model/rules_version).
        if item.get("source") not in {"cache", "manual", "screening_off", *_OUTAGE_SOURCES}:
            _persist_screening(project_id, row, item)
        manual_exclude = item.get("source") == "manual" and item["decision"] == "excluded"
        item["included"] = not manual_exclude and (mode != "enforce" or item["decision"] != "excluded")
    _record_run_screenings(run_id, project_id, results)
    return {
        "mode": mode,
        "results": results,
        "included_ids": [item["article_id"] for item in results if item["included"]],
        "screened": len(results),
        "included": sum(1 for item in results if item["included"]),
        "excluded": sum(1 for item in results if item["decision"] == "excluded"),
        "needs_review": sum(1 for item in results if item["decision"] == "needs_review"),
    }


def project_relevance_snapshot_ids(project_id: int, mode: str | None = None) -> list[int] | None:
    """The article ids evidence generation should see for this project right
    now - the whole corpus, minus whatever is genuinely excluded, not just
    this run's candidate set (screen_project_articles's `article_ids` only
    scopes what gets freshly *scored*; this scopes what the evidence
    *snapshot* admits, which has to cover articles this run never touched).

    A manual override always applies, regardless of mode - the same rule
    screen_project_articles enforces for a candidate. Absent an override, an
    `enforce`-mode article whose cached decision is currently valid (matches
    this project's scope hash and this article's own content hash) and
    `excluded` drops out too; `off`/`observe` never exclude via the cached
    decision, matching how they never exclude a candidate either.

    Read-only - no embedding or LLM calls - so calling this for the entire
    project on every run costs one query, not a re-screen. Returns None
    ("no filter, include everything") whenever there is provably nothing to
    exclude, so a caller can skip filtering rather than listing every id.
    """
    mode = str(mode or config.ARTICLE_RELEVANCE_SCREENING_MODE).strip().lower()
    if mode not in {"off", "observe", "enforce"}:
        mode = "observe"
    rows = db.fetch_all(
        """select ap.article_id,ap.relevance_decision,ap.relevance_scope_hash,
                  ap.relevance_content_hash,ap.relevance_model,ap.relevance_rules_version,
                  ap.manual_relevance_override,a.content_hash
             from article_projects ap join articles a on a.id=ap.article_id
            where ap.project_id=%s""",
        (int(project_id),),
    ) or []
    if not rows:
        return None
    has_override = any(
        str(row.get("manual_relevance_override") or "").strip().lower() in OVERRIDE_DECISIONS
        for row in rows
    )
    if mode != "enforce" and not has_override:
        return None

    project = get_project(project_id) or {}
    scope_digest = _scope_hash(project)
    rules_version = _rules_version()
    included_ids = []
    for row in rows:
        article_id = int(row["article_id"])
        override = str(row.get("manual_relevance_override") or "").strip().lower()
        if override == "exclude":
            continue
        if override == "include":
            included_ids.append(article_id)
            continue
        if mode == "enforce":
            cache_valid = (
                row.get("relevance_scope_hash") == scope_digest
                and row.get("relevance_content_hash") == str(row.get("content_hash") or "").strip()
                and row.get("relevance_model") == config.EMBEDDING_MODEL
                and row.get("relevance_rules_version") == rules_version
            )
            if cache_valid and row.get("relevance_decision") == "excluded":
                continue
        included_ids.append(article_id)
    return included_ids


def list_run_screenings(run_id: str, limit: int = 500) -> list[dict]:
    return db.fetch_all(
        """select pras.*,a.title,a.source,a.published
             from pipeline_run_article_screenings pras join articles a on a.id=pras.article_id
            where pras.run_id=%s
            order by pras.included asc,pras.decision,pras.similarity_score asc nulls first,pras.article_id
            limit %s""",
        (str(run_id), max(1, min(int(limit), 2000))),
    ) or []


def set_relevance_override(project_id: int, article_id: int, decision: str,
                           reason: str, user: dict) -> dict | None:
    decision = str(decision or "").strip().lower()
    if decision not in OVERRIDE_DECISIONS or not str(reason or "").strip():
        raise ValueError("Choose include or exclude and provide a reason.")
    return db.fetch_one(
        """update article_projects set manual_relevance_override=%s,
                  manual_relevance_reason=%s,manual_relevance_reviewer_id=%s,
                  manual_relevance_reviewer_name=%s,manual_relevance_updated_at=now()
             where project_id=%s and article_id=%s
             returning article_id,project_id,manual_relevance_override,manual_relevance_reason,
                       manual_relevance_reviewer_name,manual_relevance_updated_at""",
        (decision, str(reason).strip()[:2000], user.get("id"),
         user.get("username") or user.get("email"), int(project_id), int(article_id)),
    )
