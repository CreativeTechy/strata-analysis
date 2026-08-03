"""Tests for scraper/social_sources.py - deliberately free of scrapy (the
spider module itself imports scrapy at load time and is not importable in an
environment without it installed; this module is the scrapy-independent half
of the reddit/telegram scraping logic, see its own docstring)."""

import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("DEEPSEEK_API_KEY", "test-key")

from scraper import social_sources


class ProxyMetaTests(unittest.TestCase):
    def test_no_proxy_configured_returns_empty_dict(self):
        with patch.object(social_sources.config, "REDDIT_PROXY_URL", ""), patch.object(
            social_sources.config, "TELEGRAM_PROXY_URL", ""
        ):
            self.assertEqual(social_sources.proxy_meta("reddit"), {})
            self.assertEqual(social_sources.proxy_meta("telegram"), {})

    def test_reddit_proxy_configured_is_used_only_for_reddit(self):
        with patch.object(social_sources.config, "REDDIT_PROXY_URL", "http://user:pass@proxy:8080"), patch.object(
            social_sources.config, "TELEGRAM_PROXY_URL", ""
        ):
            self.assertEqual(social_sources.proxy_meta("reddit"), {"proxy": "http://user:pass@proxy:8080"})
            self.assertEqual(social_sources.proxy_meta("telegram"), {})

    def test_unknown_platform_returns_empty_dict(self):
        self.assertEqual(social_sources.proxy_meta("rss"), {})


class RedditOAuthTests(unittest.TestCase):
    def test_token_fetch_skipped_when_not_configured(self):
        with patch.object(social_sources.config, "REDDIT_OAUTH_CLIENT_ID", ""), patch.object(
            social_sources.config, "REDDIT_OAUTH_CLIENT_SECRET", ""
        ):
            self.assertIsNone(social_sources.fetch_reddit_oauth_token())

    def test_token_fetch_posts_client_credentials_and_returns_token(self):
        mock_response = Mock(ok=True)
        mock_response.json.return_value = {"access_token": "abc123", "expires_in": 3600}
        with patch.object(social_sources.config, "REDDIT_OAUTH_CLIENT_ID", "cid"), patch.object(
            social_sources.config, "REDDIT_OAUTH_CLIENT_SECRET", "secret"
        ), patch.object(social_sources.requests, "post", return_value=mock_response) as mock_post:
            token = social_sources.fetch_reddit_oauth_token()
        self.assertEqual(token, "abc123")
        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs["auth"], ("cid", "secret"))
        self.assertEqual(kwargs["data"], {"grant_type": "client_credentials"})

    def test_token_fetch_returns_none_on_non_ok_response(self):
        mock_response = Mock(ok=False)
        with patch.object(social_sources.config, "REDDIT_OAUTH_CLIENT_ID", "cid"), patch.object(
            social_sources.config, "REDDIT_OAUTH_CLIENT_SECRET", "secret"
        ), patch.object(social_sources.requests, "post", return_value=mock_response):
            self.assertIsNone(social_sources.fetch_reddit_oauth_token())

    def test_token_fetch_returns_none_on_request_exception(self):
        with patch.object(social_sources.config, "REDDIT_OAUTH_CLIENT_ID", "cid"), patch.object(
            social_sources.config, "REDDIT_OAUTH_CLIENT_SECRET", "secret"
        ), patch.object(social_sources.requests, "post", side_effect=RuntimeError("boom")):
            self.assertIsNone(social_sources.fetch_reddit_oauth_token())

    def test_oauth_request_url_for_subreddit(self):
        self.assertEqual(
            social_sources.reddit_oauth_request_url("https://www.reddit.com/r/test"),
            "https://oauth.reddit.com/r/test?limit=25",
        )

    def test_oauth_request_url_for_search(self):
        self.assertEqual(
            social_sources.reddit_oauth_request_url("https://www.reddit.com/search?q=ev+fires"),
            "https://oauth.reddit.com/search?q=ev+fires&limit=25",
        )

    def test_oauth_comments_url(self):
        self.assertEqual(
            social_sources.reddit_oauth_comments_url("/r/test/comments/abc/title/"),
            "https://oauth.reddit.com/r/test/comments/abc/title/",
        )

    def test_oauth_comments_url_with_no_permalink_returns_none(self):
        self.assertIsNone(social_sources.reddit_oauth_comments_url(None))

    def test_oauth_headers_with_token(self):
        self.assertEqual(social_sources.reddit_oauth_headers("abc123"), {"Authorization": "Bearer abc123"})

    def test_oauth_headers_without_token(self):
        self.assertEqual(social_sources.reddit_oauth_headers(None), {})


class RedditFetchUrlTests(unittest.TestCase):
    def test_subreddit_url_gets_json_suffix_and_limit(self):
        self.assertEqual(
            social_sources.reddit_fetch_url("https://www.reddit.com/r/test"),
            "https://www.reddit.com/r/test.json?limit=25",
        )

    def test_user_url_gets_json_suffix(self):
        self.assertEqual(
            social_sources.reddit_fetch_url("https://www.reddit.com/user/someone"),
            "https://www.reddit.com/user/someone.json?limit=25",
        )

    def test_search_url_uses_search_json_endpoint(self):
        self.assertEqual(
            social_sources.reddit_fetch_url("https://www.reddit.com/search?q=ev+fires"),
            "https://www.reddit.com/search.json?q=ev+fires&limit=25",
        )

    def test_empty_path_returns_none(self):
        self.assertIsNone(social_sources.reddit_fetch_url("https://www.reddit.com"))


class ExtractRedditListingTests(unittest.TestCase):
    def test_extracts_post_and_queues_its_permalink_for_comments(self):
        payload = {
            "kind": "Listing",
            "data": {
                "children": [
                    {
                        "kind": "t3",
                        "data": {
                            "permalink": "/r/test/comments/abc/some_title/",
                            "subreddit": "test",
                            "title": "Some title",
                            "selftext": "Post body",
                            "author": "poster",
                            "created_utc": 1700000000,
                        },
                    }
                ]
            },
        }
        items, permalinks = social_sources.extract_reddit_listing(payload)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["url"], "https://www.reddit.com/r/test/comments/abc/some_title/")
        self.assertEqual(items[0]["text"], "Post body")
        self.assertEqual(permalinks, ["/r/test/comments/abc/some_title/"])

    def test_link_only_post_falls_back_to_title_as_text(self):
        payload = {
            "data": {
                "children": [
                    {"kind": "t3", "data": {"permalink": "/r/test/comments/abc/x/", "title": "A link post", "selftext": ""}}
                ]
            }
        }
        items, _ = social_sources.extract_reddit_listing(payload)
        self.assertEqual(items[0]["text"], "A link post")

    def test_top_level_comment_from_user_listing_is_extracted(self):
        payload = {
            "data": {
                "children": [
                    {
                        "kind": "t1",
                        "data": {
                            "permalink": "/r/test/comments/abc/x/def456/",
                            "body": "A comment body",
                            "author": "commenter",
                            "subreddit": "test",
                        },
                    }
                ]
            }
        }
        items, permalinks = social_sources.extract_reddit_listing(payload)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["text"], "A comment body")
        self.assertEqual(permalinks, [])

    def test_blocked_payload_yields_nothing(self):
        items, permalinks = social_sources.extract_reddit_listing({"error": 403, "reason": "private"})
        self.assertEqual(items, [])
        self.assertEqual(permalinks, [])

    def test_empty_listing_yields_nothing_without_error(self):
        items, permalinks = social_sources.extract_reddit_listing({"data": {"children": []}})
        self.assertEqual(items, [])
        self.assertEqual(permalinks, [])


class ExtractRedditCommentTreeTests(unittest.TestCase):
    def _payload(self, comment_children):
        return [
            {"data": {"children": [{"kind": "t3", "data": {"permalink": "/r/test/comments/abc/title/"}}]}},
            {"data": {"children": comment_children}},
        ]

    def test_extracts_top_level_comment_with_permalink_built_from_post(self):
        payload = self._payload([
            {"kind": "t1", "data": {"id": "c1", "body": "First comment", "author": "a"}},
        ])
        items = social_sources.extract_reddit_comment_tree(payload)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["url"], "https://www.reddit.com/r/test/comments/abc/title/c1/")
        self.assertEqual(items[0]["text"], "First comment")

    def test_extracts_nested_reply(self):
        payload = self._payload([
            {
                "kind": "t1",
                "data": {
                    "id": "c1",
                    "body": "Parent comment",
                    "author": "a",
                    "replies": {"data": {"children": [{"kind": "t1", "data": {"id": "c2", "body": "A reply", "author": "b"}}]}},
                },
            },
        ])
        items = social_sources.extract_reddit_comment_tree(payload)
        self.assertEqual(len(items), 2)
        texts = {item["text"] for item in items}
        self.assertEqual(texts, {"Parent comment", "A reply"})

    def test_deleted_comment_is_skipped(self):
        payload = self._payload([{"kind": "t1", "data": {"id": "c1", "body": "[deleted]"}}])
        self.assertEqual(social_sources.extract_reddit_comment_tree(payload), [])

    def test_more_kind_stub_is_skipped(self):
        payload = self._payload([{"kind": "more", "data": {"children": ["c3", "c4"]}}])
        self.assertEqual(social_sources.extract_reddit_comment_tree(payload), [])

    def test_malformed_payload_shape_returns_empty(self):
        self.assertEqual(social_sources.extract_reddit_comment_tree({"not": "a list"}), [])
        self.assertEqual(social_sources.extract_reddit_comment_tree([{"data": {}}]), [])


TELEGRAM_MESSAGE_HTML = """
<div class="tgme_widget_message_wrap">
  <div class="tgme_widget_message" data-post="somechannel/42">
    <div class="tgme_widget_message_author">
      <span class="tgme_widget_message_owner_name"><span dir="auto">Some Channel</span></span>
    </div>
    <div class="tgme_widget_message_text">Hello <b>world</b></div>
    <div class="tgme_widget_message_footer">
      <a class="tgme_widget_message_date" href="https://t.me/somechannel/42">
        <time datetime="2024-12-10T18:13:03+00:00">18:13</time>
      </a>
    </div>
  </div>
</div>
"""

TELEGRAM_EMPTY_HTML = "<div class=\"tgme_widget_messages_helper\"></div>"


class ExtractTelegramMessagesTests(unittest.TestCase):
    def test_extracts_message_text_url_and_metadata(self):
        items = social_sources.extract_telegram_messages(TELEGRAM_MESSAGE_HTML)
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["url"], "https://t.me/somechannel/42")
        self.assertEqual(item["channel"], "somechannel")
        self.assertEqual(item["msg_id"], "42")
        self.assertEqual(item["text"], "Hello world")
        self.assertEqual(item["published"], "2024-12-10T18:13:03+00:00")

    def test_empty_widget_yields_no_messages(self):
        self.assertEqual(social_sources.extract_telegram_messages(TELEGRAM_EMPTY_HTML), [])

    def test_message_without_text_is_skipped(self):
        html = '<div class="tgme_widget_message_wrap"><div class="tgme_widget_message" data-post="c/1"></div></div>'
        self.assertEqual(social_sources.extract_telegram_messages(html), [])


if __name__ == "__main__":
    unittest.main()
