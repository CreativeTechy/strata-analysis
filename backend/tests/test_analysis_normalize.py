import os
import unittest

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from analysis import normalize


class NormalizeSentimentTests(unittest.TestCase):
    """normalize_sentiment() is only used for per-item fields (people_opinions,
    frequent_ideas/feedback entries) - never for the article-level
    overall_sentiment/sentiment, which comes solely from analysis/sentiment.py."""

    def test_exact_matches_pass_through(self):
        for value in ("positive", "negative", "mixed", "neutral"):
            self.assertEqual(normalize.normalize_sentiment(value), value)

    def test_trailing_punctuation_and_case_are_tolerated(self):
        self.assertEqual(normalize.normalize_sentiment("Positive."), "positive")
        self.assertEqual(normalize.normalize_sentiment("NEGATIVE"), "negative")

    def test_qualified_phrases_map_to_the_label_they_lean_toward(self):
        self.assertEqual(normalize.normalize_sentiment("mostly positive"), "positive")
        self.assertEqual(normalize.normalize_sentiment("negative overall"), "negative")
        self.assertEqual(normalize.normalize_sentiment("mixed sentiment"), "mixed")
        self.assertEqual(normalize.normalize_sentiment("somewhat positive"), "positive")

    def test_phrases_mentioning_both_directions_are_mixed(self):
        self.assertEqual(normalize.normalize_sentiment("positive and negative"), "mixed")

    def test_unrecognized_or_empty_values_fall_back_to_neutral(self):
        self.assertEqual(normalize.normalize_sentiment("unclear"), "neutral")
        self.assertEqual(normalize.normalize_sentiment(""), "neutral")
        self.assertEqual(normalize.normalize_sentiment(None), "neutral")


class NormalizeCategoryToneTests(unittest.TestCase):
    def test_valid_category_passes_through_lowercased(self):
        self.assertEqual(normalize.normalize_category("Review"), "review")

    def test_invalid_category_falls_back_to_general_article(self):
        self.assertEqual(normalize.normalize_category("not-a-category"), "general_article")

    def test_valid_tone_passes_through_lowercased(self):
        self.assertEqual(normalize.normalize_tone("Angry"), "angry")

    def test_invalid_tone_falls_back_to_neutral(self):
        self.assertEqual(normalize.normalize_tone("bogus"), "neutral")


class AsListTests(unittest.TestCase):
    def test_none_is_empty_list(self):
        self.assertEqual(normalize.as_list(None), [])

    def test_list_is_deduped_preserving_order(self):
        self.assertEqual(normalize.as_list(["a", "b", "a"]), ["a", "b"])

    def test_comma_separated_string_is_split(self):
        self.assertEqual(normalize.as_list("a, b,c"), ["a", "b", "c"])


class RelevanceScoreTests(unittest.TestCase):
    def test_clamps_to_0_10_range(self):
        self.assertEqual(normalize.normalize_relevance_score(15), 10)
        self.assertEqual(normalize.normalize_relevance_score(-3), 0)
        self.assertEqual(normalize.normalize_relevance_score(5), 5)

    def test_non_numeric_defaults_to_zero(self):
        self.assertEqual(normalize.normalize_relevance_score("high"), 0)
        self.assertEqual(normalize.normalize_relevance_score(None), 0)


class PeopleOpinionsTests(unittest.TestCase):
    def test_normalizes_and_dedupes(self):
        result = normalize.normalize_people_opinions([
            {"opinion": "Loves the range", "sentiment": "Positive", "category": "performance"},
            {"opinion": "Loves the range", "sentiment": "positive", "category": "performance"},
        ])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["sentiment"], "positive")

    def test_non_dict_items_default_to_neutral(self):
        result = normalize.normalize_people_opinions(["just a plain string"])
        self.assertEqual(result, [{
            "opinion": "just a plain string", "sentiment": "neutral", "category": "",
            "gender": "unknown", "age_range": "unknown", "region": "unknown",
        }])

    def test_demographics_are_normalized_and_default_to_unknown(self):
        result = normalize.normalize_people_opinions([
            {"opinion": "Loves the range", "sentiment": "positive", "category": "performance",
             "gender": "Female", "age_range": "25-34", "region": "lebanon"},
            {"opinion": "Slow charging", "sentiment": "negative", "category": "charging"},
        ])
        self.assertEqual(result[0]["gender"], "female")
        self.assertEqual(result[0]["age_range"], "25-34")
        self.assertEqual(result[0]["region"], "Lebanon")
        self.assertEqual(result[1]["gender"], "unknown")
        self.assertEqual(result[1]["age_range"], "unknown")
        self.assertEqual(result[1]["region"], "unknown")

    def test_non_list_input_returns_empty(self):
        self.assertEqual(normalize.normalize_people_opinions("not a list"), [])


class FrequentIdeasTests(unittest.TestCase):
    def test_unknown_type_falls_back_to_issue(self):
        result = normalize.normalize_frequent_ideas([{"idea": "battery life", "type": "bogus"}])
        self.assertEqual(result[0]["type"], "issue")

    def test_frequency_estimate_is_coerced_and_floored_at_one(self):
        result = normalize.normalize_frequent_ideas([{"idea": "range anxiety", "frequency_estimate": "not a number"}])
        self.assertEqual(result[0]["frequency_estimate"], 1)


if __name__ == "__main__":
    unittest.main()
