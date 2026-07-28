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

    def test_defaults_to_deepseek_when_llm_provider_is_unset(self):
        self._reload_with_env({})
        self.assertEqual(config.LLM_PROVIDER, "deepseek")
        self.assertEqual(config.LLM_API_STYLE, "chat_completions")

    def test_unknown_provider_falls_back_to_deepseek_not_openai(self):
        self._reload_with_env({"LLM_PROVIDER": "not-a-real-provider"})
        self.assertEqual(config.LLM_PROVIDER, "deepseek")

    def test_openai_is_still_selectable_as_an_override(self):
        self._reload_with_env({"LLM_PROVIDER": "openai"})
        self.assertEqual(config.LLM_PROVIDER, "openai")
        self.assertEqual(config.LLM_API_STYLE, "responses")


if __name__ == "__main__":
    unittest.main()
