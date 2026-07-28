import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("DEEPSEEK_API_KEY", "test-key")

import enrich


class CleanArticlesTests(unittest.TestCase):
    def _article(self, **overrides):
        article = {
            "url": "https://example.com/a",
            "title": "A real headline",
            "text": "x" * 300,
            "source": "example.com",
        }
        article.update(overrides)
        return article

    def test_duplicate_urls_are_dropped(self):
        articles = [self._article(), self._article()]
        cleaned, removed = enrich.clean_articles(articles)
        self.assertEqual(len(cleaned), 1)
        self.assertEqual(removed["example.com"]["duplicate"], 1)

    def test_short_text_is_blocked(self):
        articles = [self._article(url="https://example.com/b", text="too short")]
        cleaned, removed = enrich.clean_articles(articles)
        self.assertEqual(cleaned, [])
        self.assertEqual(removed["example.com"]["blocked"], 1)

    def test_missing_title_is_blocked(self):
        articles = [self._article(url="https://example.com/c", title="")]
        cleaned, removed = enrich.clean_articles(articles)
        self.assertEqual(cleaned, [])
        self.assertEqual(removed["example.com"]["blocked"], 1)

    def test_google_consent_page_is_blocked(self):
        articles = [self._article(url="https://consent.google.com/x", title="Before you continue to Google")]
        cleaned, removed = enrich.clean_articles(articles)
        self.assertEqual(cleaned, [])
        self.assertEqual(removed["example.com"]["blocked"], 1)

    def test_clean_article_is_kept(self):
        articles = [self._article()]
        cleaned, removed = enrich.clean_articles(articles)
        self.assertEqual(len(cleaned), 1)
        self.assertEqual(removed["example.com"], {"duplicate": 0, "blocked": 0})


class DefaultEnrichmentTests(unittest.TestCase):
    def test_default_enrichment_has_neutral_fallback_values(self):
        self.assertEqual(enrich.DEFAULT_ENRICHMENT["overall_sentiment"], "neutral")
        self.assertEqual(enrich.DEFAULT_ENRICHMENT["sentiment"], "neutral")
        self.assertEqual(enrich.DEFAULT_ENRICHMENT["article_category"], "general_article")
        self.assertEqual(enrich.DEFAULT_ENRICHMENT["category"], "general_article")
        self.assertEqual(enrich.DEFAULT_ENRICHMENT["insight_json"], {})
        self.assertEqual(enrich.DEFAULT_ENRICHMENT["embedding_json"], [])

    def test_default_enrichment_analysis_model_describes_every_stage(self):
        label = enrich.DEFAULT_ENRICHMENT["analysis_model"]
        for stage in ("sentiment=", "classification=", "extraction=", "embedding="):
            self.assertIn(stage, label)


class EnrichArticleTests(unittest.TestCase):
    """enrich_article() is now a thin, defensive wrapper around
    analysis.orchestrator.analyze_article() - the pipeline's own stage logic
    is tested in test_analysis_*.py. This only covers enrich_article()'s
    contract with the rest of enrich.py: delegate, and never raise."""

    def test_delegates_to_the_orchestrator_and_returns_its_result(self):
        sentinel = {"summary": "ok", "sentiment": "positive"}
        with patch("enrich.analyze_article", return_value=sentinel) as mock_analyze:
            result = enrich.enrich_article({"title": "t", "text": "x" * 300}, project_context="ctx")
        self.assertIs(result, sentinel)
        mock_analyze.assert_called_once()
        _, kwargs = mock_analyze.call_args
        self.assertEqual(kwargs.get("project_context"), "ctx")

    def test_orchestrator_returning_none_is_passed_through(self):
        with patch("enrich.analyze_article", return_value=None):
            self.assertIsNone(enrich.enrich_article({"title": "t", "text": "x" * 300}))

    def test_orchestrator_raising_is_caught_and_returns_none(self):
        with patch("enrich.analyze_article", side_effect=RuntimeError("boom")):
            self.assertIsNone(enrich.enrich_article({"title": "t", "text": "x" * 300}))


if __name__ == "__main__":
    unittest.main()
