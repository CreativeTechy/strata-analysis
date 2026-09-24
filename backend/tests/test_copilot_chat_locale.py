import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from fastapi.testclient import TestClient

from services.auth import auth
import main

FAKE_USER = {"id": 1, "username": "admin", "role_id": 1, "status": "active"}


def _fake_get_current_user():
    return FAKE_USER


class CopilotChatLocaleTestCase(unittest.TestCase):
    """/api/chat's `locale` param: an explicit, backend-validated request for
    the reply's output language, independent of the interface language and of
    any article's own detected source_language."""

    @classmethod
    def setUpClass(cls):
        main.app.dependency_overrides[auth.get_current_user] = _fake_get_current_user
        cls._csrf_patcher = patch("services.auth.auth._enforce_csrf")
        cls._csrf_patcher.start()
        cls._perm_patcher = patch(
            "services.auth.permissions_store.user_permission_keys",
            return_value={"articles.view"},
        )
        cls._perm_patcher.start()
        cls._full_access_patcher = patch("services.auth.permissions_store.user_is_full_access", return_value=True)
        cls._full_access_patcher.start()
        cls.client = TestClient(main.app)

    @classmethod
    def tearDownClass(cls):
        main.app.dependency_overrides.clear()
        cls._csrf_patcher.stop()
        cls._perm_patcher.stop()
        cls._full_access_patcher.stop()

    def test_no_locale_keeps_the_prior_unsteered_system_prompt(self):
        """Omitting `locale` entirely must not change behavior for existing
        callers that predate this parameter."""
        with patch("main.chat_completion", return_value="ok") as mock_chat:
            resp = self.client.post("/api/chat", json={"question": "What's trending?", "articles": []})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"reply": "ok"})
        system_message = mock_chat.call_args.kwargs["messages"][0]
        self.assertEqual(system_message["content"], main.COPILOT_SYSTEM_PROMPT)

    def test_english_locale_produces_an_english_instruction(self):
        with patch("main.chat_completion", return_value="ok") as mock_chat:
            resp = self.client.post(
                "/api/chat", json={"question": "What's trending?", "articles": [], "locale": "en"},
            )
        self.assertEqual(resp.status_code, 200)
        system_message = mock_chat.call_args.kwargs["messages"][0]
        self.assertIn("Respond in English.", system_message["content"])

    def test_arabic_locale_appends_an_arabic_instruction(self):
        with patch("main.chat_completion", return_value="مرحبا") as mock_chat:
            resp = self.client.post(
                "/api/chat", json={"question": "What's trending?", "articles": [], "locale": "ar"},
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"reply": "مرحبا"})
        system_message = mock_chat.call_args.kwargs["messages"][0]
        self.assertIn(main.COPILOT_SYSTEM_PROMPT, system_message["content"])
        self.assertIn("Arabic", system_message["content"])
        self.assertIn("proper names", system_message["content"])

    def test_unsupported_locale_is_a_stable_coded_400(self):
        with patch("main.chat_completion") as mock_chat:
            resp = self.client.post(
                "/api/chat", json={"question": "What's trending?", "articles": [], "locale": "fr"},
            )
        self.assertEqual(resp.status_code, 400)
        # main.py's global HTTPException handler wraps every raised
        # exception's `detail` as {"error": detail} - api_error()'s
        # {code, params} shape rides inside that existing envelope unchanged.
        error = resp.json()["error"]
        self.assertEqual(error["code"], "unsupported_locale")
        self.assertEqual(error["params"]["locale"], "fr")
        self.assertIn("en", error["params"]["supported"])
        self.assertIn("ar", error["params"]["supported"])
        mock_chat.assert_not_called()


if __name__ == "__main__":
    unittest.main()
