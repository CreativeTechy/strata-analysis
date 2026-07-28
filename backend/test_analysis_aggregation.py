import os
import unittest

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from analysis import aggregation


class ComputeOverallToneTests(unittest.TestCase):
    def test_matching_tones_pass_through(self):
        self.assertEqual(aggregation.compute_overall_tone("critical", "critical"), "critical")

    def test_neutral_article_tone_defers_to_writer_tone(self):
        self.assertEqual(aggregation.compute_overall_tone("neutral", "enthusiastic"), "enthusiastic")

    def test_neutral_writer_tone_defers_to_article_tone(self):
        self.assertEqual(aggregation.compute_overall_tone("critical", "neutral"), "critical")

    def test_conflicting_non_neutral_tones_are_mixed(self):
        self.assertEqual(aggregation.compute_overall_tone("critical", "enthusiastic"), "mixed")

    def test_both_neutral_is_neutral(self):
        self.assertEqual(aggregation.compute_overall_tone("neutral", "neutral"), "neutral")


class BuildTopicInsightTests(unittest.TestCase):
    def test_empty_articles_returns_neutral_defaults(self):
        result = aggregation.build_topic_insight([], topic_name="my project")
        self.assertEqual(result["topic"], "my project")
        self.assertEqual(result["overall_sentiment"], "neutral")
        self.assertEqual(result["frequent_ideas"], [])

    def _article(self, **overrides):
        article = {
            "insight_json": {
                "topic": "ev review",
                "article_category": "review",
                "overall_sentiment": "positive",
                "writer_tone": "enthusiastic",
                "article_tone": "positive",
                "positive_feedback": ["great range"],
                "negative_feedback": [],
                "frequent_ideas": [{"idea": "charging is slow", "type": "complaint", "category": "charging"}],
            },
        }
        article.update(overrides)
        return article

    def test_dominant_category_and_sentiment_are_counted(self):
        articles = [self._article(), self._article()]
        result = aggregation.build_topic_insight(articles)
        self.assertEqual(result["article_category"], "review")
        self.assertEqual(result["overall_sentiment"], "positive")

    def test_frequent_ideas_are_counted_across_articles(self):
        articles = [self._article(), self._article(), self._article()]
        result = aggregation.build_topic_insight(articles)
        self.assertEqual(result["frequent_ideas"][0]["idea"], "charging is slow")
        self.assertEqual(result["frequent_ideas"][0]["frequency_estimate"], 3)

    def test_top_level_fields_are_used_when_insight_json_is_missing(self):
        articles = [{
            "article_category": "news",
            "sentiment": "negative",
            "writer_tone": "critical",
            "article_tone": "critical",
        }]
        result = aggregation.build_topic_insight(articles)
        self.assertEqual(result["article_category"], "news")
        self.assertEqual(result["overall_sentiment"], "negative")


if __name__ == "__main__":
    unittest.main()
