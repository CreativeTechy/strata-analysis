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


if __name__ == "__main__":
    unittest.main()
