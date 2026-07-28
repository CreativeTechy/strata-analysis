import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from services.competitors import competitor_analysis


class GenerateFindingTests(unittest.TestCase):
    """generate_finding()/generate_findings() do deferred
    `from services.competitors.business_profile_store import ...` /
    `from services.competitors.competitors_store import ...` imports inside
    the function body, not at module level - a bad import path there only
    breaks at call time, so these must actually invoke the functions (not
    just import the module) to catch it. Regression tests for a reorg that
    broke exactly this: the module-level import graph checked out fine while
    these deferred imports still pointed at pre-move module paths."""

    def test_generate_finding_returns_none_without_evidence(self):
        with patch("services.competitors.competitor_analysis.db.fetch_all", return_value=[]):
            result = competitor_analysis.generate_finding(
                {"name": "Us"}, {"id": 1, "project_id": 1, "name": "Them"}
            )
        self.assertIsNone(result)

    def test_generate_findings_reports_no_tracked_competitors(self):
        with patch(
            "services.competitors.business_profile_store.get_profile", return_value=None
        ), patch(
            "services.competitors.competitors_store.list_competitors", return_value=[]
        ):
            result = competitor_analysis.generate_findings(1)
        self.assertEqual(result["generated"], 0)
        self.assertIsNotNone(result["error"])


if __name__ == "__main__":
    unittest.main()
