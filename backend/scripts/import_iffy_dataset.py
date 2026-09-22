#!/usr/bin/env python3
"""Explicitly import the public Iffy publisher dataset and reassess articles."""

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
from services.articles.source_reliability import (  # noqa: E402
    DEFAULT_FEED_URL,
    import_iffy_records,
)


MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024


def _download(url: str) -> list[dict]:
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    if len(response.content) > MAX_DOWNLOAD_BYTES:
        raise ValueError("Iffy response exceeds the 20 MB safety limit.")
    payload = response.json()
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
        description="Import Iffy.news publisher reliability data into Postgres."
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--file", type=Path, help="Import a previously downloaded JSON file.")
    source.add_argument("--url", default=None, help="Download from this JSON endpoint.")
    args = parser.parse_args()

    applied = migrate.run()
    url = args.url or DEFAULT_FEED_URL
    records = _read(args.file) if args.file else _download(url)
    result = import_iffy_records(
        records,
        source_url=str(args.file.resolve()) if args.file else url,
    )
    if applied:
        print("Applied migrations: " + ", ".join(applied))
    print(json.dumps(result, indent=2, sort_keys=True))
    print("Attribution: Iffy.news Index of Unreliable Sources, CC BY 4.0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
