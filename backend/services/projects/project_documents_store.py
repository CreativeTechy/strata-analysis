"""Uploaded documents for offline opinion-monitor projects, and their
extracted text.

Files live under the same `storage/` volume the rest of the backend already
uses for durable, container-local files (see pipeline.py, prompt_loader.py),
keyed by project so a project's documents are easy to find and to delete
alongside it. Extraction itself (the per-chunk text/OCR split) is
services.documents.extraction.iter_chunks() - this module only orchestrates:
save the file, run extraction chunk by chunk as a background task, persist
each chunk plus a rolled-up summary on the document row.

Deliberately a separate table (and separate storage subfolder) from
services/competitors/competitor_documents_store.py rather than a shared one -
same shape, but keeping the two domains' documents apart means a change to
one pipeline can't accidentally affect the other's rows.

`extracted_text` (the join of every chunk, in order) is deliberately left out
of DOCUMENT_COLUMNS (used by list/get/upload/delete) - it can run to tens of
KB and nothing in the wizard needs the raw text, only whether extraction
succeeded. get_document_text() reads it separately for whatever later phase
actually consumes it. `extraction_error` is a summary of every chunk that
failed - always populated when any chunk failed, even if others succeeded, so
a partial failure is never silently hidden behind a success pill.

Once extraction produces usable text, process_document also kicks off
project_document_articles.generate_candidates() in the same background
task - `articles_status` (pending -> generating -> ready/failed, or 'skipped'
when extraction itself failed) is that step's own progress signal, tracked the
same way status/extraction_error track extraction.

A .json/.jsonl/.ndjson upload is already a list of articles, so it skips both
OCR and the LLM split: _process_record_document() parses it with
services.documents.records and writes one candidate per record. It still moves
the same document columns through the same states, so nothing downstream of
here - polling, the review step, materialization - has to know which kind of
file it came from.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import db
from services.documents import extraction as document_extraction
from services.documents import records as document_records
from services.projects import project_document_articles

# services/projects/project_documents_store.py -> services/projects ->
# services -> backend/. Mirrors pipeline.py's STORAGE_DIR convention.
BASE_DIR = Path(__file__).resolve().parents[2]
STORAGE_DIR = BASE_DIR.parent / "storage"
DOCUMENTS_DIR = STORAGE_DIR / "project_documents"

# pdf, images, word, excel, csv - the formats the offline wizard step offers -
# plus the already-split record formats (see document_records.RECORD_EXTENSIONS),
# which take the no-extraction, no-LLM path in process_document below.
ALLOWED_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".png", ".jpg", ".jpeg",
} | document_records.RECORD_EXTENSIONS

MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024  # 25 MB/file - generous for a single document, cheap to enforce.
MAX_FILES_PER_UPLOAD = 20

DOCUMENT_COLUMNS = """
    id, project_id, original_filename, storage_path, mime_type, size_bytes, status,
    extraction_method, extraction_error, total_chunks, processed_chunks,
    length(coalesce(extracted_text, '')) as text_length,
    articles_status, articles_error,
    created_at, extracted_at
"""

CHUNK_COLUMNS = "id, document_id, chunk_index, method, error, length(coalesce(text, '')) as text_length, created_at"

_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_filename(name: str) -> str:
    name = Path(name or "").name  # strip any directory components a client might send
    cleaned = _UNSAFE_CHARS.sub("_", name).strip("._") or "file"
    return cleaned[-150:]  # keep the on-disk name bounded regardless of what was uploaded


def extension_allowed(filename: str) -> bool:
    return Path(filename or "").suffix.lower() in ALLOWED_EXTENSIONS


def save_document(project_id: int, *, filename: str, content: bytes, mime_type: str | None) -> dict:
    """Write one file to disk under this project and record it. Caller validates first."""
    DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
    project_dir = DOCUMENTS_DIR / str(int(project_id))
    project_dir.mkdir(parents=True, exist_ok=True)

    disk_name = f"{uuid.uuid4().hex}_{_safe_filename(filename)}"
    disk_path = project_dir / disk_name
    disk_path.write_bytes(content)

    storage_path = str(disk_path.relative_to(STORAGE_DIR))
    record = db.fetch_one(
        f"""
        insert into project_documents (project_id, original_filename, storage_path, mime_type, size_bytes)
        values (%s, %s, %s, %s, %s)
        returning {DOCUMENT_COLUMNS}
        """,
        (int(project_id), (filename or "").strip() or disk_name, storage_path, mime_type, len(content)),
    )
    if not record:
        disk_path.unlink(missing_ok=True)
    return record


def process_document(document_id: int) -> None:
    """Read one document and record the outcome, by whichever path its format
    calls for. Meant to run as a FastAPI background task - OCR on a scanned PDF
    can take a while, well past what an upload request should block on, so
    total_chunks/processed_chunks on the row (updated after every chunk) is
    what the wizard polls for progress, not a separate run-tracking object
    (see list_documents).

    Both paths are wrapped in one failure guard on purpose. The wizard polls
    `status` and has no timeout, so *any* escape from here - a bad file, a
    schema constraint, a dead OCR binary - would otherwise leave the row on
    'processing' and the upload step reading forever with nothing to show. A
    document has to end somewhere terminal, with the reason attached.
    """
    document = get_document(document_id)
    if not document:
        return
    disk_path = STORAGE_DIR / document["storage_path"]
    filename = document["original_filename"]
    read = _process_record_document if document_records.is_record_file(filename) else _extract_document

    try:
        read(document, disk_path, filename)
    except Exception as exc:
        db.execute(
            """
            update project_documents
               set status = 'failed', extraction_error = %s,
                   articles_status = 'skipped', extracted_at = now()
             where id = %s
            """,
            (f"Could not read this file: {exc}", int(document_id)),
        )


def _extract_document(document: dict, disk_path: Path, filename: str) -> None:
    """The text/OCR branch of process_document: extract chunk by chunk, then
    hand the combined text to the LLM to split into candidates."""
    document_id = int(document["id"])
    total = document_extraction.total_chunks(disk_path, filename)
    db.execute(
        "update project_documents set status = 'processing', total_chunks = %s, processed_chunks = 0 where id = %s",
        (total, int(document_id)),
    )
    # Reprocessing (there's no UI path to trigger this today, but process_document
    # is safe to call again) must not collide with the unique (document_id, chunk_index).
    db.execute("delete from project_document_chunks where document_id = %s", (int(document_id),))

    texts: list[str] = []
    methods: set[str] = set()
    errors: list[str] = []
    processed = 0
    for chunk in document_extraction.iter_chunks(disk_path, filename):
        db.execute(
            """
            insert into project_document_chunks (document_id, chunk_index, text, method, error)
            values (%s, %s, %s, %s, %s)
            """,
            (int(document_id), chunk["index"], chunk["text"] or None, chunk["method"], chunk["error"]),
        )
        if chunk["error"]:
            errors.append(f"Part {chunk['index'] + 1}: {chunk['error']}")
        if chunk["text"]:
            texts.append(chunk["text"])
            methods.add(chunk["method"])

        processed += 1
        db.execute(
            "update project_documents set processed_chunks = %s where id = %s",
            (processed, int(document_id)),
        )

    combined_text = "\n\n".join(texts)
    method_summary = "mixed" if len(methods) > 1 else (next(iter(methods)) if methods else None)
    # 'processed' as soon as anything usable came out, even if some chunks
    # failed - extraction_error still carries every failure either way, so a
    # partial result is never mistaken for a clean one.
    status = "processed" if combined_text else "failed"

    db.execute(
        """
        update project_documents
           set extracted_text = %s, extraction_method = %s, extraction_error = %s,
               status = %s, extracted_at = now()
         where id = %s
        """,
        (combined_text or None, method_summary, " | ".join(errors) or None, status, int(document_id)),
    )

    if status != "processed":
        # Nothing to hand the LLM - a failed extraction has no candidates to skip
        # generating, so this is a terminal state, not "not started yet".
        db.execute("update project_documents set articles_status = 'skipped' where id = %s", (int(document_id),))
        return

    db.execute("update project_documents set articles_status = 'generating' where id = %s", (int(document_id),))
    try:
        project_document_articles.generate_candidates(document_id, document["project_id"], combined_text, filename)
        db.execute("update project_documents set articles_status = 'ready' where id = %s", (int(document_id),))
    except Exception as exc:
        db.execute(
            "update project_documents set articles_status = 'failed', articles_error = %s where id = %s",
            (str(exc), int(document_id)),
        )


def _process_record_document(document: dict, disk_path: Path, filename: str) -> None:
    """The .json/.jsonl branch of process_document: parse the file's records,
    then persist one candidate per record - no OCR, no LLM split.

    Deliberately writes the same columns an extracted document does (status,
    total_chunks/processed_chunks, extraction_method, extraction_error,
    articles_status/articles_error), so the wizard's polling, progress pills
    and failure messages need no notion of a second kind of document. There is
    one chunk because there is one parse: a records file has no pages that can
    fail independently, so per-record problems land in extraction_error.
    """
    document_id = int(document["id"])
    db.execute(
        "update project_documents set status = 'processing', total_chunks = 1, processed_chunks = 0 where id = %s",
        (document_id,),
    )
    db.execute("delete from project_document_chunks where document_id = %s", (document_id,))

    parsed = document_records.parse_records(disk_path, filename)
    text = document_records.render_text(parsed.records)
    error = parsed.error_summary
    if not parsed.records and not error:
        error = "No article records found in this file."
    # Same rule as extraction: usable output means 'processed' even when some
    # records were unusable, with every reason still on extraction_error.
    status = "processed" if parsed.records else "failed"

    db.execute(
        """
        insert into project_document_chunks (document_id, chunk_index, text, method, error)
        values (%s, 0, %s, 'records', %s)
        """,
        (document_id, text or None, error),
    )
    db.execute(
        """
        update project_documents
           set extracted_text = %s, extraction_method = 'records', extraction_error = %s,
               status = %s, processed_chunks = 1, extracted_at = now()
         where id = %s
        """,
        (text or None, error, status, document_id),
    )

    if status != "processed":
        db.execute("update project_documents set articles_status = 'skipped' where id = %s", (document_id,))
        return

    db.execute("update project_documents set articles_status = 'generating' where id = %s", (document_id,))
    try:
        project_document_articles.generate_candidates_from_records(
            document_id, document["project_id"], parsed.records
        )
    except Exception as exc:
        db.execute(
            "update project_documents set articles_status = 'failed', articles_error = %s where id = %s",
            (str(exc), document_id),
        )
        return

    # A cut-off import is reported rather than left to look complete - the
    # review step would otherwise show 500 candidates with nothing saying the
    # file held 40,000.
    note = None
    if parsed.truncated:
        note = (
            f"Imported the first {len(parsed.records):,} of {parsed.total_seen:,} records in this file. "
            "Split the file to import the rest."
        )
    db.execute(
        "update project_documents set articles_status = 'ready', articles_error = %s where id = %s",
        (note, document_id),
    )


def get_document_text(document_id: int) -> str | None:
    row = db.fetch_one("select extracted_text from project_documents where id = %s", (int(document_id),))
    return row["extracted_text"] if row else None


def list_chunks(document_id: int) -> list[dict]:
    return db.fetch_all(
        f"select {CHUNK_COLUMNS} from project_document_chunks where document_id = %s order by chunk_index",
        (int(document_id),),
    )


def list_documents(project_id: int) -> list[dict]:
    return db.fetch_all(
        f"select {DOCUMENT_COLUMNS} from project_documents where project_id = %s order by created_at desc",
        (int(project_id),),
    )


def get_document(document_id: int) -> dict | None:
    return db.fetch_one(
        f"select {DOCUMENT_COLUMNS} from project_documents where id = %s",
        (int(document_id),),
    )


def delete_document(document_id: int) -> bool:
    document = get_document(document_id)
    if not document:
        return False
    db.execute("delete from project_documents where id = %s", (int(document_id),))
    (STORAGE_DIR / document["storage_path"]).unlink(missing_ok=True)
    return True
