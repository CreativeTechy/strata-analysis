"""Forward-only schema migration runner.

Why this exists
---------------
`schema.sql` is mounted into Postgres as `docker-entrypoint-initdb.d`, which
Postgres executes *only* when the data directory is empty. Every schema change
after the first `docker compose up` therefore reached existing databases only by
someone pasting SQL by hand, and nothing recorded whether they had. This runner
replaces that with an ordered, checksummed, recorded sequence.

Model
-----
- `schema.sql` is version `0001_baseline`. It is idempotent and safe to re-run
  (every statement is `if not exists` / `or replace` / `on conflict do nothing`),
  so there is exactly one code path for all three real situations: a fresh
  volume where initdb already ran it, an existing database that predates this
  runner, and a bare database with no initdb hook at all.
- `migrations/NNNN_name.sql` are the forward migrations, applied in filename
  order, each inside its own transaction.
- `schema_migrations` records version + checksum. A file edited after being
  applied fails loudly instead of silently diverging environments.

Usage
-----
    python migrate.py            # apply pending migrations
    python migrate.py --status   # show applied/pending, apply nothing
    python migrate.py --verify   # exit non-zero if anything is pending/changed
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import db

BASE_DIR = Path(__file__).resolve().parent
BASELINE_FILE = BASE_DIR / "schema.sql"
MIGRATIONS_DIR = BASE_DIR / "migrations"
BASELINE_VERSION = "0001_baseline"

_FILENAME_RE = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")

_BOOTSTRAP = """
create table if not exists public.schema_migrations (
    version    text primary key,
    checksum   text not null,
    applied_at timestamptz not null default now()
);
"""


class MigrationError(RuntimeError):
    """Raised when the migration state on disk and in the database disagree."""


@dataclass(frozen=True)
class Migration:
    version: str
    path: Path

    @property
    def sql(self) -> str:
        return self.path.read_text(encoding="utf-8")

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


def discover() -> list[Migration]:
    """Return the baseline followed by every well-named migration, in order."""
    found = [Migration(BASELINE_VERSION, BASELINE_FILE)]

    if not MIGRATIONS_DIR.is_dir():
        return found

    numbered: list[tuple[str, Migration]] = []
    for path in sorted(MIGRATIONS_DIR.iterdir()):
        if path.name.startswith(".") or path.suffix != ".sql":
            continue
        match = _FILENAME_RE.match(path.name)
        if not match:
            raise MigrationError(
                f"Migration filename {path.name!r} must look like 0002_short_name.sql"
            )
        number = match.group(1)
        if number == "0001":
            raise MigrationError(
                f"{path.name} uses 0001, which is reserved for the schema.sql baseline"
            )
        numbered.append((number, Migration(path.stem, path)))

    duplicates = {n for n, _ in numbered if [x for x, _ in numbered].count(n) > 1}
    if duplicates:
        raise MigrationError(f"Duplicate migration numbers: {sorted(duplicates)}")

    found.extend(migration for _, migration in sorted(numbered, key=lambda item: item[0]))
    return found


def _applied() -> dict[str, str]:
    rows = db.fetch_all("select version, checksum from public.schema_migrations")
    return {str(row["version"]): str(row["checksum"]) for row in rows}


def _ensure_bootstrap() -> None:
    with db.transaction() as cur:
        cur.execute(_BOOTSTRAP)


def _apply(migration: Migration) -> None:
    """Run one migration and record it, atomically."""
    with db.transaction() as cur:
        cur.execute(migration.sql)
        cur.execute(
            """
            insert into public.schema_migrations (version, checksum)
            values (%s, %s)
            on conflict (version) do update set checksum = excluded.checksum,
                                                applied_at = now()
            """,
            (migration.version, migration.checksum),
        )


def plan() -> tuple[list[Migration], list[str]]:
    """Return (pending, drifted) without touching the database schema.

    `drifted` names migrations whose file changed after they were applied — the
    environments have diverged and a human has to decide what that means.
    """
    _ensure_bootstrap()
    applied = _applied()
    pending: list[Migration] = []
    drifted: list[str] = []

    for migration in discover():
        recorded = applied.get(migration.version)
        if recorded is None:
            pending.append(migration)
        elif recorded != migration.checksum:
            # The baseline is expected to keep evolving: it is idempotent and is
            # re-applied on every drift, which is how a fresh volume and an old
            # database converge. Real migrations must never change once applied.
            if migration.version == BASELINE_VERSION:
                pending.append(migration)
            else:
                drifted.append(migration.version)

    return pending, drifted


def run(*, dry_run: bool = False) -> list[str]:
    """Apply pending migrations. Returns the versions applied (or pending, if dry)."""
    if not db.get_database_url():
        raise MigrationError("DATABASE_URL is missing; cannot migrate.")

    pending, drifted = plan()
    if drifted:
        raise MigrationError(
            "These migrations were modified after being applied: "
            + ", ".join(drifted)
            + ". Add a new migration instead of editing an applied one."
        )

    if dry_run:
        return [migration.version for migration in pending]

    applied: list[str] = []
    for migration in pending:
        print(f"  applying {migration.version} ...", flush=True)
        _apply(migration)
        applied.append(migration.version)
    return applied


def run_on_startup() -> None:
    """Best-effort entry point for the API process.

    Raises on failure. A backend serving requests against a schema it does not
    match produces wrong answers silently, which is worse than not starting.
    """
    applied = run()
    if applied:
        print(f"Migrations applied: {', '.join(applied)}")
    else:
        print("Migrations: already up to date.")


def _print_status() -> int:
    pending, drifted = plan()
    applied = _applied()

    print("Applied:")
    for version in sorted(applied):
        print(f"  {version}")
    if not applied:
        print("  (none)")

    print("Pending:")
    for migration in pending:
        print(f"  {migration.version}")
    if not pending:
        print("  (none)")

    if drifted:
        print("Modified after apply (must be resolved by hand):")
        for version in drifted:
            print(f"  {version}")

    return 1 if (pending or drifted) else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply pending schema migrations.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--status", action="store_true", help="show state, apply nothing")
    group.add_argument(
        "--verify",
        action="store_true",
        help="exit non-zero when migrations are pending or drifted (for CI)",
    )
    args = parser.parse_args()

    if not db.get_database_url():
        print("DATABASE_URL is missing; nothing to migrate.", file=sys.stderr)
        return 2

    try:
        if args.status or args.verify:
            return _print_status()
        applied = run()
    except (MigrationError, RuntimeError) as exc:
        print(f"Migration failed: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # connection refused, permission denied, bad SQL
        print(f"Migration failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    print(f"Applied {len(applied)} migration(s)." if applied else "Already up to date.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
