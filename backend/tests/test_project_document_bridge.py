"""Unit tests for services/competitors/project_document_bridge.py.

Covers: a no-op on a non-competitor project (nothing is queried/written),
mirroring a competitor-mode project's project_documents/
project_document_articles rows into competitor_documents/
competitor_document_articles via the on-conflict upsert, that upsert never
overwriting a mirror's own status, propagating a source candidate leaving
'approved' onto a mirror that hasn't been independently reviewed, an
excluded (deleted-then-resynced) document being skipped entirely, and
refresh_competitors_from_mirrored_evidence() (the derive_competitors() call,
kept separate from the mirror itself so a caller can run it in the
background - see project_documents_store.sync_competitor_evidence_after_approval)
being best-effort.
"""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from services.competitors import project_document_bridge


class SyncProjectDocumentsIntoCompetitorEvidenceTests(unittest.TestCase):
    def test_noop_for_a_non_competitor_project(self):
        with patch.object(project_document_bridge.projects_store, "get_project", return_value={"mode": "sentiment"}), \
             patch.object(project_document_bridge.db, "fetch_all") as mock_fetch_all:
            project_document_bridge.sync_project_documents_into_competitor_evidence(2)

        mock_fetch_all.assert_not_called()

    def test_noop_when_project_does_not_exist(self):
        with patch.object(project_document_bridge.projects_store, "get_project", return_value=None), \
             patch.object(project_document_bridge.db, "fetch_all") as mock_fetch_all:
            project_document_bridge.sync_project_documents_into_competitor_evidence(999)

        mock_fetch_all.assert_not_called()

    def test_noop_when_project_has_no_project_documents(self):
        with patch.object(project_document_bridge.projects_store, "get_project", return_value={"mode": "competitor"}), \
             patch.object(project_document_bridge.db, "fetch_all", return_value=[]), \
             patch.object(project_document_bridge.db, "fetch_one") as mock_fetch_one:
            project_document_bridge.sync_project_documents_into_competitor_evidence(2)

        mock_fetch_one.assert_not_called()

    def test_mirrors_each_document_and_its_approved_candidates(self):
        documents = [{"id": 3, "original_filename": "coffee_shops.jsonl"}]
        with patch.object(project_document_bridge.projects_store, "get_project", return_value={"mode": "competitor"}), \
             patch.object(project_document_bridge.db, "fetch_all", return_value=documents) as mock_fetch_all, \
             patch.object(project_document_bridge.db, "fetch_one", return_value={"id": 55}) as mock_fetch_one, \
             patch.object(project_document_bridge.db, "execute") as mock_execute:
            project_document_bridge.sync_project_documents_into_competitor_evidence(2)

        # The project_documents query itself excludes any document the user
        # opted out of the mirror (see test_skips_a_document_excluded_from_the_mirror).
        documents_sql = mock_fetch_all.call_args[0][0]
        self.assertIn("not competitor_mirror_excluded", documents_sql)

        # The mirrored competitor_documents upsert ran with a synthetic,
        # non-real storage_path and the source_project_document_id back-ref.
        mirror_sql, mirror_params = mock_fetch_one.call_args[0]
        self.assertIn("insert into competitor_documents", mirror_sql)
        self.assertIn("on conflict (source_project_document_id)", mirror_sql)
        self.assertEqual(mirror_params, (2, "coffee_shops.jsonl", "mirrored:project-document/3", 3))

        # Two execute() calls per document: the candidate mirror upsert, then
        # the rejection-propagation update. No derive_competitors() call here
        # any more - see RefreshCompetitorsFromMirroredEvidenceTests.
        self.assertEqual(mock_execute.call_count, 2)
        candidate_sql, candidate_params = mock_execute.call_args_list[0][0]
        self.assertIn("insert into competitor_document_articles", candidate_sql)
        self.assertIn("status = 'approved'", candidate_sql)
        self.assertEqual(candidate_params, (55, 3))

        # The upsert's on-conflict clause must never touch status - only a
        # mirror's article_id is refreshed, so a competitor-side review
        # decision (approved or rejected) on that candidate is never undone.
        conflict_clause = candidate_sql.split("on conflict")[1]
        self.assertNotIn("status", conflict_clause)
        self.assertIn("article_id = excluded.article_id", conflict_clause)

        propagate_sql, propagate_params = mock_execute.call_args_list[1][0]
        self.assertIn("update competitor_document_articles", propagate_sql)
        self.assertIn("status = 'rejected'", propagate_sql)
        self.assertIn("pda.status != 'approved'", propagate_sql)
        self.assertIn("cda.status = 'approved'", propagate_sql)
        self.assertEqual(propagate_params, (3,))

    def test_skips_a_document_excluded_from_the_mirror(self):
        """A document the user removed from the competitor study (deleting its
        mirror sets project_documents.competitor_mirror_excluded) must not be
        recreated by a later sync - the query itself filters it out, so
        nothing else in the loop ever runs for it."""
        with patch.object(project_document_bridge.projects_store, "get_project", return_value={"mode": "competitor"}), \
             patch.object(project_document_bridge.db, "fetch_all", return_value=[]) as mock_fetch_all, \
             patch.object(project_document_bridge.db, "fetch_one") as mock_fetch_one:
            project_document_bridge.sync_project_documents_into_competitor_evidence(2)

        mock_fetch_all.assert_called_once()
        self.assertIn("competitor_mirror_excluded", mock_fetch_all.call_args[0][0])
        mock_fetch_one.assert_not_called()


class RefreshCompetitorsFromMirroredEvidenceTests(unittest.TestCase):
    """The competitor-naming pass, split out from the mirror sync itself so a
    caller with a FastAPI BackgroundTasks can schedule it off the request
    (see project_documents_store.sync_competitor_evidence_after_approval)."""

    def test_calls_derive_competitors(self):
        with patch.object(project_document_bridge.document_analysis, "derive_competitors") as mock_derive:
            project_document_bridge.refresh_competitors_from_mirrored_evidence(2)

        mock_derive.assert_called_once_with(2)

    def test_derive_competitors_failure_does_not_raise(self):
        with patch.object(project_document_bridge.document_analysis, "derive_competitors",
                           side_effect=RuntimeError("boom")):
            project_document_bridge.refresh_competitors_from_mirrored_evidence(2)  # must not raise


if __name__ == "__main__":
    unittest.main()
