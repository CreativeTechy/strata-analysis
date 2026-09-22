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


class TableColumnsTests(unittest.TestCase):
    def setUp(self):
        store._table_columns.cache_clear()

    def tearDown(self):
        store._table_columns.cache_clear()

    def test_returns_empty_set_without_database_url(self):
        with patch("services.articles.store.config.DATABASE_URL", ""):
            self.assertEqual(store._table_columns("article_people_opinions"), set())

    def test_returns_the_columns_the_query_reports(self):
        with patch("services.articles.store.config.DATABASE_URL", "postgresql://x"):
            with patch(
                "services.articles.store.db.fetch_all",
                return_value=[{"column_name": "gender"}, {"column_name": "gender_evidence"}],
            ):
                self.assertEqual(
                    store._table_columns("article_people_opinions"),
                    {"gender", "gender_evidence"},
                )

    def test_returns_empty_set_and_does_not_raise_on_query_error(self):
        with patch("services.articles.store.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.store.db.fetch_all", side_effect=RuntimeError("boom")):
                self.assertEqual(store._table_columns("article_people_opinions"), set())


class ReplaceArticleChildrenTests(unittest.TestCase):
    def setUp(self):
        store._table_exists.cache_clear()
        store._table_columns.cache_clear()

    def tearDown(self):
        store._table_exists.cache_clear()
        store._table_columns.cache_clear()

    ARTICLE = {
        "positive_feedback": ["great range"],
        "complaints": ["slow charging"],
        "negative_feedback": [],
        "people_opinions": [{"opinion": "Loves it", "sentiment": "positive", "category": "overall"}],
        "organizations": ["Acme Motors"],
        "entities": ["Model X"],
        "topics": ["ev"],
    }

    def _opinions_insert_call(self, mock_execute):
        for call in mock_execute.call_args_list:
            sql = call.args[0].strip()
            if sql.startswith("insert into article_people_opinions"):
                return call
        return None

    def _opinion_row(self, mock_execute):
        """The single inserted row as ordered (column, value) pairs.

        Membership assertions (`assertIn(value, params)`) cannot see a row
        tuple built in a different order from the column list, which is
        exactly the mistake that would silently write age_range into
        gender_evidence and the evidence string into segment. Pairing the
        two up is what pins that."""
        call = self._opinions_insert_call(mock_execute)
        self.assertIsNotNone(call)
        sql, params = call.args
        columns = [c.strip() for c in sql[sql.index("(") + 1:sql.index(")")].split(",")]
        self.assertEqual(len(params), len(columns), "column/parameter count mismatch")
        return list(zip(columns, params))

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

    def test_gender_evidence_is_written_when_the_column_exists(self):
        """The opinions insert names and populates gender_evidence when the
        database actually has that column."""
        article = {
            **self.ARTICLE,
            "people_opinions": [{
                "opinion": "Loves it", "sentiment": "positive", "category": "overall",
                "gender": "female", "gender_evidence": "she said",
            }],
        }
        with patch("services.articles.store._table_exists", return_value=True), \
             patch("services.articles.store._table_columns", return_value={"gender_evidence"}), \
             patch("services.articles.store.db.execute") as mock_execute:
            store._replace_article_children(1, article)
        self.assertEqual(self._opinion_row(mock_execute), [
            ("article_id", 1),
            ("opinion", "Loves it"),
            ("sentiment", "positive"),
            ("category", "overall"),
            ("gender", "female"),
            ("gender_evidence", "she said"),
            ("age_range", "unknown"),
            ("region", "unknown"),
            ("segment_raw", "unknown"),
            ("segment", "unknown"),
        ])

    def test_gender_evidence_is_forced_empty_when_gender_is_unknown(self):
        article = {
            **self.ARTICLE,
            "people_opinions": [{
                "opinion": "Loves it", "sentiment": "positive", "category": "overall",
                "gender_evidence": "she said",  # gender omitted -> "unknown"
            }],
        }
        with patch("services.articles.store._table_exists", return_value=True), \
             patch("services.articles.store._table_columns", return_value={"gender_evidence"}), \
             patch("services.articles.store.db.execute") as mock_execute:
            store._replace_article_children(1, article)
        row = dict(self._opinion_row(mock_execute))
        self.assertEqual(row["gender"], "unknown")
        self.assertEqual(row["gender_evidence"], "")

    def test_gender_evidence_is_dropped_from_the_insert_when_the_column_is_missing(self):
        """A database that hasn't had migration 0019 applied yet still has
        article_people_opinions itself (so _table_exists passes) but not this
        column - the insert must adapt instead of failing outright and, with
        it, silently dropping the article_tags write that follows (see
        store.py's _replace_article_children docstring)."""
        article = {
            **self.ARTICLE,
            "people_opinions": [{
                "opinion": "Loves it", "sentiment": "positive", "category": "overall",
                "gender": "female", "gender_evidence": "she said",
            }],
        }
        with patch("services.articles.store._table_exists", return_value=True), \
             patch("services.articles.store._table_columns", return_value=set()), \
             patch("services.articles.store.db.execute") as mock_execute:
            store._replace_article_children(1, article)
        self.assertEqual(self._opinion_row(mock_execute), [
            ("article_id", 1),
            ("opinion", "Loves it"),
            ("sentiment", "positive"),
            ("category", "overall"),
            ("gender", "female"),
            ("age_range", "unknown"),
            ("region", "unknown"),
            ("segment_raw", "unknown"),
            ("segment", "unknown"),
        ])
        sql = self._opinions_insert_call(mock_execute).args[0]
        self.assertNotIn("gender_evidence", sql)
        # the tags insert (previously lost when the opinions insert raised)
        # still runs
        tag_calls = [c for c in mock_execute.call_args_list if c.args[0].strip().startswith("insert into article_tags")]
        self.assertTrue(tag_calls)

    def test_age_evidence_is_written_when_the_column_exists(self):
        """Mirrors test_gender_evidence_is_written_when_the_column_exists -
        the opinions insert names and populates age_evidence when the
        database actually has that column, alongside gender_evidence."""
        article = {
            **self.ARTICLE,
            "people_opinions": [{
                "opinion": "Loves it", "sentiment": "positive", "category": "overall",
                "gender": "female", "gender_evidence": "she said",
                "age_range": "35-44", "age_evidence": "42",
            }],
        }
        with patch("services.articles.store._table_exists", return_value=True), \
             patch("services.articles.store._table_columns", return_value={"gender_evidence", "age_evidence"}), \
             patch("services.articles.store.db.execute") as mock_execute:
            store._replace_article_children(1, article)
        self.assertEqual(self._opinion_row(mock_execute), [
            ("article_id", 1),
            ("opinion", "Loves it"),
            ("sentiment", "positive"),
            ("category", "overall"),
            ("gender", "female"),
            ("gender_evidence", "she said"),
            ("age_range", "35-44"),
            ("age_evidence", "42"),
            ("region", "unknown"),
            ("segment_raw", "unknown"),
            ("segment", "unknown"),
        ])

    def test_age_evidence_is_forced_empty_when_age_range_is_unknown(self):
        article = {
            **self.ARTICLE,
            "people_opinions": [{
                "opinion": "Loves it", "sentiment": "positive", "category": "overall",
                "age_evidence": "42",  # age_range omitted -> "unknown"
            }],
        }
        with patch("services.articles.store._table_exists", return_value=True), \
             patch("services.articles.store._table_columns", return_value={"age_evidence"}), \
             patch("services.articles.store.db.execute") as mock_execute:
            store._replace_article_children(1, article)
        row = dict(self._opinion_row(mock_execute))
        self.assertEqual(row["age_range"], "unknown")
        self.assertEqual(row["age_evidence"], "")

    def test_age_evidence_is_dropped_from_the_insert_when_the_column_is_missing(self):
        """A database that hasn't had migration 0021 applied yet still has
        article_people_opinions itself (so _table_exists passes) but not this
        column - the insert must adapt instead of failing outright, the same
        way it does for a missing gender_evidence column."""
        article = {
            **self.ARTICLE,
            "people_opinions": [{
                "opinion": "Loves it", "sentiment": "positive", "category": "overall",
                "age_range": "35-44", "age_evidence": "42",
            }],
        }
        with patch("services.articles.store._table_exists", return_value=True), \
             patch("services.articles.store._table_columns", return_value=set()), \
             patch("services.articles.store.db.execute") as mock_execute:
            store._replace_article_children(1, article)
        self.assertEqual(self._opinion_row(mock_execute), [
            ("article_id", 1),
            ("opinion", "Loves it"),
            ("sentiment", "positive"),
            ("category", "overall"),
            ("gender", "unknown"),
            ("age_range", "35-44"),
            ("region", "unknown"),
            ("segment_raw", "unknown"),
            ("segment", "unknown"),
        ])
        sql = self._opinions_insert_call(mock_execute).args[0]
        self.assertNotIn("age_evidence", sql)

    def test_gender_evidence_and_age_evidence_roll_out_independently(self):
        """A database can have one column without the other mid-rollout (the
        two migrations don't have to land in the same deploy) - each column's
        presence is checked on its own, not as an all-or-nothing pair."""
        article = {
            **self.ARTICLE,
            "people_opinions": [{
                "opinion": "Loves it", "sentiment": "positive", "category": "overall",
                "gender": "female", "gender_evidence": "she said",
                "age_range": "35-44", "age_evidence": "42",
            }],
        }
        with patch("services.articles.store._table_exists", return_value=True), \
             patch("services.articles.store._table_columns", return_value={"gender_evidence"}), \
             patch("services.articles.store.db.execute") as mock_execute:
            store._replace_article_children(1, article)
        row = dict(self._opinion_row(mock_execute))
        self.assertEqual(row["gender_evidence"], "she said")
        self.assertNotIn("age_evidence", row)

    def test_a_missing_column_is_rechecked_rather_than_cached_for_the_process(self):
        """The column is only ever added, never dropped. A memoized "absent"
        would keep this process writing no evidence after the migration lands,
        until someone restarts it."""
        article = {
            **self.ARTICLE,
            "people_opinions": [{
                "opinion": "Loves it", "sentiment": "positive", "category": "overall",
                "gender": "female", "gender_evidence": "she said",
            }],
        }
        # first article: the migration hasn't landed
        with patch("services.articles.store._table_exists", return_value=True), \
             patch("services.articles.store.config.DATABASE_URL", "postgresql://x"), \
             patch("services.articles.store.db.fetch_all", return_value=[{"column_name": "gender"}]), \
             patch("services.articles.store.db.execute") as first_execute:
            store._replace_article_children(1, article)
        self.assertNotIn("gender_evidence", self._opinions_insert_call(first_execute).args[0])

        # migration lands; the very next article must pick it up without a restart
        migrated = [{"column_name": "gender"}, {"column_name": "gender_evidence"}]
        with patch("services.articles.store._table_exists", return_value=True), \
             patch("services.articles.store.config.DATABASE_URL", "postgresql://x"), \
             patch("services.articles.store.db.fetch_all", return_value=migrated), \
             patch("services.articles.store.db.execute") as second_execute:
            store._replace_article_children(2, article)
        self.assertEqual(dict(self._opinion_row(second_execute))["gender_evidence"], "she said")


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

    def test_source_run_snapshot_dict_is_wrapped_for_jsonb(self):
        snapshot = {"id": "abc123", "started_at": "2026-08-24T00:00:00+00:00", "project_id": 7}
        value = self._field_value(self._article(source_run_snapshot=snapshot), "source_run_snapshot")
        self.assertEqual(value.obj, snapshot)

    def test_source_run_snapshot_absent_stays_sql_null(self):
        """Unlike the list-shaped ARTICLE_JSON_FIELDS, a missing snapshot must
        stay NULL rather than fall back to `[]` - it's an object column, and
        `[]` would misrepresent "no run" as an empty list."""
        value = self._field_value(self._article(), "source_run_snapshot")
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

    def test_source_run_snapshot_keeps_the_first_saved_value(self):
        """source_run_snapshot - scraper-app collection provenance, set once
        at candidate-approval time (project_document_articles.py) - must
        follow the same first-writer-wins rule as pipeline_run_id, for the
        same reason: a later save (reanalyze, re-approval) must not blank it."""
        captured = {}

        def _fake_fetch_one(sql, params):
            captured["sql"] = sql
            return {"id": 1, "source_url": "https://example.com"}

        article = {"url": "https://example.com/a"}
        with patch("services.articles.store._article_write_fields", return_value=["url", "source_run_snapshot"]):
            with patch("services.articles.store._article_columns", return_value={"url", "source_run_snapshot"}):
                with patch("services.articles.store.db.fetch_one", side_effect=_fake_fetch_one):
                    store._upsert_article_row(article)

        self.assertIn(
            "source_run_snapshot = coalesce(articles.source_run_snapshot, excluded.source_run_snapshot)",
            captured["sql"],
        )
        self.assertNotIn("source_run_snapshot = excluded.source_run_snapshot", captured["sql"])

    def test_uploaded_document_source_survives_later_url_upserts(self):
        captured = {}

        def _fake_fetch_one(sql, params):
            captured["sql"] = sql
            return {"id": 7, "source_url": "document://project-document/5"}

        article = {
            "url": "https://example.com/article",
            "source": "Website",
            "source_url": "https://example.com",
        }
        with patch("services.articles.store._article_write_fields", return_value=["url", "source", "source_url"]):
            with patch("services.articles.store._article_columns", return_value={"url", "source", "source_url"}):
                with patch("services.articles.store.db.fetch_one", side_effect=_fake_fetch_one):
                    store._upsert_article_row(article)

        self.assertIn(
            "starts_with(articles.source_url, 'document://project-document/')",
            captured["sql"],
        )
        self.assertNotIn("project-document/%", captured["sql"])
        self.assertNotIn("source_url = excluded.source_url", captured["sql"])

    def test_enrichment_fields_are_guarded_when_analysis_status_is_in_the_write(self):
        """project_document_articles._materialize() and its competitor-study
        counterpart both save a freshly-approved candidate with
        analysis_status='pending' and every enrichment field still at
        DEFAULT_ENRICHMENT's neutral placeholder - real analysis for *that
        candidate* hasn't run yet. If the candidate's url already belongs to a
        successfully-analyzed article (the same export re-imported, or a
        shared real-world url approved into a second project), that
        placeholder write must not blank out analysis already on file - see
        store.ENRICHMENT_FIELDS."""
        captured = {}

        def _fake_fetch_one(sql, params):
            captured["sql"] = sql
            return {"id": 1, "source_url": "https://example.com"}

        article = {"url": "https://example.com/a", "analysis_status": "pending", "sentiment": "neutral"}
        fields = ["url", "analysis_status", "sentiment"]
        with patch("services.articles.store._article_write_fields", return_value=fields):
            with patch("services.articles.store._article_columns", return_value=set(fields)):
                with patch("services.articles.store.db.fetch_one", side_effect=_fake_fetch_one):
                    store._upsert_article_row(article)

        self.assertIn(
            "sentiment = case when excluded.analysis_status = 'pending' "
            "and articles.analysis_status = 'success' "
            "then articles.sentiment else excluded.sentiment end",
            captured["sql"],
        )
        self.assertNotIn("sentiment = excluded.sentiment,", captured["sql"])
        # analysis_status itself must still move forward unconditionally - the
        # whole point is that this candidate needs (re)analysis.
        self.assertIn("analysis_status = excluded.analysis_status", captured["sql"])

    def test_enrichment_fields_fall_back_to_plain_overwrite_without_analysis_status(self):
        """A caller that never writes analysis_status (none exists today, but
        nothing should silently stop updating enrichment fields if one
        didn't) has no 'pending' placeholder to guard against."""
        captured = {}

        def _fake_fetch_one(sql, params):
            captured["sql"] = sql
            return {"id": 1, "source_url": "https://example.com"}

        article = {"url": "https://example.com/a", "sentiment": "positive"}
        fields = ["url", "sentiment"]
        with patch("services.articles.store._article_write_fields", return_value=fields):
            with patch("services.articles.store._article_columns", return_value=set(fields)):
                with patch("services.articles.store.db.fetch_one", side_effect=_fake_fetch_one):
                    store._upsert_article_row(article)

        self.assertIn("sentiment = excluded.sentiment", captured["sql"])
        self.assertNotIn("case when excluded.analysis_status", captured["sql"])


if __name__ == "__main__":
    unittest.main()
