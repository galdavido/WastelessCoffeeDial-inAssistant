"""Closed-loop tests of the correction policy against the simulator.

These run in CI with no database and no network, which is the point: the
engine's behaviour is verifiable today, on a user with zero logged shots.

The two that matter most:
  * test_converges_into_the_band -- the loop actually dials a shot in.
  * test_never_goes_finer_in_the_channeling_regime -- it refuses the reflex
    ("ran long? grind finer") that the old prompt hardcoded and that
    docs/science.md#cameron shows makes things worse.
"""

from __future__ import annotations

import random
import unittest

from core.brewing import (
    GrinderCaps,
    MachineCaps,
    Recipe,
    ShotRecord,
    apply_guardrails,
    beta_prior,
    brew_ratio,
    correct,
    finest_useful_clicks,
    is_finer,
    normalised_time,
    propose_dose_reduction,
    target_for,
)
from core.calibration import fit_setup, theil_sen_slope
from core.sim import BedParams, simulate_shot

K6 = GrinderCaps(
    min_clicks=0.0,
    max_clicks=90.0,
    step_clicks=1.0,
    um_per_click=16.0,
    finer_direction="lower_is_finer",
)
FIXED_TEMP_MACHINE = MachineCaps(basket_size_g=18.0, temp_controllable=False)
PID_MACHINE = MachineCaps(
    basket_size_g=18.0, temp_min_c=88.0, temp_max_c=98.0, temp_controllable=True
)
TARGET = target_for("espresso")


def _pull(clicks: float, dose_g: float = 18.0) -> ShotRecord:
    """Pull a simulated shot and package it as a measured log row."""
    bed = BedParams(dose_g=dose_g)
    sim = simulate_shot(clicks, K6, bed, target_yield_g=dose_g * 2.0)
    return ShotRecord(
        method="espresso",
        dose_g=dose_g,
        grind_clicks=clicks,
        yield_g=dose_g * 2.0,
        time_s=sim.time_s,
        taste_axis=sim.taste_axis,
        astringent=sim.taste_axis in ("bitter", "very_bitter"),
        rating=4 if sim.taste_axis == "balanced" else 2,
    )


class TestConvergence(unittest.TestCase):
    def _loop(self, start: float, max_iterations: int = 8) -> tuple[bool, float]:
        clicks = start
        beta = beta_prior("espresso", K6)
        for _ in range(max_iterations):
            shot = _pull(clicks)
            tr = normalised_time(shot)
            assert tr is not None and TARGET.tr_lo is not None
            if TARGET.tr_lo <= tr <= (TARGET.tr_hi or 0):
                return True, clicks
            recipe = correct(shot, TARGET, beta, K6, FIXED_TEMP_MACHINE)
            recipe = apply_guardrails(recipe, K6, FIXED_TEMP_MACHINE, [shot], TARGET)
            if recipe.grind_clicks is None or recipe.grind_clicks == clicks:
                break
            clicks = recipe.grind_clicks
        shot = _pull(clicks)
        tr = normalised_time(shot)
        assert tr is not None and TARGET.tr_lo is not None and TARGET.tr_hi is not None
        return (TARGET.tr_lo <= tr <= TARGET.tr_hi), clicks

    def test_converges_into_the_band(self) -> None:
        """From a spread of starting points, most runs land in target."""
        random.seed(20260905)
        starts = [random.uniform(31.0, 45.0) for _ in range(20)]
        landed = sum(1 for s in starts if self._loop(s)[0])
        self.assertGreaterEqual(
            landed,
            int(0.8 * len(starts)),
            f"only {landed}/{len(starts)} starting points converged",
        )

    def test_a_slow_shot_is_corrected_coarser(self) -> None:
        slow = _pull(31.0)  # runs long
        beta = beta_prior("espresso", K6)
        recipe = correct(slow, TARGET, beta, K6, FIXED_TEMP_MACHINE)
        assert recipe.grind_clicks is not None and slow.grind_clicks is not None
        self.assertFalse(is_finer(recipe.grind_clicks, slow.grind_clicks, K6))

    def test_a_fast_shot_is_corrected_finer(self) -> None:
        fast = _pull(42.0)  # gushes
        beta = beta_prior("espresso", K6)
        recipe = correct(fast, TARGET, beta, K6, FIXED_TEMP_MACHINE)
        assert recipe.grind_clicks is not None and fast.grind_clicks is not None
        self.assertTrue(is_finer(recipe.grind_clicks, fast.grind_clicks, K6))


class TestColdStart(unittest.TestCase):
    def test_starting_point_is_derived_not_the_hardware_midpoint(self) -> None:
        """The K6 spans 0-180 clicks; its midpoint is French press.

        300 um / 16 um-per-click ~= 19 clicks, which is a physical estimate
        and lands in the published espresso range.
        """
        from core.brewing import cold_start_clicks

        clicks = cold_start_clicks(K6, "espresso")
        assert clicks is not None
        self.assertAlmostEqual(clicks, 19.0, delta=1.0)
        self.assertNotAlmostEqual(clicks, 90.0, delta=10.0)

    def test_pourover_starts_coarser_than_espresso(self) -> None:
        from core.brewing import cold_start_clicks

        espresso = cold_start_clicks(K6, "espresso")
        pourover = cold_start_clicks(K6, "pourover")
        assert espresso is not None and pourover is not None
        self.assertGreater(pourover, espresso)

    def test_unknown_micron_per_click_means_abstain(self) -> None:
        """No way to locate the dial, so no number -- tier E."""
        from core.brewing import cold_start_clicks

        unknown = GrinderCaps(min_clicks=0.0, max_clicks=180.0, step_clicks=1.0)
        self.assertIsNone(cold_start_clicks(unknown, "espresso"))

    def test_moka_never_gets_a_derived_grind(self) -> None:
        from core.brewing import cold_start_clicks

        self.assertIsNone(cold_start_clicks(K6, "moka"))


class TestCameronGuardrail(unittest.TestCase):
    def test_finer_but_faster_history_sets_a_floor(self) -> None:
        # 26 clicks is finer than 30 but runs faster: channeling.
        history = [_pull(30.0), _pull(26.0)]
        limit = finest_useful_clicks(history, K6, TARGET)
        self.assertIsNotNone(limit.clicks)
        self.assertIsNotNone(limit.reason)

    def test_never_goes_finer_in_the_channeling_regime(self) -> None:
        """The reflex the old prompt encoded, refused.

        A long shot that still tastes sour is bypassing the puck. Grinding
        finer there makes extraction worse, so the engine must not.
        """
        history = [_pull(30.0), _pull(26.0), _pull(24.0)]
        beta = beta_prior("espresso", K6)
        last = history[-1]
        recipe = correct(last, TARGET, beta, K6, FIXED_TEMP_MACHINE)
        guarded = apply_guardrails(recipe, K6, FIXED_TEMP_MACHINE, history, TARGET)
        if guarded.grind_clicks is not None and last.grind_clicks is not None:
            self.assertFalse(
                is_finer(guarded.grind_clicks, last.grind_clicks, K6),
                "engine tried to grind finer inside the channeling regime",
            )

    def test_long_and_sour_blocks_finer(self) -> None:
        long_sour = ShotRecord(
            method="espresso",
            dose_g=18.0,
            grind_clicks=28.0,
            yield_g=36.0,
            time_s=45.0,
            taste_axis="sour",
        )
        limit = finest_useful_clicks([long_sour], K6, TARGET)
        self.assertEqual(limit.clicks, 28.0)

    def test_hardware_floor_is_respected(self) -> None:
        tight = GrinderCaps(
            min_clicks=30.0, max_clicks=40.0, step_clicks=1.0, um_per_click=16.0
        )
        recipe = Recipe(method="espresso", dose_g=18.0, grind_clicks=10.0)
        guarded = apply_guardrails(recipe, tight, FIXED_TEMP_MACHINE, [], TARGET)
        self.assertEqual(guarded.grind_clicks, 30.0)
        self.assertIn("grind_hardware_min", guarded.guardrails_hit)

    def test_dose_reduction_is_the_cameron_move(self) -> None:
        reduced, message = propose_dose_reduction(20.0)
        self.assertEqual(reduced, 16.0)  # 20% less, as in the paper
        self.assertIn("coarser", message)


class TestTastePolicy(unittest.TestCase):
    def _on_target_shot(self, **overrides: object) -> ShotRecord:
        base = {
            "method": "espresso",
            "dose_g": 18.0,
            "grind_clicks": 33.0,
            "yield_g": 36.0,
            "time_s": 28.0,
        }
        base.update(overrides)
        return ShotRecord(**base)  # type: ignore[arg-type]

    def test_bitter_without_astringency_does_not_touch_the_grind(self) -> None:
        """The most common false correction in dial-in advice."""
        shot = self._on_target_shot(taste_axis="bitter", astringent=False)
        recipe = correct(
            shot, TARGET, beta_prior("espresso", K6), K6, FIXED_TEMP_MACHINE
        )
        self.assertEqual(recipe.grind_clicks, shot.grind_clicks)
        assert recipe.yield_g is not None
        self.assertLess(recipe.yield_g, 36.0, "expected a shorter ratio instead")

    def test_bitter_and_astringent_is_treated_as_over_extraction(self) -> None:
        shot = self._on_target_shot(taste_axis="bitter", astringent=True)
        recipe = correct(shot, TARGET, beta_prior("espresso", K6), K6, PID_MACHINE)
        assert recipe.brew_temp_c is not None
        self.assertLess(recipe.brew_temp_c, 94.0)

    def test_sour_on_a_fixed_temp_machine_lengthens_the_ratio(self) -> None:
        shot = self._on_target_shot(taste_axis="sour")
        recipe = correct(
            shot, TARGET, beta_prior("espresso", K6), K6, FIXED_TEMP_MACHINE
        )
        assert recipe.yield_g is not None
        self.assertGreater(recipe.yield_g, 36.0)
        self.assertIsNone(recipe.brew_temp_c)

    def test_fixed_temp_machines_never_get_temperature_advice(self) -> None:
        recipe = Recipe(method="espresso", dose_g=18.0, brew_temp_c=93.0)
        guarded = apply_guardrails(recipe, K6, FIXED_TEMP_MACHINE, [], TARGET)
        self.assertIsNone(guarded.brew_temp_c)
        self.assertIn("temp_not_controllable", guarded.guardrails_hit)


class TestGuardrailInvariants(unittest.TestCase):
    def test_output_never_escapes_hardware_bounds(self) -> None:
        random.seed(7)
        for _ in range(200):
            recipe = Recipe(
                method="espresso",
                dose_g=random.uniform(5.0, 40.0),
                grind_clicks=random.uniform(-50.0, 150.0),
                yield_g=random.uniform(0.0, 200.0),
                brew_temp_c=random.uniform(60.0, 120.0),
            )
            guarded = apply_guardrails(recipe, K6, PID_MACHINE, [], TARGET)
            assert guarded.grind_clicks is not None
            self.assertGreaterEqual(guarded.grind_clicks, 0.0)
            self.assertLessEqual(guarded.grind_clicks, 90.0)
            self.assertGreaterEqual(guarded.dose_g, 18.0 * 0.75)
            self.assertLessEqual(guarded.dose_g, 18.0 * 1.05)
            assert guarded.brew_temp_c is not None
            self.assertGreaterEqual(guarded.brew_temp_c, 88.0)
            self.assertLessEqual(guarded.brew_temp_c, 98.0)

    def test_a_beverage_lighter_than_the_dose_is_pulled_back_into_band(self) -> None:
        # 9 g out of an 18 g dose is a 1:0.5 ratio -- physically possible but
        # far outside any espresso band, so it gets clamped to the band edge
        # rather than passed through.
        recipe = Recipe(method="espresso", dose_g=18.0, yield_g=9.0)
        guarded = apply_guardrails(recipe, K6, PID_MACHINE, [], TARGET)
        self.assertIn("ratio_out_of_band", guarded.guardrails_hit)
        assert guarded.yield_g is not None
        self.assertGreater(guarded.yield_g, guarded.dose_g)
        self.assertAlmostEqual(
            guarded.yield_g / guarded.dose_g, TARGET.ratio_lo, places=2
        )

    def test_numeric_tokens_cover_every_recommended_number(self) -> None:
        recipe = Recipe(
            method="espresso",
            dose_g=18.0,
            grind_clicks=33.0,
            yield_g=36.0,
            target_time_s=28.0,
        )
        tokens = recipe.numeric_tokens()
        for expected in ("18", "33", "36", "28"):
            self.assertIn(expected, tokens)


class TestCalibration(unittest.TestCase):
    def test_no_data_means_pure_prior(self) -> None:
        """The default path for a user who has logged nothing."""
        fit = fit_setup([], "espresso", K6, beta_prior("espresso", K6))
        self.assertEqual(fit.beta_source, "prior")
        self.assertEqual(fit.confidence, 0.0)
        self.assertEqual(fit.beta, beta_prior("espresso", K6))

    def test_repeat_shots_at_one_setting_do_not_build_confidence(self) -> None:
        shots = [_pull(33.0) for _ in range(10)]
        fit = fit_setup(shots, "espresso", K6, beta_prior("espresso", K6))
        self.assertEqual(fit.n_eff, 1)
        self.assertEqual(fit.beta_source, "prior")

    def test_theil_sen_recovers_the_simulator_slope(self) -> None:
        shots = [_pull(float(c)) for c in (31, 33, 35, 37, 39, 41, 43, 45)]
        fit = fit_setup(shots, "espresso", K6, beta_prior("espresso", K6))
        self.assertEqual(fit.beta_source, "shrunk")
        assert fit.beta is not None
        # Slope must at least have the right sign and sane magnitude.
        self.assertLess(fit.beta, 0.0)
        self.assertLess(abs(fit.beta), 0.5)

    def test_theil_sen_tolerates_one_bad_measurement(self) -> None:
        clean = [(float(c), -0.1 * c) for c in range(30, 40)]
        slope_clean = theil_sen_slope(clean)
        corrupted = [*clean, (35.0, 99.0)]  # a mis-logged shot
        slope_corrupted = theil_sen_slope(corrupted)
        assert slope_clean is not None and slope_corrupted is not None
        self.assertAlmostEqual(slope_clean, slope_corrupted, places=2)

    def test_moka_has_no_grind_law_to_fit(self) -> None:
        fit = fit_setup([], "moka", K6, None)
        self.assertIsNone(fit.beta)
        self.assertEqual(fit.beta_source, "none")


class TestMethodAwareness(unittest.TestCase):
    def test_moka_recipe_declares_no_target_time(self) -> None:
        shot = ShotRecord(
            method="moka", dose_g=15.0, water_g=120.0, time_s=300.0, grind_clicks=45.0
        )
        recipe = correct(shot, target_for("moka"), None, K6, FIXED_TEMP_MACHINE)
        self.assertIsNone(recipe.target_time_s)

    def test_pourover_ratio_uses_water_in(self) -> None:
        shot = ShotRecord(
            method="pourover",
            dose_g=15.0,
            water_g=240.0,
            time_s=180.0,
            grind_clicks=60.0,
        )
        self.assertAlmostEqual(brew_ratio(shot) or 0.0, 16.0)
        recipe = correct(
            shot,
            target_for("pourover"),
            beta_prior("pourover", K6),
            K6,
            FIXED_TEMP_MACHINE,
        )
        self.assertIsNotNone(recipe.water_g)
        self.assertIsNone(recipe.yield_g)


class TestDose(unittest.TestCase):
    """The dose the user asks for is the dose the recipe is for."""

    SHOT = ShotRecord(
        method="espresso",
        dose_g=18.0,
        grind_clicks=30.0,
        yield_g=36.0,
        time_s=27.0,
        taste_axis="balanced",
    )
    NO_BASKET = MachineCaps(basket_size_g=None, temp_controllable=False)

    def test_without_a_request_the_coffee_keeps_its_own_dose(self) -> None:
        recipe = correct(self.SHOT, TARGET, beta_prior("espresso", K6), K6, PID_MACHINE)
        self.assertEqual(recipe.dose_g, 18.0)
        self.assertEqual(recipe.yield_g, 36.0)

    def test_a_requested_dose_is_honoured_and_the_ratio_kept(self) -> None:
        """Regression: the dose field was ignored once a coffee had a shot."""
        recipe = correct(
            self.SHOT,
            TARGET,
            beta_prior("espresso", K6),
            K6,
            self.NO_BASKET,
            dose_g=20.0,
        )
        self.assertEqual(recipe.dose_g, 20.0)
        self.assertEqual(recipe.yield_g, 40.0)
        self.assertTrue(
            any("changed the dose" in note for note in recipe.notes),
            "the grind is still solved at the old dose, and the user must be told",
        )

    def test_espresso_without_a_basket_is_held_to_a_plausible_dose(self) -> None:
        recipe = Recipe(method="espresso", dose_g=30.0, yield_g=60.0)
        guarded = apply_guardrails(recipe, K6, self.NO_BASKET, [], TARGET)
        self.assertEqual(guarded.dose_g, 22.0)
        self.assertIn("dose_plausible_range", guarded.guardrails_hit)
        assert guarded.yield_g is not None
        self.assertAlmostEqual(guarded.yield_g / guarded.dose_g, 2.0, places=2)

    def test_pourover_and_moka_doses_are_not_clamped_to_an_espresso_basket(
        self,
    ) -> None:
        """Regression: a 30 g pour-over came back as 22 g at about 1:22."""
        for method, dose, water in (("pourover", 30.0, 480.0), ("moka", 28.0, 224.0)):
            recipe = Recipe(method=method, dose_g=dose, water_g=water)  # type: ignore[arg-type]
            guarded = apply_guardrails(
                recipe,
                K6,
                self.NO_BASKET,
                [],
                target_for(method),  # type: ignore[arg-type]
            )
            self.assertEqual(guarded.dose_g, dose, method)
            self.assertEqual(guarded.water_g, water, method)
            self.assertEqual(guarded.guardrails_hit, (), method)

    def test_a_basket_clamp_scales_the_water_too(self) -> None:
        moka_funnel = MachineCaps(basket_size_g=15.0)
        recipe = Recipe(method="moka", dose_g=20.0, water_g=160.0)
        guarded = apply_guardrails(recipe, K6, moka_funnel, [], target_for("moka"))
        self.assertIn("dose_basket_capacity", guarded.guardrails_hit)
        assert guarded.water_g is not None
        self.assertAlmostEqual(guarded.water_g / guarded.dose_g, 8.0, places=1)


if __name__ == "__main__":
    unittest.main()
