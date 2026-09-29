"""GET/PATCH/DELETE /api/settings[/{key}] - route wiring and permission
gating. runtime_settings.py's own validation/persistence logic is covered by
test_runtime_settings.py; this only asserts the endpoints enforce
settings.view vs settings.update correctly and translate ValueError into a
400."""

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


class SettingsRoutesTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        main.app.dependency_overrides[auth.get_current_user] = _fake_get_current_user
        cls._csrf_patcher = patch("services.auth.auth._enforce_csrf")
        cls._csrf_patcher.start()
        cls.client = TestClient(main.app)

    @classmethod
    def tearDownClass(cls):
        main.app.dependency_overrides.clear()
        cls._csrf_patcher.stop()

    def _with_permissions(self, *keys):
        return patch("services.auth.permissions_store.user_permission_keys", return_value=set(keys))


class GetSettingsTests(SettingsRoutesTestCase):
    def test_returns_settings_for_a_viewer(self):
        with self._with_permissions("settings.view"), \
             patch("services.settings.runtime_settings.resolve_all", return_value={"ANALYSIS_CONCURRENCY": {"value": 2}}):
            resp = self.client.get("/api/settings")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"settings": {"ANALYSIS_CONCURRENCY": {"value": 2}}})

    def test_403_without_settings_view(self):
        with self._with_permissions():
            resp = self.client.get("/api/settings")
        self.assertEqual(resp.status_code, 403)


class UpdateSettingTests(SettingsRoutesTestCase):
    def test_updates_a_setting_for_an_updater(self):
        with self._with_permissions("settings.update"), \
             patch("services.settings.runtime_settings.set_value", return_value={"value": 5}) as mock_set:
            resp = self.client.patch("/api/settings/ANALYSIS_CONCURRENCY", json={"value": 5})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"key": "ANALYSIS_CONCURRENCY", "setting": {"value": 5}})
        mock_set.assert_called_once_with("ANALYSIS_CONCURRENCY", 5, FAKE_USER)

    def test_403_for_a_viewer_without_update_permission(self):
        with self._with_permissions("settings.view"), \
             patch("services.settings.runtime_settings.set_value") as mock_set:
            resp = self.client.patch("/api/settings/ANALYSIS_CONCURRENCY", json={"value": 5})
        self.assertEqual(resp.status_code, 403)
        mock_set.assert_not_called()

    def test_invalid_value_becomes_a_400_not_a_500(self):
        with self._with_permissions("settings.update"), \
             patch("services.settings.runtime_settings.set_value", side_effect=ValueError("out of range")):
            resp = self.client.patch("/api/settings/ANALYSIS_CONCURRENCY", json={"value": 999})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("out of range", resp.json()["error"])


class ResetSettingTests(SettingsRoutesTestCase):
    def test_resets_a_setting_for_an_updater(self):
        with self._with_permissions("settings.update"), \
             patch("services.settings.runtime_settings.reset_value", return_value={"value": 2}) as mock_reset:
            resp = self.client.delete("/api/settings/ANALYSIS_CONCURRENCY")
        self.assertEqual(resp.status_code, 200)
        mock_reset.assert_called_once_with("ANALYSIS_CONCURRENCY")

    def test_403_without_update_permission(self):
        with self._with_permissions("settings.view"), \
             patch("services.settings.runtime_settings.reset_value") as mock_reset:
            resp = self.client.delete("/api/settings/ANALYSIS_CONCURRENCY")
        self.assertEqual(resp.status_code, 403)
        mock_reset.assert_not_called()


if __name__ == "__main__":
    unittest.main()
