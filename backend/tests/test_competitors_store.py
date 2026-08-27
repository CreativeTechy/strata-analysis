import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from services.competitors import competitors_store


class GetStudyTests(unittest.TestCase):
    def test_returns_the_row_by_id(self):
        row = {"id": 5, "name": "Study", "mode": "competitor", "status": "active",
               "last_run_at": None, "last_run_status": None}
        with patch("services.competitors.competitors_store.db.fetch_one", return_value=row) as mock_fetch_one:
            result = competitors_store.get_study(5)
        self.assertEqual(result, row)
        sql, params = mock_fetch_one.call_args[0]
        self.assertIn("from projects", sql)
        self.assertEqual(params, (5,))

    def test_returns_none_when_missing(self):
        with patch("services.competitors.competitors_store.db.fetch_one", return_value=None):
            self.assertIsNone(competitors_store.get_study(999))


class ListStudiesTests(unittest.TestCase):
    def test_dedupes_findings_per_competitor_and_excludes_rejected(self):
        """Regression coverage for the rewritten query: finding_count must
        match the study's own findings grid - one card per competitor, the
        newest, excluding rejected ones - not every generation event
        competitor_findings has ever accumulated."""
        with patch("services.competitors.competitors_store.db.fetch_all", return_value=[]) as mock_fetch_all:
            competitors_store.list_studies()
        sql = mock_fetch_all.call_args[0][0]
        self.assertIn("distinct on (competitor_id)", sql)
        self.assertIn("validation_status != 'rejected'", sql)
        self.assertIn("where p.mode = 'competitor'", sql)


class CreateStudyTests(unittest.TestCase):
    def test_inserts_a_competitor_mode_project(self):
        row = {"id": 1, "name": "Acme Study", "mode": "competitor", "status": "active", "created_at": "now"}
        with patch("services.competitors.competitors_store.db.fetch_one", return_value=row) as mock_fetch_one:
            result = competitors_store.create_study("Acme Study", "active", None)
        self.assertEqual(result, row)
        sql, params = mock_fetch_one.call_args[0]
        self.assertIn("insert into projects", sql)
        self.assertIn("'competitor'", sql)
        self.assertEqual(params, ("Acme Study", "active", None))


class UpdateStudyTests(unittest.TestCase):
    def test_updates_only_competitor_mode_projects(self):
        row = {"id": 5, "name": "Renamed", "mode": "competitor", "status": "active",
               "description": None, "created_at": "now", "updated_at": "now"}
        with patch("services.competitors.competitors_store.db.fetch_one", return_value=row) as mock_fetch_one:
            result = competitors_store.update_study(5, "Renamed", "active", None)
        self.assertEqual(result, row)
        sql, params = mock_fetch_one.call_args[0]
        self.assertIn("mode = 'competitor'", sql)
        self.assertEqual(params, ("Renamed", "active", None, 5))

    def test_returns_none_when_not_found(self):
        with patch("services.competitors.competitors_store.db.fetch_one", return_value=None):
            self.assertIsNone(competitors_store.update_study(999, "x", "active", None))


if __name__ == "__main__":
    unittest.main()
