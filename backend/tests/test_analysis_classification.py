import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import config
from analysis import classification
from analysis import labels


class ClassificationStageTests(unittest.TestCase):
    def setUp(self):
        self._original_model = config.CLASSIFICATION_MODEL
        self._original_threshold = config.CLASSIFICATION_CONFIDENCE_THRESHOLD
        config.CLASSIFICATION_MODEL = "fake/model"
        config.CLASSIFICATION_CONFIDENCE_THRESHOLD = 0.4
        classification._load_pipeline.cache_clear()

    def tearDown(self):
        config.CLASSIFICATION_MODEL = self._original_model
        config.CLASSIFICATION_CONFIDENCE_THRESHOLD = self._original_threshold
        classification._load_pipeline.cache_clear()

    def test_category_confident_result_maps_back_to_snake_case_key(self):
        fake_pipeline = lambda text, candidates, hypothesis_template, multi_label: {
            "labels": [labels.CATEGORY_HYPOTHESIS_LABELS["review"], labels.CATEGORY_HYPOTHESIS_LABELS["news"]],
            "scores": [0.8, 0.1],
        }
        with patch("analysis.classification._get_pipeline", return_value=fake_pipeline):
            result = classification.classify_category("This car review covers handling and comfort.")
        self.assertEqual(result["label"], "review")
        self.assertFalse(result["low_confidence"])

    def test_category_low_confidence_falls_back_to_general_article(self):
        fake_pipeline = lambda text, candidates, hypothesis_template, multi_label: {
            "labels": [labels.CATEGORY_HYPOTHESIS_LABELS["review"]],
            "scores": [0.1],
        }
        with patch("analysis.classification._get_pipeline", return_value=fake_pipeline):
            result = classification.classify_category("ambiguous text")
        self.assertEqual(result["label"], "general_article")
        self.assertTrue(result["low_confidence"])
        self.assertEqual(result["raw_label"], "review")

    def test_pipeline_unavailable_falls_back_to_defaults(self):
        with patch("analysis.classification._get_pipeline", return_value=None):
            category = classification.classify_category("text")
            writer_tone = classification.classify_writer_tone("text")
            article_tone = classification.classify_article_tone("text")
        self.assertEqual(category["label"], "general_article")
        self.assertEqual(writer_tone["label"], "neutral")
        self.assertEqual(article_tone["label"], "neutral")
        self.assertTrue(category["low_confidence"] and writer_tone["low_confidence"] and article_tone["low_confidence"])

    def test_writer_tone_and_article_tone_are_independent_calls(self):
        calls = []

        def fake_pipeline(text, candidates, hypothesis_template, multi_label):
            calls.append(hypothesis_template)
            if "writer" in hypothesis_template:
                return {"labels": ["enthusiastic"], "scores": [0.9]}
            return {"labels": ["critical"], "scores": [0.9]}

        with patch("analysis.classification._get_pipeline", return_value=fake_pipeline):
            writer_tone = classification.classify_writer_tone("text")
            article_tone = classification.classify_article_tone("text")
        self.assertEqual(writer_tone["label"], "enthusiastic")
        self.assertEqual(article_tone["label"], "critical")
        self.assertEqual(len(calls), 2)

    def test_inference_error_is_handled_gracefully(self):
        def boom(text, candidates, hypothesis_template, multi_label):
            raise RuntimeError("boom")

        with patch("analysis.classification._get_pipeline", return_value=boom):
            result = classification.classify_category("text")
        self.assertEqual(result["label"], "general_article")
        self.assertTrue(result["low_confidence"])


class ClassificationStageHfApiTests(unittest.TestCase):
    def setUp(self):
        self._original_model = config.CLASSIFICATION_MODEL
        self._original_threshold = config.CLASSIFICATION_CONFIDENCE_THRESHOLD
        self._original_provider = config.CLASSIFICATION_PROVIDER
        config.CLASSIFICATION_MODEL = "fake/model"
        config.CLASSIFICATION_CONFIDENCE_THRESHOLD = 0.4
        config.CLASSIFICATION_PROVIDER = "hf_api"

    def tearDown(self):
        config.CLASSIFICATION_MODEL = self._original_model
        config.CLASSIFICATION_CONFIDENCE_THRESHOLD = self._original_threshold
        config.CLASSIFICATION_PROVIDER = self._original_provider

    def test_confident_result_maps_back_to_snake_case_key(self):
        fake_result = {
            "labels": [labels.CATEGORY_HYPOTHESIS_LABELS["review"], labels.CATEGORY_HYPOTHESIS_LABELS["news"]],
            "scores": [0.8, 0.1],
        }
        with patch("hf_inference_client.classify_zero_shot", return_value=fake_result):
            result = classification.classify_category("This car review covers handling and comfort.")
        self.assertEqual(result["label"], "review")
        self.assertFalse(result["low_confidence"])

    def test_low_confidence_falls_back_to_default(self):
        fake_result = {"labels": [labels.CATEGORY_HYPOTHESIS_LABELS["review"]], "scores": [0.1]}
        with patch("hf_inference_client.classify_zero_shot", return_value=fake_result):
            result = classification.classify_category("ambiguous text")
        self.assertEqual(result["label"], "general_article")
        self.assertTrue(result["low_confidence"])

    def test_api_error_propagates_instead_of_falling_back(self):
        """An HF Inference API failure (bad token, quota, rate limit,
        outage...) means every remaining chunk/article would fail the same
        way - it must propagate instead of quietly downgrading to
        general_article/low_confidence, so the pipeline can treat it as
        fatal and stop (see services/articles/enrich.py's
        FATAL_ANALYSIS_ERRORS)."""
        from hf_inference_client import HFInferenceError

        with patch("hf_inference_client.classify_zero_shot", side_effect=HFInferenceError("boom")):
            with self.assertRaises(HFInferenceError):
                classification.classify_category("text")

    def test_no_model_configured_falls_back_to_defaults(self):
        config.CLASSIFICATION_MODEL = ""
        result = classification.classify_category("text")
        self.assertEqual(result["label"], "general_article")
        self.assertTrue(result["low_confidence"])


if __name__ == "__main__":
    unittest.main()
