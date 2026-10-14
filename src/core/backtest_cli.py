"""`wcda-backtest`: run the eval harness against the real database.

Read-only. Prints a report and writes nothing.

On a database with no measured shots -- which is the state until the shot
log has been used a few dozen times -- every metric prints INSUFFICIENT DATA
and the command exits 0. That is the correct result, not a failure.

``--compare`` adds a side-by-side ln(T_r) score of the engine against simple
baselines and, when scikit-learn is installed (``pip install -e '.[ml]'``),
the statistical challengers in ``core.challengers``.
"""

from __future__ import annotations

import argparse

from database.database import SessionLocal
from database.models import BrewSetup

from .auth import single_user_owner
from .brewing import GrinderCaps, Method, target_for
from .engine import grinder_caps, machine_caps
from .eval_harness import backtest, compare_models
from .retrieval import fetch_calibration_shots, get_active_setup_method
from .time_models import (
    BeanMeanTimeModel,
    EngineTimeModel,
    PriorOnlyTimeModel,
    TimeModel,
)


def comparison_models(method: Method, caps: GrinderCaps) -> list[TimeModel]:
    """The engine, its baselines and -- if installed -- the challengers."""
    models: list[TimeModel] = [
        EngineTimeModel(method, caps),
        PriorOnlyTimeModel(method, caps),
        BeanMeanTimeModel(),
    ]
    try:
        from .challengers import challengers
    except ImportError:
        print(
            "  note: scikit-learn is not installed, so only the engine and its "
            "baselines are compared (pip install -e '.[ml]' adds the rest)."
        )
    else:
        models += challengers()
    return models


def run(
    setup_id: int | None = None, owner: str | None = None, compare: bool = False
) -> int:
    # Every row is owner-scoped, so the CLI needs an identity too. There is no
    # request to take one from: default to the single-user owner, which is who
    # this database belongs to on a `single` instance, and let --owner name a
    # different login when pointed at the multi-user database.
    owner = (owner or single_user_owner()).strip().lower()
    db = SessionLocal()
    try:
        setups = (
            [db.get(BrewSetup, setup_id)]
            if setup_id
            else db.query(BrewSetup).filter(BrewSetup.owner == owner).all()
        )
        setups = [s for s in setups if s is not None and s.owner == owner]
        if not setups:
            print(f"No brew setups found for owner {owner!r}.")
            return 1

        for setup in setups:
            method = get_active_setup_method(setup)
            caps = grinder_caps(setup.grinder)
            machine = machine_caps(setup.machine)
            shots = fetch_calibration_shots(db, owner, setup.id, method)

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
            if compare:
                print()
                models = comparison_models(method, caps)
                for scheme in ("loo", "walk_forward"):
                    print(compare_models(shots, models, scheme).render())
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
    parser.add_argument(
        "--owner",
        default=None,
        help="whose logs to back-test (default: the single-user owner)",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="also score the engine against baselines and statistical models",
    )
    args = parser.parse_args()
    raise SystemExit(run(args.setup_id, args.owner, args.compare))


if __name__ == "__main__":
    cli()
