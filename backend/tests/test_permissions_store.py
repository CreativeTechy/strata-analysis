"""Coverage for services/auth/permissions_store.py: the dynamic RBAC storage
every require_permission() check and every project-visibility check
(services/auth/authz.py) ultimately reads through user_permission_keys()/
user_is_full_access(). db is mocked throughout - no real Postgres needed."""

import unittest
from unittest.mock import patch

from services.auth import permissions_store


class UserPermissionKeysTests(unittest.TestCase):
    def test_a_user_with_no_role_holds_no_permissions(self):
        self.assertEqual(permissions_store.user_permission_keys({"role_id": None}), set())
        self.assertEqual(permissions_store.user_permission_keys({}), set())

    def test_a_role_that_no_longer_exists_holds_no_permissions(self):
        with patch.object(permissions_store, "get_role_by_id", return_value=None):
            self.assertEqual(permissions_store.user_permission_keys({"role_id": 99}), set())

    def test_full_access_role_implicitly_holds_every_permission(self):
        """full_access must not depend on role_permissions rows existing, so
        editing the permission matrix can never lock the admin role out."""
        role = {"id": 1, "full_access": True}
        all_perms = [{"key": "projects.view"}, {"key": "users.delete"}]
        with patch.object(permissions_store, "get_role_by_id", return_value=role), \
             patch.object(permissions_store, "list_permissions", return_value=all_perms):
            keys = permissions_store.user_permission_keys({"role_id": 1})
        self.assertEqual(keys, {"projects.view", "users.delete"})

    def test_regular_role_holds_only_its_assigned_permissions(self):
        role = {"id": 2, "full_access": False}
        with patch.object(permissions_store, "get_role_by_id", return_value=role), \
             patch.object(permissions_store, "get_role_permission_keys", return_value={"articles.view"}):
            keys = permissions_store.user_permission_keys({"role_id": 2})
        self.assertEqual(keys, {"articles.view"})


class UserIsFullAccessTests(unittest.TestCase):
    def test_false_for_a_user_with_no_role(self):
        self.assertFalse(permissions_store.user_is_full_access({"role_id": None}))
        self.assertFalse(permissions_store.user_is_full_access({}))

    def test_false_when_the_role_no_longer_exists(self):
        with patch.object(permissions_store, "get_role_by_id", return_value=None):
            self.assertFalse(permissions_store.user_is_full_access({"role_id": 1}))

    def test_true_only_for_a_full_access_role(self):
        with patch.object(permissions_store, "get_role_by_id", return_value={"full_access": True}):
            self.assertTrue(permissions_store.user_is_full_access({"role_id": 1}))
        with patch.object(permissions_store, "get_role_by_id", return_value={"full_access": False}):
            self.assertFalse(permissions_store.user_is_full_access({"role_id": 1}))


class RoleMutationGuardTests(unittest.TestCase):
    """The validation/guard branches that don't need a real database to
    exercise - required-field checks and the two protections on delete_role."""

    def test_create_role_rejects_a_blank_name(self):
        with self.assertRaises(ValueError):
            permissions_store.create_role("   ")

    def test_update_role_rejects_a_blank_name(self):
        with self.assertRaises(ValueError):
            permissions_store.update_role(1, name="   ")

    def test_delete_role_404s_via_none_when_role_missing(self):
        with patch.object(permissions_store, "get_role_by_id", return_value=None):
            self.assertFalse(permissions_store.delete_role(1))

    def test_delete_role_refuses_a_system_role(self):
        with patch.object(permissions_store, "get_role_by_id", return_value={"id": 1, "is_system": True}):
            with self.assertRaises(ValueError):
                permissions_store.delete_role(1)

    def test_delete_role_refuses_a_role_still_assigned_to_users(self):
        with patch.object(permissions_store, "get_role_by_id", return_value={"id": 1, "is_system": False}), \
             patch.object(permissions_store, "db") as mock_db:
            mock_db.fetch_one.return_value = {"total": 3}
            with self.assertRaises(ValueError):
                permissions_store.delete_role(1)
            mock_db.execute.assert_not_called()

    def test_delete_role_deletes_when_unused_and_not_system(self):
        with patch.object(permissions_store, "get_role_by_id", return_value={"id": 1, "is_system": False}), \
             patch.object(permissions_store, "db") as mock_db:
            mock_db.fetch_one.return_value = {"total": 0}
            self.assertTrue(permissions_store.delete_role(1))
            mock_db.execute.assert_called_once()


class SetRolePermissionsTests(unittest.TestCase):
    def test_blank_and_duplicate_keys_are_dropped_before_writing(self):
        with patch.object(permissions_store, "db") as mock_db, \
             patch.object(permissions_store, "get_role_permission_keys", return_value={"articles.view"}):
            result = permissions_store.set_role_permissions(1, ["articles.view", "  ", "articles.view", ""])
        # One delete for the role's existing rows, one insert per distinct key.
        insert_calls = [c for c in mock_db.execute.call_args_list if "insert into role_permissions" in c.args[0]]
        self.assertEqual(len(insert_calls), 1)
        self.assertEqual(result, {"articles.view"})


class GetRoleWithPermissionsTests(unittest.TestCase):
    def test_none_when_the_role_does_not_exist(self):
        with patch.object(permissions_store, "get_role_by_id", return_value=None):
            self.assertIsNone(permissions_store.get_role_with_permissions(1))

    def test_full_access_role_reports_every_permission(self):
        role = {"id": 1, "full_access": True}
        with patch.object(permissions_store, "get_role_by_id", return_value=role), \
             patch.object(permissions_store, "list_permissions", return_value=[{"key": "b"}, {"key": "a"}]):
            result = permissions_store.get_role_with_permissions(1)
        self.assertEqual(result["permissions"], ["a", "b"])

    def test_regular_role_reports_only_its_assigned_permissions(self):
        role = {"id": 2, "full_access": False}
        with patch.object(permissions_store, "get_role_by_id", return_value=role), \
             patch.object(permissions_store, "get_role_permission_keys", return_value={"articles.view"}):
            result = permissions_store.get_role_with_permissions(2)
        self.assertEqual(result["permissions"], ["articles.view"])


if __name__ == "__main__":
    unittest.main()
