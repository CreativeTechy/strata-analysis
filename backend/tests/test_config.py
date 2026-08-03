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


class RedditTelegramSourceTypeTests(unittest.TestCase):
    """reddit/telegram source-type inference and resolution (config.py's
    half of the reddit/telegram source-type feature - see
    services/sources/sources_store.py for URL derivation)."""

    def test_reddit_urls_are_inferred_as_reddit(self):
        self.assertEqual(config._infer_source_type("https://www.reddit.com/r/test"), "reddit")
        self.assertEqual(config._infer_source_type("https://reddit.com/user/someone"), "reddit")

    def test_telegram_urls_are_inferred_as_telegram(self):
        self.assertEqual(config._infer_source_type("https://t.me/s/somechannel"), "telegram")
        self.assertEqual(config._infer_source_type("https://telegram.me/somechannel"), "telegram")

    def test_other_social_urls_still_infer_as_social_not_reddit(self):
        self.assertEqual(config._infer_source_type("https://x.com/someone"), "social")
        self.assertEqual(config._infer_source_type("https://www.facebook.com/someone"), "social")

    def test_explicit_reddit_and_telegram_types_are_trusted(self):
        self.assertEqual(config._resolve_source_type("reddit", "https://www.reddit.com/r/test"), "reddit")
        self.assertEqual(config._resolve_source_type("telegram", "https://t.me/s/somechannel"), "telegram")

    def test_legacy_rows_stored_as_social_upgrade_to_reddit_or_telegram(self):
        # reddit.com used to be lumped into the generic "social" bucket before
        # this type existed - existing rows should be reclassified on load,
        # the same way legacy rss/web rows already upgrade to "social".
        self.assertEqual(config._resolve_source_type("social", "https://www.reddit.com/r/test"), "reddit")
        self.assertEqual(config._resolve_source_type("rss", "https://t.me/s/somechannel"), "telegram")

    def test_hashtag_keyword_username_are_never_overridden(self):
        self.assertEqual(config._resolve_source_type("username", "https://x.com/someone"), "username")
        self.assertEqual(config._resolve_source_type("keyword", "https://news.google.com/rss/search?q=ev"), "keyword")


class RedditOAuthConfiguredTests(unittest.TestCase):
    def test_false_when_unset(self):
        with patch.object(config, "REDDIT_OAUTH_CLIENT_ID", ""), patch.object(config, "REDDIT_OAUTH_CLIENT_SECRET", ""):
            self.assertFalse(config.reddit_oauth_configured())

    def test_false_when_only_one_of_the_pair_is_set(self):
        with patch.object(config, "REDDIT_OAUTH_CLIENT_ID", "cid"), patch.object(config, "REDDIT_OAUTH_CLIENT_SECRET", ""):
            self.assertFalse(config.reddit_oauth_configured())

    def test_true_when_both_are_set(self):
        with patch.object(config, "REDDIT_OAUTH_CLIENT_ID", "cid"), patch.object(config, "REDDIT_OAUTH_CLIENT_SECRET", "secret"):
            self.assertTrue(config.reddit_oauth_configured())


if __name__ == "__main__":
    unittest.main()
