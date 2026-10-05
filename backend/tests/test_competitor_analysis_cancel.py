import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from services.competitors import competitor_analysis as ca


class RunAnalysisJobCancelTests(unittest.TestCase):
    """A stop sets the run row to 'cancelled'; the background job must notice it
    at a checkpoint, finish as cancelled, and never overwrite it as success."""

    def _patch(self, **overrides):
        store = MagicMock()
        store.is_cancelled.return_value = False
        store.resolve_scope.return_value = [1]
        store.documents_with_scope.return_value = []
        store.logger.return_value = lambda *a, **k: None
        for key, value in overrides.items():
            setattr(store, key, value)
        update = MagicMock()
        patchers = [
            patch.object(ca, "analysis_runs_store", store),
            patch.object(ca, "update_pipeline_run", update),
            patch.object(ca, "upsert_pipeline_run_document_stats"),
            patch.object(ca, "extract_frequent_ideas_for_documents"),
            patch.object(ca, "_regenerate_idea_comparisons"),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)
        return store, update

    def test_run_stopped_before_start_is_not_revived(self):
        store, update = self._patch()
        store.is_cancelled.return_value = True
        with patch.object(ca, "generate_findings") as gen:
            ca.run_analysis_job(5, 1, "pending")
        gen.assert_not_called()
        store.mark_running.assert_not_called()
        self.assertEqual(update.call_args.kwargs["status"], "cancelled")

    def test_stop_during_findings_ends_run_cancelled_not_failed(self):
        store, update = self._patch()

        def stop_midway(*_args, should_cancel=None, **_kwargs):
            store.is_cancelled.return_value = True
            assert should_cancel()
            raise ca.AnalysisCancelled()

        with patch.object(ca, "generate_findings", side_effect=stop_midway):
            ca.run_analysis_job(5, 1, "pending")
        store.mark_success.assert_not_called()
        store.mark_failed.assert_not_called()
        store.record_covered_documents.assert_not_called()
        self.assertEqual(update.call_args.kwargs["status"], "cancelled")

    def test_stop_after_last_checkpoint_does_not_cover_documents(self):
        store, update = self._patch()
        store.mark_success.return_value = None  # row already cancelled
        result = {"generated": 1, "skipped": [], "validation": {}, "error": None}
        with patch.object(ca, "generate_findings", return_value=result):
            ca.run_analysis_job(5, 1, "pending")
        store.record_covered_documents.assert_not_called()
        self.assertEqual(update.call_args.kwargs["status"], "cancelled")

    def test_generate_findings_checkpoint_stops_before_any_llm_call(self):
        competitors = [{"id": 1, "name": "A"}]
        with patch("services.competitors.business_profile_store.get_profile", return_value={}), \
             patch("services.competitors.competitors_store.list_competitors", return_value=competitors), \
             patch.object(ca, "validate_competitor_articles", return_value={"per_competitor": {}}), \
             patch.object(ca, "generate_finding") as llm:
            with self.assertRaises(ca.AnalysisCancelled):
                ca.generate_findings(1, should_cancel=lambda: True)
        llm.assert_not_called()


if __name__ == "__main__":
    unittest.main()
