# Integration tests

Everything under `tests/` outside this directory mocks `db` (or patches
`config.DATABASE_URL` to a fake value) — it proves the code *calls* the SQL
it means to, not that the SQL is correct against the real schema. These tests
do the opposite: they run the actual save/approve/materialize code paths
against a real Postgres, using the app's own migration runner
(`migrate.run_on_startup()`) to build the schema first.

## Running them

They're skipped automatically unless `TEST_DATABASE_URL` is set:

```
# Point this at a scratch database - these tests TRUNCATE every table they
# touch before each test. Never point it at a database you care about.
export TEST_DATABASE_URL=postgresql://strata:strata@localhost:5432/strata_test
python -m pytest tests/integration -q
```

The docker-compose `db` service (or any local/CI Postgres) works fine as long
as the target database is disposable. `migrate.run_on_startup()` applies
`schema.sql` plus every file in `migrations/`, so a brand-new empty database
is all that's required — no manual setup beyond creating it.

## What's covered

- `services/articles/store.save_articles()`: an article round-trips into
  `articles` and links into `article_projects` for the project it was saved
  for.
- `services/projects/project_document_articles.set_status()`: approving a
  candidate materializes it into a real `articles` row inside one
  transaction, and re-approving is idempotent (no duplicate row, same
  `article_id`) - the Step 1 transaction fix this exercises.
- `services/competitors/competitor_document_articles.set_status()`: the same
  approve-and-materialize flow on the competitor-study side.
