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


class NormalizeRegionAliasTests(unittest.TestCase):
    """normalize_region() canonicalizes common abbreviations/demonyms via
    services/competitors/countries.py's COUNTRY_ALIASES, not just exact
    country names/codes - see region_detection.py for the independent
    per-article stage that also relies on this."""

    def test_us_abbreviations_and_demonyms_canonicalize(self):
        for value in ("US", "USA", "U.S.", "U.S.A.", "America", "American", "us"):
            self.assertEqual(normalize.normalize_region(value), "United States")

    def test_uk_abbreviations_and_demonyms_canonicalize(self):
        for value in ("UK", "U.K.", "Britain", "British", "England", "english"):
            self.assertEqual(normalize.normalize_region(value), "United Kingdom")

    def test_other_demonyms_canonicalize(self):
        self.assertEqual(normalize.normalize_region("Emirati"), "United Arab Emirates")
        self.assertEqual(normalize.normalize_region("Saudi"), "Saudi Arabia")
        self.assertEqual(normalize.normalize_region("Japanese"), "Japan")

    def test_non_alias_free_text_passes_through_unchanged(self):
        self.assertEqual(normalize.normalize_region("Middle East"), "Middle East")
        self.assertEqual(normalize.normalize_region("Austin, Texas"), "Austin, Texas")

    def test_blank_stays_unknown(self):
        self.assertEqual(normalize.normalize_region(""), "unknown")
        self.assertEqual(normalize.normalize_region(None), "unknown")


class NormalizeGenderAliasTests(unittest.TestCase):
    """normalize_gender() accepts common synonyms/abbreviations/translations
    the extraction model sometimes emits instead of the exact "male"/"female"
    the prompt asks for (labels.GENDER_ALIASES), rather than losing that
    signal to "unknown"."""

    def test_exact_values_pass_through(self):
        for value in ("male", "female", "unknown"):
            self.assertEqual(normalize.normalize_gender(value), value)

    def test_english_synonyms_map_to_male_or_female(self):
        for value in ("M", "man", "He", "his", "Mr.", "boy"):
            self.assertEqual(normalize.normalize_gender(value), "male")
        for value in ("F", "woman", "She", "her", "Ms.", "girl"):
            self.assertEqual(normalize.normalize_gender(value), "female")

    def test_arabic_tokens_map_to_male_or_female(self):
        self.assertEqual(normalize.normalize_gender("رجل"), "male")
        self.assertEqual(normalize.normalize_gender("امرأة"), "female")

    def test_unrecognized_value_falls_back_to_unknown(self):
        self.assertEqual(normalize.normalize_gender("nonbinary"), "unknown")
        self.assertEqual(normalize.normalize_gender(""), "unknown")
        self.assertEqual(normalize.normalize_gender(None), "unknown")


class NormalizeGenderEvidenceTests(unittest.TestCase):
    def test_evidence_kept_when_gender_resolved(self):
        self.assertEqual(
            normalize.normalize_gender_evidence('she said', 'female'), 'she said'
        )

    def test_evidence_dropped_when_gender_is_unknown(self):
        self.assertEqual(normalize.normalize_gender_evidence("she said", "unknown"), "")

    def test_evidence_is_capped_in_length(self):
        long_text = "x" * 500
        result = normalize.normalize_gender_evidence(long_text, "male")
        self.assertEqual(len(result), normalize._GENDER_EVIDENCE_MAX_LEN)


class NormalizeAgeRangeAliasTests(unittest.TestCase):
    """normalize_age_range() accepts common alternate phrasings the model
    sometimes emits instead of the exact bucket tokens the prompt asks for
    (labels.AGE_RANGE_ALIASES) - in particular the natural way to write the
    two irregularly-formatted buckets, which the bare space-stripping the
    function used to do on its own could never match."""

    def test_exact_values_pass_through(self):
        for value in ("under_18", "18-24", "25-34", "35-44", "45-54", "55-64", "65_plus", "unknown"):
            self.assertEqual(normalize.normalize_age_range(value), value)

    def test_natural_phrasing_of_the_irregular_buckets_is_accepted(self):
        for value in ("65+", "65 plus", "Over 65", "senior", "elderly"):
            self.assertEqual(normalize.normalize_age_range(value), "65_plus")
        for value in ("Under 18", "under-18", "minor", "kid"):
            self.assertEqual(normalize.normalize_age_range(value), "under_18")

    def test_to_worded_ranges_canonicalize(self):
        self.assertEqual(normalize.normalize_age_range("25 to 34"), "25-34")

    def test_bare_decade_words_stay_unknown(self):
        """"30s" straddles both 25-34 and 35-44 with no correct single
        bucket, so guessing one would be worse than "unknown"."""
        self.assertEqual(normalize.normalize_age_range("30s"), "unknown")
        self.assertEqual(normalize.normalize_age_range("thirties"), "unknown")

    def test_teen_words_stay_unknown(self):
        """"teenager" spans roughly 13-19, straddling under_18 and 18-24
        exactly the way "30s" straddles 25-34 and 35-44 - same rule, so it
        must not be guessed into under_18 either."""
        for value in ("teen", "teens", "teenager"):
            self.assertEqual(normalize.normalize_age_range(value), "unknown")

    def test_unrecognized_or_blank_falls_back_to_unknown(self):
        self.assertEqual(normalize.normalize_age_range(""), "unknown")
        self.assertEqual(normalize.normalize_age_range(None), "unknown")


class BucketAgeYearsTests(unittest.TestCase):
    def test_buckets_land_on_the_right_range(self):
        self.assertEqual(normalize.bucket_age_years(10), "under_18")
        self.assertEqual(normalize.bucket_age_years(21), "18-24")
        self.assertEqual(normalize.bucket_age_years(30), "25-34")
        self.assertEqual(normalize.bucket_age_years(42), "35-44")
        self.assertEqual(normalize.bucket_age_years(50), "45-54")
        self.assertEqual(normalize.bucket_age_years(60), "55-64")
        self.assertEqual(normalize.bucket_age_years(70), "65_plus")

    def test_boundary_ages(self):
        self.assertEqual(normalize.bucket_age_years(17), "under_18")
        self.assertEqual(normalize.bucket_age_years(18), "18-24")
        self.assertEqual(normalize.bucket_age_years(65), "65_plus")

    def test_implausible_or_non_numeric_returns_empty(self):
        for value in (-1, 121, "not a number", None, "", float("inf")):
            self.assertEqual(normalize.bucket_age_years(value), "")

    def test_sentinel_zero_is_not_read_as_a_stated_age(self):
        """A model emitting "0" as a placeholder for "no age given" (instead
        of the "" the prompt asks for) must not be bucketed as under_18 -
        that would silently override a correct age_range/age_evidence the
        model separately supplied (see normalize_people_opinions)."""
        for value in (0, "0", 1, 4):
            self.assertEqual(normalize.bucket_age_years(value), "")


class NormalizeAgeEvidenceTests(unittest.TestCase):
    def test_evidence_kept_when_age_range_resolved(self):
        self.assertEqual(normalize.normalize_age_evidence("42", "35-44"), "42")

    def test_evidence_dropped_when_age_range_is_unknown(self):
        self.assertEqual(normalize.normalize_age_evidence("42", "unknown"), "")

    def test_evidence_is_capped_in_length(self):
        long_text = "x" * 500
        result = normalize.normalize_age_evidence(long_text, "25-34")
        self.assertEqual(len(result), normalize._AGE_EVIDENCE_MAX_LEN)


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
            "gender": "unknown", "gender_evidence": "", "age_range": "unknown",
            "age_evidence": "", "region": "unknown", "segment": "unknown",
        }])

    def test_demographics_are_normalized_and_default_to_unknown(self):
        result = normalize.normalize_people_opinions([
            {"opinion": "Loves the range", "sentiment": "positive", "category": "performance",
             "gender": "Female", "gender_evidence": "she said", "age_range": "25-34",
             "age_evidence": "in her thirties", "region": "lebanon"},
            {"opinion": "Slow charging", "sentiment": "negative", "category": "charging"},
        ])
        self.assertEqual(result[0]["gender"], "female")
        self.assertEqual(result[0]["gender_evidence"], "she said")
        self.assertEqual(result[0]["age_range"], "25-34")
        self.assertEqual(result[0]["age_evidence"], "in her thirties")
        self.assertEqual(result[0]["region"], "Lebanon")
        self.assertEqual(result[1]["gender"], "unknown")
        self.assertEqual(result[1]["gender_evidence"], "")
        self.assertEqual(result[1]["age_range"], "unknown")
        self.assertEqual(result[1]["age_evidence"], "")
        self.assertEqual(result[1]["region"], "unknown")

    def test_gender_evidence_is_dropped_when_gender_does_not_normalize(self):
        """A model that quotes evidence but gives an unrecognized gender word
        shouldn't leave the evidence sitting on a row that claims no signal."""
        result = normalize.normalize_people_opinions([
            {"opinion": "Loves the range", "gender": "nonbinary", "gender_evidence": "they said"},
        ])
        self.assertEqual(result[0]["gender"], "unknown")
        self.assertEqual(result[0]["gender_evidence"], "")

    def test_age_years_overrides_the_models_own_bucket_choice(self):
        """A raw stated age is trusted over the model's own bucket pick -
        see normalize.bucket_age_years."""
        result = normalize.normalize_people_opinions([
            {"opinion": "Loves the range", "age_years": 42, "age_range": "25-34"},
        ])
        self.assertEqual(result[0]["age_range"], "35-44")
        self.assertEqual(result[0]["age_evidence"], "42")

    def test_implausible_age_years_falls_back_to_the_models_bucket(self):
        result = normalize.normalize_people_opinions([
            {"opinion": "Loves the range", "age_years": 999, "age_range": "25-34",
             "age_evidence": "in her late twenties"},
        ])
        self.assertEqual(result[0]["age_range"], "25-34")
        self.assertEqual(result[0]["age_evidence"], "in her late twenties")

    def test_sentinel_zero_age_years_falls_back_to_the_models_bucket(self):
        """A placeholder age_years of 0 must not override a correct
        model-given age_range/age_evidence with under_18 - see
        normalize.bucket_age_years."""
        result = normalize.normalize_people_opinions([
            {"opinion": "Prices are too high", "age_years": 0, "age_range": "65_plus",
             "age_evidence": "retiree"},
        ])
        self.assertEqual(result[0]["age_range"], "65_plus")
        self.assertEqual(result[0]["age_evidence"], "retiree")

    def test_age_evidence_is_dropped_when_age_range_does_not_normalize(self):
        result = normalize.normalize_people_opinions([
            {"opinion": "Loves the range", "age_range": "30s", "age_evidence": "in her 30s"},
        ])
        self.assertEqual(result[0]["age_range"], "unknown")
        self.assertEqual(result[0]["age_evidence"], "")

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
