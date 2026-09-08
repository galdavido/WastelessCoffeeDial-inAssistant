"""Admin dashboard wiring. No database: these check that it is mounted only
where it is configured, and that the token gate is closed by default.

The dashboard reads *another* instance's database and the dev instance it runs
on has no identity of its own, so "absent unless deliberately switched on" is
the security property worth pinning down in a test.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.admin_db import admin_enabled
from core.admin_routes import register_admin_routes
from core.admin_stats import _pct
from core.web_server import app

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "web" / "static"

_DB = "postgresql+psycopg2://wcda_readonly:pw@wcda-prod-db-1:5432/barista_db"


class TestAdminIsOptional(unittest.TestCase):
    def test_stats_are_never_open(self) -> None:
        """The one invariant that must hold in every environment.

        Where the dashboard is not configured the route does not exist (404);
        where it is, the token gate answers first (401). It is never reachable
        without a token -- asserting that, rather than a bare 404, keeps the
        test honest on a machine whose own .env happens to configure it.
        """
        client = TestClient(app)
        self.assertIn(client.get("/api/admin/stats").status_code, (401, 404))

    def test_page_and_data_agree_on_whether_it_exists(self) -> None:
        client = TestClient(app)
        page = client.get("/admin").status_code
        data = client.get("/api/admin/stats").status_code
        if admin_enabled():
            self.assertEqual((page, data), (200, 401))
        else:
            self.assertEqual((page, data), (404, 404))

    def test_enabled_needs_both_halves(self) -> None:
        cases = {
            (): False,
            ("db",): False,  # a dashboard with no token in front of it
            ("token",): False,  # a token guarding nothing
            ("db", "token"): True,
        }
        for present, expected in cases.items():
            env = {"WCDA_ADMIN_DATABASE_URL": "", "WCDA_ADMIN_TOKEN": ""}
            if "db" in present:
                env["WCDA_ADMIN_DATABASE_URL"] = _DB
            if "token" in present:
                env["WCDA_ADMIN_TOKEN"] = "s3cret"
            with patch.dict(os.environ, env):
                self.assertEqual(admin_enabled(), expected, present)


class TestAdminTokenGate(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch.dict(
            os.environ, {"WCDA_ADMIN_DATABASE_URL": _DB, "WCDA_ADMIN_TOKEN": "s3cret"}
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        admin_app = FastAPI()
        register_admin_routes(admin_app, str(STATIC))
        self.client = TestClient(admin_app)

    def test_stats_requires_a_token(self) -> None:
        self.assertEqual(self.client.get("/api/admin/stats").status_code, 401)

    def test_stats_rejects_a_wrong_token(self) -> None:
        response = self.client.get(
            "/api/admin/stats", headers={"X-Admin-Token": "not-it"}
        )
        self.assertEqual(response.status_code, 401)

    def test_page_shell_carries_no_data(self) -> None:
        # The HTML is ungated on purpose: it holds no numbers, only the form
        # that asks for the token.
        response = self.client.get("/admin")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Admin token", response.text)


class TestAdminStatsHelpers(unittest.TestCase):
    def test_pct_guards_against_an_empty_window(self) -> None:
        # A window with nothing in it must read "no data", never 0% -- they
        # mean different things on a usage dashboard.
        self.assertIsNone(_pct(0, 0))
        self.assertIsNone(_pct(3, 0))
        self.assertEqual(_pct(0, 8), 0.0)
        self.assertEqual(_pct(1, 3), 33.3)
        self.assertEqual(_pct(8, 8), 100.0)


class TestComposeHostnamesAreUnambiguous(unittest.TestCase):
    """The dev stack must never address its own database as plain ``db``.

    compose.admin.yaml puts the dev web container on the prod network as well,
    and both projects have a service called ``db``. With the bare name the
    winner is whichever DNS answer arrives first -- which silently pointed the
    dev app at the friends database for half a day, where it read someone
    else's rows and showed the user an empty app. A unique alias exists on one
    network only and cannot be confused.
    """

    def test_dev_database_is_addressed_by_a_unique_alias(self) -> None:
        compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
        self.assertIn("wcda-dev-db", compose)
        self.assertNotIn("@db:5432", compose)
        self.assertNotIn("POSTGRES_HOST: db\n", compose)

    def test_the_overlay_still_only_touches_web(self) -> None:
        # Attaching db or db-backup to the prod network would put a second
        # `db` on their own network too.
        overlay = (ROOT / "compose.admin.yaml").read_text(encoding="utf-8")
        services, in_services = [], False
        for line in overlay.splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if not line.startswith(" "):  # a top-level key ends the block
                in_services = line.startswith("services:")
                continue
            if in_services and line.startswith("  ") and not line.startswith("   "):
                services.append(line.strip().rstrip(":"))
        self.assertEqual(services, ["web"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
