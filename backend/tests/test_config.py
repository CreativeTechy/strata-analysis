import importlib
import os
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("DEEPSEEK_API_KEY", "test-key")

import config


class ProviderDefaultsTests(unittest.TestCase):
    """`config.py`'s provider defaults, tested independently of whatever
    LLM_PROVIDER/.env this machine happens to have set."""

    def test_deepseek_provider_default_is_not_a_deprecated_legacy_model_alias(self):
        deepseek_defaults = config._LLM_PROVIDER_DEFAULTS["deepseek"]
        self.assertNotIn(deepseek_defaults["default_model"], ("deepseek-chat", "deepseek-reasoner"))
        self.assertEqual(deepseek_defaults["api_style"], "chat_completions")


class ProviderResolutionTests(unittest.TestCase):
    """Reloads config with a fully controlled environment (no backend/.env
    involved) to exercise LLM_PROVIDER's own default-and-fallback logic."""

    def _reload_with_env(self, env: dict) -> None:
        with patch.dict(os.environ, env, clear=True), patch.object(Path, "exists", return_value=False):
            importlib.reload(config)

    def tearDown(self):
        # Restore the module every other test file relies on.
        importlib.reload(config)

    def test_defaults_to_local_ollama_when_llm_provider_is_unset(self):
        """The product analyzes uploaded documents, so the out-of-the-box
        provider has to be the local one - an unset LLM_PROVIDER must never
        silently ship those documents to a hosted API."""
        self._reload_with_env({})
        self.assertEqual(config.LLM_PROVIDER, "ollama")
        self.assertEqual(config.LLM_API_STYLE, "chat_completions")
        self.assertIn("localhost", config.LLM_CHAT_BASE_URL)

    def test_unknown_provider_falls_back_to_ollama_not_a_hosted_one(self):
        self._reload_with_env({"LLM_PROVIDER": "not-a-real-provider"})
        self.assertEqual(config.LLM_PROVIDER, "ollama")

    def test_openai_is_still_selectable_as_an_override(self):
        self._reload_with_env({"LLM_PROVIDER": "openai"})
        self.assertEqual(config.LLM_PROVIDER, "openai")
        self.assertEqual(config.LLM_API_STYLE, "responses")

    def test_ollama_needs_no_real_api_key(self):
        self._reload_with_env({"LLM_PROVIDER": "ollama"})
        self.assertEqual(config.LLM_PROVIDER, "ollama")
        self.assertEqual(config.LLM_API_STYLE, "chat_completions")
        self.assertTrue(config.LLM_API_KEY)  # placeholder, but must be non-empty
        self.assertIn("localhost", config.LLM_CHAT_BASE_URL)


class CompetitorAnalysisProviderOverrideTests(unittest.TestCase):
    """COMPETITOR_ANALYSIS_LLM_PROVIDER scopes Ollama (or any other provider)
    to backend/services/competitors/ without touching the app-wide provider
    every other feature (article analysis, Copilot chat) uses."""

    def _reload_with_env(self, env: dict) -> None:
        with patch.dict(os.environ, env, clear=True), patch.object(Path, "exists", return_value=False):
            importlib.reload(config)

    def tearDown(self):
        importlib.reload(config)

    def test_unset_inherits_the_app_wide_provider(self):
        self._reload_with_env({"LLM_PROVIDER": "deepseek"})
        self.assertEqual(config.COMPETITOR_ANALYSIS_LLM_PROVIDER, "deepseek")
        self.assertEqual(config.COMPETITOR_LLM_CHAT_BASE_URL, config.LLM_CHAT_BASE_URL)
        self.assertEqual(config.COMPETITOR_LLM_CHAT_MODEL, config.LLM_CHAT_MODEL)

    def test_ollama_can_be_scoped_to_competitor_analysis_only(self):
        self._reload_with_env({"LLM_PROVIDER": "deepseek", "COMPETITOR_ANALYSIS_LLM_PROVIDER": "ollama"})
        # The app-wide provider (enrichment, Copilot, discovery) is untouched.
        self.assertEqual(config.LLM_PROVIDER, "deepseek")
        self.assertEqual(config.LLM_API_STYLE, "chat_completions")
        self.assertNotIn("localhost", config.LLM_CHAT_BASE_URL)
        # Only the competitor-analysis-scoped values point at Ollama.
        self.assertEqual(config.COMPETITOR_ANALYSIS_LLM_PROVIDER, "ollama")
        self.assertIn("localhost", config.COMPETITOR_LLM_CHAT_BASE_URL)
        self.assertNotEqual(config.COMPETITOR_LLM_CHAT_BASE_URL, config.LLM_CHAT_BASE_URL)

    def test_unknown_override_falls_back_to_the_app_wide_provider_not_deepseek(self):
        self._reload_with_env({"LLM_PROVIDER": "openai", "COMPETITOR_ANALYSIS_LLM_PROVIDER": "not-a-real-provider"})
        self.assertEqual(config.COMPETITOR_ANALYSIS_LLM_PROVIDER, "openai")
        self.assertEqual(config.COMPETITOR_LLM_CHAT_BASE_URL, config.LLM_CHAT_BASE_URL)


if __name__ == "__main__":
    unittest.main()
