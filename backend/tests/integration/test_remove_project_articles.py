"""Real-Postgres coverage for removing one project's articles (SM-101) - see
README.md for setup. Skipped entirely unless TEST_DATABASE_URL is set.

The contract being checked: removing project A's articles never touches
project B. An article only A had is deleted; an article A shares with B is
only unlinked from A; A's approved document candidates stop pointing at
removed articles (rejected, not "Analyzing..." forever); A's generated
summaries are cleared while B's stay; A's hand-entered idea-comparison facts
survive.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL", "").strip(),
    reason="Set TEST_DATABASE_URL to a scratch Postgres to run integration tests - see tests/integration/README.md",
)


def _create_project(db, name):
    row = db.fetch_one("insert into projects (name, mode) values (%s, 'sentiment') returning id", (name,))
    return int(row["id"])


def _save(url, project_id):
    from services.articles.analysis_defaults import DEFAULT_ENRICHMENT
    from services.articles.store import save_articles

    save_articles(
        [{**DEFAULT_ENRICHMENT, "url": url, "title": url, "text": f"Body of {url}", "analysis_status": "pending"}],
        project_id=project_id,
    )


def _article_id(db, url):
    row = db.fetch_one("select id from articles where url = %s", (url,))
    return int(row["id"]) if row else None


def _projects_of(db, url):
    rows = db.fetch_all(
        "select ap.project_id from article_projects ap join articles a on a.id = ap.article_id where a.url = %s",
        (url,),
    )
    return sorted(int(row["project_id"]) for row in rows)


@pytest.fixture
def two_projects(clean_db):
    db = clean_db
    db.execute("truncate table project_trend_summaries, idea_clusters restart identity cascade")
    a = _create_project(db, "Project A")
    b = _create_project(db, "Project B")
    _save("https://example.com/only-a", a)
    _save("https://example.com/shared", a)
    _save("https://example.com/shared", b)
    _save("https://example.com/only-b", b)
    return db, a, b


class TestRemoveProjectArticles:
    def test_preview_counts_what_would_be_deleted_vs_unlinked(self, two_projects):
        from services.articles.store import preview_project_article_removal

        _db, a, _b = two_projects
        assert preview_project_article_removal(a) == {
            "linked_articles": 2,
            "only_in_project": 1,
            "shared_with_other_projects": 1,
        }

    def test_only_this_projects_articles_are_removed(self, two_projects):
        from services.articles.store import remove_project_articles

        db, a, b = two_projects
        result = remove_project_articles(a, actor="tester")

        assert result == {
            "project_id": a,
            "articles_removed": 2,
            "articles_deleted": 1,
            "articles_kept_in_other_projects": 1,
            "candidates_rejected": 0,
        }
        assert _article_id(db, "https://example.com/only-a") is None
        assert _projects_of(db, "https://example.com/shared") == [b]
        assert _projects_of(db, "https://example.com/only-b") == [b]

    def test_approved_candidates_become_rejected_instead_of_pointing_at_nothing(self, two_projects):
        from services.articles.store import remove_project_articles

        db, a, _b = two_projects
        doc = db.fetch_one(
            "insert into project_documents (project_id, original_filename, storage_path) "
            "values (%s, 'a.pdf', 'a/a.pdf') returning id",
            (a,),
        )
        only_a = _article_id(db, "https://example.com/only-a")
        db.execute(
            "insert into project_document_articles (document_id, project_id, title, body, status, article_id) "
            "values (%s, %s, 'Only A', 'body', 'approved', %s)",
            (doc["id"], a, only_a),
        )

        result = remove_project_articles(a)

        assert result["candidates_rejected"] == 1
        candidate = db.fetch_one("select status, article_id from project_document_articles where project_id = %s", (a,))
        assert candidate == {"status": "rejected", "article_id": None}
        # The uploaded document itself is kept.
        assert db.fetch_one("select 1 from project_documents where id = %s", (doc["id"],)) is not None

    def test_generated_summaries_are_cleared_for_this_project_only(self, two_projects):
        from services.articles.store import remove_project_articles

        db, a, b = two_projects
        for project_id in (a, b):
            db.execute(
                "insert into project_trend_summaries (project_id, period, summary) values (%s, '30d', 'old summary')",
                (project_id,),
            )

        remove_project_articles(a)

        remaining = db.fetch_all("select project_id from project_trend_summaries order by project_id")
        assert [int(row["project_id"]) for row in remaining] == [b]

    def test_hand_entered_idea_comparison_facts_survive(self, two_projects):
        from services.articles.store import remove_project_articles

        db, a, _b = two_projects
        cluster = db.fetch_one(
            "insert into idea_clusters (project_id, idea) values (%s, 'Maintenance risk') returning id",
            (a,),
        )
        db.execute(
            "insert into idea_cluster_articles (idea_cluster_id, article_id) values (%s, %s)",
            (cluster["id"], _article_id(db, "https://example.com/shared")),
        )
        db.execute(
            "insert into idea_comparison_facts (project_id, idea_cluster_id, fact_text) values (%s, %s, 'Operator note')",
            (a, cluster["id"]),
        )

        remove_project_articles(a)

        assert db.fetch_all("select 1 from idea_cluster_articles where idea_cluster_id = %s", (cluster["id"],)) == []
        facts = db.fetch_all("select fact_text from idea_comparison_facts where project_id = %s", (a,))
        assert [row["fact_text"] for row in facts] == ["Operator note"]

    def test_a_project_with_no_articles_is_a_harmless_no_op(self, clean_db):
        from services.articles.store import remove_project_articles

        empty = _create_project(clean_db, "Empty")
        assert remove_project_articles(empty) == {
            "project_id": empty,
            "articles_removed": 0,
            "articles_deleted": 0,
            "articles_kept_in_other_projects": 0,
            "candidates_rejected": 0,
        }


class TestDeleteAllArticles:
    def test_deletes_everything_and_rejects_every_linked_candidate(self, two_projects):
        from services.articles.store import delete_all_articles

        db, a, _b = two_projects
        doc = db.fetch_one(
            "insert into project_documents (project_id, original_filename, storage_path) "
            "values (%s, 'a.pdf', 'a/a.pdf') returning id",
            (a,),
        )
        db.execute(
            "insert into project_document_articles (document_id, project_id, title, body, status, article_id) "
            "values (%s, %s, 'Only A', 'body', 'approved', %s)",
            (doc["id"], a, _article_id(db, "https://example.com/only-a")),
        )

        assert delete_all_articles(actor="tester") == 3
        assert db.fetch_all("select 1 from articles") == []
        candidate = db.fetch_one("select status, article_id from project_document_articles")
        assert candidate == {"status": "rejected", "article_id": None}


@pytest.mark.parametrize("global_delete", [False, True])
def test_inflight_analysis_blocks_removal_in_transaction(two_projects, global_delete):
    from services.articles.store import remove_project_articles, delete_all_articles, ArticleRemovalConflict
    db, a, _b = two_projects
    db.execute("insert into pipeline_runs (id, project_id, status) values ('removal-active', %s, 'running')", (a,))
    try:
        with pytest.raises(ArticleRemovalConflict):
            delete_all_articles() if global_delete else remove_project_articles(a)
        assert db.fetch_one("select count(*) as n from article_projects where project_id = %s", (a,))["n"] == 2
    finally:
        db.execute("delete from pipeline_runs where id = 'removal-active'")
