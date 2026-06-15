# -*- coding: utf-8 -*-
"""
Regression test for the history collection route path.

The frontend calls `/api/v1/history` WITHOUT a trailing slash. The list/delete
routes must register at exactly that path (empty route path under the
`/api/v1/history` prefix). Using `"/"` registers `/api/v1/history/`, and the
SPA/api catch-all 404 handler then intercepts the no-slash request before
Starlette can redirect — producing "API endpoint /api/v1/history not found".
(Regression introduced by an automated PR that replaced "" with "/".)
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

if "litellm" not in sys.modules:
    sys.modules["litellm"] = MagicMock()


class HistoryRoutePathTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import os
        cls._tmp = tempfile.TemporaryDirectory()
        static = Path(cls._tmp.name) / "static"
        static.mkdir()
        (static / "index.html").write_text("<html>spa</html>")
        # Isolate from the repo .env (which may enable auth) so requests aren't 401.
        cls._saved = {k: os.environ.get(k) for k in ("DATABASE_PATH", "ENV_FILE", "ADMIN_AUTH_ENABLED")}
        os.environ["DATABASE_PATH"] = str(Path(cls._tmp.name) / "t.db")
        os.environ["ENV_FILE"] = str(Path(cls._tmp.name) / "none.env")
        os.environ["ADMIN_AUTH_ENABLED"] = "false"
        from src.config import Config
        from src.storage import DatabaseManager
        import src.auth as auth
        Config.reset_instance()
        DatabaseManager.reset_instance()
        auth.refresh_auth_state()
        from fastapi.testclient import TestClient
        from api.app import create_app
        # static_dir present => SPA/api catch-all is active (like production).
        cls.client = TestClient(create_app(static_dir=static), follow_redirects=False)

    @classmethod
    def tearDownClass(cls):
        import os
        from src.storage import DatabaseManager
        import src.auth as auth
        DatabaseManager.reset_instance()
        cls._tmp.cleanup()
        for k, v in cls._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        auth.refresh_auth_state()

    def test_history_collection_registered_without_trailing_slash(self):
        paths = {r.path for r in self.client.app.routes}
        self.assertIn("/api/v1/history", paths)
        self.assertNotIn("/api/v1/history/", paths)

    def test_list_no_trailing_slash_returns_200(self):
        # No slash must hit the route directly (200), not the 404 catch-all.
        self.assertEqual(self.client.get("/api/v1/history").status_code, 200)

    def test_delete_no_trailing_slash_route_matches(self):
        # Empty record_ids => 400 from the handler, proving the route matched
        # (would be 404 "endpoint not found" if the path were wrong).
        resp = self.client.request("DELETE", "/api/v1/history", json={"record_ids": []})
        self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()
