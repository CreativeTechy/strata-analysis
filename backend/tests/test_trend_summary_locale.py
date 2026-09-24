import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import config
from services.intelligence import trend_summary

PROJECT = {"id": 1, "name": "Acme Watch", "keywords": []}
CANONICAL_ROW = {
    "summary": "Coverage was mostly positive this period.",
    "article_count": 12,
    "period": "30d",
    "run_id": None,
    "cached": True,
    "generated_at": "2026-01-01T00:00:00+00:00",
}


class LocalizedTrendSummaryTests(unittest.TestCase):
    """Locale-aware generation is layered on top of the canonical (English)
    summary rather than replacing it: canonical stays keyed the same way it
    always was, and a non-default locale is a separate, invalidatable
    rendering of it (CLAUDE.md: save localized output separately from
    canonical analysis with locale, source-analysis version, and generation
    metadata; invalidate it when its source analysis changes; provide a
    clear fallback when a localized version is unavailable)."""

    def test_default_locale_returns_the_canonical_summary_unchanged(self):
        """Requesting the default locale must be indistinguishable from the
        pre-locale code path - no new fields, no extra queries."""
        with patch.object(trend_summary, "_load_cached", return_value=CANONICAL_ROW) as mock_load, \
             patch.object(trend_summary, "_load_cached_localized") as mock_localized, \
             patch("services.intelligence.trend_summary.chat_completion") as mock_chat:
            result = trend_summary.generate_trend_summary(PROJECT, period="30d", locale="en")
        self.assertEqual(result, CANONICAL_ROW)
        mock_load.assert_called_once()
        mock_localized.assert_not_called()
        mock_chat.assert_not_called()

    def test_non_default_locale_renders_from_canonical_and_caches_it_separately(self):
        canonical_updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        with patch.object(trend_summary, "_load_cached", return_value=CANONICAL_ROW), \
             patch.object(trend_summary, "_canonical_updated_at", return_value=canonical_updated_at), \
             patch.object(trend_summary, "_load_cached_localized", return_value=None), \
             patch.object(trend_summary, "_save_cached_localized") as mock_save, \
             patch("services.intelligence.trend_summary.chat_completion", return_value="تغطية إيجابية بشكل عام") as mock_chat:
            result = trend_summary.generate_trend_summary(PROJECT, period="30d", locale="ar")

        self.assertEqual(result["locale"], "ar")
        self.assertFalse(result["cached"])
        self.assertNotEqual(result["summary"], CANONICAL_ROW["summary"])
        # The canonical summary was never regenerated - only rendered.
        mock_chat.assert_called_once()
        rendered_prompt = mock_chat.call_args.kwargs["messages"][1]["content"]
        self.assertEqual(rendered_prompt, CANONICAL_ROW["summary"])
        mock_save.assert_called_once_with(
            PROJECT["id"], "30d", None, "ar", result["summary"], canonical_updated_at, config.LLM_CHAT_MODEL,
        )

    def test_localized_cache_hit_skips_another_llm_call(self):
        canonical_updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        localized_row = {
            "summary": "Cached Arabic summary.",
            "source_updated_at": canonical_updated_at,
            "model": "llama3.1",
            "updated_at": canonical_updated_at,
        }
        with patch.object(trend_summary, "_load_cached", return_value=CANONICAL_ROW), \
             patch.object(trend_summary, "_canonical_updated_at", return_value=canonical_updated_at), \
             patch.object(trend_summary, "_load_cached_localized", return_value=localized_row), \
             patch("services.intelligence.trend_summary.chat_completion") as mock_chat:
            result = trend_summary.generate_trend_summary(PROJECT, period="30d", locale="ar")

        self.assertTrue(result["cached"])
        self.assertEqual(result["summary"], "Cached Arabic summary.")
        mock_chat.assert_not_called()

    def test_localized_cache_is_invalidated_when_canonical_summary_changes(self):
        """A stale localized row (source_updated_at behind the canonical
        row's current updated_at) must be re-rendered, not served stale."""
        old_updated_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
        new_updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        stale_localized_row = {
            "summary": "Outdated Arabic summary.",
            "source_updated_at": old_updated_at,
            "model": "llama3.1",
            "updated_at": old_updated_at,
        }
        with patch.object(trend_summary, "_load_cached", return_value=CANONICAL_ROW), \
             patch.object(trend_summary, "_canonical_updated_at", return_value=new_updated_at), \
             patch.object(trend_summary, "_load_cached_localized", return_value=stale_localized_row), \
             patch.object(trend_summary, "_save_cached_localized") as mock_save, \
             patch("services.intelligence.trend_summary.chat_completion", return_value="Fresh Arabic summary.") as mock_chat:
            result = trend_summary.generate_trend_summary(PROJECT, period="30d", locale="ar")

        mock_chat.assert_called_once()
        self.assertEqual(result["summary"], "Fresh Arabic summary.")
        self.assertFalse(result["cached"])
        mock_save.assert_called_once()

    def test_falls_back_to_canonical_summary_when_rendering_fails(self):
        with patch.object(trend_summary, "_load_cached", return_value=CANONICAL_ROW), \
             patch.object(trend_summary, "_canonical_updated_at", return_value=None), \
             patch.object(trend_summary, "_load_cached_localized", return_value=None), \
             patch.object(trend_summary, "_save_cached_localized") as mock_save, \
             patch("services.intelligence.trend_summary.chat_completion", side_effect=RuntimeError("boom")):
            result = trend_summary.generate_trend_summary(PROJECT, period="30d", locale="ar")

        self.assertTrue(result.get("locale_fallback"))
        self.assertEqual(result["locale"], config.DEFAULT_LOCALE)
        self.assertEqual(result["summary"], CANONICAL_ROW["summary"])
        mock_save.assert_not_called()

    def test_force_regenerates_only_the_localized_render_not_the_canonical(self):
        """Regenerating while viewing a non-default locale must not force a
        fresh (billable) canonical generation as a side effect."""
        canonical_updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        with patch.object(trend_summary, "_load_cached", return_value=CANONICAL_ROW) as mock_load, \
             patch.object(trend_summary, "_canonical_updated_at", return_value=canonical_updated_at), \
             patch.object(trend_summary, "_load_cached_localized") as mock_localized, \
             patch.object(trend_summary, "_save_cached_localized"), \
             patch("services.intelligence.trend_summary.chat_completion", return_value="Fresh render."):
            trend_summary.generate_trend_summary(PROJECT, period="30d", locale="ar", force=True)

        # _load_cached is the canonical lookup; called with force=False internally.
        mock_load.assert_called_once()
        # A localized force-regenerate must not even check the localized cache.
        mock_localized.assert_not_called()


if __name__ == "__main__":
    unittest.main()
