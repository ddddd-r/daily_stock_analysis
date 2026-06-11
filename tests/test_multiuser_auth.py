# -*- coding: utf-8 -*-
"""
Phase 1 multi-user auth tests: User model, password hashing, sessions,
and the authenticate/bootstrap helpers.

Uses a temporary SQLite DB and ADMIN_AUTH_ENABLED=true so session signing is
active. Heavy deps are stubbed in the same style as the other tests.
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock

if "litellm" not in sys.modules:
    sys.modules["litellm"] = MagicMock()
if "json_repair" not in sys.modules:
    sys.modules["json_repair"] = MagicMock()


class MultiUserAuthTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls._saved_env = {k: os.environ.get(k) for k in ("DATABASE_PATH", "ADMIN_AUTH_ENABLED")}
        os.environ["DATABASE_PATH"] = os.path.join(cls._tmp.name, "test.db")
        os.environ["ADMIN_AUTH_ENABLED"] = "true"

        from src.storage import DatabaseManager
        DatabaseManager.reset_instance()
        from src import auth, storage
        # Reset auth caches so the temp data dir / enabled flag are picked up.
        auth.refresh_auth_state()
        cls.auth = auth
        cls.db = storage.get_db()

    @classmethod
    def tearDownClass(cls):
        from src.storage import DatabaseManager
        DatabaseManager.reset_instance()
        cls._tmp.cleanup()
        # Restore environment so we don't leak auth state into other test modules.
        for k, v in cls._saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        cls.auth.refresh_auth_state()

    def test_password_hash_roundtrip(self):
        h = self.auth.hash_password("hunter2")
        self.assertIn(":", h)
        self.assertTrue(self.auth.verify_password_string("hunter2", h))
        self.assertFalse(self.auth.verify_password_string("wrong", h))
        self.assertFalse(self.auth.verify_password_string("hunter2", None))

    def test_user_crud_and_authenticate(self):
        created = self.db.create_user(
            "alice", password_hash=self.auth.hash_password("pw123456"), email="alice@example.com"
        )
        self.assertIsNotNone(created)
        self.assertFalse(created["is_admin"])
        # duplicate username rejected
        self.assertIsNone(self.db.create_user("alice", password_hash="x"))
        # authenticate
        self.assertIsNotNone(self.auth.authenticate_user("alice", "pw123456"))
        self.assertIsNone(self.auth.authenticate_user("alice", "bad"))
        # disabled user cannot authenticate
        self.db.set_user_active(created["id"], False)
        self.assertIsNone(self.auth.authenticate_user("alice", "pw123456"))
        self.db.set_user_active(created["id"], True)

    def test_session_carries_user_id(self):
        uid = "abc123def456"
        token = self.auth.create_session(uid)
        self.assertEqual(len(token.split(".")), 4)
        self.assertEqual(self.auth.verify_session(token), uid)
        # tampering / legacy format rejected
        self.assertIsNone(self.auth.verify_session(token[:-1] + ("0" if token[-1] != "0" else "1")))
        self.assertIsNone(self.auth.verify_session("nonce.ts.sig"))
        # empty user id is not a valid session
        self.assertIsNone(self.auth.verify_session(self.auth.create_session("")))

    def test_google_link_and_lookup(self):
        u = self.db.create_user("bob", password_hash=self.auth.hash_password("pw123456"))
        self.db.link_google_to_user(u["id"], "sub-xyz", "bob@example.com")
        found = self.db.get_user_by_google_sub("sub-xyz")
        self.assertEqual(found["username"], "bob")
        self.assertEqual(found["auth_provider"], "both")


if __name__ == "__main__":
    unittest.main()
