import os
import unittest

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from analysis import region_detection


class DetectRegionTests(unittest.TestCase):
    """detect_region() combines three independent signals (title+body text
    scan, quoted-opinion votes, entity/organization cross-check) and derives
    confidence from how many of them agree - not a model's self-reported
    number. See analysis/region_detection.py's module docstring."""

    def test_no_signals_returns_unknown_with_zero_confidence(self):
        result = region_detection.detect_region(title="", text="Nothing region-specific here.")
        self.assertEqual(result["region"], "unknown")
        self.assertEqual(result["region_confidence"], 0.0)
        self.assertTrue(result["region_low_confidence"])

    def test_all_signals_agreeing_gives_high_confidence(self):
        result = region_detection.detect_region(
            title="Report from Japan",
            text="Sales in Japan grew steadily this quarter, dealers said.",
            people_opinions=[{"opinion": "Great value", "region": "Japan"}],
            entities=["Japan"],
            organizations=[],
        )
        self.assertEqual(result["region"], "Japan")
        self.assertGreaterEqual(result["region_confidence"], 0.9)
        self.assertFalse(result["region_low_confidence"])

    def test_single_firing_signal_gives_medium_confidence(self):
        result = region_detection.detect_region(
            title="",
            text="The keynote happened in Germany today.",
            people_opinions=[],
            entities=[],
            organizations=[],
        )
        self.assertEqual(result["region"], "Germany")
        self.assertAlmostEqual(result["region_confidence"], 0.55)
        self.assertFalse(result["region_low_confidence"])

    def test_conflicting_signals_lower_confidence_on_the_winner(self):
        result = region_detection.detect_region(
            title="",
            text="A dealer in France commented on pricing.",
            people_opinions=[{"opinion": "Too expensive", "region": "Germany"}],
            entities=[],
            organizations=[],
        )
        # Opinion vote (weight 1.0) outweighs a single body-text mention
        # (weight 0.6), so Germany wins, but the two signals disagree.
        self.assertEqual(result["region"], "Germany")
        self.assertAlmostEqual(result["region_confidence"], 0.35)
        self.assertTrue(result["region_low_confidence"])

    def test_runs_with_no_extraction_data_using_text_scan_alone(self):
        """Must still produce a real answer when structured extraction
        failed outright (empty people_opinions/entities/organizations)."""
        result = region_detection.detect_region(
            title="Update from Brazil",
            text="",
            people_opinions=None,
            entities=None,
            organizations=None,
        )
        self.assertEqual(result["region"], "Brazil")
        self.assertGreater(result["region_confidence"], 0.0)

    def test_person_named_after_a_country_is_not_mistaken_for_a_region(self):
        """"Jordan"/"Chad"/"Georgia"/"Turkey"/"Niger" are also common personal
        names. When entity extraction already tagged the full multi-word
        name ("Jordan Peterson"), a bare word match on "Jordan" elsewhere -
        in the body text or in the same entity string - is someone's name,
        not a place, and must not be counted as a region signal."""
        result = region_detection.detect_region(
            title="Owner review: new SUV",
            text="Jordan said the ride quality impressed him but the infotainment lagged.",
            people_opinions=[{"opinion": "ride quality impressed him", "region": None}],
            entities=["Jordan Peterson"],
            organizations=[],
        )
        self.assertEqual(result["region"], "unknown")
        self.assertEqual(result["region_confidence"], 0.0)

    def test_standalone_country_entity_still_counts(self):
        """The name-collision guard only suppresses a word that's part of a
        longer extracted name - a country appearing as its own standalone
        entity (no collision risk) must still vote normally."""
        result = region_detection.detect_region(
            title="",
            text="",
            people_opinions=[],
            entities=["Turkey"],
            organizations=[],
        )
        self.assertEqual(result["region"], "Turkey")
        self.assertGreater(result["region_confidence"], 0.0)

    def test_abbreviation_with_trailing_periods_matches_as_a_standalone_word(self):
        """"U.S."/"U.K." (COUNTRY_ALIASES) end in a literal period - the most
        common way they appear in running news text is followed immediately
        by whitespace or another period, which must still count as a
        standalone match rather than being swallowed by a boundary check
        that never fires between two non-word characters."""
        result = region_detection.detect_region(
            title="",
            text="The U.S. economy grew again this quarter.",
            people_opinions=[],
            entities=[],
            organizations=[],
        )
        self.assertEqual(result["region"], "United States")
        self.assertGreater(result["region_confidence"], 0.0)

    def test_organization_named_after_a_country_does_not_suppress_a_real_mention(self):
        """"Bank of America"/"University of Georgia"-style organization names
        are the documented normal shape of `organizations` (see
        structured_extraction's prompt: "organizations, products, or models
        mentioned") - unlike a multi-word `entities` value, they must NOT be
        treated as a suppressed person-name fragment, or a genuine,
        unrelated mention of that same country elsewhere in the article
        would be silently dropped."""
        result = region_detection.detect_region(
            title="Quarterly earnings roundup",
            text="Sales in America grew steadily this quarter, according to dealers.",
            people_opinions=[],
            entities=[],
            organizations=["Bank of America"],
        )
        self.assertEqual(result["region"], "United States")
        self.assertGreaterEqual(result["region_confidence"], 0.9)


if __name__ == "__main__":
    unittest.main()
