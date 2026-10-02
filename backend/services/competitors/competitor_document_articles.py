"""Turns a document's extracted text into "article" candidates.

competitor_document_extraction produces raw text per document; this module
asks the LLM to split that text into discrete, article-like items - a report
might describe three separate competitor moves, a spreadsheet export might
list many distinct mentions - so each becomes its own row rather than the
whole document turning into one undifferentiated blob.
competitor_documents_store auto-approves every candidate right after it's
generated, so in practice a candidate is materialized before anyone has
looked at it; excluding one is a delete on the Articles page after the fact,
not a reject beforehand. The pending/approved/rejected status and
set_status()/approve_all() below still work exactly as they did when a human
drove them - nothing here assumes the caller is the auto-approve path.

A .json/.jsonl document arrives already split, so it skips the LLM entirely:
generate_candidates_from_records() persists one candidate per record (parsed
by services/documents/records.py) through the same table, review step and
materialization as an LLM-split one. The only difference downstream is
`record_metadata` - the url/author/published the record carried, which
_materialize() puts back on the article.

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

from psycopg.types.json import Jsonb

import config
import db
from llm_client import chat_completion
from prompt_loader import load_prompt
from services.articles.analysis_defaults import DEFAULT_ENRICHMENT
from services.articles.store import save_articles

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = load_prompt("document_article_extraction_system_prompt.txt")
PROMPT_VERSION = "document-article-extraction-2026-08-06"

MAX_INPUT_CHARS = 12000  # per-chunk LLM input size, matches embeddings.py's article-embedding-text cap
MAX_CANDIDATES_PER_CHUNK = 20
MAX_CANDIDATES = 100  # across the whole document, once it's been split into MAX_INPUT_CHARS-sized chunks

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


def _split_into_chunks(text: str, max_chars: int) -> list[str]:
    """Breaks text into MAX_INPUT_CHARS-sized windows so a document longer than
    one LLM call's input isn't silently cut down to its first window - every
    window gets its own _ask_llm() call in generate_candidates(). Prefers a
    blank-line boundary near the end of a window over a hard cut, so an
    article isn't split in half across two chunks more often than necessary."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    chunks = []
    start = 0
    length = len(text)
    while start < length:
        end = min(start + max_chars, length)
        if end < length:
            boundary = text.rfind("\n\n", start + max_chars // 2, end)
            if boundary != -1:
                end = boundary
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        start = end
    return chunks


def _ask_llm(text: str, filename: str, *, part: int | None = None, total_parts: int | None = None) -> list[dict]:
    part_note = f" (part {part} of {total_parts})" if total_parts and total_parts > 1 else ""
    user_prompt = (
        f"Source document: {filename}{part_note}\n\n"
        f"<document>\n{text}\n</document>\n\n"
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
    for item in items[:MAX_CANDIDATES_PER_CHUNK]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        body = str(item.get("body") or "").strip()
        summary = str(item.get("summary") or "").strip()
        if title and body:
            cleaned.append({"title": title[:300], "summary": (summary[:500] or None), "body": body})
    return cleaned


def generate_candidates(document_id: int, project_id: int, text: str, filename: str) -> dict:
    """Splits text into MAX_INPUT_CHARS windows, calls the LLM on each in turn,
    and persists every result as a 'pending' candidate - so a document longer
    than one LLM call's input still gets split end to end instead of only its
    first ~12,000 characters.

    Returns {"candidates": [...], "truncated": bool, "chunks_processed": int}
    rather than a bare list - "truncated" is true when MAX_CANDIDATES (the
    overall per-document cap) was hit before every chunk had been processed,
    which the caller (competitor_documents_store._extract_document) surfaces
    as an articles_error note, the same way a .jsonl import's own record cap
    does.

    Raises LLMError/json errors rather than swallowing them - the caller
    records articles_status from whether this raised, so a failure is visible
    rather than silently producing zero candidates that read the same as
    "nothing to extract"."""
    chunks = _split_into_chunks(text, MAX_INPUT_CHARS)
    items: list[dict] = []
    truncated = False
    chunks_processed = 0
    for index, chunk in enumerate(chunks, start=1):
        if len(items) >= MAX_CANDIDATES:
            truncated = True
            break
        chunks_processed = index
        chunk_items = _ask_llm(chunk, filename, part=index, total_parts=len(chunks))
        room = MAX_CANDIDATES - len(items)
        if len(chunk_items) > room:
            chunk_items = chunk_items[:room]
            truncated = True
        items.extend(chunk_items)

    return {
        "candidates": _insert_candidates(document_id, project_id, items),
        "truncated": truncated or chunks_processed < len(chunks),
        "chunks_processed": chunks_processed,
        "total_chunks": len(chunks),
    }


def generate_candidates_from_records(document_id: int, project_id: int, records: list[dict]) -> list[dict]:
    """Persists already-split records (services/documents/records.py) as
    'pending' candidates - the no-LLM counterpart of generate_candidates().

    Same table, same review step, same materialization; the records just carry
    `metadata` (url/author/published) that an LLM split has no equivalent of."""
    return _insert_candidates(document_id, project_id, records)


def _insert_candidates(document_id: int, project_id: int, items: list[dict]) -> list[dict]:
    saved = []
    for item in items:
        metadata = item.get("metadata") or None
        record = db.fetch_one(
            f"""
            insert into competitor_document_articles (document_id, project_id, title, summary, body, record_metadata)
            values (%s, %s, %s, %s, %s, %s)
            returning {CANDIDATE_COLUMNS}
            """,
            (
                int(document_id),
                int(project_id),
                item["title"],
                item["summary"],
                item["body"],
                Jsonb(metadata) if metadata else None,
            ),
        )
        if record:
            saved.append(record)
    return saved


def list_candidates(project_id: int, document_ids: list[int] | None = None) -> list[dict]:
    document_filter = "" if document_ids is None else "and document_id = any(%s)"
    params = (int(project_id),) if document_ids is None else (int(project_id), document_ids)
    return db.fetch_all(
        f"select {CANDIDATE_COLUMNS} from competitor_document_articles where project_id = %s {document_filter} order by created_at",
        params,
    )


def get_candidate(candidate_id: int) -> dict | None:
    return db.fetch_one(
        """
        select id, document_id, project_id, title, summary, body, status, article_id,
               record_metadata, created_at, updated_at
        from competitor_document_articles where id = %s
        """,
        (int(candidate_id),),
    )


def _materialize(candidate: dict, cur) -> int | None:
    """Turns an approved candidate into a real `articles` row via the same
    save_articles() scraped pages use, so it picks up article_projects
    linkage (and everything downstream of that) for free. Keyed on a synthetic
    but stable `url` - articles.url is unique/not-null and there is no real
    URL for an uploaded document - so re-approving is idempotent. A candidate
    that came from a .json/.jsonl record keeps that record's own url instead,
    which is both stable in the same way and what makes re-importing an export
    update the article it came from rather than duplicating it.

    Starts from DEFAULT_ENRICHMENT (analysis_defaults.py's own fallback for
    "no real analysis ran") rather than a bare dict: several `articles` columns are
    not-null with no python-side default (e.g. sentiment_low_confidence,
    analysis_attempt_count), and save_articles inserts whatever the caller
    passes - including an explicit NULL that overrides the column's own DB
    default - for any column in ARTICLE_MUTABLE_FIELDS. analysis_status is
    overridden to 'pending' rather than DEFAULT_ENRICHMENT's 'failed': nothing
    crashed here, sentiment/topic tagging just hasn't run yet.

    Runs on the caller's transaction (`cur`, from set_status()'s
    db.transaction()) for its own two direct queries, so a failure here or in
    the status/article_id write right after it rolls both back together
    instead of leaving a materialized article whose candidate row still shows
    'pending'/no article_id. save_articles() below still commits on its own
    connection - its insert is a single idempotent upsert-by-url, so retrying
    a half-finished approval re-runs it safely rather than duplicating the row."""
    cur.execute(
        "select original_filename from competitor_documents where id = %s",
        (int(candidate["document_id"]),),
    )
    document = cur.fetchone()
    metadata = candidate.get("record_metadata") or {}
    url = str(metadata.get("url") or "").strip() or (
        f"document://competitor-document/{candidate['document_id']}/article/{candidate['id']}"
    )
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
        # From a .json/.jsonl record only; an LLM split has neither. `published`
        # stays the record's raw string - save_articles() is the one place that
        # parses it into published_at/published_precision, and an analysis run's
        # date-window filter keys off that, so a record's date must survive here.
        "author": metadata.get("author") or None,
        "published": metadata.get("published") or None,
        "source_run_snapshot": metadata.get("source_run_snapshot") or None,
        "source_provenance": metadata.get("source_provenance") or None,
        "analysis_status": "pending",
        "analysis_error": None,
    }
    save_articles([article], project_id=candidate["project_id"])
    cur.execute("select id from articles where url = %s", (url,))
    row = cur.fetchone()
    return row["id"] if row else None


def set_status(candidate_id: int, status: str) -> dict | None:
    """Materializing and recording the result on this candidate row happen in
    one transaction: an approval that fails partway must not leave the
    candidate still 'pending' while an article already exists for it (or vice
    versa)."""
    if status not in {"pending", "approved", "rejected"}:
        return None
    candidate = get_candidate(candidate_id)
    if not candidate:
        return None

    article_id = candidate.get("article_id")
    with db.transaction() as cur:
        if status == "approved" and not article_id:
            article_id = _materialize(candidate, cur)
        cur.execute(
            f"""
            update competitor_document_articles
               set status = %s, article_id = %s
             where id = %s
            returning {CANDIDATE_COLUMNS}
            """,
            (status, article_id, int(candidate_id)),
        )
        return cur.fetchone()


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


def approve_for_documents(project_id: int, document_ids: list[int]) -> list[dict]:
    """Include only these documents' pending candidates; analysis is explicit."""
    wanted = {int(document_id) for document_id in document_ids}
    if not wanted:
        return []
    approved = []
    for candidate in list_candidates(project_id, document_ids=sorted(wanted)):
        if candidate["status"] == "pending" and int(candidate["document_id"]) in wanted:
            updated = set_status(candidate["id"], "approved")
            if updated:
                approved.append(updated)
    return approved
