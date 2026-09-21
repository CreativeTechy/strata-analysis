"""Fast, cached article-to-project relevance screening.

Embeddings handle clear matches and clear misses. Only the middle band reaches
the configured chat model, in batches. Missing models and malformed responses
fail open as ``needs_review`` so screening can reduce work without silently
discarding material.
"""

from __future__ import annotations

import hashlib
import json
import logging

import config
import db
from embeddings import build_project_embedding_text, cosine_similarity, get_embeddings
from llm_client import LLMError, chat_completion
from psycopg.types.json import Jsonb
from services.projects.projects_store import get_project, persist_project_embedding_for_id

logger = logging.getLogger(__name__)

RULES_VERSION = "article-relevance-v1"
DECISIONS = {"accepted", "excluded", "needs_review"}
OVERRIDE_DECISIONS = {"include", "exclude"}


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


def _article_vectors(rows: list[dict]) -> dict[int, list[float]]:
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
            {"id": int(row["id"]), "title": row.get("title"), "excerpt": str(row.get("text") or "")[:3500]}
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
            max_tokens=max(600, len(rows) * 100),
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
         config.EMBEDDING_MODEL, RULES_VERSION, int(project_id), int(row["id"])),
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
                 item["scope_hash"], item["content_hash"], RULES_VERSION, config.EMBEDDING_MODEL)
                for item in results
            ],
        )


def screen_project_articles(project_id: int, run_id: str, mode: str | None = None) -> dict:
    mode = str(mode or config.ARTICLE_RELEVANCE_SCREENING_MODE).strip().lower()
    if mode not in {"off", "observe", "enforce"}:
        mode = "observe"
    rows = db.fetch_all(
        """select a.id,a.title,a.text,a.content_hash,a.embedding_json,a.embedding_model,
                  a.embedding_source,ap.similarity_score,ap.relevance_decision,
                  ap.relevance_explanation,ap.relevance_source,ap.relevance_scope_hash,
                  ap.relevance_content_hash,ap.relevance_model,ap.relevance_rules_version,
                  ap.manual_relevance_override,ap.manual_relevance_reason
             from articles a join article_projects ap on ap.article_id=a.id
            where ap.project_id=%s order by a.id""",
        (int(project_id),),
    ) or []
    if not rows:
        return {"mode": mode, "results": [], "included_ids": [], "screened": 0,
                "included": 0, "excluded": 0, "needs_review": 0}

    project = get_project(project_id) or {}
    scope_digest = _scope_hash(project)
    project_vector = _project_vector(project) if mode != "off" and project.get("id") else []
    results, pending, borderline = [], [], []
    for row in rows:
        article_id = int(row["id"])
        content_digest = _content_hash(row)
        override = str(row.get("manual_relevance_override") or "").strip().lower()
        common = {"article_id": article_id, "scope_hash": scope_digest, "content_hash": content_digest}
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
            and row.get("relevance_rules_version") == RULES_VERSION
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

    article_vectors = _article_vectors([row for row, _common in pending]) if pending and project_vector else {}
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
        batch = borderline[start:start + batch_size]
        classified = _classify_borderline(project, [item[0] for item in batch])
        for row, common, similarity in batch:
            answer = classified[int(row["id"])]
            results.append({**common, "decision": _decision_from_label(answer["relevance"]),
                            "similarity_score": similarity, "source": "llm",
                            "explanation": answer.get("explanation") or "Borderline semantic match."})

    results.sort(key=lambda item: item["article_id"])
    rows_by_id = {int(row["id"]): row for row in rows}
    for item in results:
        row = rows_by_id[item["article_id"]]
        if item.get("source") not in {"cache", "manual", "screening_off"}:
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
