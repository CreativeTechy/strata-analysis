"""services/reports/yesterday_comparison.py: the Export Summary PDF's
"variation from yesterday" section - verified metrics computed in Python,
handed to the LLM only for the narrative, with every evidence reference
validated against the ids actually shown to the model."""

import os
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from llm_client import LLMError
from services.reports import yesterday_comparison as yc


def _row(id_, sentiment="positive", summary="s", topics=None, key_points=None, opinions=None):
    return {
        "id": id_, "sentiment": sentiment, "title": f"Article {id_}", "summary": summary,
        "topics": topics or [], "key_points": key_points or [],
        "insight_json": {"people_opinions": opinions or []},
        "relevance_score": None,
    }


class DayStartUtcTests(unittest.TestCase):
    def test_converts_local_midnight_to_the_right_utc_instant(self):
        tz = ZoneInfo("Etc/GMT-4")  # fixed UTC+4, no DST - deterministic
        start = yc._day_start_utc(date(2026, 3, 5), tz)
        self.assertEqual(start, datetime(2026, 3, 4, 20, 0, tzinfo=timezone.utc))


class ScopeDatesTests(unittest.TestCase):
    def test_run_scope_anchors_to_the_runs_own_analysis_date_not_now(self):
        """Requirement: a PDF exported today for a run from weeks ago must
        compare against the day before *that run*, not the day before the
        export click."""
        report_data = {
            "scope": {"type": "run"},
            "_run": {"finished_at": datetime(2026, 1, 10, 9, 0, tzinfo=timezone.utc)},
        }
        today, yesterday = yc._scope_dates(report_data, ZoneInfo("UTC"))
        self.assertEqual(today, date(2026, 1, 10))
        self.assertEqual(yesterday, date(2026, 1, 9))

    def test_period_scope_yesterday_is_always_one_day_before_today(self):
        report_data = {"scope": {"type": "period"}, "_run": None}
        today, yesterday = yc._scope_dates(report_data, ZoneInfo("UTC"))
        self.assertEqual(yesterday, today - timedelta(days=1))


class MetricsArithmeticTests(unittest.TestCase):
    def test_sentiment_metrics_and_net_sentiment(self):
        rows = [_row(1, "positive"), _row(2, "positive"), _row(3, "negative")]
        metrics = yc._sentiment_metrics(rows)
        self.assertEqual(metrics["total"], 3)
        self.assertEqual(metrics["positive"], 2)
        self.assertEqual(metrics["negative"], 1)
        self.assertEqual(metrics["net_sentiment"], 33)  # round((2-1)/3*100)

    def test_deltas_are_today_minus_yesterday(self):
        today = {"total": 10, "positive": 6, "negative": 2, "neutral": 2, "mixed": 0, "net_sentiment": 40}
        yesterday = {"total": 8, "positive": 3, "negative": 3, "neutral": 2, "mixed": 0, "net_sentiment": 0}
        deltas = yc._deltas(today, yesterday)
        self.assertEqual(deltas, {"total": 2, "positive": 3, "negative": -1, "neutral": 0, "mixed": 0, "net_sentiment": 40})

    def test_coverage_counts_added_removed_and_common(self):
        coverage = yc._coverage({1, 2, 3}, {2, 3, 4}, sampled=False)
        self.assertEqual(coverage, {"today_ids": 3, "yesterday_ids": 3, "common": 2, "added": 1, "removed": 1, "sampled": False})

    def test_fingerprint_stable_for_identical_rows_and_sensitive_to_changes(self):
        rows_a = [_row(1, "positive")]
        rows_b = [_row(1, "positive")]
        rows_c = [_row(1, "negative")]
        self.assertEqual(yc._data_fingerprint(rows_a, []), yc._data_fingerprint(rows_b, []))
        self.assertNotEqual(yc._data_fingerprint(rows_a, []), yc._data_fingerprint(rows_c, []))

    def test_sample_returns_everything_unsampled_under_the_limit(self):
        rows = [_row(i) for i in range(5)]
        sample, sampled = yc._sample(rows, 10)
        self.assertEqual(len(sample), 5)
        self.assertFalse(sampled)

    def test_sample_truncates_and_flags_over_the_limit(self):
        rows = [_row(i) for i in range(50)]
        sample, sampled = yc._sample(rows, 10)
        self.assertEqual(len(sample), 10)
        self.assertTrue(sampled)


class NarrativeGroundingTests(unittest.TestCase):
    """The LLM only ever sees the sampled rows handed to it - any article id
    it cites outside that set (hallucinated or from the wrong day) must not
    survive into the rendered evidence."""

    def _metrics(self):
        return {
            "today": {"total": 1, "positive": 1, "negative": 0, "neutral": 0, "mixed": 0, "net_sentiment": 100},
            "yesterday": {"total": 1, "positive": 0, "negative": 1, "neutral": 0, "mixed": 0, "net_sentiment": -100},
            "deltas": {"total": 0, "positive": 1, "negative": -1, "neutral": 0, "mixed": 0, "net_sentiment": 200},
            "coverage": {"today_ids": 1, "yesterday_ids": 1, "common": 0, "added": 1, "removed": 1, "sampled": False},
        }

    def test_valid_evidence_ids_are_kept(self):
        raw = '{"ideas": "a", "sentiment": "b", "opinions": "c", "topics": "d", "implications": "e", ' \
              '"evidence": [{"point": "claim", "article_ids": [1]}]}'
        with patch.object(yc, "chat_completion", return_value=raw):
            narrative, evidence = yc._generate_narrative([_row(1)], [_row(2)], self._metrics(), date(2026, 3, 5), date(2026, 3, 4))
        self.assertIn("Ideas & Themes", narrative)
        self.assertEqual(evidence, [{"point": "claim", "article_ids": [1]}])

    def test_ungrounded_article_ids_are_dropped(self):
        """999 was never shown to the model for either day."""
        raw = '{"ideas": "a", "sentiment": "b", "opinions": "c", "topics": "d", "implications": "e", ' \
              '"evidence": [{"point": "claim", "article_ids": [999]}]}'
        with patch.object(yc, "chat_completion", return_value=raw):
            _, evidence = yc._generate_narrative([_row(1)], [_row(2)], self._metrics(), date(2026, 3, 5), date(2026, 3, 4))
        self.assertEqual(evidence, [])

    def test_mixed_valid_and_invalid_ids_keeps_only_the_valid_ones(self):
        raw = '{"ideas": "a", "sentiment": "b", "opinions": "c", "topics": "d", "implications": "e", ' \
              '"evidence": [{"point": "claim", "article_ids": [1, 999]}]}'
        with patch.object(yc, "chat_completion", return_value=raw):
            _, evidence = yc._generate_narrative([_row(1)], [_row(2)], self._metrics(), date(2026, 3, 5), date(2026, 3, 4))
        self.assertEqual(evidence, [{"point": "claim", "article_ids": [1]}])

    def test_unparsable_response_raises_for_the_caller_to_catch(self):
        from analysis.json_utils import JSONParseError
        with patch.object(yc, "chat_completion", return_value="not json"):
            with self.assertRaises(JSONParseError):
                yc._generate_narrative([_row(1)], [_row(2)], self._metrics(), date(2026, 3, 5), date(2026, 3, 4))


class BuildVariationFromYesterdayTests(unittest.TestCase):
    def _report_data(self, analyzed_rows, scope_type="period", period="all"):
        # period="all" by default: the fixture rows below carry no
        # published/created_at date, and a rolling-window period would
        # otherwise filter yesterday's reconstructed rows out entirely (see
        # build_variation_from_yesterday's period-scope filter) - period
        # filtering itself is report_data.py's concern, not this module's.
        return {
            "project": {"id": 1, "name": "Acme"},
            "scope": {"type": scope_type, "period": period, "run_id": None, "analysis_date_label": "Last 30 days"},
            "_analyzed_rows": analyzed_rows,
        }

    def test_no_analyzed_articles_in_scope_is_unavailable(self):
        with patch.object(yc, "earliest_snapshot_at", return_value=None):
            result = yc.build_variation_from_yesterday({"id": 1}, self._report_data([]))
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("current report scope", result["reason"])

    def test_no_history_before_yesterday_is_unavailable_but_keeps_todays_metrics(self):
        today_rows = [_row(1, "positive")]
        with patch.object(yc, "earliest_snapshot_at", return_value=None), \
             patch.object(yc, "fetch_state_as_of", return_value=[]):
            result = yc.build_variation_from_yesterday({"id": 1}, self._report_data(today_rows))
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("No analysis history recorded before", result["reason"])
        self.assertEqual(result["metrics"]["today"]["total"], 1)
        self.assertIsNone(result["metrics"]["yesterday"])

    def test_successful_comparison_computes_metrics_and_calls_the_llm(self):
        today_rows = [_row(1, "positive")]
        yesterday_rows = [dict(_row(2, "negative"), analysis_status="success")]
        raw = '{"ideas": "a", "sentiment": "b", "opinions": "c", "topics": "d", "implications": "e", "evidence": []}'
        with patch.object(yc, "earliest_snapshot_at", return_value=datetime(2020, 1, 1, tzinfo=timezone.utc)), \
             patch.object(yc, "fetch_state_as_of", return_value=yesterday_rows), \
             patch("services.reports.yesterday_comparison.config.DATABASE_URL", ""), \
             patch.object(yc, "chat_completion", return_value=raw) as llm:
            result = yc.build_variation_from_yesterday({"id": 1}, self._report_data(today_rows))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["metrics"]["today"]["total"], 1)
        self.assertEqual(result["metrics"]["yesterday"]["total"], 1)
        self.assertIsNotNone(result["narrative"])
        llm.assert_called_once()

    def test_llm_failure_keeps_verified_metrics_and_marks_narrative_unavailable(self):
        today_rows = [_row(1, "positive")]
        yesterday_rows = [dict(_row(2, "negative"), analysis_status="success")]
        with patch.object(yc, "earliest_snapshot_at", return_value=datetime(2020, 1, 1, tzinfo=timezone.utc)), \
             patch.object(yc, "fetch_state_as_of", return_value=yesterday_rows), \
             patch("services.reports.yesterday_comparison.config.DATABASE_URL", ""), \
             patch.object(yc, "chat_completion", side_effect=LLMError("boom")):
            result = yc.build_variation_from_yesterday({"id": 1}, self._report_data(today_rows))
        self.assertEqual(result["status"], "llm_failed")
        self.assertIsNone(result["narrative"])
        self.assertIsNotNone(result["metrics"]["today"])
        self.assertIsNotNone(result["metrics"]["yesterday"])

    def test_cache_hit_with_matching_fingerprint_skips_the_llm_call(self):
        today_rows = [_row(1, "positive")]
        yesterday_rows = [dict(_row(2, "negative"), analysis_status="success")]
        fingerprint = yc._data_fingerprint(today_rows, yesterday_rows)
        cached_row = {
            "status": "ok", "reason": None,
            "today_metrics": {"total": 1}, "yesterday_metrics": {"total": 1}, "deltas": {}, "coverage": {},
            "data_fingerprint": fingerprint, "narrative": "cached narrative", "evidence": [], "generated_at": None,
        }
        with patch.object(yc, "earliest_snapshot_at", return_value=datetime(2020, 1, 1, tzinfo=timezone.utc)), \
             patch.object(yc, "fetch_state_as_of", return_value=yesterday_rows), \
             patch("services.reports.yesterday_comparison.config.DATABASE_URL", "postgres://x"), \
             patch("services.reports.yesterday_comparison.db.fetch_one", return_value=cached_row), \
             patch.object(yc, "chat_completion") as llm:
            result = yc.build_variation_from_yesterday({"id": 1}, self._report_data(today_rows))
        self.assertEqual(result["narrative"], "cached narrative")
        self.assertTrue(result["cached"])
        llm.assert_not_called()

    def test_short_circuits_before_any_history_lookup_when_nothing_is_in_scope_today(self):
        """No analyzed articles today means there's nothing to compare
        against - reconstructing yesterday's state (a real article_analyses
        query) is wasted work that must not run at all in that case."""
        with patch.object(yc, "earliest_snapshot_at") as earliest, \
             patch.object(yc, "fetch_state_as_of") as fetch:
            result = yc.build_variation_from_yesterday({"id": 1}, self._report_data([]))
        self.assertEqual(result["status"], "unavailable")
        earliest.assert_not_called()
        fetch.assert_not_called()

    def test_period_filter_emptying_yesterday_is_distinguished_from_no_history(self):
        """History exists (fetch_state_as_of returns real rows) but the
        period's rolling window - anchored to "now", not "yesterday" - excludes
        all of it. That's a different, more specific situation than no
        history existing at all before the cutoff, and must say so rather
        than implying historical tracking isn't working."""
        today_rows = [_row(1, "positive")]
        # No published/created_at on these fixture rows -> article_date() is
        # None -> filter_rows_for_period() drops them for any non-"all" period.
        yesterday_rows = [dict(_row(2, "negative"), analysis_status="success")]
        with patch.object(yc, "earliest_snapshot_at", return_value=datetime(2020, 1, 1, tzinfo=timezone.utc)), \
             patch.object(yc, "fetch_state_as_of", return_value=yesterday_rows):
            result = yc.build_variation_from_yesterday(
                {"id": 1}, self._report_data(today_rows, period="7d"),
            )
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("selected period", result["reason"])
        self.assertNotIn("No analysis history recorded", result["reason"])
        self.assertEqual(result["metrics"]["today"]["total"], 1)

    def test_genuinely_no_history_still_reports_the_no_history_reason(self):
        """The period-filter message above must not swallow the real "no
        history at all" case - an empty fetch_state_as_of() result (no rows
        recorded before the cutoff) still gets the original message."""
        today_rows = [_row(1, "positive")]
        with patch.object(yc, "earliest_snapshot_at", return_value=datetime(2020, 1, 1, tzinfo=timezone.utc)), \
             patch.object(yc, "fetch_state_as_of", return_value=[]):
            result = yc.build_variation_from_yesterday(
                {"id": 1}, self._report_data(today_rows, period="7d"),
            )
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("No analysis history recorded before", result["reason"])

    def test_cache_with_mismatched_fingerprint_regenerates(self):
        today_rows = [_row(1, "positive")]
        yesterday_rows = [dict(_row(2, "negative"), analysis_status="success")]
        stale_cached_row = {
            "status": "ok", "reason": None,
            "today_metrics": {}, "yesterday_metrics": {}, "deltas": {}, "coverage": {},
            "data_fingerprint": "stale-fingerprint-does-not-match", "narrative": "old narrative", "evidence": [], "generated_at": None,
        }
        raw = '{"ideas": "a", "sentiment": "b", "opinions": "c", "topics": "d", "implications": "e", "evidence": []}'
        with patch.object(yc, "earliest_snapshot_at", return_value=datetime(2020, 1, 1, tzinfo=timezone.utc)), \
             patch.object(yc, "fetch_state_as_of", return_value=yesterday_rows), \
             patch("services.reports.yesterday_comparison.config.DATABASE_URL", "postgres://x"), \
             patch("services.reports.yesterday_comparison.db.fetch_one", return_value=stale_cached_row), \
             patch("services.reports.yesterday_comparison.db.execute") as save, \
             patch.object(yc, "chat_completion", return_value=raw) as llm:
            result = yc.build_variation_from_yesterday({"id": 1}, self._report_data(today_rows))
        llm.assert_called_once()
        self.assertNotEqual(result["narrative"], "old narrative")
        save.assert_called_once()


if __name__ == "__main__":
    unittest.main()
