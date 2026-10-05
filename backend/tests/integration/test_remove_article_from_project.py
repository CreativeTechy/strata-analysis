"""Real-Postgres coverage for the Article Detail page's ordinary, per-project
remove/restore action (SM-134) - see README.md for setup. Skipped entirely
unless TEST_DATABASE_URL is set.

The contract being checked: unlike delete_article_permanently (and the old,
removed global single-article delete), remove_article_from_project() never
touches the `articles` row or any other project's link to it - it only
removes this one article_projects row, and only ever in a way that
restore_article_to_project() can undo.
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
    a = _create_project(db, "Project A")
    b = _create_project(db, "Project B")
    _save("https://example.com/only-a", a)
    _save("https://example.com/shared", a)
    _save("https://example.com/shared", b)
    return db, a, b


class TestRemoveArticleFromProject:
    def test_unlinks_only_this_project_leaving_the_article_row_intact(self, two_projects):
        from services.articles.store import remove_article_from_project

        db, a, _b = two_projects
        article_id = _article_id(db, "https://example.com/only-a")

        result = remove_article_from_project(a, article_id, actor="tester")

        assert result == {"shared_with_other_projects": False}
        assert _projects_of(db, "https://example.com/only-a") == []
        # The row survives - this is a trash-and-unlink, not a delete.
        assert _article_id(db, "https://example.com/only-a") == article_id

    def test_shared_article_stays_linked_to_the_other_project(self, two_projects):
        from services.articles.store import remove_article_from_project

        db, a, b = two_projects
        article_id = _article_id(db, "https://example.com/shared")

        result = remove_article_from_project(a, article_id, actor="tester")

        assert result == {"shared_with_other_projects": True}
        assert _projects_of(db, "https://example.com/shared") == [b]

    def test_removing_an_unlinked_article_is_a_no_op(self, two_projects):
        from services.articles.store import remove_article_from_project

        db, a, b = two_projects
        article_id = _article_id(db, "https://example.com/only-a")

        assert remove_article_from_project(b, article_id, actor="tester") is None

    def test_restore_relinks_the_article_to_the_project(self, two_projects):
        from services.articles.store import remove_article_from_project, restore_article_to_project

        db, a, _b = two_projects
        article_id = _article_id(db, "https://example.com/only-a")

        remove_article_from_project(a, article_id, actor="tester")
        assert restore_article_to_project(a, article_id, actor="tester") is True

        assert _projects_of(db, "https://example.com/only-a") == [a]
        assert db.fetch_all(
            "select 1 from removed_article_projects where project_id = %s and article_id = %s", (a, article_id)
        ) == []

    def test_restore_without_a_prior_removal_fails(self, two_projects):
        from services.articles.store import restore_article_to_project

        db, a, _b = two_projects
        article_id = _article_id(db, "https://example.com/only-a")

        assert restore_article_to_project(a, article_id) is False

    def test_removal_clears_the_articles_project_derived_rows_and_rejects_its_candidate(self, two_projects):
        from services.articles.store import remove_article_from_project

        db, a, _b = two_projects
        article_id = _article_id(db, "https://example.com/only-a")
        other_id = _article_id(db, "https://example.com/shared")
        run = int(db.fetch_one(
            "insert into pipeline_runs (project_id, status) values (%s, 'completed') returning id", (a,)
        )["id"])
        cluster = int(db.fetch_one(
            "insert into idea_clusters (project_id, idea) values (%s, 'c') returning id", (a,)
        )["id"])
        for aid in (article_id, other_id):
            db.execute("insert into idea_cluster_articles (idea_cluster_id, article_id) values (%s, %s)", (cluster, aid))

        assert remove_article_from_project(a, article_id, actor="tester") is not None

        rows = db.fetch_all("select article_id from idea_cluster_articles where idea_cluster_id = %s", (cluster,))
        assert [int(r["article_id"]) for r in rows] == [other_id]
        assert run  # run history itself is untouched
        assert db.fetch_one("select 1 as x from pipeline_runs where id = %s", (run,))

    def test_restore_is_blocked_while_a_run_is_active(self, two_projects):
        from services.articles.store import ArticleRemovalConflict, remove_article_from_project, restore_article_to_project

        db, a, _b = two_projects
        article_id = _article_id(db, "https://example.com/only-a")
        remove_article_from_project(a, article_id, actor="tester")
        db.execute("insert into pipeline_runs (project_id, status) values (%s, 'running')", (a,))

        with pytest.raises(ArticleRemovalConflict):
            restore_article_to_project(a, article_id)
        assert _projects_of(db, "https://example.com/only-a") == []


class TestDeleteArticlePermanently:
    def test_deletes_the_row_and_every_projects_link(self, two_projects):
        from services.articles.store import delete_article_permanently

        db, a, b = two_projects
        article_id = _article_id(db, "https://example.com/shared")

        assert delete_article_permanently(article_id, actor="admin") is True
        assert db.fetch_all("select 1 from articles where id = %s", (article_id,)) == []
        assert _projects_of(db, "https://example.com/shared") == []

    def test_missing_article_returns_false(self, two_projects):
        from services.articles.store import delete_article_permanently

        db, _a, _b = two_projects
        assert delete_article_permanently(999999999) is False


def test_inflight_analysis_blocks_removal_in_transaction(two_projects):
    from services.articles.store import remove_article_from_project, ArticleRemovalConflict

    db, a, _b = two_projects
    article_id = _article_id(db, "https://example.com/only-a")
    db.execute("insert into pipeline_runs (id, project_id, status) values ('removal-active', %s, 'running')", (a,))
    try:
        with pytest.raises(ArticleRemovalConflict):
            remove_article_from_project(a, article_id)
        assert _projects_of(db, "https://example.com/only-a") == [a]
    finally:
        db.execute("delete from pipeline_runs where id = 'removal-active'")
