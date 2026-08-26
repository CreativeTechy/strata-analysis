"""Turns a document's extracted text into reviewable "article" candidates.

competitor_document_extraction produces raw text per document; this module
asks the LLM to split that text into discrete, article-like items - a report
might describe three separate competitor moves, a spreadsheet export might
list many distinct mentions - so each can be reviewed and approved on its own
rather than the whole document becoming one undifferentiated blob.

Approved candidates are materialized into the same `articles` table scraped
pages use (services/articles/store.py's save_articles), linked into
`article_projects` exactly as a scraped article would be. That is deliberate:
competitor_analysis.generate_findings already turns project articles into
findings via article_projects + its own name-mention matching into
competitor_articles - an approved document candidate needs no separate
analysis path, it just needs to become a normal article.
"""

from __future__ import annotations

import json
import logging

import config
import db
from llm_client import chat_completion
from prompt_loader import load_prompt
from services.articles.analysis_defaults import DEFAULT_ENRICHMENT
from services.articles.store import save_articles

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = load_prompt("document_article_extraction_system_prompt.txt")
PROMPT_VERSION = "document-article-extraction-2026-08-06"

MAX_INPUT_CHARS = 12000  # matches embeddings.py's article-embedding-text cap
MAX_CANDIDATES = 20

CANDIDATE_COLUMNS = """
    id, document_id, project_id, title, summary, status, article_id, created_at, updated_at
"""


def _strip_fences(text: str) -> str:
    text = str(text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1] if "\n" in text else text
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()


def _ask_llm(text: str, filename: str) -> list[dict]:
    user_prompt = (
        f"Source document: {filename}\n\n"
        f"<document>\n{text[:MAX_INPUT_CHARS]}\n</document>\n\n"
        "Return the JSON now."
    )
    raw = chat_completion(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        max_tokens=3000,
        timeout=config.COMPETITOR_DOCUMENT_SPLIT_TIMEOUT_SECONDS,
        model=config.COMPETITOR_LLM_CHAT_MODEL,
        api_key=config.COMPETITOR_LLM_API_KEY,
        base_url=config.COMPETITOR_LLM_CHAT_BASE_URL,
        api_style=config.COMPETITOR_LLM_API_STYLE,
        reasoning_effort=config.COMPETITOR_LLM_REASONING_EFFORT,
        api_key_env_name=config.COMPETITOR_LLM_API_KEY_ENV_NAME,
    )
    parsed = json.loads(_strip_fences(raw))
    items = parsed.get("articles") if isinstance(parsed, dict) else parsed
    if not isinstance(items, list):
        return []

    cleaned = []
    for item in items[:MAX_CANDIDATES]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        body = str(item.get("body") or "").strip()
        summary = str(item.get("summary") or "").strip()
        if title and body:
            cleaned.append({"title": title[:300], "summary": (summary[:500] or None), "body": body})
    return cleaned


def generate_candidates(document_id: int, project_id: int, text: str, filename: str) -> list[dict]:
    """Calls the LLM and persists each result as a 'pending' candidate.

    Raises LLMError/json errors rather than swallowing them - the caller
    (competitor_documents_store.process_document) records articles_status
    from whether this raised, so a failure is visible rather than silently
    producing zero candidates that read the same as "nothing to extract"."""
    items = _ask_llm(text, filename)
    saved = []
    for item in items:
        record = db.fetch_one(
            f"""
            insert into competitor_document_articles (document_id, project_id, title, summary, body)
            values (%s, %s, %s, %s, %s)
            returning {CANDIDATE_COLUMNS}
            """,
            (int(document_id), int(project_id), item["title"], item["summary"], item["body"]),
        )
        if record:
            saved.append(record)
    return saved


def list_candidates(project_id: int) -> list[dict]:
    return db.fetch_all(
        f"select {CANDIDATE_COLUMNS} from competitor_document_articles where project_id = %s order by created_at",
        (int(project_id),),
    )


def get_candidate(candidate_id: int) -> dict | None:
    return db.fetch_one(
        """
        select id, document_id, project_id, title, summary, body, status, article_id, created_at, updated_at
        from competitor_document_articles where id = %s
        """,
        (int(candidate_id),),
    )


def _materialize(candidate: dict) -> int | None:
    """Turns an approved candidate into a real `articles` row via the same
    save_articles() scraped pages use, so it picks up article_projects
    linkage (and everything downstream of that) for free. Keyed on a synthetic
    but stable `url` - articles.url is unique/not-null and there is no real
    URL for an uploaded document - so re-approving is idempotent.

    Starts from DEFAULT_ENRICHMENT (analysis_defaults.py's own fallback for
    "no real analysis ran") rather than a bare dict: several `articles` columns are
    not-null with no python-side default (e.g. sentiment_low_confidence,
    analysis_attempt_count), and save_articles inserts whatever the caller
    passes - including an explicit NULL that overrides the column's own DB
    default - for any column in ARTICLE_MUTABLE_FIELDS. analysis_status is
    overridden to 'pending' rather than DEFAULT_ENRICHMENT's 'failed': nothing
    crashed here, sentiment/topic tagging just hasn't run yet."""
    document = db.fetch_one(
        "select original_filename from competitor_documents where id = %s",
        (int(candidate["document_id"]),),
    )
    url = f"document://competitor-document/{candidate['document_id']}/article/{candidate['id']}"
    # source_url identifies the *document*, not this one article, so every
    # article split out of the same file groups under it - that is what the
    # Articles page's source grouping and the keyword-existence document
    # filter read. `url` stays per-article because it is the unique key.
    article = {
        **DEFAULT_ENRICHMENT,
        "url": url,
        "source": (document or {}).get("original_filename") or "Uploaded document",
        "source_url": f"document://competitor-document/{candidate['document_id']}",
        "title": candidate["title"],
        "summary": candidate.get("summary") or "",
        "text": candidate["body"],
        "analysis_status": "pending",
        "analysis_error": None,
    }
    save_articles([article], project_id=candidate["project_id"])
    row = db.fetch_one("select id from articles where url = %s", (url,))
    return row["id"] if row else None


def set_status(candidate_id: int, status: str) -> dict | None:
    if status not in {"pending", "approved", "rejected"}:
        return None
    candidate = get_candidate(candidate_id)
    if not candidate:
        return None

    article_id = candidate.get("article_id")
    if status == "approved" and not article_id:
        article_id = _materialize(candidate)

    return db.fetch_one(
        f"""
        update competitor_document_articles
           set status = %s, article_id = %s
         where id = %s
        returning {CANDIDATE_COLUMNS}
        """,
        (status, article_id, int(candidate_id)),
    )


def approve_all(project_id: int) -> list[dict]:
    """Approves every still-pending candidate for a project. Already-decided
    ones (approved or rejected) are left alone - this is "approve the rest",
    not "undo any rejections"."""
    approved = []
    for candidate in list_candidates(project_id):
        if candidate["status"] == "pending":
            updated = set_status(candidate["id"], "approved")
            if updated:
                approved.append(updated)
    return approved
