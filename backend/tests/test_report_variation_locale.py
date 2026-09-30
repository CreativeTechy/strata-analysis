"""Locale-aware rendering of the "Variation from Last Run" narrative
(services/reports/yesterday_comparison.py): layered on top of the canonical
(English) narrative rather than replacing it - canonical stays keyed the
same way it always was, and a non-default locale is a separate,
invalidatable rendering of it, cached in
project_report_variation_summaries_localized. Same shape as
test_trend_summary_locale.py."""

import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import config
from services.reports import yesterday_comparison as yc

CURRENT = {"id": "run-9", "sequence_number": 9, "project_id": 1,
           "finished_at": datetime(2026, 8, 20, tzinfo=timezone.utc)}
PREVIOUS = {"id": "run-8", "sequence_number": 8, "project_id": 1,
            "finished_at": datetime(2025, 1, 2, tzinfo=timezone.utc)}

CANONICAL_NARRATIVE_JSON = (
    '{"ideas":"a","sentiment":"b","opinions":"c","topics":"d","implications":"e","evidence":[]}'
)


def _row(id_, sentiment="positive", analysis_status=None):
    row = {
        "id": id_, "sentiment": sentiment, "title": f"Article {id_}", "summary": "s",
        "topics": [], "key_points": [], "insight_json": {"people_opinions": []},
        "relevance_score": None,
    }
    if analysis_status:
        row["analysis_status"] = analysis_status
    return row


def _report_data(rows):
    return {"project": {"id": 1, "name": "Acme"},
            "scope": {"type": "run", "run_id": "run-9"},
            "_analyzed_rows": rows}


class LocalizedReportVariationTests(unittest.TestCase):
    def _build(self, locale=None, force=False, chat_side_effect=None):
        current_rows = [_row(1, "positive")]
        previous_rows = [_row(2, "negative", analysis_status="success")]
        with patch.object(yc, "get_previous_analysis_run", return_value=PREVIOUS), \
             patch.object(yc, "fetch_run_article_rows", return_value=previous_rows), \
             patch.object(yc.config, "DATABASE_URL", "postgres://fake"), \
             patch.object(yc, "chat_completion", side_effect=chat_side_effect) as mock_chat, \
             patch.object(yc, "_load_cached", return_value=None), \
             patch.object(yc, "_save_cached") as mock_save_canonical, \
             patch.object(yc, "_load_cached_localized") as mock_load_localized, \
             patch.object(yc, "_save_cached_localized") as mock_save_localized:
            result = yc.build_variation_from_last_run(
                {"id": 1}, _report_data(current_rows), run=CURRENT, force=force, locale=locale,
            )
        return result, mock_chat, mock_save_canonical, mock_load_localized, mock_save_localized

    def test_default_locale_never_touches_localized_cache(self):
        result, mock_chat, _, mock_load_localized, mock_save_localized = self._build(
            locale="en", chat_side_effect=[CANONICAL_NARRATIVE_JSON],
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["locale"], "en")
        mock_chat.assert_called_once()
        mock_load_localized.assert_not_called()
        mock_save_localized.assert_not_called()

    def test_non_default_locale_renders_from_canonical_and_caches_it_separately(self):
        result, mock_chat, mock_save_canonical, mock_load_localized, mock_save_localized = self._build(
            locale="ar", chat_side_effect=[CANONICAL_NARRATIVE_JSON, "سرد مترجم"],
        )
        self.assertEqual(result["locale"], "ar")
        self.assertFalse(result["cached"])
        self.assertEqual(result["narrative"], "سرد مترجم")
        self.assertEqual(mock_chat.call_count, 2)
        # The second call rendered the already-generated canonical narrative,
        # not a fresh comparison of the raw rows.
        rendered_prompt = mock_chat.call_args_list[1].kwargs["messages"][1]["content"]
        self.assertIn("Ideas & Themes", rendered_prompt)
        mock_save_canonical.assert_called_once()
        mock_load_localized.assert_called_once()
        mock_save_localized.assert_called_once()
        fingerprint_arg = mock_save_localized.call_args[0][-1]
        self.assertIsInstance(fingerprint_arg, str)

    def test_localized_cache_hit_skips_another_llm_call(self):
        current_rows = [_row(1, "positive")]
        previous_rows = [_row(2, "negative", analysis_status="success")]
        fingerprint = yc._data_fingerprint(current_rows, previous_rows)
        cached_localized = {"narrative": "سرد مخزّن", "source_fingerprint": fingerprint, "updated_at": None}
        with patch.object(yc, "get_previous_analysis_run", return_value=PREVIOUS), \
             patch.object(yc, "fetch_run_article_rows", return_value=previous_rows), \
             patch.object(yc.config, "DATABASE_URL", "postgres://fake"), \
             patch.object(yc, "chat_completion", side_effect=[CANONICAL_NARRATIVE_JSON]) as mock_chat, \
             patch.object(yc, "_load_cached", return_value=None), \
             patch.object(yc, "_save_cached"), \
             patch.object(yc, "_load_cached_localized", return_value=cached_localized), \
             patch.object(yc, "_save_cached_localized") as mock_save_localized:
            result = yc.build_variation_from_last_run(
                {"id": 1}, _report_data(current_rows), run=CURRENT, locale="ar",
            )
        self.assertTrue(result["cached"])
        self.assertEqual(result["narrative"], "سرد مخزّن")
        # Only the canonical (English) narrative call - the localized cache hit.
        mock_chat.assert_called_once()
        mock_save_localized.assert_not_called()

    def test_falls_back_to_canonical_narrative_when_rendering_fails(self):
        current_rows = [_row(1, "positive")]
        previous_rows = [_row(2, "negative", analysis_status="success")]
        with patch.object(yc, "get_previous_analysis_run", return_value=PREVIOUS), \
             patch.object(yc, "fetch_run_article_rows", return_value=previous_rows), \
             patch.object(yc.config, "DATABASE_URL", "postgres://fake"), \
             patch.object(yc, "chat_completion", side_effect=[CANONICAL_NARRATIVE_JSON, RuntimeError("boom")]), \
             patch.object(yc, "_load_cached", return_value=None), \
             patch.object(yc, "_save_cached"), \
             patch.object(yc, "_load_cached_localized", return_value=None), \
             patch.object(yc, "_save_cached_localized") as mock_save_localized:
            result = yc.build_variation_from_last_run(
                {"id": 1}, _report_data(current_rows), run=CURRENT, locale="ar",
            )
        self.assertTrue(result.get("locale_fallback"))
        self.assertEqual(result["locale"], config.DEFAULT_LOCALE)
        self.assertIn("Ideas & Themes", result["narrative"])
        mock_save_localized.assert_not_called()

    def test_force_bypasses_the_localized_cache_and_re_renders(self):
        current_rows = [_row(1, "positive")]
        previous_rows = [_row(2, "negative", analysis_status="success")]
        with patch.object(yc, "get_previous_analysis_run", return_value=PREVIOUS), \
             patch.object(yc, "fetch_run_article_rows", return_value=previous_rows), \
             patch.object(yc.config, "DATABASE_URL", "postgres://fake"), \
             patch.object(yc, "chat_completion", side_effect=[CANONICAL_NARRATIVE_JSON, "سرد جديد"]) as mock_chat, \
             patch.object(yc, "_save_cached"), \
             patch.object(yc, "_load_cached_localized") as mock_load_localized, \
             patch.object(yc, "_save_cached_localized") as mock_save_localized:
            result = yc.build_variation_from_last_run(
                {"id": 1}, _report_data(current_rows), run=CURRENT, locale="ar", force=True,
            )
        self.assertEqual(result["narrative"], "سرد جديد")
        self.assertFalse(result["cached"])
        mock_load_localized.assert_not_called()
        mock_save_localized.assert_called_once()
        self.assertEqual(mock_chat.call_count, 2)


if __name__ == "__main__":
    unittest.main()
