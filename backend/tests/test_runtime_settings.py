import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("DEEPSEEK_API_KEY", "test-key")

import config
from services.settings import runtime_settings


class FakeCursor:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def fetchone(self):
        return {"key": "ok"}


class FakeTransaction:
    def __init__(self, cursor=None):
        self.cursor = cursor or FakeCursor()

    def __enter__(self):
        return self.cursor

    def __exit__(self, *exc_info):
        return False


class ConfigStateTestCase(unittest.TestCase):
    """Base class that snapshots/restores every config.py attribute this
    module can mutate, so tests exercising _apply()/set_value()/reset_value()
    against the real config module never leak state into other test files."""

    def setUp(self):
        self._config_snapshot = vars(config).copy()

    def tearDown(self):
        config.__dict__.clear()
        config.__dict__.update(self._config_snapshot)


class ValidateTests(unittest.TestCase):
    def test_int_out_of_range_is_rejected(self):
        with self.assertRaises(ValueError):
            runtime_settings._validate("ANALYSIS_CONCURRENCY", 999)

    def test_int_non_numeric_is_rejected(self):
        with self.assertRaises(ValueError):
            runtime_settings._validate("ANALYSIS_CONCURRENCY", "not-a-number")

    def test_int_within_range_is_accepted(self):
        self.assertEqual(runtime_settings._validate("ANALYSIS_CONCURRENCY", "4"), 4)

    def test_float_out_of_range_is_rejected(self):
        with self.assertRaises(ValueError):
            runtime_settings._validate("SENTIMENT_CONFIDENCE_THRESHOLD", 1.5)

    def test_enum_rejects_unknown_choice(self):
        with self.assertRaises(ValueError):
            runtime_settings._validate("LLM_PROVIDER", "not-a-real-provider")

    def test_enum_is_case_insensitive(self):
        self.assertEqual(runtime_settings._validate("LLM_PROVIDER", "OLLAMA"), "ollama")

    def test_string_rejects_blank(self):
        with self.assertRaises(ValueError):
            runtime_settings._validate("SENTIMENT_CLASSIFIER_MODEL", "   ")


class CrossValidateTests(ConfigStateTestCase):
    def test_accept_below_exclude_is_rejected(self):
        config.ARTICLE_RELEVANCE_EXCLUDE_THRESHOLD = 0.5
        with self.assertRaises(ValueError):
            runtime_settings._cross_validate("ARTICLE_RELEVANCE_ACCEPT_THRESHOLD", 0.3)

    def test_exclude_above_accept_is_rejected(self):
        config.ARTICLE_RELEVANCE_ACCEPT_THRESHOLD = 0.5
        with self.assertRaises(ValueError):
            runtime_settings._cross_validate("ARTICLE_RELEVANCE_EXCLUDE_THRESHOLD", 0.7)

    def test_equal_thresholds_are_allowed(self):
        config.ARTICLE_RELEVANCE_EXCLUDE_THRESHOLD = 0.5
        runtime_settings._cross_validate("ARTICLE_RELEVANCE_ACCEPT_THRESHOLD", 0.5)


class CompetitorProviderSyncTests(ConfigStateTestCase):
    """Covers the fix for the app-provider/competitor-provider divergence: a
    live LLM_PROVIDER change must keep carrying COMPETITOR_ANALYSIS_LLM_PROVIDER
    along with it unless the competitor scope has been explicitly pinned,
    either in .env or via its own Settings override."""

    def test_llm_provider_change_cascades_when_competitor_scope_is_unpinned(self):
        config.COMPETITOR_ANALYSIS_LLM_PROVIDER_EXPLICIT = False
        with patch.object(runtime_settings.db, "fetch_one", return_value=None), \
             patch.object(runtime_settings.db, "transaction", return_value=FakeTransaction()):
            runtime_settings.set_value("LLM_PROVIDER", "deepseek", {"id": 1, "username": "alice"})
        self.assertEqual(config.LLM_PROVIDER, "deepseek")
        self.assertEqual(config.COMPETITOR_ANALYSIS_LLM_PROVIDER, "deepseek")
        self.assertEqual(config.COMPETITOR_LLM_CHAT_MODEL, config.LLM_CHAT_MODEL)

    def test_llm_provider_change_does_not_cascade_when_pinned_by_its_own_db_override(self):
        config.COMPETITOR_ANALYSIS_LLM_PROVIDER_EXPLICIT = False
        config.COMPETITOR_ANALYSIS_LLM_PROVIDER = "openai"
        with patch.object(runtime_settings.db, "fetch_one", return_value={"key": "COMPETITOR_ANALYSIS_LLM_PROVIDER"}), \
             patch.object(runtime_settings.db, "transaction", return_value=FakeTransaction()):
            runtime_settings.set_value("LLM_PROVIDER", "deepseek", {"id": 1, "username": "alice"})
        self.assertEqual(config.LLM_PROVIDER, "deepseek")
        self.assertEqual(config.COMPETITOR_ANALYSIS_LLM_PROVIDER, "openai")

    def test_llm_provider_change_does_not_cascade_when_pinned_by_env(self):
        config.COMPETITOR_ANALYSIS_LLM_PROVIDER_EXPLICIT = True
        config.COMPETITOR_ANALYSIS_LLM_PROVIDER = "openai"
        with patch.object(runtime_settings.db, "fetch_one") as mock_fetch_one, \
             patch.object(runtime_settings.db, "transaction", return_value=FakeTransaction()):
            runtime_settings.set_value("LLM_PROVIDER", "deepseek", {"id": 1, "username": "alice"})
        mock_fetch_one.assert_not_called()
        self.assertEqual(config.COMPETITOR_ANALYSIS_LLM_PROVIDER, "openai")

    def test_resolve_all_reports_live_llm_provider_as_the_competitor_default_when_unpinned(self):
        config.COMPETITOR_ANALYSIS_LLM_PROVIDER_EXPLICIT = False
        config.LLM_PROVIDER = "deepseek"
        with patch.object(runtime_settings.db, "fetch_all", return_value=[]):
            resolved = runtime_settings.resolve_all()
        entry = resolved["COMPETITOR_ANALYSIS_LLM_PROVIDER"]
        self.assertEqual(entry["default"], "deepseek")
        self.assertEqual(entry["value"], "deepseek")
        self.assertTrue(entry["is_default"])

    def test_reset_resyncs_competitor_provider_to_the_live_llm_provider_when_unpinned(self):
        config.COMPETITOR_ANALYSIS_LLM_PROVIDER_EXPLICIT = False
        config.LLM_PROVIDER = "deepseek"
        config.COMPETITOR_ANALYSIS_LLM_PROVIDER = "openai"
        with patch.object(runtime_settings.db, "transaction", return_value=FakeTransaction()), \
             patch.object(runtime_settings.db, "fetch_all", return_value=[]):
            runtime_settings.reset_value("COMPETITOR_ANALYSIS_LLM_PROVIDER")
        self.assertEqual(config.COMPETITOR_ANALYSIS_LLM_PROVIDER, "deepseek")


class SetValueTests(ConfigStateTestCase):
    def test_rejects_an_unknown_key(self):
        with self.assertRaises(ValueError):
            runtime_settings.set_value("NOT_A_REAL_SETTING", "1", {"id": 1})

    def test_persists_history_and_current_row_in_one_transaction(self):
        cursor = FakeCursor()
        with patch.object(runtime_settings.db, "transaction", return_value=FakeTransaction(cursor)), \
             patch.object(runtime_settings, "resolve_all", return_value={"ANALYSIS_CONCURRENCY": {"value": 5}}):
            result = runtime_settings.set_value("ANALYSIS_CONCURRENCY", "5", {"id": 1, "username": "alice"})
        self.assertEqual(len(cursor.calls), 2)
        self.assertIn("runtime_settings_history", cursor.calls[0][0])
        self.assertIn("on conflict (key) do update", cursor.calls[1][0])
        self.assertEqual(config.ANALYSIS_CONCURRENCY, 5)
        self.assertEqual(result, {"value": 5})

    def test_invalid_value_never_reaches_the_database(self):
        with patch.object(runtime_settings.db, "transaction") as mock_transaction:
            with self.assertRaises(ValueError):
                runtime_settings.set_value("ANALYSIS_CONCURRENCY", "not-a-number", {"id": 1})
        mock_transaction.assert_not_called()


class CrossValidationLockingTests(ConfigStateTestCase):
    """Guards against the accept/exclude threshold TOCTOU: two concurrent
    PATCH calls for the paired keys must not both read the pre-update values
    and leave the invariant inverted - see _CROSS_VALIDATION_LOCK."""

    def test_set_value_for_a_cross_validated_key_holds_the_shared_lock(self):
        config.ARTICLE_RELEVANCE_EXCLUDE_THRESHOLD = 0.1
        with patch.object(runtime_settings, "_CROSS_VALIDATION_LOCK") as mock_lock, \
             patch.object(runtime_settings.db, "transaction", return_value=FakeTransaction()):
            runtime_settings.set_value("ARTICLE_RELEVANCE_ACCEPT_THRESHOLD", "0.5", {"id": 1})
        mock_lock.__enter__.assert_called_once()
        mock_lock.__exit__.assert_called_once()

    def test_set_value_for_an_unrelated_key_does_not_touch_the_lock(self):
        with patch.object(runtime_settings, "_CROSS_VALIDATION_LOCK") as mock_lock, \
             patch.object(runtime_settings.db, "transaction", return_value=FakeTransaction()):
            runtime_settings.set_value("ANALYSIS_CONCURRENCY", "3", {"id": 1})
        mock_lock.__enter__.assert_not_called()

    def test_reset_refuses_to_revert_into_an_inverted_pair(self):
        """The accept threshold's own .env default is below the exclude
        threshold's current override - resetting accept must not silently
        land the pair in an inverted state."""
        config.ARTICLE_RELEVANCE_EXCLUDE_THRESHOLD = 0.9
        with patch.object(runtime_settings, "_ENV_DEFAULTS", {**runtime_settings._ENV_DEFAULTS, "ARTICLE_RELEVANCE_ACCEPT_THRESHOLD": 0.1}), \
             patch.object(runtime_settings.db, "transaction") as mock_transaction:
            with self.assertRaises(ValueError):
                runtime_settings.reset_value("ARTICLE_RELEVANCE_ACCEPT_THRESHOLD")
        mock_transaction.assert_not_called()


if __name__ == "__main__":
    unittest.main()
