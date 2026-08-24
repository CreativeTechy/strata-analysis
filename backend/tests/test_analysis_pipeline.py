"""The analysis run: what it selects, what it records, and how it ends.

These are the guarantees the dashboard's run pages read - live counters, a
per-document breakdown, and a terminal status that distinguishes "some articles
failed" from "the model host is unreachable and every article failed".
"""

import unittest
from unittest.mock import patch

from services.pipeline import pipeline


def _rows(*specs):
    """(article_id, document_id, document_name) tuples as _select_articles returns them."""
    return [{"id": aid, "document_id": did, "document": name} for aid, did, name in specs]


class RunAnalysisPipelineTests(unittest.TestCase):
    def setUp(self):
        self.updates = []
        self.documents = {}
        self.completions = []

        def record_update(run_id, **fields):
            self.updates.append(fields)
            return None

        def record_documents(run_id, stats):
            for label, counts in (stats or {}).items():
                self.documents[label] = dict(counts)

        self.patchers = [
            patch.object(pipeline, "update_pipeline_run", side_effect=record_update),
            patch.object(pipeline, "upsert_pipeline_run_document_stats", side_effect=record_documents),
            patch.object(pipeline, "record_run_completion",
                         side_effect=lambda pid, **kw: self.completions.append(kw)),
            patch.object(pipeline, "mark_processing"),
            # Serial execution: these assert on ordering and on cancellation
            # landing at a specific article, neither of which is meaningful
            # against a pool that has already dispatched the next one.
            patch.object(pipeline.config, "ANALYSIS_CONCURRENCY", 1),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self):
        for patcher in self.patchers:
            patcher.stop()

    def _final(self):
        """The terminal update - the one carrying finished_at."""
        return next(u for u in reversed(self.updates) if "finished_at" in u)

    def test_successful_run_counts_and_attributes_every_article(self):
        rows = _rows((1, 10, "survey.pdf"), (2, 10, "survey.pdf"), (3, 11, "interviews.docx"))
        with patch.object(pipeline, "_select_articles", return_value=rows), \
             patch.object(pipeline, "reanalyze_article", return_value={"ok": True}):
            pipeline.run_analysis_pipeline("run-1", project_id=5)

        final = self._final()
        self.assertEqual(final["status"], "success")
        self.assertEqual(final["articles_analyzed"], 3)
        self.assertEqual(final["articles_failed"], 0)
        self.assertEqual(self.documents["survey.pdf"]["selected"], 2)
        self.assertEqual(self.documents["survey.pdf"]["analyzed"], 2)
        self.assertEqual(self.documents["interviews.docx"]["analyzed"], 1)
        self.assertEqual(self.completions[-1]["status"], "success")

    def test_articles_without_a_document_are_grouped_rather_than_dropped(self):
        """A JSONL import has no document behind it, but its articles still have
        to appear in the run's breakdown - a total that doesn't add up reads as
        a bug in the run, not as a difference in provenance."""
        rows = _rows((1, None, None), (2, 10, "survey.pdf"))
        with patch.object(pipeline, "_select_articles", return_value=rows), \
             patch.object(pipeline, "reanalyze_article", return_value={"ok": True}):
            pipeline.run_analysis_pipeline("run-1", project_id=5)

        self.assertEqual(self.documents[pipeline.UNATTRIBUTED]["selected"], 1)
        self.assertEqual(self.documents[pipeline.UNATTRIBUTED]["analyzed"], 1)

    def test_partial_failure_is_still_a_successful_run_but_carries_the_reason(self):
        rows = _rows((1, 10, "survey.pdf"), (2, 10, "survey.pdf"))
        results = iter([
            {"ok": True},
            {"ok": False, "analysis_error": "structured extraction failed"},
        ])
        with patch.object(pipeline, "_select_articles", return_value=rows), \
             patch.object(pipeline, "reanalyze_article", side_effect=lambda *a, **k: next(results)):
            pipeline.run_analysis_pipeline("run-1", project_id=5)

        final = self._final()
        self.assertEqual(final["status"], "success")
        self.assertEqual(final["articles_failed"], 1)
        self.assertIn("1 failed", final["message"])
        self.assertIn("structured extraction failed", self.documents["survey.pdf"]["note"])

    def test_every_article_failing_fails_the_run(self):
        """That is what an unreachable local model looks like from here, and
        reporting it as a success with a footnote hides it."""
        rows = _rows((1, 10, "survey.pdf"))
        with patch.object(pipeline, "_select_articles", return_value=rows), \
             patch.object(pipeline, "reanalyze_article",
                          return_value={"ok": False, "analysis_error": "connection refused"}):
            pipeline.run_analysis_pipeline("run-1", project_id=5)

        final = self._final()
        self.assertEqual(final["status"], "failed")
        self.assertTrue(final["error"])
        self.assertEqual(self.completions[-1]["status"], "failed")

    def test_nothing_to_analyze_succeeds_and_says_so(self):
        with patch.object(pipeline, "_select_articles", return_value=[]), \
             patch.object(pipeline, "reanalyze_article") as analyze:
            pipeline.run_analysis_pipeline("run-1", project_id=5)

        analyze.assert_not_called()
        final = self._final()
        self.assertEqual(final["status"], "success")
        self.assertIn("Nothing to analyze", final["message"])

    def test_a_stop_lands_at_the_next_article_boundary(self):
        """Cancellation can't interrupt an in-flight model call, so the contract
        is that no *further* article is analyzed once stop is requested."""
        rows = _rows((1, 10, "a.pdf"), (2, 10, "a.pdf"), (3, 10, "a.pdf"))
        analyzed = []

        def analyze(article_id, run_id=None):
            analyzed.append(article_id)
            pipeline.cancel_pipeline_run("run-1")
            return {"ok": True}

        with patch.object(pipeline, "_select_articles", return_value=rows), \
             patch.object(pipeline, "reanalyze_article", side_effect=analyze):
            pipeline.run_analysis_pipeline("run-1", project_id=5)

        self.assertEqual(analyzed, [1])
        final = self._final()
        self.assertEqual(final["status"], "cancelled")
        self.assertTrue(final["cancelled_at"])

    def test_a_run_cancelled_before_it_starts_never_analyzes_anything(self):
        pipeline.cancel_pipeline_run("run-2")
        with patch.object(pipeline, "_select_articles") as select:
            pipeline.run_analysis_pipeline("run-2", project_id=5)

        select.assert_not_called()
        self.assertEqual(self._final()["status"], "cancelled")

    def test_cancellation_does_not_leak_into_the_next_run_with_the_same_id(self):
        pipeline.cancel_pipeline_run("run-3")
        with patch.object(pipeline, "_select_articles", return_value=[]):
            pipeline.run_analysis_pipeline("run-3", project_id=5)
            self.assertEqual(self._final()["status"], "cancelled")

            self.updates.clear()
            pipeline.run_analysis_pipeline("run-3", project_id=5)
            self.assertEqual(self._final()["status"], "success")

    def test_a_run_without_a_project_fails_instead_of_analyzing_everything(self):
        with patch.object(pipeline, "_select_articles") as select:
            pipeline.run_analysis_pipeline("run-4", project_id=None)

        select.assert_not_called()
        self.assertEqual(self._final()["status"], "failed")

    def test_the_run_id_is_passed_to_every_article_it_analyzes(self):
        """Articles carry the run that analyzed them, which is what per-run
        report scoping filters on."""
        rows = _rows((1, 10, "a.pdf"), (2, 10, "a.pdf"))
        with patch.object(pipeline, "_select_articles", return_value=rows), \
             patch.object(pipeline, "reanalyze_article", return_value={"ok": True}) as analyze:
            pipeline.run_analysis_pipeline("run-5", project_id=5)

        self.assertEqual([call.kwargs["run_id"] for call in analyze.call_args_list], ["run-5", "run-5"])


class SelectArticlesTests(unittest.TestCase):
    """The prepare stage's SQL is built from `scope`; what matters is that
    "pending" narrows to unfinished analysis and "all" does not narrow at all."""

    def _query_for(self, scope):
        with patch.object(pipeline.db, "fetch_all", return_value=[]) as fetch:
            pipeline._select_articles(5, scope)
        return fetch.call_args[0][0], fetch.call_args[0][1]

    def test_pending_scope_filters_on_analysis_status(self):
        query, params = self._query_for("pending")
        self.assertIn("analysis_status", query)
        self.assertEqual(params[0], 5)
        self.assertEqual(params[1], list(pipeline.PENDING_STATUSES))

    def test_all_scope_takes_everything_linked_to_the_project(self):
        query, params = self._query_for("all")
        self.assertNotIn("analysis_status", query)
        self.assertEqual(params, (5,))


if __name__ == "__main__":
    unittest.main()
