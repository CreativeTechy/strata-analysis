import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from services.articles import store


class BulkInsertTests(unittest.TestCase):
    def test_no_rows_does_not_call_execute(self):
        with patch("services.articles.store.db.execute") as mock_execute:
            store._bulk_insert("some_table", ("a", "b"), [])
        mock_execute.assert_not_called()

    def test_builds_one_multi_row_insert_with_flattened_params(self):
        with patch("services.articles.store.db.execute") as mock_execute:
            store._bulk_insert("article_tags", ("article_id", "tag_type", "value"), [
                (1, "organization", "Acme"),
                (1, "topic", "ev"),
            ])
        mock_execute.assert_called_once()
        sql, params = mock_execute.call_args[0]
        self.assertIn("insert into article_tags (article_id, tag_type, value)", sql)
        self.assertEqual(sql.count("%s"), 6)
        self.assertEqual(params, (1, "organization", "Acme", 1, "topic", "ev"))


class TableExistsTests(unittest.TestCase):
    def setUp(self):
        store._table_exists.cache_clear()

    def tearDown(self):
        store._table_exists.cache_clear()

    def test_returns_false_without_database_url(self):
        with patch("services.articles.store.config.DATABASE_URL", ""):
            self.assertFalse(store._table_exists("article_tags"))

    def test_returns_true_when_query_reports_exists(self):
        with patch("services.articles.store.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.store.db.fetch_one", return_value={"exists": True}):
                self.assertTrue(store._table_exists("article_tags"))

    def test_returns_false_and_does_not_raise_on_query_error(self):
        with patch("services.articles.store.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.store.db.fetch_one", side_effect=RuntimeError("boom")):
                self.assertFalse(store._table_exists("article_tags"))


class ReplaceArticleChildrenTests(unittest.TestCase):
    def setUp(self):
        store._table_exists.cache_clear()

    def tearDown(self):
        store._table_exists.cache_clear()

    ARTICLE = {
        "positive_feedback": ["great range"],
        "complaints": ["slow charging"],
        "negative_feedback": [],
        "people_opinions": [{"opinion": "Loves it", "sentiment": "positive", "category": "overall"}],
        "organizations": ["Acme Motors"],
        "entities": ["Model X"],
        "topics": ["ev"],
    }

    def test_noop_when_table_does_not_exist(self):
        with patch("services.articles.store._table_exists", return_value=False):
            with patch("services.articles.store.db.execute") as mock_execute:
                store._replace_article_children(1, self.ARTICLE)
        mock_execute.assert_not_called()

    def test_deletes_before_inserting(self):
        with patch("services.articles.store._table_exists", return_value=True):
            with patch("services.articles.store.db.execute") as mock_execute:
                store._replace_article_children(1, self.ARTICLE)
        delete_calls = [c for c in mock_execute.call_args_list if c.args[0].strip().startswith("delete")]
        insert_calls = [c for c in mock_execute.call_args_list if c.args[0].strip().startswith("insert")]
        self.assertEqual(len(delete_calls), 3)
        self.assertTrue(insert_calls)
        # every delete happens before any insert
        first_insert_index = mock_execute.call_args_list.index(insert_calls[0])
        last_delete_index = mock_execute.call_args_list.index(delete_calls[-1])
        self.assertLess(last_delete_index, first_insert_index)

    def test_db_error_is_caught_and_logged_not_raised(self):
        with patch("services.articles.store._table_exists", return_value=True):
            with patch("services.articles.store.db.execute", side_effect=RuntimeError("boom")):
                store._replace_article_children(1, self.ARTICLE)  # must not raise


class ArticleRowFieldHandlingTests(unittest.TestCase):
    """_article_row() special-cases a handful of fields beyond the generic
    JSON/plain-value path - these tests pin that behavior directly rather
    than through a live DB round trip."""

    def _article(self, **overrides):
        article = {
            "url": "https://example.com/a",
            "embedding_json": [0.1, 0.2, 0.3],
            "analysis_status": None,
            "analysis_started_at": "",
            "reprocess_requested_at": "",
        }
        article.update(overrides)
        return article

    def _field_value(self, article, field_name):
        with patch("services.articles.store._article_write_fields", return_value=[field_name, "embedding_json"]):
            fields, params = store._article_row(article)
        return dict(zip(fields, params))[field_name]

    def test_embedding_dimensions_is_derived_from_embedding_json_length(self):
        value = self._field_value(self._article(), "embedding_dimensions")
        self.assertEqual(value, 3)

    def test_embedding_dimensions_is_none_when_no_embedding(self):
        value = self._field_value(self._article(embedding_json=None), "embedding_dimensions")
        self.assertIsNone(value)

    def test_blank_analysis_status_falls_back_to_success(self):
        value = self._field_value(self._article(), "analysis_status")
        self.assertEqual(value, "success")

    def test_explicit_analysis_status_is_preserved(self):
        value = self._field_value(self._article(analysis_status="failed"), "analysis_status")
        self.assertEqual(value, "failed")

    def test_blank_timestamp_fields_become_none(self):
        value = self._field_value(self._article(), "analysis_started_at")
        self.assertIsNone(value)

    def test_reprocess_requested_at_defaults_to_none(self):
        """The pipeline never sets this - it's operator-controlled - so a
        normal analysis write always clears it back to null."""
        value = self._field_value(self._article(reprocess_requested_at="2026-01-01T00:00:00+00:00"), "reprocess_requested_at")
        self.assertEqual(value, "2026-01-01T00:00:00+00:00")
        value = self._field_value(self._article(), "reprocess_requested_at")
        self.assertIsNone(value)


class UpsertArticleRowConflictClauseTests(unittest.TestCase):
    """_upsert_article_row()'s on-conflict clause must not blindly overwrite
    pipeline_run_id from `excluded.*` like every other field. It records which
    run *first* saved this article - every run re-crawls all of a project's
    sources, so a later run routinely re-upserts URLs an earlier run already
    saved, and must not steal that article's run attribution. It also must
    not blank the field out for saves that don't know a run id at all
    (reanalyze, import, competitor doc extraction). Mirrors the existing
    content_changed_at conditional-update coverage style in this file."""

    def test_pipeline_run_id_keeps_the_first_saved_value(self):
        captured = {}

        def _fake_fetch_one(sql, params):
            captured["sql"] = sql
            return {"id": 1, "source_url": "https://example.com"}

        article = {"url": "https://example.com/a"}
        with patch("services.articles.store._article_write_fields", return_value=["url", "pipeline_run_id"]):
            with patch("services.articles.store._article_columns", return_value={"url", "pipeline_run_id"}):
                with patch("services.articles.store.db.fetch_one", side_effect=_fake_fetch_one):
                    store._upsert_article_row(article)

        self.assertIn(
            "pipeline_run_id = coalesce(articles.pipeline_run_id, excluded.pipeline_run_id)",
            captured["sql"],
        )
        self.assertNotIn("pipeline_run_id = excluded.pipeline_run_id", captured["sql"])


if __name__ == "__main__":
    unittest.main()
