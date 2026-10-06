"""`wcda-backtest` against a real (disposable) database, read-only."""

from __future__ import annotations

import contextlib
import io
import unittest
from unittest.mock import patch

from sqlalchemy.orm import Session

from _db import Seeded, require_database
from core import backtest_cli


def run_cli(*argv: str) -> tuple[int | str | None, str]:
    """Run cli() as the shell would; return (exit code, stdout)."""
    out = io.StringIO()
    code: int | str | None = None
    with (
        patch("sys.argv", ["wcda-backtest", *argv]),
        contextlib.redirect_stdout(out),
    ):
        try:
            backtest_cli.cli()
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue()


class TestBacktestCli(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        require_database()

    def test_a_sparse_history_exits_zero_with_every_metric_insufficient(self) -> None:
        seeded = Seeded()
        seeded.add_shot()
        seeded.add_shot()

        code, out = run_cli("--owner", seeded.owner)

        self.assertEqual(code, 0)
        self.assertIn("Seeded  [espresso]  -- 2 measured shots", out)
        metrics = [line for line in out.splitlines() if "INSUFFICIENT DATA (n=" in line]
        self.assertGreaterEqual(len(metrics), 2)
        self.assertEqual(len(metrics), len({line.split(":")[0] for line in metrics}))
        self.assertIn("Metrics marked INSUFFICIENT DATA need more logged shots", out)

    def test_only_measured_shots_are_counted(self) -> None:
        seeded = Seeded()
        seeded.add_shot()
        seeded.add_shot(data_quality="synthetic")
        seeded.add_shot(time_s=None)

        _, out = run_cli("--owner", seeded.owner)

        self.assertIn("-- 1 measured shots", out)

    def test_an_owner_with_no_setups_exits_one(self) -> None:
        code, out = run_cli("--owner", "  Nobody-Here@Example.com ")

        self.assertEqual(code, 1)
        self.assertIn("'nobody-here@example.com'", out)

    def test_another_owners_setup_id_is_refused(self) -> None:
        mine, theirs = Seeded(), Seeded()

        code, out = run_cli("--owner", mine.owner, "--setup-id", str(theirs.setup_id))

        self.assertEqual(code, 1)
        self.assertNotIn("Seeded", out)

    def test_setup_id_limits_the_report_to_that_setup(self) -> None:
        seeded = Seeded()
        seeded.add_shot()

        code, out = run_cli("--owner", seeded.owner, "--setup-id", str(seeded.setup_id))

        self.assertEqual(code, 0)
        self.assertEqual(out.count("-- 1 measured shots"), 1)

    def test_a_grinder_without_a_range_says_the_engine_abstains(self) -> None:
        # Seeded equipment records no click range.
        seeded = Seeded()

        _, out = run_cli("--owner", seeded.owner)

        self.assertIn("abstains from naming a grind setting", out)

    def test_it_writes_nothing(self) -> None:
        seeded = Seeded()
        seeded.add_shot()
        with (
            patch.object(Session, "commit") as commit,
            patch.object(Session, "add") as add,
            patch.object(Session, "delete") as delete,
            patch.object(Session, "flush") as flush,
        ):
            code, _ = run_cli("--owner", seeded.owner)

        self.assertEqual(code, 0)
        for call in (commit, add, delete, flush):
            call.assert_not_called()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
