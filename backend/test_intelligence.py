import unittest
from collections import Counter
from datetime import datetime, timezone

from intelligence import (
    classify_platform,
    count_configured_terms,
    emotion_signature,
    filter_rows_for_period,
    net_sentiment,
    pipeline_discovery_series,
)


class IntelligenceHelpersTests(unittest.TestCase):
    def test_net_sentiment_is_positive_percentage_minus_negative_percentage(self):
        self.assertEqual(net_sentiment(Counter(positive=58, negative=15, neutral=27), 100), 43)
        self.assertEqual(net_sentiment(Counter(), 0), 0)

    def test_platform_classification_uses_x_hosts(self):
        self.assertEqual(classify_platform({"url": "https://x.com/strata/status/1"}), "X")
        self.assertEqual(classify_platform({"source_url": "https://twitter.com/strata"}), "X")
        self.assertEqual(classify_platform({"url": "https://example.com/story"}), "Web")

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

    def test_period_filter_uses_article_date(self):
        now = datetime(2026, 7, 23, tzinfo=timezone.utc)
        rows = [
            {"published": "2026-07-22T12:00:00Z"},
            {"published": "2026-06-01T12:00:00Z"},
        ]
        self.assertEqual(len(filter_rows_for_period(rows, "7d", now)), 1)


if __name__ == "__main__":
    unittest.main()
