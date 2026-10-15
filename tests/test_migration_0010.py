"""Migration 0010 drops the brew-method and water columns, and refuses to
when there is data they would take with them.

Each test migrates a database of its own, created and dropped around it on
the server DATABASE_URL names, so the shared test database stays at head.
"""

from __future__ import annotations

import os
import unittest
import uuid

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from _db import refuse_live_database

DROPPED = {
    "brew_setups": ["method"],
    "dial_in_logs": ["brew_method", "water_g"],
    "recommendations": ["method", "water_g"],
}


@unittest.skipUnless(os.getenv("DATABASE_URL"), "needs DATABASE_URL")
class TestMigration0010(unittest.TestCase):
    def setUp(self) -> None:
        self.original = os.environ["DATABASE_URL"]
        refuse_live_database(self.original)
        self.name = f"wcda_mig_{uuid.uuid4().hex[:8]}"
        server = make_url(self.original)
        self.admin = create_engine(server, isolation_level="AUTOCOMMIT")
        with self.admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{self.name}"'))
        self.url = server.set(database=self.name)
        os.environ["DATABASE_URL"] = self.url.render_as_string(hide_password=False)
        self.engine = create_engine(self.url)

    def tearDown(self) -> None:
        os.environ["DATABASE_URL"] = self.original
        self.engine.dispose()
        with self.admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{self.name}"'))
        self.admin.dispose()

    def _migrate(self, direction: str, revision: str) -> None:
        from alembic import command

        from core.db_bootstrap import _alembic_config

        getattr(command, direction)(_alembic_config(), revision)

    def _columns(self, table: str) -> dict[str, bool]:
        return {
            c["name"]: c["nullable"] for c in inspect(self.engine).get_columns(table)
        }

    def _version(self) -> str:
        with self.engine.connect() as conn:
            return conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()

    def _refused(self, insert: str, named: str) -> None:
        self._migrate("upgrade", "0009")
        with self.engine.begin() as conn:
            conn.execute(text(insert))
        with self.assertRaises(RuntimeError) as caught:
            self._migrate("upgrade", "head")
        self.assertIn(named, str(caught.exception))
        self.assertEqual(self._version(), "0009")
        self.assertIn("method", self._columns("brew_setups"))

    def test_refuses_when_non_espresso_equipment_exists(self) -> None:
        self._refused(
            "INSERT INTO equipment (type, brand, model) VALUES ('filter', 'x', 'y')",
            "equipment.type",
        )

    def test_refuses_on_water_g(self) -> None:
        self._refused(
            "INSERT INTO recommendations (owner, engine_version, water_g) "
            "VALUES ('me', 'test', 250.0)",
            "recommendations.water_g",
        )

    def _setup_rows(self, *methods: str | None) -> None:
        """A grinder, an espresso machine, and one setup per method on them."""
        with self.engine.begin() as conn:
            ids = [
                conn.execute(
                    text(
                        "INSERT INTO equipment (type, brand, model) "
                        "VALUES (:type, 'x', 'y') RETURNING id"
                    ),
                    {"type": kind},
                ).scalar_one()
                for kind in ("grinder", "espresso_machine")
            ]
            for method in methods:
                conn.execute(
                    text(
                        "INSERT INTO brew_setups "
                        "(owner, name, grinder_id, machine_id, method) "
                        "VALUES ('me', 's', :g, :m, :method)"
                    ),
                    {"g": ids[0], "m": ids[1], "method": method},
                )

    def test_espresso_and_unset_methods_pass(self) -> None:
        """What the live databases hold: the guard must let it through."""
        self._migrate("upgrade", "0009")
        self._setup_rows(None, "espresso")
        self._migrate("upgrade", "head")
        self.assertEqual(self._version(), "0010")

    def test_refuses_on_a_non_espresso_method(self) -> None:
        self._migrate("upgrade", "0009")
        self._setup_rows(None, "pourover")
        with self.assertRaises(RuntimeError) as caught:
            self._migrate("upgrade", "head")
        self.assertIn("brew_setups.method=1", str(caught.exception))
        self.assertEqual(self._version(), "0009")

    def test_upgrade_drops_and_downgrade_restores(self) -> None:
        self._migrate("upgrade", "head")
        for table, columns in DROPPED.items():
            present = self._columns(table)
            for column in columns:
                self.assertNotIn(column, present, f"{table}.{column}")

        self._migrate("downgrade", "0009")
        for table, columns in DROPPED.items():
            present = self._columns(table)
            for column in columns:
                self.assertTrue(present.get(column), f"{table}.{column} nullable")
        checks = {
            table: {
                c["name"] for c in inspect(self.engine).get_check_constraints(table)
            }
            for table in ("brew_setups", "dial_in_logs")
        }
        self.assertIn("ck_brew_setups_method", checks["brew_setups"])
        self.assertIn("ck_dial_in_logs_brew_method", checks["dial_in_logs"])


if __name__ == "__main__":
    unittest.main()
