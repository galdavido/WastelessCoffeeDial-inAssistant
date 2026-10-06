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
from sqlalchemy.engine import make_url

_ready: bool | None = None

# Hosts and ports that belong to the live stacks (dev owns 5434; ``db`` is a
# live stack's service name inside the compose network).
_LIVE_HOSTS = {"wcda-dev-db", "wcda-prod-db-1", "db"}
_LIVE_PORTS = {5434}


def refuse_live_database(url: str | None) -> None:
    """Raise if ``url`` names a live database, unless explicitly overridden.

    The tests create rows (some visible to every user) and run migrations, so
    pointing them at the dev or prod database pollutes real data. A skip would
    hide the mistake, so this fails loudly.
    """
    if not url or os.getenv("WCDA_TESTS_ALLOW_LIVE_DB") == "1":
        return
    parsed = make_url(url)
    if parsed.host in _LIVE_HOSTS or parsed.port in _LIVE_PORTS:
        raise RuntimeError(
            f"refusing to run tests against {parsed.host}:{parsed.port}: it looks "
            "like a live database. Point DATABASE_URL at a disposable Postgres, "
            "or set WCDA_TESTS_ALLOW_LIVE_DB=1 to override."
        )


def require_database() -> None:
    """Skip (locally) or fail (in CI) unless the schema is at head."""
    global _ready
    refuse_live_database(os.getenv("DATABASE_URL"))
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


class Seeded:
    """Rows written straight to the database for one fresh owner.

    A unique owner per instance keeps tests isolated without any teardown, the
    same trick ``ApiClient`` uses.
    """

    def __init__(self, owner: str | None = None) -> None:
        from database.database import SessionLocal
        from database.models import Bean, BrewSetup, Equipment

        self.owner = owner or f"seed-{uuid.uuid4().hex[:10]}@example.com"
        with SessionLocal() as db:
            grinder = Equipment(owner=self.owner, type="grinder", brand="T", model="G")
            machine = Equipment(owner=self.owner, type="machine", brand="T", model="M")
            bean = Bean(
                owner=self.owner,
                roaster="R",
                name="B",
                origin="O",
                process="washed",
                roast_level="medium",
            )
            db.add_all([grinder, machine, bean])
            db.flush()
            setup = BrewSetup(
                owner=self.owner,
                name="Seeded",
                grinder_id=grinder.id,
                machine_id=machine.id,
                method="espresso",
            )
            db.add(setup)
            db.commit()
            self.grinder_id, self.machine_id = grinder.id, machine.id
            self.bean_id, self.setup_id = bean.id, setup.id

    def add_shot(self, **fields: Any) -> int:
        """Add one shot; ``fields`` override the measured-espresso defaults."""
        from database.database import SessionLocal
        from database.models import DialInLog

        values: dict[str, Any] = {
            "owner": self.owner,
            "bean_id": self.bean_id,
            "grinder_id": self.grinder_id,
            "machine_id": self.machine_id,
            "setup_id": self.setup_id,
            "grind_setting": "20",
            "grind_clicks": 20,
            "dose_g": 18.0,
            "yield_g": 36.0,
            "time_s": 28,
            "brew_method": "espresso",
            "data_quality": "measured",
        }
        values.update(fields)
        with SessionLocal() as db:
            row = DialInLog(**values)
            db.add(row)
            db.commit()
            return int(row.id)

    def add_recommendation(self, **fields: Any) -> int:
        from database.database import SessionLocal
        from database.models import Recommendation

        values: dict[str, Any] = {
            "owner": self.owner,
            "bean_id": self.bean_id,
            "setup_id": self.setup_id,
            "engine_version": "test",
        }
        values.update(fields)
        with SessionLocal() as db:
            row = Recommendation(**values)
            db.add(row)
            db.commit()
            return int(row.id)
