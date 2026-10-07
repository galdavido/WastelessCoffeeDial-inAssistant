"""engine.py's own decisions, apart from the brewing maths it calls.

The first-shot branch is exercised with no history, so the bean-feature
lookup never reaches a database and these stay pure.
"""

from __future__ import annotations

import unittest
from datetime import date, timedelta
from types import SimpleNamespace

from _fixtures import K6, MACHINE_18G
from core.brewing import beta_prior, fresh_note, target_for, value_of
from core.calibration import fit_setup
from core.engine import _first_shot_recipe

TARGET = target_for("espresso")


def _first_shot(days: int | None) -> tuple:
    calibration = fit_setup([], "espresso", K6, beta_prior("espresso", K6))
    bean = SimpleNamespace(
        id=1,
        roast_level_ord=3,
        process="Washed",
        origin="Kenya",
        roast_date=None if days is None else date.today() - timedelta(days=days),
    )
    return _first_shot_recipe(
        None,  # type: ignore[arg-type]
        "owner",
        "espresso",
        TARGET,
        K6,
        MACHINE_18G,
        calibration,
        bean,  # type: ignore[arg-type]
        days,
        18.0,
    )


class TestFirstShotOnFreshCoffee(unittest.TestCase):
    """docs/science.md#fresh-band: the warning holds on a first shot too."""

    def test_a_fresh_coffee_is_warned_about(self) -> None:
        recipe, basis, _ = _first_shot(3)
        self.assertEqual(basis, "prior")
        self.assertIn(fresh_note(3), recipe.notes)

    def test_a_rested_or_undated_coffee_is_not(self) -> None:
        rested = int(value_of("degas_rest_days"))
        for days in (rested, 20, None):
            recipe, _, _ = _first_shot(days)
            self.assertFalse(
                any("days off roast" in note for note in recipe.notes), days
            )

    def test_the_warning_changes_no_number(self) -> None:
        fresh, _, _ = _first_shot(3)
        rested, _, _ = _first_shot(20)
        self.assertEqual(fresh.grind_clicks, rested.grind_clicks)
        self.assertEqual(fresh.dose_g, rested.dose_g)
        self.assertEqual(fresh.yield_g, rested.yield_g)


if __name__ == "__main__":
    unittest.main()
