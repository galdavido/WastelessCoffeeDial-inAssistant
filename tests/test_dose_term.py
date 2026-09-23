"""The grind law's dose term, docs/science.md#dose-term.

Checked against the simulator, whose bed model is Darcy at a fixed pressure
with bed depth proportional to dose -- the same physics the prior comes from,
so a fit on simulated shots should recover it.
"""

from __future__ import annotations

import math
import unittest
from dataclasses import replace

from _sim import BedParams, simulate_shot
from core.brewing import (
    GrinderCaps,
    MachineCaps,
    ShotRecord,
    beta_prior,
    clicks_for_target,
    correct,
    dose_log,
    is_finer,
    normalised_time,
    target_for,
    value_of,
)
from core.calibration import bean_offsets, fit_gamma, fit_setup

K6 = GrinderCaps(
    min_clicks=0.0,
    max_clicks=90.0,
    step_clicks=1.0,
    um_per_click=16.0,
    finer_direction="lower_is_finer",
)
MACHINE = MachineCaps(basket_size_g=None, temp_controllable=False)
TARGET = target_for("espresso")
BETA = beta_prior("espresso", K6)


def _pull(clicks: float, dose_g: float, bean_id: int = 1) -> ShotRecord:
    sim = simulate_shot(clicks, K6, BedParams(dose_g=dose_g), dose_g * 2.0)
    return ShotRecord(
        method="espresso",
        dose_g=dose_g,
        bean_id=bean_id,
        grind_clicks=clicks,
        yield_g=dose_g * 2.0,
        time_s=sim.time_s,
        taste_axis="balanced",
    )


def _tr(shot: ShotRecord) -> float:
    tr = normalised_time(shot)
    assert tr is not None
    return tr


class TestThePrior(unittest.TestCase):
    def test_the_simulator_obeys_the_dose_squared_law(self) -> None:
        """If this fails the fixture changed, not the engine."""
        light, heavy = _pull(40.0, 16.0), _pull(40.0, 20.0)
        exponent = math.log(_tr(heavy) / _tr(light)) / math.log(20.0 / 16.0)
        self.assertAlmostEqual(exponent, value_of("dose_exponent_prior"), places=1)


class TestFittingGamma(unittest.TestCase):
    def test_it_recovers_the_exponent_from_mixed_doses_and_settings(self) -> None:
        # Dose varies within each setting. Had dose and grind always moved
        # together, any error in beta would pass straight into gamma -- the
        # confound science.md#dose-term says no fit can undo.
        shots = [
            _pull(clicks, dose)
            for clicks, dose in ((40.0, 16.0), (40.0, 19.0), (42.0, 17.0), (42.0, 20.0))
        ]
        gamma, fitted, weight, pairs = fit_gamma(shots, BETA or 0.0, 2.0)
        assert fitted is not None
        self.assertAlmostEqual(fitted, 2.0, delta=0.3)
        self.assertEqual(pairs, 6)
        self.assertGreater(weight, 0.5)

    def test_a_heavier_dose_that_ran_faster_is_discarded(self) -> None:
        a = _pull(40.0, 16.0)
        b = replace(_pull(40.0, 20.0), time_s=(a.time_s or 0) * 0.8)
        gamma, fitted, weight, _ = fit_gamma([a, b], BETA or 0.0, 2.0)
        self.assertIsNone(fitted)
        self.assertEqual((gamma, weight), (2.0, 0.0))

    def test_pairs_across_coffees_or_preparations_say_nothing(self) -> None:
        a = replace(_pull(40.0, 16.0, bean_id=1), preinfusion_s=0.0)
        b = _pull(40.0, 20.0, bean_id=2)
        c = replace(_pull(40.0, 20.0, bean_id=1), preinfusion_s=10.0)
        _, fitted, _, pairs = fit_gamma([a, b, c], BETA or 0.0, 2.0)
        self.assertIsNone(fitted)
        self.assertEqual(pairs, 0)

    def test_pour_over_and_moka_have_no_dose_term(self) -> None:
        shots = [_pull(c, d) for c, d in ((36.0, 16.0), (40.0, 18.0), (44.0, 20.0))]
        pourover = [replace(s, method="pourover", water_g=s.yield_g) for s in shots]
        calibration = fit_setup(
            pourover, "pourover", K6, beta_prior("pourover", K6), bean_id=1
        )
        self.assertEqual(calibration.gamma, 0.0)


class TestTheDoseNoLongerHidesInTheBeanOffset(unittest.TestCase):
    def test_two_identical_coffees_dosed_differently_get_the_same_offset(self) -> None:
        """The reference-history confound: one bag always 18 g, one always 16 g."""
        shots = [_pull(c, 18.0, bean_id=1) for c in (36.0, 39.0, 42.0)]
        shots += [_pull(c, 16.0, bean_id=2) for c in (36.0, 39.0, 42.0)]
        calibration = fit_setup(shots, "espresso", K6, BETA, bean_id=1)
        offsets = calibration.bean_offsets
        self.assertLess(abs(offsets[1] - offsets[2]), 0.02)

        # Without the term the same shots read the dose gap as a coffee gap.
        without = bean_offsets(shots, calibration.alpha, calibration.beta, 0.0)
        self.assertGreater(abs(without[1] - without[2]), 0.1)


class TestBedDepthNotGrams(unittest.TestCase):
    """A darker roast fills the basket at fewer grams: the owner's two coffees."""

    def test_a_basket_of_light_and_a_basket_of_dark_are_the_same_bed(self) -> None:
        light = dose_log(18.5, roast_level_ord=2)
        dark = dose_log(16.5, roast_level_ord=5)
        self.assertAlmostEqual(light, dark, delta=0.01)
        self.assertAlmostEqual(dose_log(18.0), 0.0)  # unknown roast: grams only

    def test_a_lighter_dark_roast_dose_is_not_read_as_a_coffee_difference(
        self,
    ) -> None:
        """Same coffee behaviour; the dark one is less dense and dosed to fill."""
        light_bed = BedParams(dose_g=18.5)
        dark_bed = BedParams(
            dose_g=16.5, bulk_density_kg_m3=light_bed.bulk_density_kg_m3 * 16.5 / 18.5
        )
        shots = []
        for bean_id, roast, bed in ((1, 2, light_bed), (2, 5, dark_bed)):
            for clicks in (36.0, 39.0, 42.0):
                sim = simulate_shot(clicks, K6, bed, bed.dose_g * 2.0)
                shots.append(
                    ShotRecord(
                        method="espresso",
                        dose_g=bed.dose_g,
                        bean_id=bean_id,
                        grind_clicks=clicks,
                        yield_g=bed.dose_g * 2.0,
                        time_s=sim.time_s,
                        roast_level_ord=roast,
                    )
                )
        offsets = fit_setup(shots, "espresso", K6, BETA, bean_id=1).bean_offsets
        self.assertLess(abs(offsets[1] - offsets[2]), 0.03)

        # Reading grams as depth would call the dark coffee a faster one.
        grams_only = [replace(s, roast_level_ord=None) for s in shots]
        wrong = fit_setup(grams_only, "espresso", K6, BETA, bean_id=1).bean_offsets
        self.assertGreater(abs(wrong[1] - wrong[2]), 0.05)

    def test_a_new_dark_coffee_differs_only_by_its_smaller_drink(self) -> None:
        """Same depth, so no Darcy difference -- but 16.5 g at 1:2 is a smaller
        drink than 18.5 g, which takes less time. Only that is left."""
        light = clicks_for_target(
            1.0, -0.1, 14.0, gamma=2.0, dose_g=18.5, roast_level_ord=2
        )
        dark = clicks_for_target(
            1.0, -0.1, 14.0, gamma=2.0, dose_g=16.5, roast_level_ord=5
        )
        assert light is not None and dark is not None
        drink_only = math.log(16.5 / 18.5) / 0.1  # clicks, beta = -0.1
        self.assertAlmostEqual(dark - light, drink_only, delta=0.05)


class TestCorrectingForADoseChange(unittest.TestCase):
    def _in_band_setting(self, dose_g: float) -> ShotRecord:
        assert TARGET.tr_lo is not None and TARGET.tr_hi is not None
        centre = (TARGET.tr_lo + TARGET.tr_hi) / 2
        return min(
            (_pull(float(c), dose_g) for c in range(20, 70)),
            key=lambda s: abs(_tr(s) - centre),
        )

    def test_a_heavier_dose_grinds_coarser_and_lands_nearer_the_target(self) -> None:
        anchor = self._in_band_setting(18.0)
        assert anchor.grind_clicks is not None
        recipe = correct(anchor, TARGET, BETA, K6, MACHINE, dose_g=21.0, gamma=2.0)
        assert recipe.grind_clicks is not None
        self.assertTrue(is_finer(anchor.grind_clicks, recipe.grind_clicks, K6))
        self.assertTrue(any("at 21 g" in note for note in recipe.notes))

        assert TARGET.tr_lo is not None and TARGET.tr_hi is not None
        centre = (TARGET.tr_lo + TARGET.tr_hi) / 2
        moved = _tr(_pull(recipe.grind_clicks, 21.0))
        stayed = _tr(_pull(anchor.grind_clicks, 21.0))
        self.assertLess(abs(moved - centre), abs(stayed - centre))

    def test_without_a_dose_term_the_grind_stays_and_says_so(self) -> None:
        anchor = self._in_band_setting(18.0)
        recipe = correct(anchor, TARGET, BETA, K6, MACHINE, dose_g=21.0, gamma=0.0)
        self.assertEqual(recipe.grind_clicks, anchor.grind_clicks)
        self.assertTrue(any("still worked out" in note for note in recipe.notes))

    def test_the_same_dose_changes_nothing(self) -> None:
        anchor = self._in_band_setting(18.0)
        with_term = correct(anchor, TARGET, BETA, K6, MACHINE, gamma=2.0)
        without = correct(anchor, TARGET, BETA, K6, MACHINE, gamma=0.0)
        self.assertEqual(with_term, without)


class TestSolvingForANewCoffee(unittest.TestCase):
    def test_the_reference_dose_matches_the_law_without_a_dose(self) -> None:
        self.assertEqual(
            clicks_for_target(1.0, -0.1, 14.0, gamma=2.0, dose_g=18.0),
            clicks_for_target(1.0, -0.1, 14.0),
        )

    def test_a_heavier_first_dose_is_set_coarser(self) -> None:
        light = clicks_for_target(1.0, -0.1, 14.0, gamma=2.0, dose_g=16.0)
        heavy = clicks_for_target(1.0, -0.1, 14.0, gamma=2.0, dose_g=20.0)
        assert light is not None and heavy is not None
        # beta < 0 here means lower is finer, so coarser is a larger number.
        self.assertGreater(heavy, light)


if __name__ == "__main__":
    unittest.main()
