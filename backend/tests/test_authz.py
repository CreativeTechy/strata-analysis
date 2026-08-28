"""Coverage for services/auth/authz.py: the per-user project-visibility check
every project-scoped route (main.py, project_documents_api.py,
competitor_api.py) applies on top of RBAC - see the architecture review's
Step 1 authorization-gap fix. db is mocked throughout via
projects_store.list_project_ids_for_user."""

import unittest
from unittest.mock import patch

from fastapi import HTTPException

from services.auth import authz


class VisibleProjectIdsOrNoneTests(unittest.TestCase):
    def test_full_access_user_gets_no_restriction(self):
        with patch.object(authz.permissions_store, "user_is_full_access", return_value=True), \
             patch.object(authz, "list_project_ids_for_user") as mock_list:
            result = authz.visible_project_ids_or_none({"id": 1, "role_id": 1})
        self.assertIsNone(result)
        mock_list.assert_not_called()

    def test_non_admin_gets_their_linked_project_ids(self):
        with patch.object(authz.permissions_store, "user_is_full_access", return_value=False), \
             patch.object(authz, "list_project_ids_for_user", return_value=[3, 7]):
            result = authz.visible_project_ids_or_none({"id": 2, "role_id": 2})
        self.assertEqual(result, [3, 7])


class EnsureProjectVisibleTests(unittest.TestCase):
    def test_full_access_user_always_passes_without_a_lookup(self):
        with patch.object(authz.permissions_store, "user_is_full_access", return_value=True), \
             patch.object(authz, "list_project_ids_for_user") as mock_list:
            authz.ensure_project_visible(999, {"id": 1, "role_id": 1})
        mock_list.assert_not_called()

    def test_non_admin_passes_for_a_project_they_are_linked_to(self):
        with patch.object(authz.permissions_store, "user_is_full_access", return_value=False), \
             patch.object(authz, "list_project_ids_for_user", return_value=[3, 7]):
            authz.ensure_project_visible(7, {"id": 2, "role_id": 2})  # must not raise

    def test_non_admin_gets_a_404_not_a_403_for_a_project_they_cannot_see(self):
        """404, not 403: a project outside the user's links should look
        exactly like it doesn't exist, not confirm its existence to someone
        probing ids they aren't linked to."""
        with patch.object(authz.permissions_store, "user_is_full_access", return_value=False), \
             patch.object(authz, "list_project_ids_for_user", return_value=[3, 7]):
            with self.assertRaises(HTTPException) as ctx:
                authz.ensure_project_visible(99, {"id": 2, "role_id": 2})
        self.assertEqual(ctx.exception.status_code, 404)

    def test_non_admin_with_no_linked_projects_sees_nothing(self):
        with patch.object(authz.permissions_store, "user_is_full_access", return_value=False), \
             patch.object(authz, "list_project_ids_for_user", return_value=[]):
            with self.assertRaises(HTTPException) as ctx:
                authz.ensure_project_visible(1, {"id": 2, "role_id": 2})
        self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
