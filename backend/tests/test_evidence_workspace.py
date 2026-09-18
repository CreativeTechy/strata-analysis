import unittest

from services.evidence import workspace


class EvidenceRuleTests(unittest.TestCase):
    def test_forecast_is_classified_separately(self):
        self.assertEqual(workspace._claim_type("Production will recover next quarter."), "forecast")

    def test_causal_claim_is_classified_separately(self):
        self.assertEqual(workspace._claim_type("Lower supply caused prices to rise."), "causal_explanation")

    def test_fingerprint_groups_positive_and_negative_forms(self):
        positive = workspace._fingerprint("Oil", "Oil production increased in August")
        negative = workspace._fingerprint("Oil", "Oil production decreased in August")
        self.assertEqual(positive, negative)

    def test_story_group_collapses_republished_hosts(self):
        first = {"story_id": 44, "url": "https://one.example/report"}
        second = {"story_id": 44, "url": "https://two.example/reprint"}
        self.assertEqual(workspace._origin(first), workspace._origin(second))

    def test_best_passage_is_exact_stored_text(self):
        row = {
            "title": "Market update",
            "summary": "",
            "text": "Inventories remained stable. Oil production increased by five percent in August.",
        }
        passage = workspace._best_passage(row, "Oil production increased in August")
        self.assertIn(passage, row["text"])
        self.assertIn("production increased", passage)

    def test_two_opposing_origins_can_contradict_single_source_claim(self):
        assessment, _ = workspace._assessment("factual_assertion", {"source"}, {"origin-a", "origin-b"})
        self.assertEqual(assessment, "contradicted")

    def test_rule_change_is_not_needed_to_explain_mixed_evidence(self):
        assessment, _ = workspace._assessment("factual_assertion", {"origin-a", "origin-b"}, {"origin-c"})
        self.assertEqual(assessment, "mixed_evidence")

    def test_declared_origin_group_collapses_copied_records(self):
        first = {"source_provenance": {"origin_group": "announcement-17"}, "url": "https://one.example"}
        second = {"source_provenance": {"origin_group": "announcement-17"}, "url": "https://two.example"}
        self.assertEqual(workspace._origin(first), workspace._origin(second))


if __name__ == "__main__":
    unittest.main()
