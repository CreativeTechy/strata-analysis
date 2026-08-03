import unittest

import content_guard


class RedditBlockedPayloadTests(unittest.TestCase):
    def test_error_dict_is_blocked(self):
        self.assertTrue(content_guard.is_reddit_blocked_payload({"error": 404, "message": "Not Found"}))

    def test_private_subreddit_reason_is_blocked(self):
        self.assertTrue(content_guard.is_reddit_blocked_payload({"reason": "private", "message": "Forbidden"}))

    def test_banned_subreddit_reason_is_blocked(self):
        self.assertTrue(content_guard.is_reddit_blocked_payload({"reason": "banned"}))

    def test_normal_listing_is_not_blocked(self):
        self.assertFalse(content_guard.is_reddit_blocked_payload({"kind": "Listing", "data": {"children": []}}))

    def test_non_dict_payload_is_not_blocked(self):
        self.assertFalse(content_guard.is_reddit_blocked_payload([{"kind": "Listing"}, {"kind": "Listing"}]))
        self.assertFalse(content_guard.is_reddit_blocked_payload(None))


class TelegramChannelUnavailableTests(unittest.TestCase):
    def test_redirect_statuses_are_unavailable(self):
        for status in (301, 302, 303, 307, 308):
            self.assertTrue(content_guard.is_telegram_channel_unavailable(status))

    def test_200_is_available(self):
        self.assertFalse(content_guard.is_telegram_channel_unavailable(200))


if __name__ == "__main__":
    unittest.main()
