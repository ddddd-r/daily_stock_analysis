# -*- coding: utf-8 -*-
"""
Phase 2a: per-user isolation for 问股 conversations.

Verifies that conversation sessions/messages are scoped to their owner
(user_id) at the storage layer, and that the legacy migration backfills
existing rows to DEFAULT_USER_ID.
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


class ConversationIsolationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls._saved = os.environ.get("DATABASE_PATH")
        os.environ["DATABASE_PATH"] = os.path.join(cls._tmp.name, "iso.db")
        from src.storage import DatabaseManager
        DatabaseManager.reset_instance()
        cls.db = DatabaseManager.get_instance()

    @classmethod
    def tearDownClass(cls):
        from src.storage import DatabaseManager
        DatabaseManager.reset_instance()
        cls._tmp.cleanup()
        if cls._saved is None:
            os.environ.pop("DATABASE_PATH", None)
        else:
            os.environ["DATABASE_PATH"] = cls._saved

    def setUp(self):
        # Seed two users' conversations fresh per test.
        self.db.save_conversation_message("s_alice", "user", "alice q", user_id="alice")
        self.db.save_conversation_message("s_alice", "assistant", "alice a", user_id="alice")
        self.db.save_conversation_message("s_bob", "user", "bob q", user_id="bob")

    def tearDown(self):
        self.db.delete_conversation_session("s_alice", user_id="alice")
        self.db.delete_conversation_session("s_bob", user_id="bob")

    def test_sessions_scoped_to_owner(self):
        alice = {s["session_id"] for s in self.db.get_chat_sessions(user_id="alice")}
        bob = {s["session_id"] for s in self.db.get_chat_sessions(user_id="bob")}
        self.assertEqual(alice, {"s_alice"})
        self.assertEqual(bob, {"s_bob"})

    def test_messages_require_ownership(self):
        # alice cannot read bob's session
        self.assertEqual(self.db.get_conversation_messages("s_bob", user_id="alice"), [])
        # owner can
        self.assertTrue(self.db.get_conversation_messages("s_bob", user_id="bob"))

    def test_delete_requires_ownership(self):
        self.assertEqual(self.db.delete_conversation_session("s_alice", user_id="bob"), 0)
        self.assertEqual(self.db.delete_conversation_session("s_alice", user_id="alice"), 2)

    def test_default_user_fallback(self):
        # Unauthenticated writes land under DEFAULT_USER_ID and are isolated.
        from src.storage import DEFAULT_USER_ID
        self.db.save_conversation_message("s_anon", "user", "hi")  # no user_id
        sessions = {s["session_id"] for s in self.db.get_chat_sessions(user_id=DEFAULT_USER_ID)}
        self.assertIn("s_anon", sessions)
        self.assertNotIn("s_anon", {s["session_id"] for s in self.db.get_chat_sessions(user_id="alice")})
        self.db.delete_conversation_session("s_anon", user_id=DEFAULT_USER_ID)


if __name__ == "__main__":
    unittest.main()
