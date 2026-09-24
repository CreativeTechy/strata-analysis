-- The GDELT coverage-check feature that populated coverage_evidence has been
-- removed. It stays in schema.sql only so a fresh database has the column
-- when migration 0024 (already applied elsewhere, and immutable per
-- migrations/README.md) runs its revalidation update against it. Once that
-- has happened, on both a fresh and an existing database, it is dead weight.
alter table public.articles
    drop column if exists coverage_evidence;
