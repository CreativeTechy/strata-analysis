import json
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from fastapi.testclient import TestClient

from services.articles import articles_store
from services.auth import auth
import main

FAKE_USER = {"id": 1, "username": "admin", "role_id": 1, "status": "active"}


def _fake_get_current_user():
    return FAKE_USER


class ExportSelectTests(unittest.TestCase):
    """The export exists to be re-importable (e.g. into another project or a
    fresh database), so any column an import target would need has to survive
    the export select."""

    def test_export_selects_every_column_the_upsert_writes(self):
        from services.articles.store import stored_article_fields

        articles_store._export_select.cache_clear()
        selected = articles_store._export_select().split(",")
        missing = [field for field in stored_article_fields() if field not in selected]
        self.assertEqual(missing, [])

    def test_export_still_carries_what_the_dashboard_list_shows(self):
        articles_store._export_select.cache_clear()
        selected = set(articles_store._export_select().split(","))
        dropped = [field for field in articles_store.ARTICLES_SELECT.split(",") if field not in selected]
        self.assertEqual(dropped, [])

    def test_a_column_missing_from_a_pre_migration_database_is_dropped_not_queried(self):
        """ARTICLES_SELECT's names (segment, source_run_snapshot, ...) are
        hardcoded, unlike stored_article_fields() which is already filtered
        against the live table - so they must be filtered again here, or a
        database that hasn't had the migration adding one of them applied yet
        would have the whole export query fail on an unknown column name."""
        from services.articles import store

        articles_store._export_select.cache_clear()
        live_columns = (set(store.ARTICLE_MUTABLE_FIELDS) | {"id", "created_at"}) - {
            "segment", "source_run_snapshot",
        }
        with patch.object(store, "_article_table_columns", return_value=live_columns):
            selected = articles_store._export_select().split(",")

        self.assertNotIn("segment", selected)
        self.assertNotIn("source_run_snapshot", selected)
        self.assertIn("id", selected)
        self.assertIn("title", selected)

    def test_an_unreachable_database_falls_back_to_trusting_every_candidate_column(self):
        """_article_table_columns() returns an empty set both when there is no
        DATABASE_URL and when the query itself fails - in either case there is
        nothing to check against, so every candidate name (including the ones
        unioned in from ARTICLES_SELECT) is kept rather than partially
        filtered out, matching stored_article_fields()'s own "can't check, so
        trust everything" fallback for the same condition."""
        from services.articles import store

        articles_store._export_select.cache_clear()
        with patch.object(store, "_article_table_columns", return_value=set()):
            selected = articles_store._export_select().split(",")

        self.assertIn("segment", selected)
        self.assertIn("source_run_snapshot", selected)


class ExportRouteTests(unittest.TestCase):
    """GET /api/articles/export writes NDJSON straight off the generator, so
    rows are pulled from the database as the response is written rather than
    collected first."""

    @classmethod
    def setUpClass(cls):
        main.app.dependency_overrides[auth.get_current_user] = _fake_get_current_user
        cls._patchers = [
            patch("services.auth.auth._enforce_csrf"),
            patch("services.auth.permissions_store.user_permission_keys", return_value={"articles.view"}),
            patch("services.auth.permissions_store.user_is_full_access", return_value=True),
        ]
        for patcher in cls._patchers:
            patcher.start()
        cls.client = TestClient(main.app)

    @classmethod
    def tearDownClass(cls):
        main.app.dependency_overrides.clear()
        for patcher in cls._patchers:
            patcher.stop()

    def test_the_response_is_one_json_object_per_line(self):
        rows = [{"id": i, "url": f"https://example.com/{i}", "title": f"T{i}"} for i in range(3)]
        with patch("main.export_articles", return_value=iter(rows)):
            res = self.client.get("/api/articles/export")

        self.assertEqual(res.status_code, 200)
        self.assertIn("application/x-ndjson", res.headers["content-type"])
        self.assertIn("attachment", res.headers["content-disposition"])
        lines = [json.loads(line) for line in res.text.splitlines() if line.strip()]
        self.assertEqual(lines, rows)

    def test_rows_are_pulled_lazily_as_the_response_is_written(self):
        pulled = []

        def lazy_rows():
            for i in range(3):
                pulled.append(i)
                yield {"id": i, "url": f"https://example.com/{i}"}

        with patch("main.export_articles", return_value=lazy_rows()):
            self.assertEqual(pulled, [])  # the generator is not drained up front
            res = self.client.get("/api/articles/export")

        self.assertEqual(res.status_code, 200)
        self.assertEqual(pulled, [0, 1, 2])


if __name__ == "__main__":
    unittest.main()
