import os
import unittest
from collections import Counter
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("DEEPSEEK_API_KEY", "test-key")

from services.articles import enrich


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

    def test_short_tweet_is_kept(self):
        articles = [
            self._article(
                url="https://x.com/someuser/status/1234567890",
                title="@someuser",
                text="lol nice",
                source="x.com/someuser",
            )
        ]
        cleaned, removed = enrich.clean_articles(articles)
        self.assertEqual(len(cleaned), 1)
        self.assertEqual(removed["x.com/someuser"]["blocked"], 0)

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
    contract with the rest of enrich.py: delegate, swallow an ordinary bug,
    but re-raise an LLMError (provider call failed) instead of masking it as
    a per-article failure - see scraper/pipelines.py/services/pipeline/
    pipeline.py for how the caller treats that as fatal and stops the run."""

    def test_delegates_to_the_orchestrator_and_returns_its_result(self):
        sentinel = {"summary": "ok", "sentiment": "positive"}
        with patch("services.articles.enrich.analyze_article", return_value=sentinel) as mock_analyze:
            result = enrich.enrich_article({"title": "t", "text": "x" * 300}, project_context="ctx")
        self.assertIs(result, sentinel)
        mock_analyze.assert_called_once()
        _, kwargs = mock_analyze.call_args
        self.assertEqual(kwargs.get("project_context"), "ctx")

    def test_orchestrator_returning_none_is_passed_through(self):
        with patch("services.articles.enrich.analyze_article", return_value=None):
            self.assertIsNone(enrich.enrich_article({"title": "t", "text": "x" * 300}))

    def test_orchestrator_raising_is_caught_and_returns_none(self):
        with patch("services.articles.enrich.analyze_article", side_effect=RuntimeError("boom")):
            self.assertIsNone(enrich.enrich_article({"title": "t", "text": "x" * 300}))

    def test_orchestrator_raising_llm_error_propagates(self):
        from llm_client import LLMQuotaError

        with patch(
            "services.articles.enrich.analyze_article",
            side_effect=LLMQuotaError("402 - Insufficient Balance"),
        ):
            with self.assertRaises(LLMQuotaError):
                enrich.enrich_article({"title": "t", "text": "x" * 300})

    def test_orchestrator_raising_hf_inference_error_propagates(self):
        """Same fatal treatment as LLMError, but for the Hugging Face
        Inference API path (SENTIMENT_CLASSIFIER_PROVIDER/
        CLASSIFICATION_PROVIDER=hf_api) - see FATAL_ANALYSIS_ERRORS."""
        from hf_inference_client import HFQuotaError

        with patch(
            "services.articles.enrich.analyze_article",
            side_effect=HFQuotaError("402 - exceeded monthly included credits"),
        ):
            with self.assertRaises(HFQuotaError):
                enrich.enrich_article({"title": "t", "text": "x" * 300})


class PersistSourceStatsTests(unittest.TestCase):
    """_persist_source_stats() merges scraper-recorded diagnostics (blocked/
    404/DNS failure/empty - see source_diagnostics.py) into the per-source
    breakdown, so a source that scraped 0 articles still gets a row."""

    def test_no_pipeline_run_id_skips_persist_entirely(self):
        with patch.object(enrich, "PIPELINE_RUN_ID", ""), patch.object(enrich, "upsert_pipeline_run_source_stats") as mock_upsert:
            enrich._persist_source_stats({}, {}, {}, {}, {}, {}, {})
        mock_upsert.assert_not_called()

    def test_zero_scraped_source_gets_a_row_via_diagnostics_alone(self):
        with patch.object(enrich, "PIPELINE_RUN_ID", "run-1"), patch.object(
            enrich, "load_source_diagnostics",
            return_value=[{"source_name": "r/messi", "http_status": 403, "network_blocked": True}],
        ), patch.object(enrich, "upsert_pipeline_run_source_stats") as mock_upsert:
            enrich._persist_source_stats({}, {}, {}, {}, {}, {}, {})

        mock_upsert.assert_called_once()
        run_id, stats = mock_upsert.call_args[0]
        self.assertEqual(run_id, "run-1")
        self.assertIn("r/messi", stats)
        self.assertEqual(stats["r/messi"]["scraped"], 0)
        self.assertTrue(stats["r/messi"]["network_blocked"])
        self.assertIn("Blocked", stats["r/messi"]["fetch_note"])

    def test_healthy_scraped_source_has_no_fetch_note(self):
        with patch.object(enrich, "PIPELINE_RUN_ID", "run-1"), patch.object(
            enrich, "load_source_diagnostics", return_value=[]
        ), patch.object(enrich, "upsert_pipeline_run_source_stats") as mock_upsert:
            enrich._persist_source_stats(Counter({"good-source": 3}), {}, {}, {}, {}, {}, {})

        _, stats = mock_upsert.call_args[0]
        self.assertEqual(stats["good-source"]["scraped"], 3)
        self.assertEqual(stats["good-source"]["fetch_note"], "")
        self.assertFalse(stats["good-source"]["network_blocked"])

    def test_source_with_no_diagnostic_and_zero_scraped_notes_empty(self):
        with patch.object(enrich, "PIPELINE_RUN_ID", "run-1"), patch.object(
            enrich, "load_source_diagnostics", return_value=[]
        ), patch.object(enrich, "upsert_pipeline_run_source_stats") as mock_upsert:
            # date_filtered still references the source even though nothing was scraped/kept.
            enrich._persist_source_stats({}, {}, Counter({"quiet-source": 1}), {}, {}, {}, {})

        _, stats = mock_upsert.call_args[0]
        self.assertEqual(stats["quiet-source"]["fetch_note"], "Returned 0 articles.")


if __name__ == "__main__":
    unittest.main()
