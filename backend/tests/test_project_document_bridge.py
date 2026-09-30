"""Unit tests for services/competitors/project_document_bridge.py.

Covers: a no-op on a non-competitor project (nothing is queried/written),
mirroring a competitor-mode project's project_documents/
project_document_articles rows into competitor_documents/
competitor_document_articles via the on-conflict upsert, and
derive_competitors() being called (best-effort) after the mirror.
"""

import os
import unittest
from unittest.mock import call, patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from services.competitors import project_document_bridge


class SyncProjectDocumentsIntoCompetitorEvidenceTests(unittest.TestCase):
    def test_noop_for_a_non_competitor_project(self):
        with patch.object(project_document_bridge.projects_store, "get_project", return_value={"mode": "sentiment"}), \
             patch.object(project_document_bridge.db, "fetch_all") as mock_fetch_all, \
             patch.object(project_document_bridge.document_analysis, "derive_competitors") as mock_derive:
            project_document_bridge.sync_project_documents_into_competitor_evidence(2)

        mock_fetch_all.assert_not_called()
        mock_derive.assert_not_called()

    def test_noop_when_project_does_not_exist(self):
        with patch.object(project_document_bridge.projects_store, "get_project", return_value=None), \
             patch.object(project_document_bridge.db, "fetch_all") as mock_fetch_all:
            project_document_bridge.sync_project_documents_into_competitor_evidence(999)

        mock_fetch_all.assert_not_called()

    def test_noop_when_project_has_no_project_documents(self):
        with patch.object(project_document_bridge.projects_store, "get_project", return_value={"mode": "competitor"}), \
             patch.object(project_document_bridge.db, "fetch_all", return_value=[]), \
             patch.object(project_document_bridge.db, "fetch_one") as mock_fetch_one, \
             patch.object(project_document_bridge.document_analysis, "derive_competitors") as mock_derive:
            project_document_bridge.sync_project_documents_into_competitor_evidence(2)

        mock_fetch_one.assert_not_called()
        mock_derive.assert_not_called()

    def test_mirrors_each_document_and_its_approved_candidates(self):
        documents = [{"id": 3, "original_filename": "coffee_shops.jsonl"}]
        with patch.object(project_document_bridge.projects_store, "get_project", return_value={"mode": "competitor"}), \
             patch.object(project_document_bridge.db, "fetch_all", return_value=documents), \
             patch.object(project_document_bridge.db, "fetch_one", return_value={"id": 55}) as mock_fetch_one, \
             patch.object(project_document_bridge.db, "execute") as mock_execute, \
             patch.object(project_document_bridge.document_analysis, "derive_competitors") as mock_derive:
            project_document_bridge.sync_project_documents_into_competitor_evidence(2)

        # The mirrored competitor_documents upsert ran with a synthetic,
        # non-real storage_path and the source_project_document_id back-ref.
        mirror_sql, mirror_params = mock_fetch_one.call_args[0]
        self.assertIn("insert into competitor_documents", mirror_sql)
        self.assertIn("on conflict (source_project_document_id)", mirror_sql)
        self.assertEqual(mirror_params, (2, "coffee_shops.jsonl", "mirrored:project-document/3", 3))

        # The candidate mirror ran against the returned mirrored document id (55).
        candidate_sql, candidate_params = mock_execute.call_args[0]
        self.assertIn("insert into competitor_document_articles", candidate_sql)
        self.assertIn("status = 'approved'", candidate_sql)
        self.assertEqual(candidate_params, (55, 3))

        mock_derive.assert_called_once_with(2)

    def test_derive_competitors_failure_does_not_raise(self):
        with patch.object(project_document_bridge.projects_store, "get_project", return_value={"mode": "competitor"}), \
             patch.object(project_document_bridge.db, "fetch_all", return_value=[{"id": 3, "original_filename": "f.jsonl"}]), \
             patch.object(project_document_bridge.db, "fetch_one", return_value={"id": 55}), \
             patch.object(project_document_bridge.db, "execute"), \
             patch.object(project_document_bridge.document_analysis, "derive_competitors", side_effect=RuntimeError("boom")):
            project_document_bridge.sync_project_documents_into_competitor_evidence(2)  # must not raise


if __name__ == "__main__":
    unittest.main()
