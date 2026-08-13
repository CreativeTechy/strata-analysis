import json
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("DEEPSEEK_API_KEY", "test-key")

import config
import llm_client
from analysis import structured_extraction as se


VALID_PAYLOAD = {
    "topic": "new model launch",
    "summary": "A glowing review of the new model.",
    "positive_feedback": ["great range"],
    "negative_feedback": [],
    "nice_to_have_features": [],
    "complaints": [],
    "great_features": [],
    "comfort_issues": [],
    "performance_feedback": [],
    "price_value_feedback": [],
    "maintenance_reliability_feedback": [],
    "technology_feedback": [],
    "safety_feedback": [],
    "key_points": [],
    "risks": [],
    "opportunities": [],
    "organizations": ["Acme Motors"],
    "entities": ["Model X"],
    "topics": ["ev"],
    "relevance_score": 8,
    "people_opinions": [],
    "frequent_ideas": [],
}


class ExtractStructuredDataTests(unittest.TestCase):
    def setUp(self):
        self._original_retries = config.STRUCTURED_EXTRACTION_MAX_RETRIES
        config.STRUCTURED_EXTRACTION_MAX_RETRIES = 1

    def tearDown(self):
        config.STRUCTURED_EXTRACTION_MAX_RETRIES = self._original_retries

    def test_valid_json_response_is_parsed_and_normalized(self):
        with patch("analysis.structured_extraction._run_generation", return_value=json.dumps(VALID_PAYLOAD)):
            result = se.extract_structured_data("title", "body")
        self.assertFalse(result.failed)
        self.assertEqual(result.data["summary"], VALID_PAYLOAD["summary"])
        self.assertEqual(result.data["positive_feedback"], ["great range"])
        self.assertEqual(result.data["relevance_score"], 8)

    def test_code_fenced_and_trailing_comma_json_is_repaired(self):
        messy = "```json\n" + json.dumps(VALID_PAYLOAD).rstrip("}") + ",}\n```"
        with patch("analysis.structured_extraction._run_generation", return_value=messy):
            result = se.extract_structured_data("title", "body")
        self.assertFalse(result.failed)
        self.assertEqual(result.data["summary"], VALID_PAYLOAD["summary"])

    def test_model_unavailable_fails_immediately(self):
        with patch("analysis.structured_extraction._run_generation", return_value=None):
            result = se.extract_structured_data("title", "body")
        self.assertTrue(result.failed)
        self.assertEqual(result.reason, "model_unavailable")

    def test_missing_required_summary_field_fails_after_retry(self):
        bad = json.dumps({"topic": "x"})
        with patch("analysis.structured_extraction._run_generation", return_value=bad) as mock_run:
            result = se.extract_structured_data("title", "body")
        self.assertTrue(result.failed)
        self.assertIn("invalid_json", result.reason)
        # One initial attempt + one correction retry.
        self.assertEqual(mock_run.call_count, 2)

    def test_correction_retry_succeeds_on_second_attempt(self):
        responses = iter(["not json at all", json.dumps(VALID_PAYLOAD)])
        with patch("analysis.structured_extraction._run_generation", side_effect=lambda messages: next(responses)):
            result = se.extract_structured_data("title", "body")
        self.assertFalse(result.failed)
        self.assertEqual(result.data["summary"], VALID_PAYLOAD["summary"])

    def test_correction_prompt_includes_the_bad_response_and_errors(self):
        responses = iter(["not json at all", json.dumps(VALID_PAYLOAD)])
        captured_messages = []

        def fake_run(messages):
            captured_messages.append(messages)
            return next(responses)

        with patch("analysis.structured_extraction._run_generation", side_effect=fake_run):
            se.extract_structured_data("title", "body")
        second_call_messages = captured_messages[1]
        self.assertEqual(second_call_messages[-2]["content"], "not json at all")
        self.assertIn("Problems:", second_call_messages[-1]["content"])

    def test_empty_summary_is_treated_as_failure(self):
        payload = dict(VALID_PAYLOAD, summary="")
        with patch("analysis.structured_extraction._run_generation", return_value=json.dumps(payload)):
            result = se.extract_structured_data("title", "body")
        self.assertTrue(result.failed)
        self.assertEqual(result.reason, "empty_summary")

    def test_retries_disabled_fails_after_one_attempt(self):
        config.STRUCTURED_EXTRACTION_MAX_RETRIES = 0
        with patch("analysis.structured_extraction._run_generation", return_value="garbage") as mock_run:
            result = se.extract_structured_data("title", "body")
        self.assertTrue(result.failed)
        self.assertEqual(mock_run.call_count, 1)


class RunGenerationTests(unittest.TestCase):
    """`_run_generation` is the seam onto the configured LLM provider - no
    local model is loaded for this stage anymore (see llm_client.py)."""

    def test_calls_the_provider_backed_client_in_json_mode(self):
        messages = [{"role": "user", "content": "hi"}]
        with patch("analysis.structured_extraction.llm_client.chat_completion", return_value="{}") as mock_chat:
            result = se._run_generation(messages)
        self.assertEqual(result, "{}")
        mock_chat.assert_called_once_with(
            messages=messages,
            temperature=config.STRUCTURED_EXTRACTION_TEMPERATURE,
            max_tokens=config.STRUCTURED_EXTRACTION_MAX_NEW_TOKENS,
            json_mode=True,
        )

    def test_provider_error_propagates_instead_of_returning_none(self):
        """A provider-level failure (bad key, insufficient balance, rate
        limit...) is not the same situation as "the model answered but the
        JSON didn't validate" - every other article would fail identically,
        so this must propagate as a real exception instead of being folded
        into a per-article "model_unavailable" result. The pipeline
        (services/articles/enrich.py, scraper/pipelines.py) treats it as
        fatal and stops rather than grinding through doomed calls."""
        with patch(
            "analysis.structured_extraction.llm_client.chat_completion",
            side_effect=llm_client.LLMConfigError("no key configured"),
        ):
            with self.assertRaises(llm_client.LLMConfigError):
                se._run_generation([{"role": "user", "content": "hi"}])

    def test_provider_error_propagates_end_to_end(self):
        with patch(
            "analysis.structured_extraction.llm_client.chat_completion",
            side_effect=llm_client.LLMRateLimitError("rate limited"),
        ):
            with self.assertRaises(llm_client.LLMRateLimitError):
                se.extract_structured_data("title", "body")


if __name__ == "__main__":
    unittest.main()
