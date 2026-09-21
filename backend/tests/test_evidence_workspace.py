import json
import unittest
from pathlib import Path
from unittest.mock import patch

from services.evidence import workspace


class EvidenceRuleTests(unittest.TestCase):
    def test_blocked_and_arabic_unavailable_pages_are_excluded(self):
        english = workspace._content_quality({"text": "Access denied. Sign in to continue. Verification code required."})
        arabic = workspace._content_quality({"text": "المحتوى غير متاح. سجّل الدخول وأدخل رمز التحقق للمتابعة."})
        self.assertFalse(english["usable"])
        self.assertFalse(arabic["usable"])
        self.assertEqual(english["code"], "blocked_or_unavailable")
        self.assertEqual(arabic["code"], "blocked_or_unavailable")

    def test_incidental_cookie_notice_does_not_hide_substantive_article(self):
        text = (
            "Cookie policy. We use cookies to improve this site.\n"
            "The energy ministry raised gasoline prices by 40000 pounds on Monday after global oil costs increased. "
            "The new official schedule also lowered the price of household gas and took effect immediately."
        )
        result = workspace._content_quality({"text": text})
        self.assertTrue(result["usable"])

    def test_meta_claim_is_rejected_even_when_it_mentions_the_topic(self):
        row = {"text": "Fuel prices increased by 40000 pounds on Monday after the ministry issued its schedule."}
        result = workspace._evaluate_claim_candidate(
            row, "Fuel", "The article discusses fuel prices but the content is unavailable due to a login error.",
        )
        self.assertEqual(result["status"], "rejected")

    def test_claim_candidates_do_not_fallback_to_summary_or_title(self):
        row = {"topics": ["Fuel"], "key_points": [], "summary": "The article discusses fuel prices.",
               "title": "Fuel update"}
        self.assertEqual(workspace._claim_candidates(row), [])

    def test_exact_duplicate_content_is_one_independent_origin(self):
        body = "The ministry increased fuel prices by 40000 pounds after international oil prices rose."
        first = {"text": body, "url": "https://one.example/a"}
        second = {"text": body, "url": "https://two.example/b"}
        key = workspace._content_key(first)
        first["_content_cluster"] = key
        first["_content_duplicate"] = True
        second["_content_cluster"] = workspace._content_key(second)
        second["_content_duplicate"] = True
        self.assertEqual(workspace._origin(first), workspace._origin(second))

    def test_passage_cache_config_changes_with_thresholds(self):
        with patch.object(workspace.config, "EVIDENCE_PASSAGE_DIRECT_THRESHOLD", 0.72):
            first = workspace._passage_decision_config()
        with patch.object(workspace.config, "EVIDENCE_PASSAGE_DIRECT_THRESHOLD", 0.80):
            second = workspace._passage_decision_config()
        self.assertNotEqual(first, second)

    def test_shared_geography_alone_is_not_contextual_evidence(self):
        with patch.object(workspace.config, "EVIDENCE_PASSAGE_DIRECT_THRESHOLD", 0.8), \
             patch.object(workspace.config, "EVIDENCE_PASSAGE_CONTEXTUAL_THRESHOLD", 0.6):
            relevance, reason = workspace._passage_relevance_label(
                0.7, "A football club in Lebanon announced its squad today.",
                {"lebanon", "fuel", "crisis", "price"}, {"lebanon"},
            )
        self.assertEqual(relevance, "unrelated")
        self.assertIn("geography", reason)

    def test_concrete_scope_connection_can_be_contextual(self):
        with patch.object(workspace.config, "EVIDENCE_PASSAGE_DIRECT_THRESHOLD", 0.8), \
             patch.object(workspace.config, "EVIDENCE_PASSAGE_CONTEXTUAL_THRESHOLD", 0.6):
            relevance, _ = workspace._passage_relevance_label(
                0.7, "Transport costs rose after fuel prices increased.",
                {"fuel", "price", "transport", "cost"}, set(),
            )
        self.assertEqual(relevance, "contextual")

    def test_reviewed_content_quality_fixture(self):
        fixture = Path(__file__).parent / "fixtures" / "evidence_quality_evaluation.json"
        examples = json.loads(fixture.read_text(encoding="utf-8"))
        correct = 0
        for example in examples:
            predicted = "usable" if workspace._content_quality({"text": example["text"]})["usable"] else "unusable"
            correct += predicted == example["label"]
        self.assertEqual(correct, len(examples))

    def test_generation_selection_defaults_to_published_not_newest_failed_attempt(self):
        generations = [
            {"generation": 4, "status": "failed", "published_at": None},
            {"generation": 3, "status": "success", "published_at": "2026-09-21"},
        ]
        self.assertEqual(workspace._select_generation(generations, None, 3, False), 3)

    def test_generation_selection_allows_opening_failed_attempt(self):
        generations = [
            {"generation": 4, "status": "failed", "published_at": None},
            {"generation": 3, "status": "success", "published_at": "2026-09-21"},
        ]
        self.assertEqual(workspace._select_generation(generations, 4, 3, False), 4)

    def test_generation_selection_supports_legacy_evidence(self):
        self.assertEqual(workspace._select_generation([], None, 0, True), 0)

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


class EvidenceSnapshotTests(unittest.TestCase):
    def test_snapshot_is_limited_to_screened_article_ids(self):
        with patch.object(workspace.db, "execute", return_value=None) as execute, \
             patch.object(workspace.db, "fetch_one", return_value={"count": 2}):
            count = workspace.capture_run_snapshot("run-1", 7, article_ids=[11, 12])

        insert_query, insert_params = execute.call_args_list[0].args
        self.assertIn("a.id = any", insert_query)
        self.assertEqual(insert_params, ("run-1", 7, 7, [11, 12]))
        self.assertEqual(count, 2)

    def test_empty_admitted_corpus_captures_no_source_rows(self):
        with patch.object(workspace.db, "execute", return_value=None) as execute, \
             patch.object(workspace.db, "fetch_one", return_value={"count": 0}):
            workspace.capture_run_snapshot("run-2", 7, article_ids=[])

        insert_query, insert_params = execute.call_args_list[0].args
        self.assertIn("and false", insert_query)
        self.assertEqual(insert_params, ("run-2", 7, 7))

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
            "passage": "Fuel prices increased today.",
        }
        with patch.object(workspace, "_snapshot_rows", return_value=[row]), \
             patch.object(workspace, "_screen_articles", return_value=([row], {"source_articles": 1, "usable_articles": 1, "included_articles": 1, "excluded_articles": 0, "pending_articles": 0, "duplicate_articles": 0, "decision_config": {}})), \
             patch.object(workspace, "_claim_candidates", return_value=[("Fuel", candidate["claim"])]), \
             patch.object(workspace, "_evaluate_claim_candidate", return_value={"fingerprint": "fuel-price", "status": "accepted", "passage": candidate["claim"], "reason": "grounded"}), \
             patch.object(workspace, "get_embeddings", return_value=[{"embedding_json": [1.0]}]), \
             patch.object(workspace, "_group_claim_candidates", return_value=[{"canonical": candidate, "fingerprint": "fuel-price", "items": [candidate]}]), \
             patch.object(workspace, "_project_scope", return_value={"name": "Fuel monitor"}), \
             patch.object(workspace, "_classify_relevance", return_value={"fuel-price": {"relevance": "direct", "explanation": "Directly addresses fuel prices.", "score": 0.99, "status": "success"}}), \
             patch.object(workspace, "_grounded_model_assessment", side_effect=RuntimeError("interrupted")), \
             patch.object(workspace.db, "transaction"), \
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

    def test_embedding_relevance_mode_classifies_without_llm(self):
        groups = [
            {"fingerprint": "direct", "canonical": {"embedding": [1.0, 0.0]}},
            {"fingerprint": "context", "canonical": {"embedding": [0.75, 0.66]}},
            {"fingerprint": "other", "canonical": {"embedding": [0.0, 1.0]}},
        ]
        with patch.object(workspace.config, "EVIDENCE_RELEVANCE_MODE", "embedding"), \
             patch.object(workspace.config, "EVIDENCE_RELEVANCE_DIRECT_THRESHOLD", 0.9), \
             patch.object(workspace.config, "EVIDENCE_RELEVANCE_CONTEXTUAL_THRESHOLD", 0.7), \
             patch.object(workspace, "get_embedding", return_value={"embedding_json": [1.0, 0.0]}), \
             patch.object(workspace, "chat_completion") as chat:
            result = workspace._classify_relevance({"name": "Fuel"}, groups)

        self.assertEqual(result["direct"]["relevance"], "direct")
        self.assertEqual(result["context"]["relevance"], "contextual")
        self.assertEqual(result["other"]["relevance"], "unrelated")
        chat.assert_not_called()

    def test_failed_relevance_batch_is_split_to_isolate_transient_failure(self):
        groups = [{"fingerprint": key} for key in ("one", "two")]
        failed = {
            key: {"relevance": "uncertain", "explanation": "failed", "score": 0, "status": "failed"}
            for key in ("one", "two")
        }
        successful = lambda key: {
            key: {"relevance": "direct", "explanation": "matches", "score": 1, "status": "success"}
        }
        with patch.object(
            workspace, "_classify_relevance_batch",
            side_effect=[failed, successful("one"), successful("two")],
        ) as classify:
            result = workspace._classify_relevance_resilient({"name": "Fuel"}, groups)
        self.assertEqual({key: value["status"] for key, value in result.items()}, {
            "one": "success", "two": "success",
        })
        self.assertEqual(classify.call_count, 3)

    def test_failed_relevance_does_not_replace_published_generation(self):
        row = {"id": 7, "text": "Fuel prices increased today.", "source_provenance": {}}
        candidate = {
            "row": row, "topic": "Fuel", "claim": "Fuel prices increased today",
            "type": "factual_assertion", "direction": "positive",
            "fingerprint": "fuel-price", "embedding": [1.0], "passage": "Fuel prices increased today.",
        }
        failed = {"fuel-price": {
            "relevance": "uncertain", "explanation": "Provider unavailable.",
            "score": 0.0, "status": "failed",
        }}
        with patch.object(workspace, "_snapshot_rows", return_value=[row]), \
             patch.object(workspace, "_screen_articles", return_value=([row], {"source_articles": 1, "usable_articles": 1, "included_articles": 1, "excluded_articles": 0, "pending_articles": 0, "duplicate_articles": 0, "decision_config": {}})), \
             patch.object(workspace, "_claim_candidates", return_value=[("Fuel", candidate["claim"])]), \
             patch.object(workspace, "_evaluate_claim_candidate", return_value={"fingerprint": "fuel-price", "status": "accepted", "passage": candidate["claim"], "reason": "grounded"}), \
             patch.object(workspace, "get_embeddings", return_value=[{"embedding_json": [1.0]}]), \
             patch.object(workspace, "_group_claim_candidates", return_value=[{
                 "canonical": candidate, "fingerprint": "fuel-price", "items": [candidate],
             }]), \
             patch.object(workspace, "_project_scope", return_value={"name": "Fuel monitor"}), \
             patch.object(workspace, "_classify_relevance", return_value=failed), \
             patch.object(workspace.db, "transaction"), \
             patch.object(workspace.db, "execute") as execute:
            with self.assertRaisesRegex(RuntimeError, "previously published evidence generation remains visible"):
                workspace._generate_for_run("run-1", 3, 2)

        self.assertFalse(any("active=false" in call.args[0] for call in execute.call_args_list))


if __name__ == "__main__":
    unittest.main()
