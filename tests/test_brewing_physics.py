"""Physics and derived-metric tests for the brewing engine.

The headline test here is test_extraction_yield_peaks_then_declines: it checks
that the simulator reproduces the central experimental result of Cameron et
al. 2020 (docs/science.md#cameron), which is the finding the engine's
anti-channeling guardrail is built on. If that curve ever becomes monotonic,
the guardrail is testing nothing.
"""

from __future__ import annotations

import unittest

from _fixtures import K6
from _sim import BedParams, simulate_shot
from core.brewing import (
    GrinderCaps,
    ShotRecord,
    beta_prior,
    brew_ratio,
    normalised_time,
    snap_to_step,
    solve_grind,
    target_for,
    temp_band_for_roast,
)


class TestDerivedMetrics(unittest.TestCase):
    def test_espresso_ratio_uses_beverage_out(self) -> None:
        shot = ShotRecord(dose_g=18.0, yield_g=36.0, time_s=28)
        ratio = brew_ratio(shot)
        assert ratio is not None
        self.assertAlmostEqual(ratio, 2.0)

    def test_brew_ratio_is_yield_over_dose(self) -> None:
        self.assertEqual(brew_ratio(ShotRecord(dose_g=18.0, yield_g=36.0)), 2.0)
        self.assertIsNone(brew_ratio(ShotRecord(dose_g=18.0)))

    def test_normalised_time_matches_the_worked_example(self) -> None:
        # docs/science.md#normalised-time: 18 -> 36 g in 28 s is T_r = 14.
        shot = ShotRecord(dose_g=18.0, yield_g=36.0, time_s=28)
        tr = normalised_time(shot)
        assert tr is not None
        self.assertAlmostEqual(tr, 14.0)

    def test_normalised_time_is_comparable_across_ratios(self) -> None:
        # The whole point: same extraction rate, different ratios, same T_r.
        short = ShotRecord(dose_g=18.0, yield_g=27.0, time_s=21)
        long = ShotRecord(dose_g=18.0, yield_g=45.0, time_s=35)
        tr_short, tr_long = normalised_time(short), normalised_time(long)
        assert tr_short is not None and tr_long is not None
        self.assertAlmostEqual(tr_short, tr_long)

    def test_metrics_are_none_when_unmeasured(self) -> None:
        shot = ShotRecord(dose_g=18.0)
        self.assertIsNone(normalised_time(shot))
        self.assertIsNone(brew_ratio(shot))


class TestGrindLaw(unittest.TestCase):
    def test_beta_prior_for_a_known_grinder(self) -> None:
        # 2 * 16 / 300 = 0.1067, negative because higher clicks = coarser.
        beta = beta_prior(K6)
        assert beta is not None
        self.assertAlmostEqual(beta, -0.10667, places=4)

    def test_beta_prior_sign_follows_the_dial_direction(self) -> None:
        inverted = GrinderCaps(um_per_click=16.0, finer_direction="higher_is_finer")
        beta = beta_prior(inverted)
        assert beta is not None
        self.assertGreater(beta, 0)

    def test_solve_grind_goes_coarser_when_the_shot_runs_long(self) -> None:
        beta = beta_prior(K6)
        assert beta is not None
        # Observed T_r above target -> need a coarser (higher) setting.
        new = solve_grind(33.0, tr_observed=18.0, tr_target=14.0, beta=beta)
        self.assertGreater(new, 33.0)

    def test_solve_grind_goes_finer_when_the_shot_runs_fast(self) -> None:
        beta = beta_prior(K6)
        assert beta is not None
        new = solve_grind(33.0, tr_observed=10.0, tr_target=14.0, beta=beta)
        self.assertLess(new, 33.0)

    def test_solve_grind_round_trips(self) -> None:
        beta = beta_prior(K6)
        assert beta is not None
        # Moving to c* should, by construction, predict the target T_r.
        c_star = solve_grind(33.0, tr_observed=18.0, tr_target=14.0, beta=beta)
        import math

        predicted = 18.0 * math.exp(beta * (c_star - 33.0))
        self.assertAlmostEqual(predicted, 14.0, places=6)

    def test_snap_to_step(self) -> None:
        self.assertEqual(snap_to_step(33.4, K6), 33.0)
        half = GrinderCaps(step_clicks=0.5)
        self.assertEqual(snap_to_step(33.4, half), 33.5)


class TestTargets(unittest.TestCase):
    def test_one_espresso_target(self) -> None:
        t = target_for()
        self.assertEqual((t.ratio_lo, t.ratio_aim, t.ratio_hi), (1.8, 2.0, 2.5))
        self.assertEqual((t.time_lo, t.time_hi), (25.0, 30.0))
        self.assertEqual((t.temp_lo, t.temp_hi), (90.5, 96.0))


class TestRoastTimeModifier(unittest.TestCase):
    """docs/science.md#roast-time-modifier."""

    def _band(self, roast: int | None) -> tuple[float, float]:
        t = target_for(roast)
        return t.time_lo, t.time_hi

    def test_light_aims_longer_dark_shorter(self) -> None:
        self.assertEqual(self._band(1), (26.0, 31.0))
        self.assertEqual(self._band(2), (26.0, 31.0))
        self.assertEqual(self._band(4), (24.0, 29.0))
        self.assertEqual(self._band(5), (24.0, 29.0))

    def test_medium_and_unknown_keep_the_band(self) -> None:
        self.assertEqual(self._band(3), (25.0, 30.0))
        self.assertEqual(self._band(None), (25.0, 30.0))

    def test_ratio_is_untouched(self) -> None:
        light = target_for(1)
        self.assertEqual(light.ratio_aim, target_for().ratio_aim)
        self.assertGreater(light.tr_hi, target_for().tr_hi)

    def test_split_matches_the_temperature_bands(self) -> None:
        # One idea of "light" and "dark" across the engine.
        for roast in range(1, 6):
            shifted = self._band(roast) != self._band(None)
            moved_temp = temp_band_for_roast(roast) != temp_band_for_roast(3)
            self.assertEqual(shifted, moved_temp, roast)


class TestSimulatorReproducesCameron(unittest.TestCase):
    """docs/science.md#cameron -- the result the guardrail depends on."""

    def _sweep(self) -> list[tuple[float, float, float]]:
        bed = BedParams(dose_g=18.0)
        out: list[tuple[float, float, float]] = []
        for clicks in range(10, 61):
            shot = simulate_shot(float(clicks), K6, bed, target_yield_g=36.0)
            out.append((float(clicks), shot.ey_pct, shot.time_s))
        return out

    def test_extraction_yield_peaks_then_declines(self) -> None:
        sweep = self._sweep()
        yields = [ey for _, ey, _ in sweep]
        peak_index = yields.index(max(yields))

        # The peak must be interior -- that is the whole finding. A monotonic
        # curve would mean the simulator has lost the channeling mechanism.
        self.assertGreater(peak_index, 0, "yield peaks at the finest setting")
        self.assertLess(peak_index, len(yields) - 1, "yield peaks at the coarsest")

        # And yield genuinely falls off on the fine side of the peak.
        self.assertLess(yields[0], max(yields) * 0.9)

    def test_finer_but_faster_pairs_exist(self) -> None:
        """The exact fingerprint the anti-channeling guardrail detects.

        Under homogeneous flow, a finer grind is always slower. Where that
        breaks -- a finer setting running *faster* than a coarser one -- flow
        has gone inhomogeneous. Trigger 1 of finest_useful_clicks() keys on
        precisely this, so the fixture has to be able to produce it.
        """
        sweep = self._sweep()
        breaks = [
            (fine[0], coarse[0])
            for fine, coarse in zip(sweep, sweep[1:], strict=False)
            # sweep runs fine -> coarse; fine[2] is the finer setting's time
            if fine[2] < coarse[2]
        ]
        self.assertTrue(
            breaks,
            "simulator never produces a finer-but-faster pair, so the "
            "channeling guardrail would have nothing to detect",
        )

    def test_a_taste_balanced_shot_is_reachable(self) -> None:
        """The correction policy needs a reachable target to converge on."""
        bed = BedParams(dose_g=18.0)
        tastes = {
            simulate_shot(float(c), K6, bed, 36.0).taste_axis for c in range(20, 61)
        }
        self.assertIn("balanced", tastes)

    def test_a_mid_range_setting_lands_near_the_target_band(self) -> None:
        """Sanity: the fixture is calibrated somewhere realistic."""
        bed = BedParams(dose_g=18.0)
        shot = simulate_shot(33.0, K6, bed, target_yield_g=36.0)
        self.assertGreater(shot.time_s, 10.0)
        self.assertLess(shot.time_s, 90.0)


if __name__ == "__main__":
    unittest.main()
