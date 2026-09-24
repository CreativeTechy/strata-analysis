import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from llm_client import LLMConnectionError
from services.articles import idea_comparisons


class SourceLabelTests(unittest.TestCase):
    def test_prefers_source_url_host(self):
        row = {"source_url": "https://www.eia.gov/petroleum/report", "url": "https://twitter.com/x/1", "source": "file.pdf"}
        self.assertEqual(idea_comparisons._source_label(row), "eia.gov")

    def test_falls_back_to_url_host_without_www(self):
        row = {"source_url": "", "url": "https://twitter.com/someuser/status/1", "source": ""}
        self.assertEqual(idea_comparisons._source_label(row), "twitter.com")

    def test_falls_back_to_document_filename(self):
        row = {"source_url": "", "url": "", "source": "quarterly-report.pdf"}
        self.assertEqual(idea_comparisons._source_label(row), "quarterly-report.pdf")

    def test_unknown_when_nothing_present(self):
        self.assertEqual(idea_comparisons._source_label({}), "Unknown source")


class GroupAndQualifyClustersTests(unittest.TestCase):
    def _rows(self):
        return [
            {
                "idea_cluster_id": 1, "idea": "petrol price", "type": "issue", "frequency_estimate": 3,
                "article_id": 10, "title": "EIA report", "url": "", "source": "", "source_url": "https://www.eia.gov/a",
                "published": None, "summary": "Fuel costs.", "value": "$98/barrel",
            },
            {
                "idea_cluster_id": 1, "idea": "petrol price", "type": "issue", "frequency_estimate": 3,
                "article_id": 11, "title": "Tweet", "url": "https://twitter.com/x/1", "source": "", "source_url": "",
                "published": None, "summary": "People are angry.", "value": "$120/barrel",
            },
            {
                # Same source repeating its own idea - must not count as a second distinct source.
                "idea_cluster_id": 2, "idea": "single source idea", "type": "praise", "frequency_estimate": 2,
                "article_id": 12, "title": "A", "url": "", "source": "", "source_url": "https://www.eia.gov/a",
                "published": None, "summary": "", "value": "",
            },
            {
                "idea_cluster_id": 2, "idea": "single source idea", "type": "praise", "frequency_estimate": 2,
                "article_id": 13, "title": "B", "url": "", "source": "", "source_url": "https://www.eia.gov/b",
                "published": None, "summary": "", "value": "",
            },
        ]

    def test_diverging_values_across_distinct_sources_are_flagged(self):
        clusters = idea_comparisons._group_clusters(self._rows())
        qualifying = idea_comparisons._qualifying_clusters(clusters, limit=10)
        self.assertEqual(len(qualifying), 1)
        self.assertEqual(qualifying[0]["idea_cluster_id"], 1)
        self.assertTrue(qualifying[0]["diverges"])

    def test_single_distinct_source_is_excluded_even_with_two_articles(self):
        clusters = idea_comparisons._group_clusters(self._rows())
        qualifying = idea_comparisons._qualifying_clusters(clusters, limit=10)
        self.assertNotIn(2, [c["idea_cluster_id"] for c in qualifying])


class GenerateIdeaComparisonsTests(unittest.TestCase):
    def setUp(self):
        self.facts = patch("services.articles.idea_comparisons.list_comparison_facts", return_value=[])
        self.revision = patch("services.articles.idea_comparisons._current_facts_revision", return_value=0)
        self.facts.start()
        self.revision.start()

    def tearDown(self):
        self.facts.stop()
        self.revision.stop()

    def test_writes_one_row_per_qualifying_cluster_and_uses_synthesized_summary(self):
        rows = GroupAndQualifyClustersTests()._rows()[:2]
        with patch("services.articles.idea_comparisons.config.DATABASE_URL", "postgres://x"), \
             patch("services.articles.idea_comparisons._cluster_candidates", return_value=rows), \
             patch("services.articles.idea_comparisons.chat_completion", return_value='{"summary": "eia.gov says $98, Twitter says $120."}'), \
             patch("services.articles.idea_comparisons.db.execute") as mock_execute:
            written = idea_comparisons.generate_idea_comparisons(project_id=1)
        self.assertEqual(written, 1)
        mock_execute.assert_called_once()
        sql, params = mock_execute.call_args[0]
        self.assertIn("insert into idea_comparisons", sql)
        self.assertEqual(params[2], "")  # run_id: '' for the project-wide (unscoped) view
        self.assertEqual(params[3], "petrol price")
        self.assertTrue(params[5])  # diverges
        self.assertEqual(params[7], "eia.gov says $98, Twitter says $120.")

    def test_model_relationship_updates_the_comparison_status(self):
        rows = GroupAndQualifyClustersTests()._rows()[:2]
        with patch("services.articles.idea_comparisons.config.DATABASE_URL", "postgres://x"), \
             patch("services.articles.idea_comparisons._cluster_candidates", return_value=rows), \
             patch("services.articles.idea_comparisons.chat_completion", return_value='{"summary": "The evidence is compatible.", "diverges": false}'), \
             patch("services.articles.idea_comparisons.db.execute") as mock_execute:
            idea_comparisons.generate_idea_comparisons(project_id=1)
        params = mock_execute.call_args[0][1]
        self.assertFalse(params[5])

    def test_unparsable_llm_response_still_saves_the_card_without_a_summary(self):
        rows = GroupAndQualifyClustersTests()._rows()[:2]
        with patch("services.articles.idea_comparisons.config.DATABASE_URL", "postgres://x"), \
             patch("services.articles.idea_comparisons._cluster_candidates", return_value=rows), \
             patch("services.articles.idea_comparisons.chat_completion", return_value="not json"), \
             patch("services.articles.idea_comparisons.db.execute") as mock_execute:
            written = idea_comparisons.generate_idea_comparisons(project_id=1)
        self.assertEqual(written, 1)
        params = mock_execute.call_args[0][1]
        self.assertIsNone(params[7])

    def test_run_scoped_generation_passes_run_id_through_and_tags_rows(self):
        rows = GroupAndQualifyClustersTests()._rows()[:2]
        with patch("services.articles.idea_comparisons.config.DATABASE_URL", "postgres://x"), \
             patch("services.articles.idea_comparisons._cluster_candidates", return_value=rows) as mock_candidates, \
             patch("services.articles.idea_comparisons.chat_completion", return_value='{"summary": "x"}'), \
             patch("services.articles.idea_comparisons.db.execute") as mock_execute:
            idea_comparisons.generate_idea_comparisons(project_id=1, run_id="run-123")
        mock_candidates.assert_called_once_with(1, idea_comparisons.config.IDEA_COMPARISON_MAX_CLUSTERS, run_id="run-123")
        # First call is the comparison row insert; a run-scoped generation also
        # marks the run as attempted afterward (see the attempt-marker tests
        # below), so the insert can't be asserted via the (now second) last call.
        insert_sql, insert_params = mock_execute.call_args_list[0][0]
        self.assertIn("insert into idea_comparisons", insert_sql)
        self.assertEqual(insert_params[2], "run-123")

    def test_run_scoped_generation_marks_the_run_as_attempted(self):
        """The attempt marker is what stops get_project_idea_comparisons_view
        from regenerating (and, during an outage, re-failing) on every single
        view of a run whose articles genuinely have nothing to show - see
        has_run_generation_attempt."""
        with patch("services.articles.idea_comparisons.config.DATABASE_URL", "postgres://x"), \
             patch("services.articles.idea_comparisons._cluster_candidates", return_value=[]), \
             patch("services.articles.idea_comparisons.db.execute") as mock_execute:
            written = idea_comparisons.generate_idea_comparisons(project_id=1, run_id="run-123")
        self.assertEqual(written, 0)
        mock_execute.assert_called_once()
        sql, params = mock_execute.call_args[0]
        self.assertIn("insert into idea_comparisons_generation_attempts", sql)
        self.assertEqual(params, (1, "run-123"))

    def test_project_wide_generation_does_not_write_an_attempt_marker(self):
        with patch("services.articles.idea_comparisons.config.DATABASE_URL", "postgres://x"), \
             patch("services.articles.idea_comparisons._cluster_candidates", return_value=[]), \
             patch("services.articles.idea_comparisons.db.execute") as mock_execute:
            idea_comparisons.generate_idea_comparisons(project_id=1)
        mock_execute.assert_not_called()

    def test_a_provider_failure_partway_through_leaves_the_run_unmarked(self):
        """An LLMError propagates out of generate_idea_comparisons before the
        marker is written, so a transient outage is retried on the next view
        instead of being cached as "nothing to show"."""
        rows = GroupAndQualifyClustersTests()._rows()[:2]
        with patch("services.articles.idea_comparisons.config.DATABASE_URL", "postgres://x"), \
             patch("services.articles.idea_comparisons._cluster_candidates", return_value=rows), \
             patch("services.articles.idea_comparisons.chat_completion", side_effect=LLMConnectionError("down")), \
             patch("services.articles.idea_comparisons.db.execute") as mock_execute:
            with self.assertRaises(LLMConnectionError):
                idea_comparisons.generate_idea_comparisons(project_id=1, run_id="run-123")
        for sql, _params in (call[0] for call in mock_execute.call_args_list):
            self.assertNotIn("idea_comparisons_generation_attempts", sql)

    def test_noop_without_database(self):
        with patch("services.articles.idea_comparisons.config.DATABASE_URL", ""), \
             patch("services.articles.idea_comparisons.db.execute") as mock_execute:
            written = idea_comparisons.generate_idea_comparisons(project_id=1)
        self.assertEqual(written, 0)
        mock_execute.assert_not_called()


class HasRunGenerationAttemptTests(unittest.TestCase):
    def test_false_without_a_run_id(self):
        with patch("services.articles.idea_comparisons.config.DATABASE_URL", "postgres://x"), \
             patch("services.articles.idea_comparisons.db.fetch_one") as mock_fetch_one:
            self.assertFalse(idea_comparisons.has_run_generation_attempt(1, None))
        mock_fetch_one.assert_not_called()

    def test_false_without_a_database(self):
        with patch("services.articles.idea_comparisons.config.DATABASE_URL", ""), \
             patch("services.articles.idea_comparisons.db.fetch_one") as mock_fetch_one:
            self.assertFalse(idea_comparisons.has_run_generation_attempt(1, "run-123"))
        mock_fetch_one.assert_not_called()

    def test_true_when_a_marker_row_exists(self):
        with patch("services.articles.idea_comparisons.config.DATABASE_URL", "postgres://x"), \
             patch("services.articles.idea_comparisons.db.fetch_one", return_value={"?column?": 1}):
            self.assertTrue(idea_comparisons.has_run_generation_attempt(1, "run-123"))

    def test_false_when_no_marker_row_exists(self):
        with patch("services.articles.idea_comparisons.config.DATABASE_URL", "postgres://x"), \
             patch("services.articles.idea_comparisons.db.fetch_one", return_value=None):
            self.assertFalse(idea_comparisons.has_run_generation_attempt(1, "run-123"))


class ComparisonFactsTests(unittest.TestCase):
    def test_fact_becomes_explicit_user_provided_evidence(self):
        source = idea_comparisons._fact_as_source({
            "fact_text": "Audited sales grew by 12%.",
            "reference_label": "Finance review",
            "stated_value": "12%",
            "observed_at": "2026-08-31",
        })
        self.assertEqual(source["source_label"], "Finance review [user-provided]")
        self.assertEqual(source["value"], "12%")
        self.assertIn("2026-08-31", source["title"])

    def test_fact_requires_text_and_valid_reference_url(self):
        with self.assertRaisesRegex(ValueError, "Fact text"):
            idea_comparisons._validate_fact({})
        with self.assertRaisesRegex(ValueError, "Reference URL"):
            idea_comparisons._validate_fact({"fact_text": "x", "reference_url": "javascript:alert(1)"})

    def test_fact_date_must_be_iso_date(self):
        with self.assertRaisesRegex(ValueError, "YYYY-MM-DD"):
            idea_comparisons._validate_fact({"fact_text": "x", "observed_at": "tomorrow"})

    def test_structured_observation_is_validated(self):
        clean = idea_comparisons._validate_fact({
            "fact_text": "Production is forecast to rise.",
            "observations": [{
                "metric": "Oil production", "numeric_value": "1.10", "unit": "million bpd",
                "period_label": "2026 Q4", "value_kind": "forecast",
            }],
        })
        self.assertEqual(clean["observations"][0]["numeric_value"], idea_comparisons.Decimal("1.10"))
        self.assertEqual(clean["observations"][0]["value_kind"], "forecast")

    def test_structured_observation_rejects_non_numeric_value(self):
        with self.assertRaisesRegex(ValueError, "valid number"):
            idea_comparisons._validate_fact({
                "fact_text": "Production changed.",
                "observations": [{"metric": "Production", "numeric_value": "many", "unit": "bpd"}],
            })

    def test_structured_observation_rejects_values_outside_json_number_range(self):
        with self.assertRaisesRegex(ValueError, "supported range"):
            idea_comparisons._validate_fact({
                "fact_text": "Production changed.",
                "observations": [{"metric": "Production", "numeric_value": "1e400", "unit": "bpd"}],
            })

    def test_fact_creation_uses_one_transaction_for_all_writes(self):
        cursor = MagicMock()
        cursor.fetchone.side_effect = [{"id": 3}, {"id": 7}, {"revision": 1}]
        transaction = MagicMock()
        transaction.__enter__.return_value = cursor
        fact = {"id": 7, "fact_text": "Production changed."}
        with patch("services.articles.idea_comparisons.db.transaction", return_value=transaction), \
             patch("services.articles.idea_comparisons.list_comparison_facts", return_value=[fact]):
            result = idea_comparisons.create_comparison_fact(
                1, 3,
                {
                    "fact_text": "Production changed.",
                    "observations": [{"metric": "Production", "numeric_value": "12", "unit": "%"}],
                },
                {"id": 5, "username": "analyst"},
            )
        self.assertEqual(result, fact)
        self.assertEqual(cursor.execute.call_count, 5)
        transaction.__exit__.assert_called_once_with(None, None, None)


class NumericEvidenceTests(unittest.TestCase):
    def test_currency_units_group_with_or_without_spacing(self):
        evidence = idea_comparisons._numeric_evidence("Annual saving", [
            {"source_label": "A", "value": "£120 annual saving"},
        ], [{
            "id": 9, "reference_label": "User estimate", "observed_at": None,
            "observations": [{
                "id": 3, "metric": "Annual saving", "numeric_value": 140,
                "unit": "£ annual saving", "period_label": None, "value_kind": "estimate",
                "display_value": "£140 annual saving",
            }],
        }])
        self.assertEqual(len(evidence["groups"]), 1)
        self.assertEqual(evidence["groups"][0]["display_type"], "comparison")

    def test_parses_existing_free_text_values_into_comparison(self):
        evidence = idea_comparisons._numeric_evidence("Oil production", [
            {"source_label": "A", "value": "1.10 million bpd"},
            {"source_label": "B", "value": "0.92 million bpd"},
        ], [])
        self.assertEqual(evidence["total_observations"], 2)
        self.assertEqual(evidence["groups"][0]["display_type"], "comparison")
        self.assertAlmostEqual(evidence["groups"][0]["spread"], 0.18)

    def test_ambiguous_free_text_values_are_not_charted(self):
        for value in (
            "2.5 million barrels, up 3% from 2024",
            "2.5 million barrels — % of quota",
            "10-15%",
            "$98 to $120",
        ):
            with self.subTest(value=value):
                self.assertIsNone(idea_comparisons._parse_numeric_value(value))
        self.assertEqual(idea_comparisons._parse_numeric_value("2.5% of quota")["unit"], "%")

    def test_dated_observations_become_trend_with_direction(self):
        facts = [{
            "id": 8, "reference_label": "Forecast", "observed_at": None,
            "observations": [
                {"id": 1, "metric": "Oil production", "numeric_value": 0.9, "unit": "million bpd", "period_label": "2026 Q3", "value_kind": "actual", "display_value": "0.9 million bpd"},
                {"id": 2, "metric": "Oil production", "numeric_value": 1.1, "unit": "million bpd", "period_label": "2026 Q4", "value_kind": "forecast", "display_value": "1.1 million bpd"},
            ],
        }]
        group = idea_comparisons._numeric_evidence("Oil production", [], facts)["groups"][0]
        self.assertEqual(group["display_type"], "trend")
        self.assertEqual(group["direction"], "up")
        self.assertAlmostEqual(group["change"], 0.2)

    def test_quarter_first_periods_are_sorted_chronologically(self):
        facts = [{
            "id": 8, "reference_label": "Forecast", "observed_at": None,
            "observations": [
                {"id": 1, "metric": "Oil production", "numeric_value": 0.9, "unit": "million bpd", "period_label": "Q4 2025", "value_kind": "actual", "display_value": "0.9 million bpd"},
                {"id": 2, "metric": "Oil production", "numeric_value": 1.1, "unit": "million bpd", "period_label": "Q1 2026", "value_kind": "forecast", "display_value": "1.1 million bpd"},
            ],
        }]
        group = idea_comparisons._numeric_evidence("Oil production", [], facts)["groups"][0]
        self.assertEqual([item["period_label"] for item in group["observations"]], ["Q4 2025", "Q1 2026"])
        self.assertEqual(group["direction"], "up")
        self.assertAlmostEqual(group["change"], 0.2)

    def test_unknown_period_formats_do_not_claim_a_trend(self):
        facts = [{
            "id": 8, "reference_label": "Forecast", "observed_at": None,
            "observations": [
                {"id": 1, "metric": "Oil production", "numeric_value": 0.9, "unit": "million bpd", "period_label": "before policy", "value_kind": "actual", "display_value": "0.9 million bpd"},
                {"id": 2, "metric": "Oil production", "numeric_value": 1.1, "unit": "million bpd", "period_label": "after policy", "value_kind": "forecast", "display_value": "1.1 million bpd"},
            ],
        }]
        group = idea_comparisons._numeric_evidence("Oil production", [], facts)["groups"][0]
        self.assertEqual(group["display_type"], "comparison")
        self.assertIsNone(group["direction"])
        self.assertIsNone(group["change"])

    def test_non_numeric_evidence_does_not_create_chart(self):
        evidence = idea_comparisons._numeric_evidence("Customer sentiment", [
            {"source_label": "A", "value": "mostly positive"},
        ], [])
        self.assertEqual(evidence, {"groups": [], "total_observations": 0})


if __name__ == "__main__":
    unittest.main()
