"""The guard that keeps the DB tests off the live dev and prod databases."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from _db import refuse_live_database

PG = "postgresql+psycopg2://u:p@{}/barista_db"


class RefuseLiveDatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "WCDA_TESTS_ALLOW_LIVE_DB"}
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_dev_port_is_refused(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "localhost:5434"):
            refuse_live_database(PG.format("localhost:5434"))

    def test_live_hosts_are_refused(self) -> None:
        for host in ("wcda-dev-db:5432", "wcda-prod-db-1:5432", "db:5432"):
            with self.subTest(host=host), self.assertRaises(RuntimeError):
                refuse_live_database(PG.format(host))

    def test_disposable_database_is_allowed(self) -> None:
        refuse_live_database(PG.format("localhost:5432"))
        refuse_live_database(PG.format("localhost:5440"))

    def test_override_allows_live_database(self) -> None:
        os.environ["WCDA_TESTS_ALLOW_LIVE_DB"] = "1"
        refuse_live_database(PG.format("localhost:5434"))
