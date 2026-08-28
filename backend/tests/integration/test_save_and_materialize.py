"""Real-Postgres coverage for the save and approve/materialize paths - see
README.md for setup. Skipped entirely unless TEST_DATABASE_URL is set.

Each test creates its own project/document rows directly (the minimal
columns schema.sql requires), then drives the real application functions -
never hand-written SQL for the thing actually under test - so what's being
checked is the app's own code against the real schema, not a reimplementation
of it.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL", "").strip(),
    reason="Set TEST_DATABASE_URL to a scratch Postgres to run integration tests - see tests/integration/README.md",
)


def _create_project(db, name="Test Project", mode="sentiment"):
    row = db.fetch_one(
        "insert into projects (name, mode) values (%s, %s) returning id",
        (name, mode),
    )
    return int(row["id"])


class TestSaveArticlesRoundTrip:
    def test_a_saved_article_round_trips_and_links_to_its_project(self, clean_db):
        from services.articles.analysis_defaults import DEFAULT_ENRICHMENT
        from services.articles.store import save_articles

        project_id = _create_project(clean_db)
        article = {
            **DEFAULT_ENRICHMENT,
            "url": "https://example.com/one-article",
            "source": "Example Source",
            "title": "A Title",
            "text": "Body text.",
            "summary": "A summary.",
            "sentiment": "neutral",
            "analysis_status": "pending",
        }

        sent, by_source = save_articles([article], project_id=project_id)

        assert sent == 1
        assert by_source == {"Example Source": 1}

        row = clean_db.fetch_one("select id, title, text from articles where url = %s", (article["url"],))
        assert row is not None
        assert row["title"] == "A Title"
        assert row["text"] == "Body text."

        link = clean_db.fetch_one(
            "select 1 from article_projects where article_id = %s and project_id = %s",
            (row["id"], project_id),
        )
        assert link is not None

    def test_saving_the_same_url_again_upserts_instead_of_duplicating(self, clean_db):
        from services.articles.analysis_defaults import DEFAULT_ENRICHMENT
        from services.articles.store import save_articles

        project_id = _create_project(clean_db)
        url = "https://example.com/upsert-me"
        save_articles([{**DEFAULT_ENRICHMENT, "url": url, "title": "First pass", "text": "v1"}], project_id=project_id)
        save_articles([{**DEFAULT_ENRICHMENT, "url": url, "title": "Second pass", "text": "v2"}], project_id=project_id)

        rows = clean_db.fetch_all("select id, title from articles where url = %s", (url,))
        assert len(rows) == 1
        assert rows[0]["title"] == "Second pass"


class TestProjectDocumentApproveAndMaterialize:
    """The Step 1 transaction fix: set_status()'s materialize-then-record
    sequence must leave the candidate and the article it produced consistent
    even across repeated approvals."""

    def _create_document(self, db, project_id):
        row = db.fetch_one(
            """
            insert into project_documents (project_id, original_filename, storage_path)
            values (%s, 'test.txt', 'test/test.txt')
            returning id
            """,
            (project_id,),
        )
        return int(row["id"])

    def test_approving_a_candidate_materializes_exactly_one_article(self, clean_db):
        from services.projects import project_document_articles as pda

        project_id = _create_project(clean_db)
        document_id = self._create_document(clean_db, project_id)
        [candidate] = pda._insert_candidates(
            document_id, project_id, [{"title": "Candidate A", "summary": "s", "body": "candidate body"}]
        )

        approved = pda.set_status(candidate["id"], "approved")

        assert approved["status"] == "approved"
        assert approved["article_id"] is not None

        article = clean_db.fetch_one("select title, text from articles where id = %s", (approved["article_id"],))
        assert article["title"] == "Candidate A"
        assert article["text"] == "candidate body"

        link = clean_db.fetch_one(
            "select 1 from article_projects where article_id = %s and project_id = %s",
            (approved["article_id"], project_id),
        )
        assert link is not None

    def test_re_approving_is_idempotent_and_does_not_duplicate_the_article(self, clean_db):
        from services.projects import project_document_articles as pda

        project_id = _create_project(clean_db)
        document_id = self._create_document(clean_db, project_id)
        [candidate] = pda._insert_candidates(
            document_id, project_id, [{"title": "Candidate B", "summary": "s", "body": "candidate body"}]
        )

        first = pda.set_status(candidate["id"], "approved")
        second = pda.set_status(candidate["id"], "approved")

        assert first["article_id"] == second["article_id"]
        count = clean_db.fetch_one(
            "select count(*)::int as total from articles where id = %s", (first["article_id"],)
        )
        assert count["total"] == 1

    def test_rejecting_a_candidate_never_materializes_an_article(self, clean_db):
        from services.projects import project_document_articles as pda

        project_id = _create_project(clean_db)
        document_id = self._create_document(clean_db, project_id)
        [candidate] = pda._insert_candidates(
            document_id, project_id, [{"title": "Candidate C", "summary": "s", "body": "candidate body"}]
        )

        rejected = pda.set_status(candidate["id"], "rejected")

        assert rejected["status"] == "rejected"
        assert rejected["article_id"] is None
        total = clean_db.fetch_one("select count(*)::int as total from articles")
        assert total["total"] == 0


class TestCompetitorDocumentApproveAndMaterialize:
    """Same approve-and-materialize contract, competitor-study side."""

    def _create_document(self, db, project_id):
        row = db.fetch_one(
            """
            insert into competitor_documents (project_id, original_filename, storage_path)
            values (%s, 'test.txt', 'test/test.txt')
            returning id
            """,
            (project_id,),
        )
        return int(row["id"])

    def test_approving_a_candidate_materializes_exactly_one_article(self, clean_db):
        from services.competitors import competitor_document_articles as cda

        project_id = _create_project(clean_db, mode="competitor")
        document_id = self._create_document(clean_db, project_id)
        [candidate] = cda._insert_candidates(
            document_id, project_id, [{"title": "Finding A", "summary": "s", "body": "finding body"}]
        )

        approved = cda.set_status(candidate["id"], "approved")

        assert approved["status"] == "approved"
        assert approved["article_id"] is not None
        article = clean_db.fetch_one("select title from articles where id = %s", (approved["article_id"],))
        assert article["title"] == "Finding A"

    def test_re_approving_is_idempotent_and_does_not_duplicate_the_article(self, clean_db):
        from services.competitors import competitor_document_articles as cda

        project_id = _create_project(clean_db, mode="competitor")
        document_id = self._create_document(clean_db, project_id)
        [candidate] = cda._insert_candidates(
            document_id, project_id, [{"title": "Finding B", "summary": "s", "body": "finding body"}]
        )

        first = cda.set_status(candidate["id"], "approved")
        second = cda.set_status(candidate["id"], "approved")

        assert first["article_id"] == second["article_id"]
        count = clean_db.fetch_one(
            "select count(*)::int as total from articles where id = %s", (first["article_id"],)
        )
        assert count["total"] == 1
