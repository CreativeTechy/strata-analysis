"""Per-run analysis snapshots: the thing that makes two analysis runs
comparable instead of collapsing into "the latest analysis".

The regression these guard against is subtle and was live before
article_analyses existed. Analysis output lives on the `articles` row and
`articles.pipeline_run_id` records which run *first* saved the article and is
never re-attributed, so a second run over the same project used to tag zero
articles (empty dashboard) while overwriting the first run's conclusions on the
shared row (the first run's dashboard retroactively showed the second's
numbers).
"""

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import db
from services.articles import article_analyses
from services.intelligence import intelligence


class RecordAnalysisSnapshotTests(unittest.TestCase):
    def test_snapshot_reads_the_persisted_article_row(self):
        """The INSERT selects from `articles`, not from the analysis dict.

        The dict uses the pipeline's own key names (overall_sentiment, topic)
        which store._row() maps onto columns; building the snapshot from the
        persisted row is what keeps this from being a second copy of that
        mapping, quietly drifting the first time a stage renames an output.
        """
        executed = []
        with patch.object(article_analyses.db, "execute", side_effect=lambda sql, params: executed.append((sql, params))):
            self.assertTrue(article_analyses.record_analysis_snapshot("run-1", 7))

        sql, params = executed[0]
        self.assertIn("insert into article_analyses", sql)
        self.assertIn("from articles a", sql)
        self.assertIn("on conflict (run_id, article_id) do update", sql)
        self.assertEqual(params, ("run-1", 7))

    def test_snapshot_carries_segment_and_people_opinions(self):
        """Both are written by follow-up statements inside save_articles, not by
        the article upsert - a snapshot that missed them would lose the whole
        demographic breakdown for the run."""
        executed = []
        with patch.object(article_analyses.db, "execute", side_effect=lambda sql, params: executed.append(sql)):
            article_analyses.record_analysis_snapshot("run-1", 7)

        sql = executed[0]
        self.assertIn("a.segment", sql)
        self.assertIn("article_people_opinions", sql)

    def test_snapshot_never_raises_and_reports_failure(self):
        """A snapshot is the comparison history layered on top of the run; losing
        one must not turn an article the run actually analyzed into a failure."""
        with patch.object(article_analyses.db, "execute", side_effect=RuntimeError("table missing")):
            self.assertFalse(article_analyses.record_analysis_snapshot("run-1", 7))

    def test_missing_run_id_writes_nothing(self):
        with patch.object(article_analyses.db, "execute") as execute:
            self.assertFalse(article_analyses.record_analysis_snapshot("", 7))
            self.assertFalse(article_analyses.record_analysis_snapshot(None, 7))
        execute.assert_not_called()


class RunScopedReadTests(unittest.TestCase):
    def test_run_scoped_rows_take_analysis_from_the_snapshot_and_identity_from_the_article(self):
        """Analysis fields are frozen per run; url/title/text/published are read
        live, so correcting an article's metadata fixes it on every historical
        run rather than only the newest."""
        captured = {}

        def fake_fetch_all(sql, params):
            captured["sql"] = sql
            captured["params"] = params
            return [{"id": 1, "sentiment": "positive"}]

        with patch.object(article_analyses, "_table_exists", return_value=True), \
             patch.object(article_analyses.db, "fetch_all", side_effect=fake_fetch_all):
            rows = article_analyses.fetch_run_article_rows(3, "run-2")

        self.assertEqual(rows, [{"id": 1, "sentiment": "positive"}])
        self.assertEqual(captured["params"], (3, "run-2"))
        # Analysis from the snapshot...
        for column in ("an.sentiment", "an.writer_tone", "an.article_tone", "an.insight_json", "an.segment"):
            self.assertIn(column, captured["sql"])
        # ...identity from the live article row.
        for column in ("a.url", "a.title", "a.text", "a.published", "a.verified"):
            self.assertIn(column, captured["sql"])

    def test_intelligence_reads_snapshots_when_scoped_to_a_run(self):
        """The bug in one assertion: before this, a run-scoped read was
        `articles where pipeline_run_id = X`, which showed every run whichever
        conclusions the newest run had overwritten onto the row."""
        with patch.object(intelligence, "_database_ready", return_value=True), \
             patch.object(article_analyses, "fetch_run_article_rows", return_value=[{"id": 9}]) as scoped, \
             patch.object(db, "fetch_all") as fetch_all:
            rows = intelligence._fetch_project_rows(3, run_id="run-2")

        self.assertEqual(rows, [{"id": 9}])
        scoped.assert_called_once_with(3, "run-2")
        fetch_all.assert_not_called()

    def test_unscoped_intelligence_still_reads_the_article_row(self):
        """"No run selected" means "the current state of the project", which is
        exactly what `articles` holds - snapshots are only for historical runs."""
        with patch.object(intelligence, "_database_ready", return_value=True), \
             patch.object(db, "fetch_all", return_value=[{"id": 1}]) as fetch_all:
            intelligence._fetch_project_rows(3)

        sql = fetch_all.call_args[0][0]
        self.assertIn("from articles a", sql)
        self.assertNotIn("article_analyses", sql)

    def test_sentiment_counts_group_by_the_snapshot_not_first_attribution(self):
        """Grouping `articles` by pipeline_run_id credited every article to the
        run that first analyzed it, so a later run always compared as zero."""
        with patch.object(article_analyses, "_table_exists", return_value=True), \
             patch.object(article_analyses.db, "fetch_all", return_value=[
                 {"run_id": "run-1", "sentiment": "neutral", "total": 34},
                 {"run_id": "run-2", "sentiment": "positive", "total": 10},
                 {"run_id": "run-2", "sentiment": "neutral", "total": 24},
             ]):
            counts = article_analyses.sentiment_counts_by_run(3, ["run-1", "run-2"])

        self.assertEqual(counts["run-1"], {"neutral": 34})
        self.assertEqual(counts["run-2"], {"positive": 10, "neutral": 24})

    def test_sentiment_counts_short_circuit_without_run_ids(self):
        with patch.object(article_analyses.db, "fetch_all") as fetch_all:
            self.assertEqual(article_analyses.sentiment_counts_by_run(3, []), {})
            self.assertEqual(article_analyses.sentiment_counts_by_run(3, [None]), {})
        fetch_all.assert_not_called()

    def test_reads_degrade_to_empty_before_the_migration_lands(self):
        with patch.object(article_analyses, "_table_exists", return_value=False):
            self.assertEqual(article_analyses.fetch_run_article_rows(3, "run-2"), [])
            self.assertEqual(article_analyses.sentiment_counts_by_run(3, ["run-2"]), {})
            self.assertEqual(article_analyses.run_article_count("run-2"), 0)


class SnapshotGenderEvidenceColumnTests(unittest.TestCase):
    """gender_evidence arrived in migration 0019, so the snapshot insert has to
    survive a database that hasn't applied it yet. Naming the column
    unconditionally made the whole INSERT fail, and because
    record_analysis_snapshot() swallows failures the run then produced *no*
    article_analyses rows at all - silently, for every article."""

    def _snapshot_sql(self, column_present):
        executed = []
        with patch.object(article_analyses, "_table_has_column", return_value=column_present),              patch.object(article_analyses.db, "execute", side_effect=lambda sql, params: executed.append(sql)):
            ok = article_analyses.record_analysis_snapshot("run-1", 7)
        self.assertTrue(ok)
        self.assertEqual(len(executed), 1)
        return executed[0]

    def test_evidence_key_is_selected_when_the_column_exists(self):
        sql = self._snapshot_sql(True)
        self.assertIn("'gender_evidence', po.gender_evidence", sql)

    def test_evidence_key_is_omitted_when_the_column_is_missing(self):
        sql = self._snapshot_sql(False)
        self.assertNotIn("gender_evidence", sql)
        # the rest of the snapshot is untouched - a missing key must not cost
        # the run its whole comparison row
        for key in ("'opinion', po.opinion", "'gender', po.gender", "'segment', po.segment"):
            self.assertIn(key, sql)
        self.assertIn("insert into article_analyses", sql)

    def test_column_check_failure_degrades_instead_of_raising(self):
        with patch.object(article_analyses.db, "fetch_one", side_effect=RuntimeError("boom")):
            self.assertFalse(article_analyses._table_has_column("article_people_opinions", "gender_evidence"))

    def test_column_presence_is_not_memoized_across_calls(self):
        """A cached False would keep this process emitting the degraded shape
        after the migration lands, until it restarts."""
        answers = [{"exists": False}, {"exists": True}]
        with patch.object(article_analyses.db, "fetch_one", side_effect=answers):
            first = article_analyses._table_has_column("article_people_opinions", "gender_evidence")
            second = article_analyses._table_has_column("article_people_opinions", "gender_evidence")
        self.assertFalse(first)
        self.assertTrue(second)

    def test_failure_is_logged_rather_than_vanishing(self):
        with patch.object(article_analyses.db, "execute", side_effect=RuntimeError("boom")):
            with self.assertLogs("services.articles.article_analyses", level="WARNING") as logged:
                self.assertFalse(article_analyses.record_analysis_snapshot("run-1", 7))
        self.assertTrue(any("snapshot not recorded" in line for line in logged.output))


class SnapshotAgeEvidenceColumnTests(unittest.TestCase):
    """Mirrors SnapshotGenderEvidenceColumnTests: age_evidence arrived in
    migration 0021, so the snapshot insert has to survive a database that
    hasn't applied it yet, independently of whether gender_evidence has."""

    def _snapshot_sql(self, *, gender_evidence, age_evidence):
        def fake_has_column(table, column):
            return {"gender_evidence": gender_evidence, "age_evidence": age_evidence}[column]

        executed = []
        with patch.object(article_analyses, "_table_has_column", side_effect=fake_has_column),              patch.object(article_analyses.db, "execute", side_effect=lambda sql, params: executed.append(sql)):
            ok = article_analyses.record_analysis_snapshot("run-1", 7)
        self.assertTrue(ok)
        self.assertEqual(len(executed), 1)
        return executed[0]

    def test_evidence_key_is_selected_when_the_column_exists(self):
        sql = self._snapshot_sql(gender_evidence=True, age_evidence=True)
        self.assertIn("'age_evidence', po.age_evidence", sql)

    def test_evidence_key_is_omitted_when_the_column_is_missing(self):
        sql = self._snapshot_sql(gender_evidence=True, age_evidence=False)
        self.assertNotIn("age_evidence", sql)
        # the rest of the snapshot, including gender_evidence, is untouched
        for key in ("'opinion', po.opinion", "'gender_evidence', po.gender_evidence", "'segment', po.segment"):
            self.assertIn(key, sql)

    def test_the_two_evidence_columns_roll_out_independently(self):
        """age_evidence (migration 0021) can land on a database before or
        after gender_evidence (migration 0019) - neither is checked as a
        stand-in for the other."""
        sql = self._snapshot_sql(gender_evidence=False, age_evidence=True)
        self.assertNotIn("gender_evidence", sql)
        self.assertIn("'age_evidence', po.age_evidence", sql)


class AdhocSnapshotRunTests(unittest.TestCase):
    """One-off (re)analysis (main.py's .../analyze, .../reprocess, batch
    .../analyze - none pass run_id) used to be invisible to article_analyses
    entirely. ensure_adhoc_snapshot_run() gives those saves a real (synthetic)
    pipeline_runs row to snapshot against, so the Reports "variation from
    yesterday" comparison can see them too."""

    def test_returns_none_without_a_project_to_scope_it_to(self):
        with patch("services.articles.article_analyses.config.DATABASE_URL", "postgres://x"), \
             patch("services.pipeline.pipeline_runs.create_pipeline_run") as create:
            self.assertIsNone(article_analyses.ensure_adhoc_snapshot_run(None))
        create.assert_not_called()

    def test_returns_none_without_a_database(self):
        with patch("services.articles.article_analyses.config.DATABASE_URL", ""), \
             patch("services.pipeline.pipeline_runs.create_pipeline_run") as create:
            self.assertIsNone(article_analyses.ensure_adhoc_snapshot_run(3))
        create.assert_not_called()

    def test_creates_a_deterministic_per_project_per_day_run(self):
        when = datetime(2026, 3, 5, 10, 30, tzinfo=timezone.utc)
        with patch("services.articles.article_analyses.config.DATABASE_URL", "postgres://x"), \
             patch("services.pipeline.pipeline_runs.create_pipeline_run", return_value={"id": "snap-3-2026-03-05"}) as create:
            run_id = article_analyses.ensure_adhoc_snapshot_run(3, when=when)

        self.assertEqual(run_id, "snap-3-2026-03-05")
        create.assert_called_once()
        kwargs = create.call_args.kwargs
        self.assertEqual(kwargs["run_id"], "snap-3-2026-03-05")
        self.assertEqual(kwargs["pipeline"], "report-snapshot")
        self.assertEqual(kwargs["project_id"], 3)

    def test_repeated_calls_the_same_day_reuse_the_same_run_id(self):
        morning = datetime(2026, 3, 5, 1, 0, tzinfo=timezone.utc)
        evening = datetime(2026, 3, 5, 23, 0, tzinfo=timezone.utc)
        with patch("services.articles.article_analyses.config.DATABASE_URL", "postgres://x"), \
             patch("services.pipeline.pipeline_runs.create_pipeline_run", side_effect=lambda **kw: {"id": kw["run_id"]}):
            first = article_analyses.ensure_adhoc_snapshot_run(3, when=morning)
            second = article_analyses.ensure_adhoc_snapshot_run(3, when=evening)
        self.assertEqual(first, second)

    def test_adhoc_run_never_collides_with_the_real_analysis_pipeline(self):
        """_fetch_pipeline_runs/list_pipeline_runs filter pipeline='analysis'
        for the run picker - a snapshot-only row must use a different value
        so it never appears there."""
        with patch("services.articles.article_analyses.config.DATABASE_URL", "postgres://x"), \
             patch("services.pipeline.pipeline_runs.create_pipeline_run", return_value={"id": "x"}) as create:
            article_analyses.ensure_adhoc_snapshot_run(3, when=datetime.now(timezone.utc))
        self.assertNotEqual(create.call_args.kwargs["pipeline"], "analysis")


class PointInTimeReconstructionTests(unittest.TestCase):
    def test_fetch_state_as_of_filters_by_cutoff_and_takes_latest_per_article(self):
        captured = {}

        def fake_fetch_all(sql, params):
            captured["sql"] = sql
            captured["params"] = params
            return [{"article_id": 1, "sentiment": "positive"}]

        cutoff = datetime(2026, 3, 5, tzinfo=timezone.utc)
        with patch.object(article_analyses, "_table_exists", return_value=True), \
             patch.object(article_analyses.db, "fetch_all", side_effect=fake_fetch_all):
            rows = article_analyses.fetch_state_as_of(3, cutoff)

        self.assertEqual(rows, [{"article_id": 1, "sentiment": "positive"}])
        self.assertEqual(captured["params"], (3, cutoff))
        self.assertIn("distinct on (an.article_id)", captured["sql"])
        self.assertIn("an.created_at <= %s", captured["sql"])
        self.assertIn("order by an.article_id, an.created_at desc", captured["sql"])

    def test_no_cutoff_or_missing_table_returns_empty(self):
        with patch.object(article_analyses, "_table_exists", return_value=False):
            self.assertEqual(article_analyses.fetch_state_as_of(3, datetime.now(timezone.utc)), [])
        with patch.object(article_analyses, "_table_exists", return_value=True):
            self.assertEqual(article_analyses.fetch_state_as_of(3, None), [])

    def test_reconstruction_failure_degrades_to_empty_not_a_raise(self):
        with patch.object(article_analyses, "_table_exists", return_value=True), \
             patch.object(article_analyses.db, "fetch_all", side_effect=RuntimeError("boom")):
            self.assertEqual(article_analyses.fetch_state_as_of(3, datetime.now(timezone.utc)), [])

    def test_earliest_snapshot_at_returns_none_when_nothing_recorded(self):
        with patch.object(article_analyses, "_table_exists", return_value=True), \
             patch.object(article_analyses.db, "fetch_one", return_value={"earliest": None}):
            self.assertIsNone(article_analyses.earliest_snapshot_at(3))

    def test_earliest_snapshot_at_missing_table_degrades_to_none(self):
        with patch.object(article_analyses, "_table_exists", return_value=False):
            self.assertIsNone(article_analyses.earliest_snapshot_at(3))


if __name__ == "__main__":
    unittest.main()
