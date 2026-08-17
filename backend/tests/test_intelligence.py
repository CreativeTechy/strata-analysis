import unittest
from collections import Counter
from datetime import datetime, timezone
from unittest.mock import patch

from services.intelligence import intelligence
from services.intelligence.intelligence import (
    classify_platform,
    count_configured_terms,
    emotion_signature,
    filter_rows_for_period,
    get_project_intelligence,
    keyword_existence_over_time,
    net_sentiment,
    pipeline_discovery_series,
    sentiment_by_run_series,
)


class IntelligenceHelpersTests(unittest.TestCase):
    def test_net_sentiment_is_positive_percentage_minus_negative_percentage(self):
        self.assertEqual(net_sentiment(Counter(positive=58, negative=15, neutral=27), 100), 43)
        self.assertEqual(net_sentiment(Counter(), 0), 0)

    def test_platform_classification_uses_x_hosts(self):
        self.assertEqual(classify_platform({"url": "https://x.com/strata/status/1"}), "X")
        self.assertEqual(classify_platform({"source_url": "https://twitter.com/strata"}), "X")
        self.assertEqual(classify_platform({"url": "https://example.com/story"}), "Web")

    def test_platform_classification_uses_reddit_and_telegram_hosts(self):
        self.assertEqual(classify_platform({"url": "https://www.reddit.com/r/test/comments/1/x/"}), "Reddit")
        self.assertEqual(classify_platform({"source": "reddit.com/r/test"}), "Reddit")
        self.assertEqual(classify_platform({"url": "https://t.me/somechannel/1"}), "Telegram")
        self.assertEqual(classify_platform({"source": "t.me/somechannel"}), "Telegram")

    def test_emotions_are_mapped_from_existing_tones(self):
        signature = {item["axis"]: item["count"] for item in emotion_signature([
            {"article_tone": "optimistic", "writer_tone": "neutral"},
            {"article_tone": "angry", "writer_tone": "neutral"},
            {"article_tone": "positive", "writer_tone": "neutral"},
        ])}
        self.assertEqual(signature["anticipation"], 1)
        self.assertEqual(signature["anger"], 1)
        self.assertEqual(signature["joy"], 1)

    def test_configured_terms_count_case_insensitive_occurrences(self):
        terms = count_configured_terms(
            [{"title": "Launch #Strata", "summary": "", "text": "Strata is here. #strata"}],
            hashtags=["Strata"],
            keywords=["launch"],
        )
        self.assertEqual({item["term"]: item["mentions"] for item in terms}, {"#Strata": 3, "launch": 1})

    def test_pipeline_deltas_cover_first_and_zero_baseline_runs(self):
        values = pipeline_discovery_series([
            {"id": "a", "articles_scraped": 0},
            {"id": "b", "articles_scraped": 10},
            {"id": "c", "articles_scraped": 5},
        ])
        self.assertIsNone(values[0]["change_pct"])
        self.assertEqual(values[1]["change_pct"], 100)
        self.assertEqual(values[2]["change_pct"], -50)

    def test_sentiment_by_run_pairs_each_run_with_its_own_counts(self):
        points = sentiment_by_run_series(
            [{"id": "a", "finished_at": "2026-07-01T00:00:00Z"}, {"id": "b", "finished_at": "2026-07-02T00:00:00Z"}],
            {"a": {"positive": 3, "negative": 1}},
        )
        self.assertEqual(points[0], {
            "run_id": "a", "completed_at": "2026-07-01T00:00:00Z", "total": 4,
            "positive": 3, "negative": 1, "neutral": 0, "mixed": 0,
        })
        self.assertEqual(points[1], {
            "run_id": "b", "completed_at": "2026-07-02T00:00:00Z", "total": 0,
            "positive": 0, "negative": 0, "neutral": 0, "mixed": 0,
        })

    def test_period_filter_uses_article_date(self):
        now = datetime(2026, 7, 23, tzinfo=timezone.utc)
        rows = [
            {"published": "2026-07-22T12:00:00Z"},
            {"published": "2026-06-01T12:00:00Z"},
        ]
        self.assertEqual(len(filter_rows_for_period(rows, "7d", now)), 1)

    def test_keyword_existence_splits_into_one_series_per_keyword(self):
        rows = [
            {"published": "2026-07-20T00:00:00Z", "title": "EV recall", "summary": "", "text": ""},
            {"published": "2026-07-20T00:00:00Z", "title": "battery fire", "summary": "", "text": ""},
            {"published": "2026-07-21T00:00:00Z", "title": "no matches here", "summary": "", "text": ""},
        ]
        series = keyword_existence_over_time(rows, ["EV", "battery"], all_keywords=True)
        self.assertEqual(
            series,
            [
                {"date": "2026-07-20", "EV": 1, "battery": 1},
                {"date": "2026-07-21", "EV": 0, "battery": 0},
            ],
        )

    def test_keyword_existence_combines_keywords_without_double_counting(self):
        rows = [
            {"published": "2026-07-20T00:00:00Z", "title": "EV battery recall", "summary": "", "text": ""},
            {"published": "2026-07-20T00:00:00Z", "title": "battery only", "summary": "", "text": ""},
        ]
        series = keyword_existence_over_time(rows, ["EV", "battery"], all_keywords=False)
        self.assertEqual(series, [{"date": "2026-07-20", "matches": 2}])

    def test_keyword_existence_filters_by_source_url(self):
        rows = [
            {"published": "2026-07-20T00:00:00Z", "source_url": "https://a.example.com", "title": "EV news", "summary": "", "text": ""},
            {"published": "2026-07-20T00:00:00Z", "source_url": "https://b.example.com", "title": "EV news too", "summary": "", "text": ""},
        ]
        series = keyword_existence_over_time(rows, ["EV"], source_url="https://a.example.com", all_keywords=False)
        self.assertEqual(series, [{"date": "2026-07-20", "matches": 1}])

    def test_keyword_existence_returns_empty_without_keywords(self):
        self.assertEqual(keyword_existence_over_time([{"title": "EV"}], []), [])


class GetProjectIntelligenceTests(unittest.TestCase):
    """get_project_intelligence() does a deferred `from
    services.articles.articles_store import _topic_summary` import inside the
    function body, not at module level - a bad import path there only breaks
    at call time, so this must actually invoke the function (not just import
    the module) to catch it. Regression test for a reorg that broke exactly
    this: the module-level import graph checked out fine while this deferred
    import still pointed at the pre-move module path."""

    def test_runs_end_to_end_without_a_database(self):
        with patch.object(intelligence, "_database_ready", return_value=False):
            result = get_project_intelligence({"id": 1, "hashtags": [], "keywords": []})
        self.assertEqual(result["project_id"], 1)
        self.assertEqual(result["period"], "30d")
        self.assertIsNone(result["run_id"])
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["active_sources"], 0)
        self.assertIn("insights", result)

    def test_run_id_passes_through_into_the_response(self):
        """When a specific pipeline run is selected, the response should echo
        it back so the frontend can confirm which run it's looking at."""
        with patch.object(intelligence, "_database_ready", return_value=False):
            result = get_project_intelligence({"id": 1, "hashtags": [], "keywords": []}, run_id="run-123")
        self.assertEqual(result["run_id"], "run-123")
        self.assertEqual(result["total"], 0)


if __name__ == "__main__":
    unittest.main()
