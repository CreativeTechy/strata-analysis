import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import config
import llm_client
from analysis import demographics_detection


class DetectDemographicsDefaultModeTests(unittest.TestCase):
    """config.DEMOGRAPHICS_LLM_FALLBACK == "off" (the default) delegates to
    aggregation.compute_dominant_demographics - see test_analysis_aggregation.py
    for that function's own majority-vote behavior."""

    def test_majority_vote_over_people_opinions(self):
        result = demographics_detection.detect_demographics(
            title="t", text="x",
            people_opinions=[{"gender": "female", "age_range": "25-34"}, {"gender": "female"}],
        )
        self.assertEqual(result["gender"], "female")
        self.assertEqual(result["age_range"], "25-34")

    def test_no_opinions_stays_unknown(self):
        result = demographics_detection.detect_demographics(title="t", text="x", people_opinions=[])
        self.assertEqual(result["gender"], "unknown")
        self.assertEqual(result["age_range"], "unknown")

    @patch("analysis.llm_fallback.llm_client.chat_completion")
    def test_llm_never_called_in_default_mode(self, mock_chat):
        demographics_detection.detect_demographics(title="t", text="x", people_opinions=[])
        mock_chat.assert_not_called()


class LlmOnlyDemographicsModeTests(unittest.TestCase):
    """config.DEMOGRAPHICS_LLM_FALLBACK == "on" bypasses the majority vote
    entirely - see demographics_detection.py's _llm_only_demographics()."""

    def setUp(self):
        patcher = patch.object(config, "DEMOGRAPHICS_LLM_FALLBACK", "on")
        patcher.start()
        self.addCleanup(patcher.stop)

    @patch("analysis.llm_fallback.llm_client.chat_completion")
    def test_llm_answer_is_used_even_when_vote_would_disagree(self, mock_chat):
        mock_chat.return_value = '{"gender": "female", "age_range": "35-44"}'
        result = demographics_detection.detect_demographics(
            title="t", text="x", people_opinions=[{"gender": "male"}, {"gender": "male"}],
        )
        self.assertEqual(result["gender"], "female")
        self.assertEqual(result["age_range"], "35-44")
        mock_chat.assert_called_once()

    @patch("analysis.llm_fallback.llm_client.chat_completion")
    def test_majority_vote_never_runs_in_this_mode(self, mock_chat):
        mock_chat.return_value = '{"gender": "unknown", "age_range": "unknown"}'
        result = demographics_detection.detect_demographics(
            title="t", text="x", people_opinions=[{"gender": "male"}, {"gender": "male"}],
        )
        mock_chat.assert_called_once()
        self.assertEqual(result["gender"], "unknown")

    @patch("analysis.llm_fallback.llm_client.chat_completion")
    def test_unparseable_json_returns_unknown_rather_than_falling_back_to_the_vote(self, mock_chat):
        mock_chat.return_value = "not json at all"
        result = demographics_detection.detect_demographics(title="t", text="x")
        self.assertEqual(result["gender"], "unknown")
        self.assertEqual(result["age_range"], "unknown")

    @patch("analysis.llm_fallback.llm_client.chat_completion")
    def test_non_object_json_returns_unknown_rather_than_crashing(self, mock_chat):
        mock_chat.return_value = '["female"]'
        result = demographics_detection.detect_demographics(title="t", text="x")
        self.assertEqual(result["gender"], "unknown")
        self.assertEqual(result["age_range"], "unknown")

    @patch("analysis.llm_fallback.llm_client.chat_completion")
    def test_aliases_in_llm_response_are_normalized(self, mock_chat):
        mock_chat.return_value = '{"gender": "she", "age_range": "65+"}'
        result = demographics_detection.detect_demographics(title="t", text="x")
        self.assertEqual(result["gender"], "female")
        self.assertEqual(result["age_range"], "65_plus")

    @patch(
        "analysis.llm_fallback.llm_client.chat_completion",
        side_effect=llm_client.LLMConnectionError("ollama unreachable"),
    )
    def test_provider_failure_propagates_instead_of_being_swallowed(self, mock_chat):
        """Same contract as region_detection.py's LLM fallback - a provider
        outage must stop the run rather than read as an ordinary "unknown"
        demographic. See FATAL_ANALYSIS_ERRORS in
        services/articles/analysis_defaults.py."""
        with self.assertRaises(llm_client.LLMConnectionError):
            demographics_detection.detect_demographics(title="t", text="x")


if __name__ == "__main__":
    unittest.main()
