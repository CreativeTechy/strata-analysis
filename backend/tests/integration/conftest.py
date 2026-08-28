"""Fixtures for real-Postgres integration tests - see README.md.

Every test in this directory is skipped automatically unless
TEST_DATABASE_URL is set (checked per-module via `pytestmark` in each test
file, not here, so `pytest --collect-only` never needs a live database just
to enumerate tests).
"""

from __future__ import annotations

import os

import pytest

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "").strip()


@pytest.fixture(scope="session")
def real_db():
    """Points config.DATABASE_URL / db's connection pool at TEST_DATABASE_URL
    and applies the schema. Session-scoped: migrate.run_on_startup() re-reads
    and re-applies schema.sql (it's idempotent, but there's no reason to pay
    for that once per test).

    Not autouse - only the tests that actually declare this fixture (or
    `clean_db`, which depends on it) touch the database at all, so an
    accidental import of this conftest without TEST_DATABASE_URL set never
    tries to connect anywhere.
    """
    import config
    import db
    import migrate
    from services.articles.store import _table_exists

    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    config.DATABASE_URL = TEST_DATABASE_URL
    db._pool = None  # drop any pool a mocked-config test opened earlier in this run
    # _table_exists() is lru_cached and reads config.DATABASE_URL - a False
    # cached from an earlier test module's mocked ("") config must not leak
    # into these tests believing real tables don't exist.
    _table_exists.cache_clear()
    migrate.run_on_startup()
    yield db
    db._pool = None


@pytest.fixture
def clean_db(real_db):
    """Truncates every table these tests touch before each test, so tests
    don't depend on execution order or leak state into each other."""
    real_db.execute(
        """
        truncate table
            projects, project_documents, project_document_articles,
            competitor_documents, competitor_document_articles,
            articles, article_projects
        restart identity cascade
        """
    )
    yield real_db
