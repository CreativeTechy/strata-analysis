import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from services.competitors import analysis_runs_store


class ResolveScopeTests(unittest.TestCase):
    """resolve_scope() is what actually decides which documents a run reads -
    every branch is exercised against the same fixture: three documents, one
    with no approved articles at all, one already covered by a completed run,
    one that is genuinely new."""

    DOCUMENTS = [
        {"id": 1, "original_filename": "a.pdf", "approved_article_count": 3, "analyzed": True},
        {"id": 2, "original_filename": "b.pdf", "approved_article_count": 2, "analyzed": False},
        {"id": 3, "original_filename": "c.pdf", "approved_article_count": 0, "analyzed": False},
    ]

    def test_all_scope_includes_every_document_with_approved_articles(self):
        with patch.object(analysis_runs_store, "documents_with_scope", return_value=self.DOCUMENTS):
            self.assertEqual(analysis_runs_store.resolve_scope(1, "all"), [1, 2])

    def test_pending_scope_excludes_already_analyzed_documents(self):
        with patch.object(analysis_runs_store, "documents_with_scope", return_value=self.DOCUMENTS):
            self.assertEqual(analysis_runs_store.resolve_scope(1, "pending"), [2])

    def test_selected_scope_is_restricted_to_eligible_documents(self):
        """A hand-picked id with nothing approved, or one that doesn't belong
        to this study at all, must not sneak evidence in."""
        with patch.object(analysis_runs_store, "documents_with_scope", return_value=self.DOCUMENTS):
            self.assertEqual(analysis_runs_store.resolve_scope(1, "selected", [1, 3, 999]), [1])

    def test_pending_scope_with_nothing_new_resolves_to_empty(self):
        all_analyzed = [{**doc, "analyzed": True} for doc in self.DOCUMENTS if doc["approved_article_count"]]
        with patch.object(analysis_runs_store, "documents_with_scope", return_value=all_analyzed):
            self.assertEqual(analysis_runs_store.resolve_scope(1, "pending"), [])


class AnalyzedDocumentIdsTests(unittest.TestCase):
    def test_only_successful_runs_count_as_coverage(self):
        """A failed or still-running run never durably covered anything - see
        run_analysis_job, which only records coverage after a success."""
        with patch.object(analysis_runs_store.db, "fetch_all", return_value=[{"document_id": 4}]) as fetch_all:
            result = analysis_runs_store.analyzed_document_ids(1)

        sql = fetch_all.call_args[0][0]
        self.assertIn("r.status = 'success'", sql)
        self.assertEqual(result, {4})


if __name__ == "__main__":
    unittest.main()
