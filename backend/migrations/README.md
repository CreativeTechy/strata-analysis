# Migrations

`../schema.sql` is the whole schema, applied as `0001_baseline`. This directory
holds the forward migrations layered on top of it, applied in filename order by
`../migrate.py`.

Everything through `0028` was squashed back into the baseline once the product
had no database left to preserve, so this directory starts empty again. Add the
next one as `0002_short_name.sql`.

## Rules

- Name files `NNNN_short_name.sql` — four digits, then lowercase and
  underscores. `0001` is reserved for the baseline. Anything else is rejected by
  the runner rather than silently skipped.
- **Never edit a migration once it has been applied anywhere.** The runner
  checksums each file and fails loudly on a mismatch, because a changed file
  means two environments silently disagree about their schema. Add a new
  migration instead.
- Prefer additive, idempotent statements (`add column if not exists`,
  `create index if not exists`). Each file runs in its own transaction.
- Fold a migration into `schema.sql` only when squashing, and only when no
  database that matters is still on the old shape. `schema.sql` is the one file
  that *is* allowed to change: it is idempotent and gets re-applied whenever its
  checksum moves, which is how a fresh volume and an existing database converge.

## Commands

Run from `backend/`:

    python migrate.py            # apply pending migrations
    python migrate.py --status   # show applied/pending, apply nothing
    python migrate.py --verify   # exit non-zero if anything is pending/changed
