import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from llm_client import LLMQuotaError
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

    def test_generate_findings_surfaces_llm_error_instead_of_false_success(self):
        """A provider failure (e.g. DeepSeek 402 insufficient balance) must not
        be reported the same way as "no evidence this period" - the caller
        needs to know the AI call itself failed, not that there was nothing
        to say."""
        competitor = {"id": 1, "project_id": 1, "name": "Them"}
        validation = {
            "scanned": 5, "linked": 0,
            "per_competitor": {1: {"valid": 1, "rejected": 0, "stories": 1}},
            "rejection_reasons": {}, "period_days": 30,
        }
        with patch(
            "services.competitors.business_profile_store.get_profile", return_value={"name": "Us"}
        ), patch(
            "services.competitors.competitors_store.list_competitors", return_value=[competitor]
        ), patch.object(
            competitor_analysis, "validate_competitor_articles", return_value=validation
        ), patch.object(
            competitor_analysis, "generate_finding",
            side_effect=LLMQuotaError("402 error for url: https://api.deepseek.com/v1/chat/completions - Insufficient Balance"),
        ):
            result = competitor_analysis.generate_findings(1)

        self.assertEqual(result["generated"], 0)
        self.assertIsNotNone(result["error"])
        self.assertEqual(result["error_code"], "llm_quota_exceeded")


if __name__ == "__main__":
    unittest.main()
