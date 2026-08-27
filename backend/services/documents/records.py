"""Article records uploaded as a document: .json / .jsonl / .ndjson.

The sibling of extraction.py. Where that module turns a PDF, spreadsheet or
scan into raw text for the LLM to split into candidate articles, this one
handles files that are *already* split - a JSONL export from
GET /api/articles/export, or any hand-made JSON list of items - so those skip
the LLM entirely: each record is one candidate article, no splitting to guess
at and no model call to pay for.

Accepting these here rather than only on the Articles page's import button is
what lets an export go through the same review-then-approve step every other
uploaded document does, keeping one path into `articles` for a project instead
of two.

Shapes accepted, so that "the file I have" usually just works:

* `.jsonl` / `.ndjson` - one JSON object per line (blank lines ignored).
* `.json` - a list of objects, a single object, or an envelope object whose
  `articles`/`records`/`items`/`data` key holds the list. A `.json` file that
  is really JSONL, or a `.jsonl` file that is really a JSON array, is read the
  way its *content* says rather than being rejected on its extension.

Per record, the title/body/summary keys are matched loosely (`title` or
`headline` or ..., `text` or `body` or ...) because the second source of these
files is whatever the operator exported out of some other tool. `url`,
`author`, `published` and `source_run_snapshot` are carried through as
metadata - everything else in a record (including any analysis fields an
export carries) is deliberately dropped, since a candidate is re-analyzed by
this app's own pipeline once approved.

`source_run_snapshot` is scraper-app's collection provenance for this
article - `{id, started_at, project_id}` naming the pipeline run that first
scraped it, in scraper-app's own database (see that repo's
services/articles/store.py). It rides through untouched so an approved
candidate can carry it onto the real `articles` row (see
services/projects/project_document_articles.py's `_materialize()`), the same
way `url`/`author`/`published` already do; a record from anywhere else
(a hand-made JSON list, another tool's export) simply won't have it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

RECORD_EXTENSIONS = {".json", ".jsonl", ".ndjson"}

# Every record becomes a row in the review step's un-paginated candidate list,
# so a 50,000-line export has to be cut off somewhere or that step becomes
# unusable. The remainder is reported, never silently dropped - see
# ParsedRecords.truncated.
MAX_RECORDS = 500

# A file with the wrong shape would otherwise report one error per line.
MAX_ERRORS_REPORTED = 5

# Loose key matching, first hit wins. Ordered most- to least-specific so an
# export carrying both `summary` and `description` uses the former.
TITLE_KEYS = ("title", "headline", "subject", "name")
BODY_KEYS = ("text", "body", "content", "article_text", "full_text", "message", "comment")
SUMMARY_KEYS = ("summary", "description", "excerpt", "snippet")
URL_KEYS = ("url", "link", "permalink")
AUTHOR_KEYS = ("author", "byline", "writer")
PUBLISHED_KEYS = ("published", "published_at", "date", "published_date", "created_at")
SOURCE_RUN_SNAPSHOT_KEY = "source_run_snapshot"

# The keys an envelope object may hide the actual list behind.
LIST_KEYS = ("articles", "records", "items", "data", "results")

TITLE_MAX_CHARS = 300
SUMMARY_MAX_CHARS = 500
# Title derived from the body when a record has none - long enough to tell two
# respondents' answers apart in the review list, short enough to stay one line.
DERIVED_TITLE_CHARS = 120


@dataclass
class ParsedRecords:
    """What one records file yielded. `errors` is per-record and capped;
    `total_seen` counts every usable-shaped record in the file including the
    ones past MAX_RECORDS, so the caller can say how many were left behind."""

    records: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    total_seen: int = 0
    skipped: int = 0
    truncated: bool = False

    @property
    def error_summary(self) -> str | None:
        parts = list(self.errors)
        hidden = self.skipped - len(self.errors)
        if hidden > 0:
            parts.append(f"...and {hidden:,} more unusable record(s)")
        return " | ".join(parts) or None


def is_record_file(filename: str) -> bool:
    return Path(filename or "").suffix.lower() in RECORD_EXTENSIONS


def _first_string(item: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        # An exported timestamp can arrive as a number; anything else (list,
        # dict, None) is not a value these fields can use.
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
    return ""


def _source_run_snapshot(item: dict) -> dict | None:
    """scraper-app's collection-run provenance for this record, if the
    export it came from carried one - see the module docstring. Validated
    just enough to keep garbage out of record_metadata: a dict with a
    non-empty `id` is the shape scraper-app's store.py actually produces."""
    value = item.get(SOURCE_RUN_SNAPSHOT_KEY)
    if not isinstance(value, dict) or not value.get("id"):
        return None
    return {
        "id": str(value.get("id")),
        "started_at": value.get("started_at"),
        "project_id": value.get("project_id"),
    }


def _derive_title(body: str) -> str:
    first_line = next((line.strip() for line in body.splitlines() if line.strip()), "")
    if len(first_line) <= DERIVED_TITLE_CHARS:
        return first_line
    return first_line[:DERIVED_TITLE_CHARS].rsplit(" ", 1)[0] + "..."


def _to_record(item: dict) -> dict | None:
    """One raw record -> the candidate shape, or None if it holds no text.

    `body` is not-null on project_document_articles, so a record with only a
    title or only a summary still gets a body - the alternative would be
    dropping a row the operator can see in their own file."""
    title = _first_string(item, TITLE_KEYS)
    body = _first_string(item, BODY_KEYS)
    summary = _first_string(item, SUMMARY_KEYS)
    if not body:
        body = summary or title
    if not body:
        return None
    if not title:
        title = _derive_title(body)

    metadata = {
        "url": _first_string(item, URL_KEYS),
        "author": _first_string(item, AUTHOR_KEYS),
        "published": _first_string(item, PUBLISHED_KEYS),
        "source_run_snapshot": _source_run_snapshot(item),
    }
    return {
        "title": title[:TITLE_MAX_CHARS],
        "summary": summary[:SUMMARY_MAX_CHARS] or None,
        "body": body,
        "metadata": {key: value for key, value in metadata.items() if value},
    }


def _decode(path: Path) -> str:
    # errors="replace" rather than a hard failure: one bad byte in a 20MB
    # export should cost that one character, not the whole upload.
    return path.read_bytes().decode("utf-8-sig", errors="replace")


def _line_items(text: str):
    for line_number, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            yield f"Line {line_number}", json.loads(line)
        except json.JSONDecodeError:
            yield f"Line {line_number}", "is not valid JSON"


def _iter_raw(text: str, suffix: str):
    """Yield (label, item) per record, where a `str` item is that record's own
    parse error rather than a record.

    Content wins over extension - a `.json` holding newline-delimited objects
    and a `.jsonl` holding an array are both things operators actually have.
    """
    file_error = None
    if suffix == ".json" or text.lstrip()[:1] == "[":
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            file_error = f"is not valid JSON ({exc.msg}, line {exc.lineno})"
        else:
            if isinstance(parsed, dict):
                for key in LIST_KEYS:
                    if isinstance(parsed.get(key), list):
                        parsed = parsed[key]
                        break
                else:
                    parsed = [parsed]  # a single article object
            if not isinstance(parsed, list):
                yield "File", "holds a single JSON value, not article records"
                return
            for index, item in enumerate(parsed, start=1):
                yield f"Record {index}", item
            return

    # Line-delimited: the .jsonl/.ndjson default, and the fallback for a file
    # the whole-file parse just rejected - which is what a .json that really
    # holds one object per line looks like.
    lines = list(_line_items(text))
    if file_error and not any(isinstance(item, dict) for _, item in lines):
        # Genuinely malformed: one file-level reason beats one error per line.
        yield "File", file_error
        return
    yield from lines


def parse_records(path: Path, filename: str) -> ParsedRecords:
    """Read one .json/.jsonl/.ndjson file into candidate-article records.

    Never raises for content reasons: a file that is entirely unusable comes
    back with no records and the reasons in `errors`, which the caller records
    on the document row the same way an extraction failure is recorded."""
    result = ParsedRecords()
    suffix = Path(filename or path.name).suffix.lower()
    try:
        text = _decode(path)
    except OSError as exc:
        result.errors.append(f"Could not read the file: {exc}")
        return result

    def note(message: str) -> None:
        result.skipped += 1
        if len(result.errors) < MAX_ERRORS_REPORTED:
            result.errors.append(message)

    for label, item in _iter_raw(text, suffix):
        if isinstance(item, str):  # this line's/file's own parse error
            note(f"{label} {item}")
            continue
        if not isinstance(item, dict):
            note(f"{label} is not a JSON object")
            continue
        result.total_seen += 1
        if len(result.records) >= MAX_RECORDS:
            result.truncated = True
            continue
        record = _to_record(item)
        if record is None:
            note(f"{label} has no title or text")
            continue
        result.records.append(record)

    return result


def render_text(records: list[dict]) -> str:
    """The document's `extracted_text` for a records file - the same thing
    extraction.py produces for a PDF, so anything reading a document's text
    later sees article text rather than raw JSON."""
    return "\n\n".join(f"{record['title']}\n{record['body']}" for record in records)
