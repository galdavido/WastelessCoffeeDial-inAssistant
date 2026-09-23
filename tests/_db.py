"""Support for the tests that run against a real Postgres.

Most of the suite is DB-free. The API-flow tests are not: they exercise the
routes, the engine and the models together, which is the only way to catch a
bug that lives in how those pieces meet.

Locally, with no database reachable, those tests skip. In CI (``CI`` set, as
GitHub Actions does) an unreachable database is a failure instead, so a broken
service container can never turn the suite green by skipping it.
"""

from __future__ import annotations

import os
import unittest
import uuid
from typing import Any

from fastapi.testclient import TestClient

_ready: bool | None = None


def require_database() -> None:
    """Skip (locally) or fail (in CI) unless the schema is at head."""
    global _ready
    if _ready is None:
        try:
            from core.db_bootstrap import run_migrations

            run_migrations(retries=1)
            _ready = True
        except Exception as exc:
            if os.getenv("CI"):
                raise
            _ready = False
            print(f"database tests skipped: {exc}")
    if not _ready:
        raise unittest.SkipTest("no database reachable (set DATABASE_URL)")


class ApiClient:
    """A TestClient that speaks as one Tailscale user.

    Every test gets a fresh owner, so tests are isolated from each other and
    from whatever the database already holds without any teardown -- and the
    same mechanism is what keeps two friends' data apart in production.
    """

    def __init__(self, client: TestClient, owner: str | None = None) -> None:
        self.client = client
        self.owner = owner or f"tester-{uuid.uuid4().hex[:10]}@example.com"
        self.headers = {"Tailscale-User-Login": self.owner}

    def get(self, url: str, **kwargs: Any) -> Any:
        return self.client.get(url, headers=self.headers, **kwargs)

    def post(self, url: str, **kwargs: Any) -> Any:
        return self.client.post(url, headers=self.headers, **kwargs)

    def put(self, url: str, **kwargs: Any) -> Any:
        return self.client.put(url, headers=self.headers, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> Any:
        return self.client.delete(url, headers=self.headers, **kwargs)


class DatabaseTestCase(unittest.TestCase):
    """Runs every request in ``tailscale`` mode, as a fresh user per test."""

    @classmethod
    def setUpClass(cls) -> None:
        require_database()
        from core.web_server import app

        cls.client = TestClient(app)

    def setUp(self) -> None:
        self._saved_mode = os.environ.get("WCDA_AUTH_MODE")
        os.environ["WCDA_AUTH_MODE"] = "tailscale"
        self.api = ApiClient(self.client)

    def tearDown(self) -> None:
        if self._saved_mode is None:
            os.environ.pop("WCDA_AUTH_MODE", None)
        else:
            os.environ["WCDA_AUTH_MODE"] = self._saved_mode

    def another_user(self) -> ApiClient:
        return ApiClient(self.client)

    def ok(self, response: Any) -> Any:
        """The JSON body of a 200, or a failure that shows what came back."""
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()
