"""The Export Summary PDF's "variation from last run" service: verified metrics,
handed to the LLM only for the narrative, with every evidence reference
validated against the ids actually shown to the model."""

import os
import unittest
from datetime import date, datetime, timezone
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


class RunLabelsTests(unittest.TestCase):
    def test_run_date_and_label_use_the_runs_timestamp_and_sequence(self):
        run = {"sequence_number": 7, "finished_at": datetime(2026, 1, 10, 9, 0, tzinfo=timezone.utc)}
        self.assertEqual(yc._run_date(run, ZoneInfo("UTC")), date(2026, 1, 10))
        self.assertEqual(yc._run_label(run, ZoneInfo("UTC")), "Analysis #7 - Jan 10, 2026")


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
        self.assertEqual(coverage, {"current_ids": 3, "previous_ids": 3, "common": 2, "added": 1, "removed": 1, "sampled": False})

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
            "current": {"total": 1, "positive": 1, "negative": 0, "neutral": 0, "mixed": 0, "net_sentiment": 100},
            "previous": {"total": 1, "positive": 0, "negative": 1, "neutral": 0, "mixed": 0, "net_sentiment": -100},
            "deltas": {"total": 0, "positive": 1, "negative": -1, "neutral": 0, "mixed": 0, "net_sentiment": 200},
            "coverage": {"current_ids": 1, "previous_ids": 1, "common": 0, "added": 1, "removed": 1, "sampled": False},
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


class BuildVariationFromLastRunTests(unittest.TestCase):
    CURRENT = {"id": "run-9", "sequence_number": 9, "project_id": 1,
               "finished_at": datetime(2026, 8, 20, tzinfo=timezone.utc)}
    PREVIOUS = {"id": "run-8", "sequence_number": 8, "project_id": 1,
                "finished_at": datetime(2025, 1, 2, tzinfo=timezone.utc)}

    def _report_data(self, rows, scope_type="run"):
        return {"project": {"id": 1, "name": "Acme"},
                "scope": {"type": scope_type, "run_id": "run-9" if scope_type == "run" else None},
                "_analyzed_rows": rows}

    def test_period_report_requires_a_selected_run(self):
        with patch.object(yc, "get_previous_analysis_run") as previous:
            result = yc.build_variation_from_last_run({"id": 1}, self._report_data([_row(1)], "period"))
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("Select an analysis run", result["reason"])
        self.assertEqual(result["reason_code"], "no_run_selected")
        previous.assert_not_called()

    def test_first_run_is_unavailable_but_keeps_selected_run_metrics(self):
        with patch.object(yc, "get_previous_analysis_run", return_value=None):
            result = yc.build_variation_from_last_run({"id": 1}, self._report_data([_row(1)]), run=self.CURRENT)
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("No previous analysis run", result["reason"])
        self.assertEqual(result["reason_code"], "no_previous_run")
        self.assertEqual(result["current_sequence_number"], 9)
        self.assertIsNone(result["previous_sequence_number"])
        self.assertEqual(result["metrics"]["current"]["total"], 1)

    def test_compares_with_previous_run_regardless_of_time_gap(self):
        current_rows = [_row(1, "positive")]
        previous_rows = [dict(_row(2, "negative"), analysis_status="success")]
        raw = '{"ideas":"a","sentiment":"b","opinions":"c","topics":"d","implications":"e","evidence":[]}'
        with patch.object(yc, "get_previous_analysis_run", return_value=self.PREVIOUS), \
             patch.object(yc, "fetch_run_article_rows", return_value=previous_rows) as fetch, \
             patch.object(yc, "chat_completion", return_value=raw), \
             patch.object(yc.config, "DATABASE_URL", ""):
            result = yc.build_variation_from_last_run({"id": 1}, self._report_data(current_rows), run=self.CURRENT)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["current_run_id"], "run-9")
        self.assertEqual(result["previous_run_id"], "run-8")
        self.assertEqual(result["current_sequence_number"], 9)
        self.assertEqual(result["previous_sequence_number"], 8)
        self.assertIsNone(result["reason_code"])
        self.assertEqual(result["current_date"], "2026-08-20")
        self.assertEqual(result["previous_date"], "2025-01-02")
        self.assertEqual(result["metrics"]["current"]["positive"], 1)
        self.assertEqual(result["metrics"]["previous"]["negative"], 1)
        fetch.assert_called_once_with(1, "run-8")

    def test_llm_failure_keeps_both_runs_verified_metrics(self):
        previous_rows = [dict(_row(2, "negative"), analysis_status="success")]
        with patch.object(yc, "get_previous_analysis_run", return_value=self.PREVIOUS), \
             patch.object(yc, "fetch_run_article_rows", return_value=previous_rows), \
             patch.object(yc, "chat_completion", side_effect=LLMError("boom")), \
             patch.object(yc.config, "DATABASE_URL", ""):
            result = yc.build_variation_from_last_run({"id": 1}, self._report_data([_row(1)]), run=self.CURRENT)
        self.assertEqual(result["status"], "llm_failed")
        self.assertIsNotNone(result["metrics"]["current"])
        self.assertIsNotNone(result["metrics"]["previous"])


if __name__ == "__main__":
    unittest.main()
