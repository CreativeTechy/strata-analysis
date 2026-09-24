"""Unit tests for services/articles/translation.py.

Covers the four gaps F005 flagged as untested: cache invalidation on
analyzed_at change, the length/type guard that keeps translated list items
paired with the right originals, the locale_fallback path (plus its negative
cache so a failing provider isn't retried at full timeout on every view), and
skipping the LLM call entirely for the default locale.
"""

import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import config
from services.articles import translation

ANALYSIS = {
    "article_id": 1,
    "analyzed_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
    "insight_json": {
        "topic": "Battery life",
        "summary": "Reviewers were mostly positive about battery life.",
        "positive_feedback": ["Lasts all day"],
        "negative_feedback": [],
        "people_opinions": [{"opinion": "Great battery", "source": "reviewer-1"}],
        "frequent_ideas": [{"idea": "battery", "count": 3}],
    },
}


class LocalizeArticleAnalysisTests(unittest.TestCase):
    def setUp(self):
        translation._failure_cache.clear()

    def test_default_locale_never_calls_the_llm(self):
        with patch("services.articles.translation.chat_completion") as mock_chat, \
             patch.object(translation, "_load_cached") as mock_load:
            result = translation.localize_article_analysis(
                ANALYSIS, article_id=1, locale=config.DEFAULT_LOCALE,
            )
        self.assertEqual(result, ANALYSIS)
        mock_chat.assert_not_called()
        mock_load.assert_not_called()

    def test_cache_hit_when_analyzed_at_matches(self):
        cached_row = {
            "translated": {"topic": "عمر البطارية", "summary": "كانت آراء المراجعين إيجابية.", "positive_feedback": ["يدوم طوال اليوم"], "negative_feedback": [], "people_opinions": ["بطارية رائعة"], "frequent_ideas": ["بطارية"]},
            "source_analyzed_at": ANALYSIS["analyzed_at"],
        }
        with patch.object(translation, "_load_cached", return_value=cached_row), \
             patch("services.articles.translation.chat_completion") as mock_chat:
            result = translation.localize_article_analysis(ANALYSIS, article_id=1, locale="ar")

        self.assertTrue(result["cached"])
        self.assertEqual(result["locale"], "ar")
        self.assertEqual(result["insight_json"]["topic"], "عمر البطارية")
        mock_chat.assert_not_called()

    def test_cache_miss_after_analyzed_at_changes(self):
        """A reanalysis (a later analyzed_at) must not serve a translation
        rendered from the article's previous analysis."""
        stale_cached_row = {
            "translated": {"topic": "old translation"},
            "source_analyzed_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
        }
        with patch.object(translation, "_load_cached", return_value=stale_cached_row), \
             patch.object(translation, "_save_cached") as mock_save, \
             patch(
                 "services.articles.translation.chat_completion",
                 return_value='{"topic": "fresh translation", "summary": "s", "positive_feedback": ["Lasts all day"], "negative_feedback": [], "people_opinions": ["Great battery"], "frequent_ideas": ["battery"]}',
             ) as mock_chat:
            result = translation.localize_article_analysis(ANALYSIS, article_id=1, locale="ar")

        mock_chat.assert_called_once()
        self.assertFalse(result["cached"])
        self.assertEqual(result["insight_json"]["topic"], "fresh translation")
        mock_save.assert_called_once()

    def test_mismatched_list_length_leaves_that_field_untranslated(self):
        """A translated list whose length doesn't match the original is
        dropped rather than risk pairing translated text with the wrong item."""
        translated_payload = {
            "topic": "عمر البطارية",
            "summary": "s",
            # Original has one positive_feedback item; the model returned two.
            "positive_feedback": ["ترجمة أولى", "ترجمة إضافية غير متوقعة"],
            "negative_feedback": [],
            "people_opinions": ["بطارية رائعة"],
            "frequent_ideas": ["بطارية"],
        }
        with patch.object(translation, "_load_cached", return_value=None), \
             patch.object(translation, "_save_cached"), \
             patch("services.articles.translation.chat_completion", return_value=None), \
             patch.object(translation, "_translate_payload", return_value=translated_payload):
            result = translation.localize_article_analysis(ANALYSIS, article_id=1, locale="ar")

        # topic (a scalar field) is translated...
        self.assertEqual(result["insight_json"]["topic"], "عمر البطارية")
        # ...but positive_feedback keeps its original English value, since the
        # translated list's length doesn't match the original's.
        self.assertEqual(result["insight_json"]["positive_feedback"], ["Lasts all day"])

    def test_llm_failure_returns_locale_fallback(self):
        with patch.object(translation, "_load_cached", return_value=None), \
             patch.object(translation, "_save_cached") as mock_save, \
             patch("services.articles.translation.chat_completion", side_effect=RuntimeError("model unreachable")):
            result = translation.localize_article_analysis(ANALYSIS, article_id=1, locale="ar")

        self.assertTrue(result.get("locale_fallback"))
        self.assertEqual(result["locale"], config.DEFAULT_LOCALE)
        mock_save.assert_not_called()

    def test_recent_failure_short_circuits_without_calling_the_llm_again(self):
        """A failing/unreachable provider shouldn't cost a fresh
        LLM_REQUEST_TIMEOUT_SECONDS wait on every subsequent view of the same
        article (F004) - a failure recorded moments ago for the same
        (article_id, locale, analyzed_at) skips straight to the fallback."""
        with patch.object(translation, "_load_cached", return_value=None), \
             patch("services.articles.translation.chat_completion", side_effect=RuntimeError("model unreachable")) as mock_chat:
            first = translation.localize_article_analysis(ANALYSIS, article_id=1, locale="ar")
            second = translation.localize_article_analysis(ANALYSIS, article_id=1, locale="ar")

        self.assertTrue(first.get("locale_fallback"))
        self.assertTrue(second.get("locale_fallback"))
        # Only the first call actually reached the LLM; the second was
        # short-circuited by the negative cache.
        mock_chat.assert_called_once()

    def test_recent_failure_is_cleared_by_a_later_success(self):
        with patch.object(translation, "_load_cached", return_value=None), \
             patch.object(translation, "_save_cached"), \
             patch("services.articles.translation.chat_completion", side_effect=RuntimeError("boom")):
            translation.localize_article_analysis(ANALYSIS, article_id=1, locale="ar")

        # Simulate the negative-cache window having elapsed (rather than
        # actually sleeping FAILURE_CACHE_SECONDS in the test).
        _, failed_source_analyzed_at = translation._failure_cache[(1, "ar")]
        translation._failure_cache[(1, "ar")] = (0.0, failed_source_analyzed_at)

        translated_payload = {
            "topic": "عمر البطارية", "summary": "s", "positive_feedback": ["Lasts all day"],
            "negative_feedback": [], "people_opinions": ["Great battery"], "frequent_ideas": ["battery"],
        }
        with patch.object(translation, "_load_cached", return_value=None), \
             patch.object(translation, "_save_cached"), \
             patch.object(translation, "_translate_payload", return_value=translated_payload) as mock_translate:
            recovered = translation.localize_article_analysis(ANALYSIS, article_id=1, locale="ar")

        self.assertFalse(recovered.get("locale_fallback"))
        mock_translate.assert_called_once()

    def test_recent_failure_does_not_short_circuit_a_different_locale(self):
        with patch.object(translation, "_load_cached", return_value=None), \
             patch("services.articles.translation.chat_completion", side_effect=RuntimeError("boom")):
            translation.localize_article_analysis(ANALYSIS, article_id=1, locale="ar")

        with patch.object(translation, "_load_cached", return_value=None), \
             patch.object(translation, "_save_cached"), \
             patch.object(translation, "_translate_payload", return_value={"topic": "t", "summary": "s"}) as mock_translate:
            translation.localize_article_analysis(ANALYSIS, article_id=1, locale="fr")

        mock_translate.assert_called_once()

    def test_force_bypasses_both_the_translation_cache_and_the_failure_cache(self):
        translation._failure_cache[(1, "ar")] = (float("inf"), ANALYSIS["analyzed_at"])
        translated_payload = {
            "topic": "عمر البطارية", "summary": "s", "positive_feedback": ["Lasts all day"],
            "negative_feedback": [], "people_opinions": ["Great battery"], "frequent_ideas": ["battery"],
        }
        with patch.object(translation, "_load_cached") as mock_load, \
             patch.object(translation, "_save_cached"), \
             patch.object(translation, "_translate_payload", return_value=translated_payload) as mock_translate:
            result = translation.localize_article_analysis(ANALYSIS, article_id=1, locale="ar", force=True)

        mock_load.assert_not_called()
        mock_translate.assert_called_once()
        self.assertFalse(result.get("locale_fallback"))


if __name__ == "__main__":
    unittest.main()
