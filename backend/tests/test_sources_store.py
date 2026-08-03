import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("DEEPSEEK_API_KEY", "test-key")

from services.sources import sources_store


class DeriveRedditUrlTests(unittest.TestCase):
    def test_full_url_is_passed_through_unchanged(self):
        self.assertEqual(
            sources_store._derive_reddit_url("https://www.reddit.com/r/test/"),
            "https://www.reddit.com/r/test",
        )

    def test_full_url_strips_query_string(self):
        self.assertEqual(
            sources_store._derive_reddit_url("https://www.reddit.com/r/test?sort=new"),
            "https://www.reddit.com/r/test",
        )

    def test_non_reddit_url_is_rejected(self):
        self.assertEqual(sources_store._derive_reddit_url("https://example.com/r/test"), "")

    def test_r_prefix_builds_subreddit_url(self):
        self.assertEqual(sources_store._derive_reddit_url("r/test"), "https://www.reddit.com/r/test")

    def test_u_prefix_builds_user_url(self):
        self.assertEqual(sources_store._derive_reddit_url("u/someone"), "https://www.reddit.com/user/someone")

    def test_user_prefix_builds_user_url(self):
        self.assertEqual(sources_store._derive_reddit_url("user/someone"), "https://www.reddit.com/user/someone")

    def test_bare_word_defaults_to_subreddit(self):
        self.assertEqual(sources_store._derive_reddit_url("test"), "https://www.reddit.com/r/test")

    def test_bare_word_with_user_kind_builds_user_url(self):
        self.assertEqual(sources_store._derive_reddit_url("someone", kind="user"), "https://www.reddit.com/user/someone")

    def test_bare_word_with_search_kind_builds_search_url(self):
        self.assertEqual(
            sources_store._derive_reddit_url("electric vehicles", kind="search"),
            "https://www.reddit.com/search?q=electric+vehicles",
        )

    def test_explicit_prefix_wins_over_kind_hint(self):
        # r/ prefix is unambiguous, so an (incorrect) kind="user" hint must not override it.
        self.assertEqual(sources_store._derive_reddit_url("r/test", kind="user"), "https://www.reddit.com/r/test")

    def test_empty_input_returns_empty_string(self):
        self.assertEqual(sources_store._derive_reddit_url(""), "")

    def test_full_search_url_keeps_q_and_drops_reddits_own_tracking_params(self):
        # Reddit's search UI appends cId/iId/type alongside the real query -
        # the whole query string used to be stripped (see the "full url"
        # tests above), which silently threw away the search term itself.
        url = (
            "https://www.reddit.com/search/?q=donald+news&type=posts"
            "&cId=f6e3b9b2-4518-4f92-9e9f-01a1a0a48c49&iId=e437d424-b0ac-4631-bd4d-b66d199c2e1b"
        )
        self.assertEqual(sources_store._derive_reddit_url(url), "https://www.reddit.com/search?q=donald+news")

    def test_full_search_url_without_q_is_rejected(self):
        self.assertEqual(sources_store._derive_reddit_url("https://www.reddit.com/search?type=posts"), "")


class DeriveTelegramUrlTests(unittest.TestCase):
    def test_full_channel_url_normalizes_to_s_preview(self):
        self.assertEqual(sources_store._derive_telegram_url("https://t.me/somechannel"), "https://t.me/s/somechannel")

    def test_full_s_preview_url_is_kept(self):
        self.assertEqual(sources_store._derive_telegram_url("https://t.me/s/somechannel"), "https://t.me/s/somechannel")

    def test_at_handle_form(self):
        self.assertEqual(sources_store._derive_telegram_url("@somechannel"), "https://t.me/s/somechannel")

    def test_bare_handle_form(self):
        self.assertEqual(sources_store._derive_telegram_url("somechannel"), "https://t.me/s/somechannel")

    def test_non_telegram_url_is_rejected(self):
        self.assertEqual(sources_store._derive_telegram_url("https://example.com/somechannel"), "")

    def test_empty_input_returns_empty_string(self):
        self.assertEqual(sources_store._derive_telegram_url(""), "")


class UpsertPayloadRedditTelegramTests(unittest.TestCase):
    """The end-to-end path a create/update API call actually goes through."""

    def test_reddit_source_normalizes_bare_subreddit_kind(self):
        payload = sources_store._upsert_payload({"source_type": "reddit", "url": "test", "reddit_kind": "subreddit"})
        self.assertEqual(payload["url"], "https://www.reddit.com/r/test")
        self.assertEqual(payload["source_type"], "reddit")

    def test_reddit_source_normalizes_bare_search_kind(self):
        payload = sources_store._upsert_payload({"source_type": "reddit", "url": "ev fires", "reddit_kind": "search"})
        self.assertEqual(payload["url"], "https://www.reddit.com/search?q=ev+fires")

    def test_telegram_source_normalizes_at_handle(self):
        payload = sources_store._upsert_payload({"source_type": "telegram", "url": "@somechannel"})
        self.assertEqual(payload["url"], "https://t.me/s/somechannel")
        self.assertEqual(payload["source_type"], "telegram")

    def test_telegram_web_app_internal_chat_id_link_is_rejected_not_saved_raw(self):
        # web.telegram.org/a/#-100... is Telegram Web's internal numeric
        # chat-ID deep link, not a public @username/t.me link - it must not
        # be silently saved as-is (that used to happen via a stray `or url`
        # fallback, producing a "telegram" source that would scrape forever
        # and yield zero articles instead of failing at creation time).
        payload = sources_store._upsert_payload(
            {"source_type": "telegram", "url": "https://web.telegram.org/a/#-1001613270320"}
        )
        self.assertEqual(payload["url"], "")

    def test_reddit_non_reddit_host_is_rejected_not_saved_raw(self):
        payload = sources_store._upsert_payload({"source_type": "reddit", "url": "https://example.com/r/test"})
        self.assertEqual(payload["url"], "")


if __name__ == "__main__":
    unittest.main()
