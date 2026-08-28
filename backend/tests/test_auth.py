"""Coverage for services/auth/auth.py: session resolution, RBAC permission
gating, and the double-submit CSRF check - the machinery every other route's
tests bypass via dependency overrides/patches (see test_main_analysis_routes.py's
docstring). Exercised end-to-end through a tiny throwaway FastAPI app so the
real Depends() wiring (get_current_user -> require_permission -> CSRF) runs
exactly as it does in main.py, with only the store-layer calls mocked.
"""

import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from fastapi import Depends, FastAPI, Response
from fastapi.testclient import TestClient

from services.auth import auth

app = FastAPI()


@app.get("/whoami")
def whoami(user: dict = Depends(auth.get_current_user)):
    return {"user_id": user["id"]}


@app.get("/needs-perm-get")
def needs_perm_get(user: dict = Depends(auth.require_permission("articles.view"))):
    return {"ok": True}


@app.post("/needs-perm")
def needs_perm(user: dict = Depends(auth.require_permission("articles.view"))):
    return {"ok": True}


@app.post("/needs-any-perm")
def needs_any_perm(user: dict = Depends(auth.require_any_permission("articles.view", "articles.import"))):
    return {"ok": True}


@app.post("/no-perm-needed")
def no_perm_needed(user: dict = Depends(auth.require_permission())):
    return {"ok": True}


SESSION_COOKIE = auth.config.SESSION_COOKIE_NAME
CSRF_COOKIE = auth.config.CSRF_COOKIE_NAME


class GetCurrentUserTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_401_without_a_session_cookie_at_all(self):
        resp = self.client.get("/whoami")
        self.assertEqual(resp.status_code, 401)

    def test_401_when_the_token_matches_no_session(self):
        with patch("services.auth.auth.sessions_store.get_session", return_value=None):
            resp = self.client.get("/whoami", cookies={SESSION_COOKIE: "bad-token"})
        self.assertEqual(resp.status_code, 401)

    def test_401_when_the_session_users_account_no_longer_exists(self):
        session = {"user_id": 1, "csrf_token": "csrf"}
        with patch("services.auth.auth.sessions_store.get_session", return_value=session), \
             patch("services.auth.auth.users_store.get_user_by_id", return_value=None):
            resp = self.client.get("/whoami", cookies={SESSION_COOKIE: "tok"})
        self.assertEqual(resp.status_code, 401)

    def test_401_when_the_account_is_disabled(self):
        """A disabled user's still-live session must not authenticate them -
        this is what makes disabling an account actually revoke access rather
        than only hiding them from the roster."""
        session = {"user_id": 1, "csrf_token": "csrf"}
        user = {"id": 1, "status": "disabled"}
        with patch("services.auth.auth.sessions_store.get_session", return_value=session), \
             patch("services.auth.auth.users_store.get_user_by_id", return_value=user):
            resp = self.client.get("/whoami", cookies={SESSION_COOKIE: "tok"})
        self.assertEqual(resp.status_code, 401)

    def test_success_returns_the_user_and_touches_the_session(self):
        session = {"user_id": 7, "csrf_token": "csrf"}
        user = {"id": 7, "status": "active"}
        with patch("services.auth.auth.sessions_store.get_session", return_value=session), \
             patch("services.auth.auth.users_store.get_user_by_id", return_value=user), \
             patch("services.auth.auth.sessions_store.touch_session") as mock_touch:
            resp = self.client.get("/whoami", cookies={SESSION_COOKIE: "tok"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"user_id": 7})
        mock_touch.assert_called_once_with("tok")


class _AuthenticatedTestCase(unittest.TestCase):
    """Base for tests that need a valid session already resolved, so they can
    focus on what require_permission()/CSRF do on top of that."""

    def setUp(self):
        self.client = TestClient(app)
        self.session = {"user_id": 1, "csrf_token": "csrf-secret"}
        self.user = {"id": 1, "status": "active", "role_id": 2}
        self._session_patcher = patch("services.auth.auth.sessions_store.get_session", return_value=self.session)
        self._user_patcher = patch("services.auth.auth.users_store.get_user_by_id", return_value=self.user)
        self._touch_patcher = patch("services.auth.auth.sessions_store.touch_session")
        self._session_patcher.start()
        self._user_patcher.start()
        self._touch_patcher.start()
        self.addCleanup(self._session_patcher.stop)
        self.addCleanup(self._user_patcher.stop)
        self.addCleanup(self._touch_patcher.stop)

    def _authed(self, **extra_cookies):
        return {SESSION_COOKIE: "tok", **extra_cookies}


class RequirePermissionTests(_AuthenticatedTestCase):
    def test_403_when_the_user_lacks_the_required_permission(self):
        with patch("services.auth.permissions_store.user_permission_keys", return_value={"articles.import"}):
            resp = self.client.post(
                "/needs-perm",
                cookies=self._authed(**{CSRF_COOKIE: "csrf-secret"}),
                headers={"X-CSRF-Token": "csrf-secret"},
            )
        self.assertEqual(resp.status_code, 403)

    def test_200_when_the_user_holds_the_required_permission(self):
        with patch("services.auth.permissions_store.user_permission_keys", return_value={"articles.view"}):
            resp = self.client.post(
                "/needs-perm",
                cookies=self._authed(**{CSRF_COOKIE: "csrf-secret"}),
                headers={"X-CSRF-Token": "csrf-secret"},
            )
        self.assertEqual(resp.status_code, 200)

    def test_get_requests_bypass_csrf_but_not_permission_checks(self):
        with patch("services.auth.permissions_store.user_permission_keys", return_value=set()):
            resp = self.client.get("/needs-perm-get", cookies=self._authed())
        self.assertEqual(resp.status_code, 403)

        with patch("services.auth.permissions_store.user_permission_keys", return_value={"articles.view"}):
            resp = self.client.get("/needs-perm-get", cookies=self._authed())
        self.assertEqual(resp.status_code, 200)

    def test_no_permissions_required_still_requires_authentication_and_csrf(self):
        with patch("services.auth.permissions_store.user_permission_keys", return_value=set()):
            resp = self.client.post("/no-perm-needed", cookies=self._authed())
        self.assertEqual(resp.status_code, 403)  # missing CSRF header

        with patch("services.auth.permissions_store.user_permission_keys", return_value=set()):
            resp = self.client.post(
                "/no-perm-needed",
                cookies=self._authed(**{CSRF_COOKIE: "csrf-secret"}),
                headers={"X-CSRF-Token": "csrf-secret"},
            )
        self.assertEqual(resp.status_code, 200)


class RequireAnyPermissionTests(_AuthenticatedTestCase):
    def test_200_when_holding_only_one_of_the_listed_permissions(self):
        with patch("services.auth.permissions_store.user_permission_keys", return_value={"articles.import"}):
            resp = self.client.post(
                "/needs-any-perm",
                cookies=self._authed(**{CSRF_COOKIE: "csrf-secret"}),
                headers={"X-CSRF-Token": "csrf-secret"},
            )
        self.assertEqual(resp.status_code, 200)

    def test_403_when_holding_none_of_the_listed_permissions(self):
        with patch("services.auth.permissions_store.user_permission_keys", return_value={"projects.view"}):
            resp = self.client.post(
                "/needs-any-perm",
                cookies=self._authed(**{CSRF_COOKIE: "csrf-secret"}),
                headers={"X-CSRF-Token": "csrf-secret"},
            )
        self.assertEqual(resp.status_code, 403)


class CsrfEnforcementTests(_AuthenticatedTestCase):
    """Double-submit CSRF: an unsafe request must echo the CSRF cookie's value
    back in the X-CSRF-Token header. Permission is granted throughout - these
    isolate the CSRF gate itself, not RBAC."""

    def setUp(self):
        super().setUp()
        self._perm_patcher = patch("services.auth.permissions_store.user_permission_keys", return_value={"articles.view"})
        self._perm_patcher.start()
        self.addCleanup(self._perm_patcher.stop)

    def test_403_with_no_csrf_header_at_all(self):
        resp = self.client.post("/needs-perm", cookies=self._authed(**{CSRF_COOKIE: "csrf-secret"}))
        self.assertEqual(resp.status_code, 403)

    def test_403_when_the_header_does_not_match_the_sessions_csrf_token(self):
        resp = self.client.post(
            "/needs-perm",
            cookies=self._authed(**{CSRF_COOKIE: "csrf-secret"}),
            headers={"X-CSRF-Token": "not-the-right-token"},
        )
        self.assertEqual(resp.status_code, 403)

    def test_200_when_the_header_matches(self):
        resp = self.client.post(
            "/needs-perm",
            cookies=self._authed(**{CSRF_COOKIE: "csrf-secret"}),
            headers={"X-CSRF-Token": "csrf-secret"},
        )
        self.assertEqual(resp.status_code, 200)


class AuthCookieHelperTests(unittest.TestCase):
    """set_auth_cookies()/clear_auth_cookies() are the only place cookie
    flags (HttpOnly, Secure, SameSite) are decided - a regression here is a
    session/CSRF cookie silently shipped with the wrong flags."""

    def test_session_cookie_is_httponly_and_csrf_cookie_is_not(self):
        response = Response()
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        auth.set_auth_cookies(response, "raw-token", "csrf-token", expires_at)
        set_cookie_headers = response.headers.getlist("set-cookie")
        session_header = next(h for h in set_cookie_headers if h.startswith(f"{SESSION_COOKIE}="))
        csrf_header = next(h for h in set_cookie_headers if h.startswith(f"{CSRF_COOKIE}="))
        self.assertIn("HttpOnly", session_header)
        self.assertNotIn("HttpOnly", csrf_header)

    def test_clear_auth_cookies_expires_both(self):
        response = Response()
        auth.clear_auth_cookies(response)
        set_cookie_headers = response.headers.getlist("set-cookie")
        self.assertTrue(any(h.startswith(f"{SESSION_COOKIE}=") for h in set_cookie_headers))
        self.assertTrue(any(h.startswith(f"{CSRF_COOKIE}=") for h in set_cookie_headers))


if __name__ == "__main__":
    unittest.main()
