import unittest
from unittest.mock import patch

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

    def test_fingerprint_keeps_time_scope_separate(self):
        first = workspace._fingerprint("Oil", "Oil production increased in 2024")
        second = workspace._fingerprint("Oil", "Oil production decreased in 2025")
        self.assertNotEqual(first, second)

    def test_fingerprint_keeps_quantities_separate(self):
        first = workspace._fingerprint("Oil", "Oil production increased by 5 percent")
        second = workspace._fingerprint("Oil", "Oil production decreased by 15 percent")
        self.assertNotEqual(first, second)

    def test_lower_is_direction_not_grammatical_negation(self):
        self.assertEqual(workspace._direction("Production was lower in August"), "negative")

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

    def test_semantic_match_groups_paraphrases_across_topics(self):
        first = {"claim": "More than two million electric vehicles are registered on UK roads", "embedding": [1.0, 0.0]}
        second = {"claim": "The number of EVs on British roads passed two million", "embedding": [0.99, 0.01]}
        self.assertTrue(workspace._claims_match(first, second))

    def test_semantic_match_rejects_different_time_scopes(self):
        first = {"claim": "Electric car sales reached 20 percent in 2024", "embedding": [1.0, 0.0]}
        second = {"claim": "Electric car sales reached 20 percent in 2025", "embedding": [1.0, 0.0]}
        self.assertFalse(workspace._claims_match(first, second))

    def test_semantic_match_rejects_different_quantities(self):
        first = {"claim": "Electric car sales reached 20 percent", "embedding": [1.0, 0.0]}
        second = {"claim": "Electric car sales reached 35 percent", "embedding": [1.0, 0.0]}
        self.assertFalse(workspace._claims_match(first, second))

    def test_semantic_match_rejects_missing_quantitative_scope(self):
        quantified = {"claim": "Over 2 million electric vehicles are registered on UK roads", "embedding": [1.0, 0.0]}
        unquantified = {"claim": "Electric vehicles are registered on UK roads", "embedding": [1.0, 0.0]}
        self.assertFalse(workspace._claims_match(quantified, unquantified))

    def test_quantity_scope_reads_percentages_and_comma_numbers(self):
        _, percentages = workspace._normalized_scopes("Sales reached 3% and then 19 percent")
        _, registrations = workspace._normalized_scopes("There were 43,106 registrations")
        self.assertEqual(percentages, {"3%", "19%"})
        self.assertEqual(registrations, {"43106"})

    def test_quantity_scope_matches_number_words(self):
        self.assertTrue(workspace._scope_compatible(
            "More than 2 million electric vehicles are registered",
            "Electric vehicle registrations passed two million",
        ))

    def test_passage_qualification_rejects_conflicting_quantity(self):
        qualified, _, reason = workspace._passage_qualification(
            "Electric car sales increased by 45 percent in July 2025",
            "Electric car sales increased by 12 percent in July 2025.",
        )
        self.assertFalse(qualified)
        self.assertIn("incompatible", reason)

    def test_passage_qualification_allows_additional_context(self):
        qualified, _, _ = workspace._passage_qualification(
            "Over 2 million electric vehicles are registered on UK roads",
            "Sales rose 45% in July 2025, and more than two million electric vehicles were registered on UK roads.",
        )
        self.assertTrue(qualified)

    def test_group_claim_candidates_preserves_independent_rows(self):
        first = {
            "row": {"id": 1}, "topic": "Policy", "claim": "More than two million electric vehicles are registered on UK roads",
            "type": "factual_assertion", "direction": "neutral", "fingerprint": "one", "embedding": [1.0, 0.0],
        }
        second = {
            "row": {"id": 2}, "topic": "Climate", "claim": "The number of EVs on British roads passed two million",
            "type": "factual_assertion", "direction": "neutral", "fingerprint": "two", "embedding": [0.99, 0.01],
        }
        groups = workspace._group_claim_candidates([first, second])
        self.assertEqual(len(groups), 1)
        self.assertEqual([item["row"]["id"] for item in groups[0]["items"]], [1, 2])

    def test_arabic_claim_words_are_preserved(self):
        words = workspace._claim_words("ارتفع سعر صفيحة البنزين في لبنان")
        self.assertTrue({"ارتفع", "سعر", "صفيحة", "البنزين", "لبنان"}.issubset(words))

    def test_arabic_passage_can_qualify_exact_claim(self):
        qualified, score, _ = workspace._passage_qualification(
            "ارتفع سعر صفيحة البنزين ٥٠٠٠٠ ليرة لبنانية",
            "ارتفع صباح اليوم سعر صفيحة البنزين 50000 ليرة لبنانية بسبب تغير الأسعار العالمية.",
        )
        self.assertTrue(qualified)
        self.assertGreaterEqual(score, 0.35)

    def test_arabic_direction_and_claim_types(self):
        self.assertEqual(workspace._direction("انخفض سعر المازوت اليوم"), "negative")
        self.assertEqual(workspace._direction("ارتفع سعر البنزين اليوم"), "positive")
        self.assertEqual(workspace._claim_type("من المتوقع أن يرتفع السعر غداً"), "forecast")
        self.assertEqual(workspace._claim_type("ارتفع السعر بسبب زيادة النفط عالمياً"), "causal_explanation")

    def test_arabic_dates_and_digits_are_normalized(self):
        structured = workspace._structured_claim("المحروقات", "ارتفع السعر ٥٠٠٠٠ ليرة في ١٨ أيلول ٢٠٢٦")
        self.assertIn("18 أيلول 2026", structured["dates"])
        self.assertIn("50000", structured["quantities"])

    def test_claim_candidates_accept_common_object_shapes_and_json_strings(self):
        row = {
            "topics": ["المحروقات"],
            "key_points": '[{"claim":"ارتفع سعر البنزين خمسين ألف ليرة لبنانية"}]',
            "summary": "",
            "title": "",
        }
        self.assertEqual(
            workspace._claim_candidates(row),
            [("المحروقات", "ارتفع سعر البنزين خمسين ألف ليرة لبنانية")],
        )

    def test_generation_fails_clearly_without_frozen_snapshot(self):
        with patch.object(workspace, "_snapshot_rows", return_value=[]):
            with self.assertRaisesRegex(ValueError, "no frozen evidence snapshot"):
                workspace._generate_for_run("old-run", 3, 1)

    def test_interrupted_rebuild_does_not_deactivate_existing_claims(self):
        row = {
            "id": 7,
            "text": "Fuel prices increased today.",
            "source_provenance": {},
            "provenance_status": "unassessed",
        }
        candidate = {
            "row": row,
            "topic": "Fuel",
            "claim": "Fuel prices increased today",
            "type": "factual_assertion",
            "direction": "positive",
            "fingerprint": "fuel-price",
            "embedding": [1.0],
        }
        with patch.object(workspace, "_snapshot_rows", return_value=[row]), \
             patch.object(workspace, "_claim_candidates", return_value=[("Fuel", candidate["claim"])]), \
             patch.object(workspace, "get_embedding", return_value={"embedding_json": [1.0]}), \
             patch.object(workspace, "_group_claim_candidates", return_value=[{"canonical": candidate, "fingerprint": "fuel-price", "items": [candidate]}]), \
             patch.object(workspace, "_project_scope", return_value={"name": "Fuel monitor"}), \
             patch.object(workspace, "_classify_relevance", return_value={"fuel-price": {"relevance": "direct", "explanation": "Directly addresses fuel prices.", "score": 0.99, "status": "success"}}), \
             patch.object(workspace, "_grounded_model_assessment", side_effect=RuntimeError("interrupted")), \
             patch.object(workspace.db, "execute") as execute:
            with self.assertRaisesRegex(RuntimeError, "interrupted"):
                workspace._generate_for_run("run-1", 3, 2)

        self.assertFalse(any("active=false" in call.args[0] for call in execute.call_args_list))

    def test_relevance_response_requires_every_candidate(self):
        parsed = workspace._validate_relevance_result({"results": [
            {"id": "arabic", "relevance": "direct", "score": 0.92, "explanation": "يتعلق مباشرة بأزمة الوقود"},
            {"id": "sport", "relevance": "unrelated", "score": 0.98, "explanation": "Sports news"},
        ]}, {"arabic", "sport"})
        self.assertEqual(parsed["arabic"]["relevance"], "direct")
        self.assertEqual(parsed["sport"]["relevance"], "unrelated")
        self.assertIsNone(workspace._validate_relevance_result(
            {"results": [{"id": "arabic", "relevance": "direct"}]}, {"arabic", "sport"},
        ))

    def test_failed_relevance_provider_returns_uncertain_for_review(self):
        group = {"fingerprint": "claim-1", "canonical": {
            "claim": "ارتفع سعر البنزين في لبنان", "topic": "Fuel prices",
            "row": {"text": "ارتفع سعر البنزين في لبنان هذا الأسبوع.", "title": "أسعار المحروقات"},
        }}
        with patch.object(workspace, "chat_completion", side_effect=workspace.LLMError("down")):
            result = workspace._classify_relevance_batch({"name": "Lebanon Fuel Crisis Monitor"}, [group])
        self.assertEqual(result["claim-1"]["relevance"], "uncertain")
        self.assertEqual(result["claim-1"]["status"], "failed")

    def test_failed_relevance_does_not_replace_published_generation(self):
        row = {"id": 7, "text": "Fuel prices increased today.", "source_provenance": {}}
        candidate = {
            "row": row, "topic": "Fuel", "claim": "Fuel prices increased today",
            "type": "factual_assertion", "direction": "positive",
            "fingerprint": "fuel-price", "embedding": [1.0],
        }
        failed = {"fuel-price": {
            "relevance": "uncertain", "explanation": "Provider unavailable.",
            "score": 0.0, "status": "failed",
        }}
        with patch.object(workspace, "_snapshot_rows", return_value=[row]), \
             patch.object(workspace, "_claim_candidates", return_value=[("Fuel", candidate["claim"])]), \
             patch.object(workspace, "get_embedding", return_value={"embedding_json": [1.0]}), \
             patch.object(workspace, "_group_claim_candidates", return_value=[{
                 "canonical": candidate, "fingerprint": "fuel-price", "items": [candidate],
             }]), \
             patch.object(workspace, "_project_scope", return_value={"name": "Fuel monitor"}), \
             patch.object(workspace, "_classify_relevance", return_value=failed), \
             patch.object(workspace.db, "execute") as execute:
            with self.assertRaisesRegex(RuntimeError, "previously published evidence generation remains visible"):
                workspace._generate_for_run("run-1", 3, 2)

        self.assertFalse(any("active=false" in call.args[0] for call in execute.call_args_list))


if __name__ == "__main__":
    unittest.main()
