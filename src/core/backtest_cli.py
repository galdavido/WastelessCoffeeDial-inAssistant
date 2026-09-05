"""`wcda-backtest`: run the eval harness against the real database.

Read-only. Prints a report and writes nothing.

On a database with no measured shots -- which is the state until the shot
log has been used a few dozen times -- every metric prints INSUFFICIENT DATA
and the command exits 0. That is the correct result, not a failure.
"""

from __future__ import annotations

import argparse

from database.database import SessionLocal
from database.models import BrewSetup

from .brewing import target_for
from .engine import _grinder_caps, _machine_caps
from .eval_harness import backtest
from .retrieval import fetch_calibration_shots, get_active_setup_method


def run(setup_id: int | None = None) -> int:
    db = SessionLocal()
    try:
        setups = (
            [db.get(BrewSetup, setup_id)] if setup_id else db.query(BrewSetup).all()
        )
        setups = [s for s in setups if s is not None]
        if not setups:
            print("No brew setups found.")
            return 1

        for setup in setups:
            method = get_active_setup_method(setup)
            caps = _grinder_caps(setup.grinder)
            machine = _machine_caps(setup.machine)
            shots = fetch_calibration_shots(db, setup.id, method)

            print("=" * 60)
            print(f"{setup.name}  [{method}]  -- {len(shots)} measured shots")
            print("=" * 60)
            if not caps.has_range:
                print(
                    "  note: this grinder has no recorded range, so the engine "
                    "abstains from naming a grind setting here."
                )
            report = backtest(shots, target_for(method), caps, machine, method)
            print(report.render())
            print()

        print(
            "Metrics marked INSUFFICIENT DATA need more logged shots. Each shot "
            "with a grind, a time and a weight counts toward them."
        )
        return 0
    finally:
        db.close()


def cli() -> None:
    parser = argparse.ArgumentParser(
        prog="wcda-backtest",
        description="Measure the recommendation engine against your own logs.",
    )
    parser.add_argument(
        "--setup-id", type=int, default=None, help="only back-test this setup"
    )
    args = parser.parse_args()
    raise SystemExit(run(args.setup_id))


if __name__ == "__main__":
    cli()
