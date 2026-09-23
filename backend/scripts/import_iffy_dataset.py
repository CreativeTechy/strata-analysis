#!/usr/bin/env python3
"""Explicitly import the public Iffy.news publisher-concern dataset.

Operator-run tooling, never called by the running app - see
services/articles/iffy_dataset.py's module docstring for why that
distinction matters in this fork (nothing fetches from the network except
the configured LLM, and this is the one deliberate, explicit exception: an
operator choosing to download a public CC BY 4.0 dataset once).

Usage (from backend/):
    python scripts/import_iffy_dataset.py                 # download the default feed
    python scripts/import_iffy_dataset.py --url <feed>     # a different JSON feed
    python scripts/import_iffy_dataset.py --file dump.json # a previously downloaded file
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import requests

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import config  # noqa: E402,F401 - loads backend/.env before migration/database access
import migrate  # noqa: E402
from services.articles.iffy_dataset import (  # noqa: E402
    DEFAULT_FEED_URL,
    import_records,
)

MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024


def _download(url: str) -> list[dict]:
    # Streamed and capped as it arrives, not after: `requests.get(url)` with
    # no `stream=True` reads the entire body into `response.content` before
    # this function gets to look at its length, so the "20 MB safety limit"
    # would otherwise already have let an oversized (or runaway) response
    # fully buffer in memory before being rejected - the exact thing the cap
    # is meant to prevent.
    body = bytearray()
    with requests.get(url, timeout=60, stream=True) as response:
        response.raise_for_status()
        for chunk in response.iter_content(chunk_size=65536):
            body.extend(chunk)
            if len(body) > MAX_DOWNLOAD_BYTES:
                raise ValueError("Iffy response exceeds the 20 MB safety limit.")
    payload = json.loads(bytes(body).decode("utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Iffy response must be a JSON list.")
    return payload


def _read(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Iffy file must contain a JSON list.")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import the Iffy.news publisher-concern dataset into Postgres."
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--file", type=Path, help="Import a previously downloaded JSON file.")
    source.add_argument("--url", default=None, help="Download from this JSON endpoint.")
    args = parser.parse_args()

    applied = migrate.run()
    url = args.url or DEFAULT_FEED_URL
    records = _read(args.file) if args.file else _download(url)
    result = import_records(
        records,
        source_url=str(args.file.resolve()) if args.file else url,
    )
    if applied:
        print("Applied migrations: " + ", ".join(applied))
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    print("Attribution: Iffy.news Index of Unreliable Sources, CC BY 4.0 - https://iffy.news/index/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
