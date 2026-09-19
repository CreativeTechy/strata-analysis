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


if __name__ == "__main__":
    unittest.main()
