"""Admin dashboard wiring and usage aggregates.

The wiring tests need no database: they check that it is mounted only where it
is configured, and that the token gate is closed by default. The aggregate
tests run against the disposable Postgres (skipped locally without one).

The dashboard reads *another* instance's database and the dev instance it runs
on has no identity of its own, so "absent unless deliberately switched on" is
the security property worth pinning down in a test.
"""

from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from _db import Seeded, require_database
from core.admin_db import admin_enabled
from core.admin_routes import register_admin_routes
from core.admin_stats import (
    _pct,
    dashboard,
    feature_usage,
    fleet_summary,
    method_mix,
    per_owner,
    weekly_activity,
)
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


class TestAdminStatsAgainstTheDatabase(unittest.TestCase):
    """The aggregates, run for real.

    The dashboard is deliberately an all-users view -- it reads the friends
    database to show how much each person uses the app -- so there is no owner
    it must *not* select across. What has to hold is that each person's row
    counts only their own shots, and that the fleet numbers are the sum of
    them. Every test seeds fresh owners, and fleet figures are compared as
    before/after deltas because the database is shared with other tests.
    """

    DAYS = 30

    @classmethod
    def setUpClass(cls) -> None:
        require_database()

    def people(self) -> dict[str, dict[str, Any]]:
        from database.database import SessionLocal

        with SessionLocal() as db:
            return {row["owner"]: row for row in per_owner(db, self.DAYS)}

    def summary(self) -> dict[str, Any]:
        from database.database import SessionLocal

        with SessionLocal() as db:
            return fleet_summary(db, self.DAYS)

    def test_each_person_is_counted_only_for_their_own_shots(self) -> None:
        busy, quiet = Seeded(), Seeded()
        rec = busy.add_recommendation()
        busy.add_shot(recommendation_id=rec)
        busy.add_shot(preinfusion_s=5)
        busy.add_shot()
        quiet.add_shot()

        people = self.people()

        self.assertEqual(people[busy.owner]["shots"], 3)
        self.assertEqual(people[busy.owner]["recommendations"], 1)
        self.assertEqual(people[busy.owner]["coffees"], 1)
        self.assertEqual(people[busy.owner]["timer_pct"], 33.3)
        self.assertEqual(people[busy.owner]["follow_through_pct"], 100.0)
        self.assertEqual(people[quiet.owner]["shots"], 1)
        self.assertEqual(people[quiet.owner]["recommendations"], 0)
        self.assertEqual(people[quiet.owner]["follow_through_pct"], None)
        self.assertEqual(people[quiet.owner]["timer_pct"], 0.0)

    def test_the_table_is_ordered_busiest_first(self) -> None:
        busy, quiet = Seeded(), Seeded()
        for _ in range(3):
            busy.add_shot()
        quiet.add_shot()

        owners = [row["owner"] for row in self.people().values()]

        self.assertLess(owners.index(busy.owner), owners.index(quiet.owner))

    def test_someone_who_asked_but_never_logged_still_appears(self) -> None:
        lurker = Seeded()
        lurker.add_recommendation()

        row = self.people()[lurker.owner]

        self.assertEqual(row["shots"], 0)
        self.assertEqual(row["recommendations"], 1)
        self.assertEqual(row["follow_through_pct"], 0.0)
        self.assertIsNone(row["last_seen"])

    def test_shots_outside_the_window_are_left_out(self) -> None:
        old = Seeded()
        old.add_shot(created_at=datetime.now(UTC) - timedelta(days=self.DAYS + 5))

        self.assertNotIn(old.owner, self.people())

    def test_a_persons_weekly_sparkline_sums_to_their_shots(self) -> None:
        seeded = Seeded()
        for days_ago in (0, 0, 8):
            seeded.add_shot(created_at=datetime.now(UTC) - timedelta(days=days_ago))

        row = self.people()[seeded.owner]

        self.assertEqual(sum(row["weekly"].values()), 3)
        self.assertEqual(row["active_days"], 2)

    def test_the_fleet_summary_grows_by_exactly_what_was_added(self) -> None:
        before = self.summary()
        seeded = Seeded()
        rec = seeded.add_recommendation()
        seeded.add_recommendation()
        seeded.add_shot(recommendation_id=rec)
        seeded.add_shot()
        after = self.summary()

        self.assertEqual(after["shots"] - before["shots"], 2)
        self.assertEqual(after["recommendations"] - before["recommendations"], 2)
        self.assertGreaterEqual(after["owners_total"], before["owners_total"] + 1)
        self.assertGreaterEqual(after["active_7d"], before["active_7d"] + 1)
        self.assertEqual(after["days"], self.DAYS)

    def test_a_previous_window_with_shots_gives_a_percentage_change(self) -> None:
        seeded = Seeded()
        seeded.add_shot(created_at=datetime.now(UTC) - timedelta(days=45))
        seeded.add_shot()

        self.assertIsInstance(self.summary()["shots_change_pct"], float)

    def test_method_mix_counts_each_method_and_names_unspecified(self) -> None:
        from database.database import SessionLocal

        def mix() -> dict[str, int]:
            with SessionLocal() as db:
                return {m["method"]: m["shots"] for m in method_mix(db, self.DAYS)}

        before = mix()
        seeded = Seeded()
        seeded.add_shot(brew_method="moka")
        seeded.add_shot(brew_method="moka")
        seeded.add_shot(brew_method=None)
        after = mix()

        self.assertEqual(after.get("moka", 0) - before.get("moka", 0), 2)
        self.assertEqual(after.get("unspecified", 0) - before.get("unspecified", 0), 1)
        with SessionLocal() as db:
            shares = [m["share_pct"] for m in method_mix(db, self.DAYS)]
        self.assertAlmostEqual(sum(shares), 100.0, delta=0.6)

    def test_weekly_activity_puts_this_weeks_shots_in_this_week(self) -> None:
        from database.database import SessionLocal

        def this_week() -> dict[str, int]:
            with SessionLocal() as db:
                return weekly_activity(db, weeks=2)[-1]

        before = this_week()
        seeded = Seeded()
        seeded.add_recommendation()
        seeded.add_shot()
        after = this_week()

        self.assertEqual(after["week"], before["week"])
        self.assertEqual(after["shots"] - before["shots"], 1)
        self.assertEqual(after["recommendations"] - before["recommendations"], 1)
        self.assertGreaterEqual(after["people"], 1)

    def test_feature_usage_reports_shares_between_zero_and_a_hundred(self) -> None:
        from database.database import SessionLocal

        seeded = Seeded()
        seeded.add_shot(preinfusion_s=4, image_path="a.jpg")
        seeded.add_shot(yield_g=None)

        with SessionLocal() as db:
            usage = feature_usage(db, self.DAYS)

        self.assertEqual(
            set(usage), {"timer_pct", "measured_pct", "from_recipe_pct", "scanned_pct"}
        )
        for name, value in usage.items():
            self.assertIsNotNone(value, name)
            self.assertTrue(0.0 <= value <= 100.0, (name, value))

    def test_the_dashboard_bundles_every_section(self) -> None:
        from database.database import SessionLocal

        with SessionLocal() as db:
            data = dashboard(db, self.DAYS)

        self.assertEqual(
            set(data),
            {"summary", "weekly", "methods", "usage", "people", "generated_at"},
        )

    def test_no_section_carries_what_a_person_drinks(self) -> None:
        # Activity only, never content: no bean names, notes or ratings.
        from database.database import SessionLocal

        seeded = Seeded()
        seeded.add_shot(tasting_notes="SECRET-NOTE", rating=5)
        with SessionLocal() as db:
            blob = repr(dashboard(db, self.DAYS))

        self.assertNotIn("SECRET-NOTE", blob)


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
