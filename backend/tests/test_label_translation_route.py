import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from fastapi.testclient import TestClient

from services.auth import auth
import main

FAKE_USER = {"id": 1, "username": "analyst", "role_id": 2, "status": "active"}


class LabelTranslationRouteTests(unittest.TestCase):
    """POST /api/i18n/labels: auth, project visibility and input validation."""

    def setUp(self):
        main.app.dependency_overrides[auth.get_current_user] = lambda: FAKE_USER
        self._patchers = [
            patch("services.auth.auth._enforce_csrf"),
            patch("services.auth.permissions_store.user_permission_keys", return_value={"articles.view"}),
            patch("services.auth.permissions_store.user_is_full_access", return_value=False),
            patch("services.auth.authz.list_project_ids_for_user", return_value=[7]),
        ]
        for patcher in self._patchers:
            patcher.start()
        self.client = TestClient(main.app)

    def tearDown(self):
        main.app.dependency_overrides.clear()
        for patcher in self._patchers:
            patcher.stop()

    def _post(self, **body):
        return self.client.post("/api/i18n/labels", json=body)

    def test_unauthenticated_is_401(self):
        main.app.dependency_overrides.clear()
        resp = TestClient(main.app).post("/api/i18n/labels", json={"project_id": 7, "locale": "ar", "values": ["Gulf"]})
        self.assertEqual(resp.status_code, 401)

    def test_without_articles_view_is_403(self):
        with patch("services.auth.permissions_store.user_permission_keys", return_value=set()):
            resp = self._post(project_id=7, locale="ar", values=["Gulf"])
        self.assertEqual(resp.status_code, 403)

    def test_project_the_user_cannot_see_is_404_and_never_translates(self):
        with patch("main.translate_labels") as mock_translate:
            resp = self._post(project_id=99, locale="ar", values=["Gulf"])
        self.assertEqual(resp.status_code, 404)
        mock_translate.assert_not_called()

    def test_missing_project_id_is_400(self):
        self.assertEqual(self._post(locale="ar", values=["Gulf"]).status_code, 400)

    def test_unsupported_locale_is_400(self):
        resp = self._post(project_id=7, locale="fr", values=["Gulf"])
        self.assertEqual(resp.status_code, 400)
        self.assertIn("unsupported_locale", resp.text)

    def test_non_list_or_non_string_values_are_400(self):
        self.assertEqual(self._post(project_id=7, locale="ar", values="Gulf").status_code, 400)
        self.assertEqual(self._post(project_id=7, locale="ar", values=["Gulf", 3]).status_code, 400)

    def test_default_locale_is_identity_without_llm(self):
        with patch("services.i18n.label_translation.chat_completion") as mock_chat:
            resp = self._post(project_id=7, locale="en", values=["Gulf"])
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["labels"], {"Gulf": "Gulf"})
        mock_chat.assert_not_called()

    def test_translation_is_scoped_to_the_requested_project(self):
        with patch("main.translate_labels", return_value={"Gulf": "الخليج"}) as mock_translate:
            resp = self._post(project_id=7, locale="ar", values=["Gulf"])
        self.assertEqual(resp.status_code, 200)
        mock_translate.assert_called_once_with(7, ["Gulf"], "ar")


if __name__ == "__main__":
    unittest.main()
