"""Per-configured-source fetch diagnostics: read the side-channel file
scraper/spiders/source_rss.py writes on spider close, and turn it into
plain-language notes.

Kept separate from pipeline_runs.py (DB access) and pipeline.py (subprocess
orchestration) so this is a small set of pure functions - no DB, no
subprocess, easy to unit test and reused by both enrich.py (per-source rows)
and pipeline.py (the run's top-level message).
"""

import json
from pathlib import Path

DIAGNOSTICS_FILENAME = "source_diagnostics.json"


def load_source_diagnostics(workdir):
    """Read the list of per-source diagnostic entries the spider wrote, keyed
    by source_name: {source_name, source_url, http_status, network_blocked,
    note}. Missing/unreadable/empty is the common, expected case (nothing
    went wrong) - not an error, just an empty list."""
    if not workdir:
        return []
    path = Path(workdir) / DIAGNOSTICS_FILENAME
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def build_fetch_note(diagnostic, scraped_count):
    """Plain-language note for one source's row in the per-source breakdown.

    Priority: a network-level block or HTTP error is the most actionable
    thing to tell the user, then any other note the spider recorded (e.g. a
    connection failure, or a private/missing Telegram channel), then falling
    back to "0 articles" when the fetch itself didn't error but nothing came
    of it (e.g. a legitimately empty subreddit). "" for a healthy source."""
    diagnostic = diagnostic or {}
    if diagnostic.get("network_blocked"):
        return (
            f"Blocked (HTTP {diagnostic.get('http_status')}) - likely anti-bot protection "
            "against this server's network, not a problem with the source itself."
        )
    if diagnostic.get("http_status"):
        return f"HTTP {diagnostic['http_status']} - the source's page could not be fetched."
    if diagnostic.get("note"):
        return diagnostic["note"]
    if not scraped_count:
        return "Returned 0 articles."
    return ""


def summarize_notable_diagnostics(diagnostics):
    """Short addendum for the pipeline run's top-level message - only
    sources with a network-level issue (this runs before enrich.py, so it
    can't yet know which sources ended up with 0 articles - see
    build_fetch_note for the fuller per-source picture). "" if nothing to
    report."""
    notable = [d for d in (diagnostics or []) if d.get("http_status") or d.get("note")]
    if not notable:
        return ""
    parts = []
    for entry in notable:
        label = entry.get("source_name") or entry.get("source_url") or "unknown source"
        if entry.get("network_blocked"):
            parts.append(f"{label} (blocked, HTTP {entry.get('http_status')})")
        elif entry.get("http_status"):
            parts.append(f"{label} (HTTP {entry.get('http_status')})")
        else:
            parts.append(f"{label} ({entry.get('note')})")
    return f"{len(parts)} source(s) had fetch issues: " + "; ".join(parts) + "."
