import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from services.competitors import document_analysis


class AnalyzeDocumentsIdeaComparisonsTests(unittest.TestCase):
    """analyze_documents() is the synchronous (non-run-tracked) analysis path
    document-based studies use before any competitor is tracked - the other
    caller of generate_findings besides competitor_analysis.run_analysis_job.
    It has no document-scope picker of its own, so frequent-ideas extraction
    here must run over the whole project (document_ids=None), not a specific
    document set."""

    def _run(self, derived, generate_result):
        with patch.object(document_analysis, "derive_competitors", return_value=derived), \
             patch.object(document_analysis, "extract_frequent_ideas_for_documents") as extract_ideas, \
             patch.object(document_analysis.competitor_analysis, "generate_findings", return_value=generate_result), \
             patch.object(document_analysis.competitor_analysis, "_regenerate_idea_comparisons") as regenerate_ideas:
            result = document_analysis.analyze_documents(7)
        return result, extract_ideas, regenerate_ideas

    def test_successful_run_extracts_ideas_project_wide_and_regenerates_comparisons(self):
        derived = {"competitors": [{"id": 1, "name": "Acme"}], "considered": 3, "error": None}
        generate_result = {"generated": 1, "skipped": [], "validation": {}, "error": None}
        result, extract_ideas, regenerate_ideas = self._run(derived, generate_result)

        extract_ideas.assert_called_once_with(7)
        regenerate_ideas.assert_called_once_with(7)
        self.assertIsNone(result["error"])

    def test_failed_generation_does_not_regenerate_comparisons(self):
        derived = {"competitors": [{"id": 1, "name": "Acme"}], "considered": 3, "error": None}
        generate_result = {
            "generated": 0, "skipped": [], "validation": {},
            "error": "Insufficient balance", "error_code": "llm_quota_exceeded",
        }
        result, extract_ideas, regenerate_ideas = self._run(derived, generate_result)

        extract_ideas.assert_called_once_with(7)
        regenerate_ideas.assert_not_called()
        self.assertEqual(result["error"], "Insufficient balance")


if __name__ == "__main__":
    unittest.main()
