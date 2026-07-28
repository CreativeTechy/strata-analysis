"""Backfill the signal-layer coordinates over already-stored articles.

Two passes, neither of which re-scrapes or calls a model:

  dates    `articles.published` (free text) -> `published_at` + `published_precision`
  stories  near-identical bodies -> `story_groups`, so prevalence can be counted
           per independent story instead of per URL

Both are batched, committed per batch, and resumable: progress lives in the data
(`published_precision is null`, `story_id is null`), not in a checkpoint file, so
an interrupted run is continued simply by running it again.

Usage
-----
    python backfill_signal_layer.py --dry-run       # report only, change nothing
    python backfill_signal_layer.py                 # both passes
    python backfill_signal_layer.py --only dates
    python backfill_signal_layer.py --only stories --limit 500
"""

from __future__ import annotations

import argparse
from collections import Counter

import db
import dedup
from timestamps import parse_published

# Deliberately not importing `config`: it pulls trafilatura (and its dateparser
# chain) in at module import time, which a database-only maintenance script has
# no reason to load.

DEFAULT_BATCH_SIZE = 500


def _require_column(table: str, column: str) -> bool:
    row = db.fetch_one(
        """
        select 1 as present
        from information_schema.columns
        where table_schema = 'public' and table_name = %s and column_name = %s
        """,
        (table, column),
    )
    return bool(row)


def _pending_dates() -> int:
    row = db.fetch_one(
        "select count(*)::int as total from articles where published_precision is null"
    )
    return int((row or {}).get("total") or 0)


def _pending_stories() -> int:
    row = db.fetch_one(
        "select count(*)::int as total from articles where story_id is null"
    )
    return int((row or {}).get("total") or 0)


def backfill_dates(batch_size: int = DEFAULT_BATCH_SIZE, limit: int | None = None, dry_run: bool = False) -> Counter:
    """Parse `published` into `published_at` for every row that has no precision yet."""
    stats = Counter()
    processed = 0

    while True:
        remaining = None if limit is None else max(0, limit - processed)
        if remaining == 0:
            break
        size = batch_size if remaining is None else min(batch_size, remaining)

        rows = db.fetch_all(
            """
            select id, published
            from articles
            where published_precision is null
            order by id
            limit %s
            """,
            (size,),
        )
        if not rows:
            break

        updates = []
        for row in rows:
            parsed, precision = parse_published(row.get("published"))
            stats[precision] += 1
            updates.append((parsed, precision, row["id"]))

        if not dry_run:
            with db.transaction() as cur:
                cur.executemany(
                    """
                    update articles
                       set published_at = %s,
                           published_precision = %s
                     where id = %s
                    """,
                    updates,
                )

        processed += len(rows)
        print(f"  dates: {processed} processed", flush=True)

        if dry_run:
            # Nothing was written, so the same rows would be selected forever.
            break

    stats["processed"] = processed
    return stats


def backfill_stories(batch_size: int = DEFAULT_BATCH_SIZE, limit: int | None = None, dry_run: bool = False) -> Counter:
    """Group articles into `story_groups` by body similarity.

    Ordered by id so the lowest-id member becomes a group's canonical article,
    which makes the grouping reproducible for a given corpus.
    """
    stats = Counter()
    processed = 0

    while True:
        remaining = None if limit is None else max(0, limit - processed)
        if remaining == 0:
            break
        size = batch_size if remaining is None else min(batch_size, remaining)

        rows = db.fetch_all(
            """
            select id, title, text, published_at
            from articles
            where story_id is null
            order by id
            limit %s
            """,
            (size,),
        )
        if not rows:
            break

        if dry_run:
            for row in rows:
                key = "singleton" if dedup.fingerprint(row.get("title"), row.get("text")) is None else "fingerprintable"
                stats[key] += 1
            processed += len(rows)
            print(f"  stories: {processed} inspected", flush=True)
            break

        # One transaction per batch: a group created early in the batch must be
        # visible to later members of the same batch, or duplicates inside a
        # single batch would each create their own group.
        assigned = 0
        with db.transaction() as cur:
            for row in rows:
                story_id, created = dedup.assign_story(cur, row, project_id=None)
                if story_id is None:
                    stats["failed"] += 1
                    continue
                stats["new_groups" if created else "joined_existing"] += 1
                cur.execute(
                    "update articles set story_id = %s where id = %s",
                    (story_id, row["id"]),
                )
                assigned += 1

        processed += len(rows)
        print(f"  stories: {processed} processed", flush=True)

        # Guard against a non-progressing loop: the selector keys on
        # `story_id is null`, so a batch that assigned nothing would be
        # re-selected identically forever.
        if assigned == 0:
            print("  stories: batch made no progress, stopping", flush=True)
            break

    stats["processed"] = processed
    return stats


def _report() -> None:
    total = int((db.fetch_one("select count(*)::int as t from articles") or {}).get("t") or 0)
    print(f"Articles stored: {total}")
    print(f"  needing a date pass:  {_pending_dates()}")
    print(f"  needing a story pass: {_pending_stories()}")

    precision = db.fetch_all(
        """
        select coalesce(published_precision, '(unset)') as precision, count(*)::int as total
        from articles group by 1 order by 2 desc
        """
    )
    if precision:
        print("  publish-date precision:")
        for row in precision:
            print(f"    {row['precision']:<10} {row['total']}")

    collapse = db.fetch_one(
        """
        select count(*)::int as grouped,
               count(distinct story_id)::int as stories
        from articles where story_id is not null
        """
    )
    if collapse and collapse["grouped"]:
        grouped, stories = int(collapse["grouped"]), int(collapse["stories"])
        saved = grouped - stories
        print(f"  syndication: {grouped} grouped articles -> {stories} independent stories "
              f"({saved} duplicate{'' if saved == 1 else 's'} collapsed)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--only", choices=("dates", "stories"), help="run a single pass")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--limit", type=int, help="stop after this many articles per pass")
    parser.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    args = parser.parse_args()

    if not db.get_database_url():
        print("DATABASE_URL is missing.")
        return 2

    missing = [
        f"articles.{column}"
        for column in ("published_at", "published_precision", "story_id")
        if not _require_column("articles", column)
    ]
    if missing:
        print(f"Missing columns: {', '.join(missing)} — run `python migrate.py` first.")
        return 2

    print("Before:")
    _report()
    print()

    if args.dry_run:
        print("Dry run — nothing will be written.\n")

    if args.only in (None, "dates"):
        print("Pass 1: publish dates")
        stats = backfill_dates(args.batch_size, args.limit, args.dry_run)
        print(f"  exact={stats['exact']} day={stats['day']} unknown={stats['unknown']} "
              f"(of {stats['processed']})\n")

    if args.only in (None, "stories"):
        print("Pass 2: syndication grouping")
        stats = backfill_stories(args.batch_size, args.limit, args.dry_run)
        if args.dry_run:
            print(f"  fingerprintable={stats['fingerprintable']} singletons={stats['singleton']} "
                  f"(of {stats['processed']})\n")
        else:
            print(f"  new_groups={stats['new_groups']} joined={stats['joined_existing']} "
                  f"failed={stats['failed']} (of {stats['processed']})\n")

    if not args.dry_run:
        print("After:")
        _report()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
