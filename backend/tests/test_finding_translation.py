"""Unit tests for services/competitors/finding_translation.py.

Mirrors test_article_translation.py's coverage: cache hit/miss keyed on the
finding's own generated_at, the length guard that keeps translated
signals/actions paired with the right originals, the locale_fallback path
(plus its negative cache), and skipping the LLM call entirely for the
default locale. LocalizeFindingsTests covers the batch entry point's own
budget/concurrency behavior on top of that.
"""

import os
import time
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import config
from services.competitors import finding_translation

FINDING = {
    "id": 1,
    "project_id": 10,
    "competitor_id": 20,
    "generated_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
    "headline": "Competitor launched a new pricing tier",
    "whats_up": "They introduced a mid-tier plan targeting SMBs.",
    "impact": "Could pressure our own mid-market pricing.",
    "confidence_reason": "Based on three separate press mentions.",
    "signals": ["pricing", "smb"],
    "actions": [{"action": "Review pricing page", "rationale": "Stay competitive", "effort": "low", "urgency": "now"}],
}


class LocalizeFindingTests(unittest.TestCase):
    def setUp(self):
        finding_translation._failure_cache.clear()

    def test_default_locale_never_calls_the_llm(self):
        with patch("services.competitors.finding_translation.chat_completion") as mock_chat, \
             patch.object(finding_translation, "_load_cached") as mock_load:
            result = finding_translation.localize_finding(FINDING, locale=config.DEFAULT_LOCALE)
        self.assertEqual(result, FINDING)
        mock_chat.assert_not_called()
        mock_load.assert_not_called()

    def test_cache_hit_when_generated_at_matches(self):
        cached_row = {
            "translated": {
                "headline": "أطلق المنافس شريحة تسعير جديدة",
                "whats_up": "قدموا خطة متوسطة تستهدف الشركات الصغيرة.",
                "impact": "قد يضغط على تسعيرنا للسوق المتوسط.",
                "confidence_reason": "بناءً على ثلاث إشارات صحفية منفصلة.",
                "signals": ["تسعير", "شركات صغيرة"],
                "actions": [{"action": "مراجعة صفحة التسعير", "rationale": "البقاء تنافسيًا"}],
            },
            "source_generated_at": FINDING["generated_at"],
        }
        with patch.object(finding_translation, "_load_cached", return_value=cached_row), \
             patch("services.competitors.finding_translation.chat_completion") as mock_chat:
            result = finding_translation.localize_finding(FINDING, locale="ar")

        self.assertTrue(result["cached"])
        self.assertEqual(result["locale"], "ar")
        self.assertEqual(result["headline"], "أطلق المنافس شريحة تسعير جديدة")
        self.assertEqual(result["actions"][0]["action"], "مراجعة صفحة التسعير")
        self.assertEqual(result["actions"][0]["effort"], "low")  # untouched, not sent to the model
        mock_chat.assert_not_called()

    def test_cache_miss_after_generated_at_changes(self):
        stale_cached_row = {
            "translated": {"headline": "old translation"},
            "source_generated_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
        }
        fresh_payload = {
            "headline": "fresh translation", "whats_up": "w", "impact": "i", "confidence_reason": "c",
            "signals": ["pricing", "smb"],
            "actions": [{"action": "Review pricing page", "rationale": "Stay competitive"}],
        }
        with patch.object(finding_translation, "_load_cached", return_value=stale_cached_row), \
             patch.object(finding_translation, "_save_cached") as mock_save, \
             patch.object(finding_translation, "_translate_payload", return_value=fresh_payload) as mock_translate:
            result = finding_translation.localize_finding(FINDING, locale="ar")

        mock_translate.assert_called_once()
        self.assertFalse(result["cached"])
        self.assertEqual(result["headline"], "fresh translation")
        mock_save.assert_called_once()

    def test_mismatched_list_length_leaves_that_field_untranslated(self):
        translated_payload = {
            "headline": "أطلق المنافس شريحة تسعير جديدة",
            "whats_up": "w", "impact": "i", "confidence_reason": "c",
            # Original has two signals; the model returned one.
            "signals": ["تسعير"],
            "actions": [{"action": "مراجعة صفحة التسعير", "rationale": "البقاء تنافسيًا"}],
        }
        with patch.object(finding_translation, "_load_cached", return_value=None), \
             patch.object(finding_translation, "_save_cached"), \
             patch.object(finding_translation, "_translate_payload", return_value=translated_payload):
            result = finding_translation.localize_finding(FINDING, locale="ar")

        self.assertEqual(result["headline"], "أطلق المنافس شريحة تسعير جديدة")
        # signals keeps its original English value, since the translated
        # list's length doesn't match the original's.
        self.assertEqual(result["signals"], ["pricing", "smb"])
        # actions matched in length, so it is translated.
        self.assertEqual(result["actions"][0]["action"], "مراجعة صفحة التسعير")

    def test_llm_failure_returns_locale_fallback(self):
        with patch.object(finding_translation, "_load_cached", return_value=None), \
             patch.object(finding_translation, "_save_cached") as mock_save, \
             patch("services.competitors.finding_translation.chat_completion", side_effect=RuntimeError("model unreachable")):
            result = finding_translation.localize_finding(FINDING, locale="ar")

        self.assertTrue(result.get("locale_fallback"))
        self.assertEqual(result["locale"], config.DEFAULT_LOCALE)
        mock_save.assert_not_called()

    def test_recent_failure_short_circuits_without_calling_the_llm_again(self):
        with patch.object(finding_translation, "_load_cached", return_value=None), \
             patch("services.competitors.finding_translation.chat_completion", side_effect=RuntimeError("model unreachable")) as mock_chat:
            first = finding_translation.localize_finding(FINDING, locale="ar")
            second = finding_translation.localize_finding(FINDING, locale="ar")

        self.assertTrue(first.get("locale_fallback"))
        self.assertTrue(second.get("locale_fallback"))
        mock_chat.assert_called_once()

    def test_force_bypasses_both_the_translation_cache_and_the_failure_cache(self):
        finding_translation._failure_cache[(1, "ar")] = (float("inf"), FINDING["generated_at"])
        translated_payload = {
            "headline": "h", "whats_up": "w", "impact": "i", "confidence_reason": "c",
            "signals": ["pricing", "smb"],
            "actions": [{"action": "a", "rationale": "r"}],
        }
        with patch.object(finding_translation, "_load_cached") as mock_load, \
             patch.object(finding_translation, "_save_cached"), \
             patch.object(finding_translation, "_translate_payload", return_value=translated_payload) as mock_translate:
            result = finding_translation.localize_finding(FINDING, locale="ar", force=True)

        mock_load.assert_not_called()
        mock_translate.assert_called_once()
        self.assertFalse(result.get("locale_fallback"))


class LocalizeFindingsTests(unittest.TestCase):
    """localize_findings() - the batch entry point list_findings()/get_finding()
    use so a whole findings list doesn't cost one serial LLM call per finding
    (see config.FINDING_TRANSLATION_BUDGET_SECONDS)."""

    def setUp(self):
        finding_translation._failure_cache.clear()

    def test_default_locale_returns_unchanged_without_scheduling_work(self):
        findings = [dict(FINDING, id=1), dict(FINDING, id=2)]
        with patch.object(finding_translation, "localize_finding") as mock_localize:
            result = finding_translation.localize_findings(findings, locale=config.DEFAULT_LOCALE)
        self.assertEqual(result, findings)
        mock_localize.assert_not_called()

    def test_empty_list_returns_as_is(self):
        with patch.object(finding_translation, "localize_finding") as mock_localize:
            result = finding_translation.localize_findings([], locale="ar")
        self.assertEqual(result, [])
        mock_localize.assert_not_called()

    def test_translates_each_finding_and_preserves_order(self):
        findings = [dict(FINDING, id=1), dict(FINDING, id=2), dict(FINDING, id=3)]

        def fake_localize(finding, *, locale):
            # finding 2 finishes slower than 1 and 3, to exercise the thread
            # pool completing out of submission order.
            if finding["id"] == 2:
                time.sleep(0.05)
            return {**finding, "locale": locale, "cached": False}

        with patch.object(finding_translation, "localize_finding", side_effect=fake_localize):
            result = finding_translation.localize_findings(findings, locale="ar")

        self.assertEqual([f["id"] for f in result], [1, 2, 3])
        self.assertTrue(all(f["locale"] == "ar" for f in result))
        self.assertFalse(any(f.get("locale_fallback") for f in result))

    def test_budget_already_exhausted_falls_back_every_finding(self):
        """A budget that's already elapsed by the time the loop starts must
        not submit any translation - every finding comes back as its
        canonical version, tagged locale_fallback like an outright failure."""
        findings = [dict(FINDING, id=1), dict(FINDING, id=2)]
        with patch.object(config, "FINDING_TRANSLATION_BUDGET_SECONDS", -1.0), \
             patch.object(finding_translation, "localize_finding") as mock_localize:
            result = finding_translation.localize_findings(findings, locale="ar")

        mock_localize.assert_not_called()
        self.assertEqual([f["id"] for f in result], [1, 2])
        self.assertTrue(all(f.get("locale_fallback") for f in result))
        self.assertTrue(all(f["locale"] == config.DEFAULT_LOCALE for f in result))

    def test_thread_pool_is_capped_by_competitor_analysis_concurrency(self):
        findings = [dict(FINDING, id=i) for i in range(10)]
        with patch.object(config, "COMPETITOR_ANALYSIS_CONCURRENCY", 3), \
             patch.object(
                 finding_translation, "ThreadPoolExecutor", wraps=finding_translation.ThreadPoolExecutor
             ) as mock_pool, \
             patch.object(finding_translation, "localize_finding", side_effect=lambda f, *, locale: {**f, "locale": locale}):
            finding_translation.localize_findings(findings, locale="ar")

        mock_pool.assert_called_once_with(max_workers=3)


if __name__ == "__main__":
    unittest.main()
