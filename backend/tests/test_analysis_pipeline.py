"""The analysis run: what it selects, what it records, and how it ends.

These are the guarantees the dashboard's run pages read - live counters, a
per-document breakdown, and a terminal status that distinguishes "some articles
failed" from "the model host is unreachable and every article failed".
"""

import unittest
from unittest.mock import patch

from services.pipeline import pipeline
from services.pipeline import pipeline_runs


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
            patch.object(pipeline, "capture_run_snapshot", return_value=3),
            patch.object(pipeline, "generate_for_run", return_value={"claims": 2, "articles": 3}),
            patch.object(pipeline, "_queue_evidence_after_analysis"),
            # Serial execution: these assert on ordering and on cancellation
            # landing at a specific article, neither of which is meaningful
            # against a pool that has already dispatched the next one.
            patch.object(pipeline.config, "ANALYSIS_CONCURRENCY", 1),
        ]
        for patcher in self.patchers:
            patcher.start()

        pipeline._pending_followup.clear()

    def tearDown(self):
        for patcher in self.patchers:
            patcher.stop()
        pipeline._pending_followup.clear()

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
        pipeline.capture_run_snapshot.assert_called_once_with("run-1", 5)
        pipeline.generate_for_run.assert_not_called()
        pipeline._queue_evidence_after_analysis.assert_called_once_with("run-1", 5)

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
        self.assertEqual(final["stage"], "no_work")
        self.assertIn("No articles require analysis", final["message"])
        pipeline.generate_for_run.assert_not_called()
        pipeline._queue_evidence_after_analysis.assert_not_called()

    def test_evidence_failure_cannot_change_completed_analysis_status(self):
        with patch.object(pipeline, "generate_for_run", side_effect=RuntimeError("evidence failed")), \
             patch.object(pipeline.logger, "exception") as logged:
            pipeline._generate_evidence_after_analysis("run-1", 5)
        logged.assert_called_once()
        self.assertFalse(any(update.get("status") == "failed" for update in self.updates))

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

    def test_a_pending_followup_starts_once_the_run_finishes(self):
        """start_or_reuse_analysis_run() marks a project in _pending_followup
        when it's asked to queue work while a run is already active for it
        (its own work-set snapshot at `prepare` already missed that work) -
        this is the other half: a run that finishes normally must start
        exactly one follow-up run for a project left marked that way, when
        there is still pending work to justify it (_project_has_pending_articles)."""
        pipeline._pending_followup.add(5)
        rows = _rows((1, 10, "survey.pdf"))
        with patch.object(pipeline, "_select_articles", return_value=rows), \
             patch.object(pipeline, "reanalyze_article", return_value={"ok": True}), \
             patch.object(pipeline, "_project_has_pending_articles", return_value=True), \
             patch.object(pipeline, "start_or_reuse_analysis_run") as mock_start:
            pipeline.run_analysis_pipeline("run-1", project_id=5)

        mock_start.assert_called_once_with(5)
        self.assertNotIn(5, pipeline._pending_followup)

    def test_no_followup_when_nothing_was_marked_pending(self):
        rows = _rows((1, 10, "survey.pdf"))
        with patch.object(pipeline, "_select_articles", return_value=rows), \
             patch.object(pipeline, "reanalyze_article", return_value={"ok": True}), \
             patch.object(pipeline, "_project_has_pending_articles") as mock_has_pending, \
             patch.object(pipeline, "start_or_reuse_analysis_run") as mock_start:
            pipeline.run_analysis_pipeline("run-1", project_id=5)

        mock_start.assert_not_called()
        # The existence check only exists to save a wasted run when there IS
        # a mark to act on - nothing was marked here, so it must not even run.
        mock_has_pending.assert_not_called()

    def test_no_followup_when_marked_but_nothing_is_actually_pending(self):
        """The run that just finished, and the caller that marked the
        project, can both have raced over the exact same small batch of
        articles - already fully covered by the run that just finished. The
        mark alone doesn't mean work is still outstanding."""
        pipeline._pending_followup.add(5)
        rows = _rows((1, 10, "survey.pdf"))
        with patch.object(pipeline, "_select_articles", return_value=rows), \
             patch.object(pipeline, "reanalyze_article", return_value={"ok": True}), \
             patch.object(pipeline, "_project_has_pending_articles", return_value=False), \
             patch.object(pipeline, "start_or_reuse_analysis_run") as mock_start:
            pipeline.run_analysis_pipeline("run-1", project_id=5)

        mock_start.assert_not_called()
        self.assertNotIn(5, pipeline._pending_followup)

    def test_a_cancelled_run_does_not_start_a_followup(self):
        """A user-cancelled run must not immediately restart itself, even if
        work was marked pending for the project while it was running."""
        pipeline._pending_followup.add(5)

        def analyze(article_id, run_id=None):
            pipeline.cancel_pipeline_run("run-1")
            return {"ok": True}

        rows = _rows((1, 10, "a.pdf"), (2, 10, "a.pdf"))
        with patch.object(pipeline, "_select_articles", return_value=rows), \
             patch.object(pipeline, "reanalyze_article", side_effect=analyze), \
             patch.object(pipeline, "start_or_reuse_analysis_run") as mock_start:
            pipeline.run_analysis_pipeline("run-1", project_id=5)

        self.assertEqual(self._final()["status"], "cancelled")
        mock_start.assert_not_called()
        # Left marked - a caller that already asked for this project's
        # analysis while it was cancelled should still get it once something
        # starts a run again, just not automatically from here.
        self.assertIn(5, pipeline._pending_followup)


class StartOrReuseAnalysisRunTests(unittest.TestCase):
    def setUp(self):
        pipeline._pending_followup.clear()

    def tearDown(self):
        pipeline._pending_followup.clear()

    def test_reusing_an_active_run_marks_the_project_for_followup(self):
        # get_active_run_for_project is checked more than once now (the
        # self-drain re-check below) - returning the same active run every
        # time simulates it staying active throughout, so the re-check finds
        # nothing to do and the original "active" result stands.
        with patch.object(pipeline, "get_active_run_for_project", return_value={"id": "run-active"}):
            result = pipeline.start_or_reuse_analysis_run(5)

        self.assertEqual(result, {"run_id": "run-active", "started": False})
        self.assertIn(5, pipeline._pending_followup)

    def test_starting_a_fresh_run_does_not_mark_followup(self):
        with patch.object(pipeline, "get_active_run_for_project", return_value=None), \
             patch.object(pipeline, "create_pipeline_run", return_value={"id": "run-new"}), \
             patch.object(pipeline.threading, "Thread") as mock_thread:
            result = pipeline.start_or_reuse_analysis_run(5)

        self.assertEqual(result, {"run_id": "run-new", "started": True})
        self.assertNotIn(5, pipeline._pending_followup)
        mock_thread.assert_called_once()

    def test_a_run_that_finishes_between_the_active_check_and_the_mark_still_gets_a_followup(self):
        """Reproduces the race a stranded mark would come from: the run seen
        as active on the first check can finish - and _maybe_start_followup
        can drain an empty _pending_followup - in the window between that
        first check and the mark being written. The self-drain re-check in
        start_or_reuse_analysis_run must rescue its own mark instead of
        leaving it stranded with nothing left to notice it."""
        calls = {"n": 0}

        def get_active_run(project_id):
            calls["n"] += 1
            # Only the very first check (before the mark is written) sees the
            # run as active - every check after that (the self-drain
            # re-check, and _maybe_start_followup's own inner
            # start_or_reuse_analysis_run call) sees it as already finished.
            return {"id": "run-R"} if calls["n"] == 1 else None

        with patch.object(pipeline, "get_active_run_for_project", side_effect=get_active_run), \
             patch.object(pipeline, "_project_has_pending_articles", return_value=True), \
             patch.object(pipeline, "create_pipeline_run", return_value={"id": "run-followup"}) as mock_create, \
             patch.object(pipeline.threading, "Thread") as mock_thread:
            pipeline.start_or_reuse_analysis_run(5)

        # A new run was actually created and started - the mark was rescued,
        # not stranded with nothing left to drain it.
        mock_create.assert_called_once_with(
            status="queued", stage="queued", message="Queued for execution.", project_id=5
        )
        mock_thread.assert_called_once()
        self.assertNotIn(5, pipeline._pending_followup)

    def test_maybe_start_followup_starts_exactly_one_run_and_clears_the_flag(self):
        pipeline._pending_followup.add(5)
        with patch.object(pipeline, "_project_has_pending_articles", return_value=True), \
             patch.object(pipeline, "start_or_reuse_analysis_run") as mock_start:
            pipeline._maybe_start_followup(5)
            pipeline._maybe_start_followup(5)  # nothing left pending the 2nd time

        mock_start.assert_called_once_with(5)
        self.assertNotIn(5, pipeline._pending_followup)

    def test_maybe_start_followup_is_a_noop_when_nothing_pending(self):
        with patch.object(pipeline, "_project_has_pending_articles") as mock_has_pending, \
             patch.object(pipeline, "start_or_reuse_analysis_run") as mock_start:
            pipeline._maybe_start_followup(5)

        mock_start.assert_not_called()
        mock_has_pending.assert_not_called()

    def test_maybe_start_followup_is_a_noop_when_marked_but_nothing_pending(self):
        pipeline._pending_followup.add(5)
        with patch.object(pipeline, "_project_has_pending_articles", return_value=False), \
             patch.object(pipeline, "start_or_reuse_analysis_run") as mock_start:
            pipeline._maybe_start_followup(5)

        mock_start.assert_not_called()
        self.assertNotIn(5, pipeline._pending_followup)


class ProjectHasPendingArticlesTests(unittest.TestCase):
    def test_true_when_the_query_reports_a_pending_article(self):
        with patch.object(pipeline.db, "fetch_one", return_value={"has_pending": True}):
            self.assertTrue(pipeline._project_has_pending_articles(5))

    def test_false_when_the_query_reports_none_pending(self):
        with patch.object(pipeline.db, "fetch_one", return_value={"has_pending": False}):
            self.assertFalse(pipeline._project_has_pending_articles(5))

    def test_fails_open_on_a_database_error(self):
        """This check only exists to save a wasted follow-up run - skipping
        one because the check itself broke would silently reintroduce the
        stranded-work failure the follow-up mechanism exists to prevent."""
        with patch.object(pipeline.db, "fetch_one", side_effect=RuntimeError("boom")):
            self.assertTrue(pipeline._project_has_pending_articles(5))


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


class PipelineRunEligibilityTests(unittest.TestCase):
    def test_zero_result_run_is_not_eligible_for_dashboard_analytics(self):
        run = pipeline_runs._normalize({"id": "run-1", "pipeline": "analysis", "analysis_result_count": 0})
        self.assertFalse(run["analytics_eligible"])

    def test_saved_analysis_results_make_run_eligible(self):
        run = pipeline_runs._normalize({"id": "run-2", "pipeline": "analysis", "analysis_result_count": 12})
        self.assertTrue(run["analytics_eligible"])
        self.assertEqual(run["analysis_result_count"], 12)


if __name__ == "__main__":
    unittest.main()
