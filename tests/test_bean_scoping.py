"""The recommendation must be about the coffee you are actually brewing.

The bug these cover: the engine anchored its correction on the most recent
shot on the *setup*, so brewing a Brazil at 36 and then switching to a Rwanda
proposed 35 -- a correction to the Brazil's shot -- instead of working from the
Rwanda's own 28 that had run fast. Every field `correct()` reads off that
anchor came from the wrong bag: grind, dose, temperature, ratio and taste.

DB-free like the rest of the engine tests. The pieces the fix rests on are
pure functions over ShotRecord lists, which is what makes the branch testable
without a live Postgres.
"""

from __future__ import annotations

import math
import unittest

from core.brewing import (
    GrinderCaps,
    MachineCaps,
    Recipe,
    ShotRecord,
    apply_guardrails,
    beta_prior,
    clicks_for_target,
    correct,
    finest_useful_clicks,
    is_finer,
    normalised_time,
    target_for,
    value_of,
)
from core.calibration import bean_offsets, fit_setup, theil_sen_comparable
from core.retrieval import BeanFeatures, borrow_bean_offset, shots_for_bean

K6 = GrinderCaps(
    min_clicks=0.0,
    max_clicks=180.0,
    step_clicks=1.0,
    um_per_click=16.0,
    finer_direction="lower_is_finer",
)
FIXED_TEMP_MACHINE = MachineCaps(basket_size_g=None, temp_controllable=False)
TARGET = target_for("espresso")

BRAZIL = 8
RWANDA = 7


def _shot(
    bean_id: int,
    clicks: float,
    time_s: float,
    dose_g: float = 18.0,
    taste: str | None = "balanced",
) -> ShotRecord:
    return ShotRecord(
        method="espresso",
        dose_g=dose_g,
        setup_id=1,
        bean_id=bean_id,
        grind_clicks=clicks,
        yield_g=dose_g * 2.0,
        time_s=time_s,
        taste_axis=taste,  # type: ignore[arg-type]
    )


# The reported case, newest first -- the order fetch_calibration_shots returns.
# The Rwanda ran fast at 28; the Brazil was pulled after it at 35.
#
# Physically consistent within each coffee (the K6 is lower-is-finer, so a
# lower setting must run slower) but not across them: the Rwanda at 28 runs
# faster than the Brazil at 36 despite being much finer. That is exactly what
# delta_bean describes, and exactly what a setup-wide channeling check
# misreads as the water bypassing the puck.
REPORTED = [
    _shot(BRAZIL, 35.0, 32.0, dose_g=16.0),  # T_r 16.0
    _shot(RWANDA, 28.0, 22.0, taste="sour"),  # T_r 11.0 -- ran fast
    _shot(BRAZIL, 36.0, 30.0, dose_g=16.0),  # T_r 15.0
    _shot(RWANDA, 30.0, 18.0, taste="sour"),  # T_r  9.0
]


class TestAnchorIsTheSameCoffee(unittest.TestCase):
    def test_shots_for_bean_keeps_only_this_coffee_newest_first(self) -> None:
        rwanda = shots_for_bean(REPORTED, RWANDA)
        self.assertEqual([s.grind_clicks for s in rwanda], [28.0, 30.0])

    def test_an_unsaved_coffee_has_no_anchor(self) -> None:
        """A first-time scan gets a transient Bean with no id."""
        self.assertEqual(shots_for_bean(REPORTED, None), [])

    def _recommend(self, bean_id: int) -> Recipe:
        """What engine.recommend() now does, minus the database."""
        beta = beta_prior("espresso", K6)
        bean_history = shots_for_bean(REPORTED, bean_id)
        recipe = correct(bean_history[0], TARGET, beta, K6, FIXED_TEMP_MACHINE)
        return apply_guardrails(recipe, K6, FIXED_TEMP_MACHINE, bean_history, TARGET)

    def test_the_rwanda_is_corrected_from_the_rwanda(self) -> None:
        """The reported bug: it proposed 35, next to the Brazil's setting."""
        anchor = shots_for_bean(REPORTED, RWANDA)[0]
        self.assertEqual(anchor.grind_clicks, 28.0)

        recipe = self._recommend(RWANDA)

        assert recipe.grind_clicks is not None
        self.assertTrue(
            is_finer(recipe.grind_clicks, 28.0, K6),
            "the Rwanda ran fast at 28, so the next setting must be finer",
        )
        self.assertLess(
            recipe.grind_clicks,
            32.0,
            "must not land in the Brazil's neighbourhood",
        )
        self.assertEqual(recipe.dose_g, 18.0, "the Brazil's 16 g must not carry over")

    def test_two_coffees_on_one_setup_do_not_get_the_same_recipe(self) -> None:
        rwanda, brazil = self._recommend(RWANDA), self._recommend(BRAZIL)
        self.assertNotEqual(rwanda.grind_clicks, brazil.grind_clicks)
        self.assertNotEqual(rwanda.dose_g, brazil.dose_g)


class TestChannelingFloorIsBeanScoped(unittest.TestCase):
    """The floor reads normalised times and taste, which delta_bean says are
    not comparable across coffees."""

    def test_another_coffee_does_not_set_this_one_s_floor(self) -> None:
        cross_bean = finest_useful_clicks(REPORTED, K6, TARGET)
        own_bean = finest_useful_clicks(shots_for_bean(REPORTED, RWANDA), K6, TARGET)

        assert cross_bean.clicks is not None
        self.assertIsNone(
            own_bean.clicks,
            "the Rwanda's own two shots show no channeling",
        )
        self.assertFalse(
            is_finer(cross_bean.clicks, 30.0, K6),
            "mixing the Brazil in pins the Rwanda coarser than it has brewed",
        )

    def test_a_new_coffee_still_gets_the_setup_wide_floor(self) -> None:
        """Falling back is the conservative direction: more triggers, not fewer."""
        self.assertEqual(shots_for_bean(REPORTED, 999) or REPORTED, REPORTED)


class TestBeanOffsets(unittest.TestCase):
    def _synthetic(self, alpha: float, beta: float) -> list[ShotRecord]:
        """Shots generated from a known law, so the offsets are known too.

        The Brazil is given a +0.30 offset in log space: it runs slower than
        the setup's average bean at the same setting, so it wants a coarser
        dial.
        """
        shots = []
        for bean_id, delta in ((RWANDA, 0.0), (BRAZIL, 0.30)):
            for clicks in (28.0, 32.0, 36.0, 40.0):
                tr = math.exp(alpha + delta + beta * clicks)
                shots.append(
                    _shot(bean_id, clicks, time_s=tr * 2.0)  # yield is 2x dose
                )
        return shots

    def test_offsets_recover_an_injected_per_bean_difference(self) -> None:
        alpha, beta = 6.0, -0.12
        offsets = bean_offsets(self._synthetic(alpha, beta), alpha, beta)

        # Shrunk by n/(n + kappa_bean) with four shots each.
        shrink = 4 / (4 + value_of("kappa_bean"))
        self.assertAlmostEqual(offsets[RWANDA], 0.0, places=6)
        self.assertAlmostEqual(offsets[BRAZIL], shrink * 0.30, places=6)

    def test_offsets_are_empty_without_a_fitted_law(self) -> None:
        self.assertEqual(bean_offsets(REPORTED, None, -0.12), {})
        self.assertEqual(bean_offsets(REPORTED, 6.0, None), {})

    def test_fit_setup_exposes_every_bean_not_just_the_one_asked_for(self) -> None:
        """A new coffee is seeded from the others, so it needs all of them."""
        shots = self._synthetic(6.0, -0.12)
        calibration = fit_setup(
            shots, "espresso", K6, beta_prior("espresso", K6), bean_id=RWANDA
        )
        self.assertEqual(set(calibration.bean_offsets), {RWANDA, BRAZIL})
        self.assertAlmostEqual(
            calibration.delta_bean, calibration.bean_offsets[RWANDA], places=9
        )


class TestSlopeIsFittedWithinCoffees(unittest.TestCase):
    """A pairwise slope must not straddle two bean intercepts.

    beta stays a property of the grinder and is still fitted across every bag,
    but by pooling each coffee's own *pairs* into one median -- not by pairing
    one coffee's shot against another's. The rise of a cross-bean pair is the
    grind difference plus the delta_bean gap, and REPORTED is exactly the case
    where that gap is the larger of the two.
    """

    def test_a_cross_bean_pair_is_not_evidence_about_the_grinder(self) -> None:
        # The Rwanda at 28 is seven clicks finer than the Brazil at 35 and ran
        # faster anyway. Read as one curve that is a *rising* slope, which
        # contradicts the physics -- and fit_setup discards the whole fit.
        cross_only = [REPORTED[0], REPORTED[1]]  # one Brazil, one Rwanda
        self.assertIsNone(theil_sen_comparable(cross_only))

    def test_the_slope_is_the_median_of_what_each_coffee_measured(self) -> None:
        slope = theil_sen_comparable(REPORTED)
        assert slope is not None
        brazil = math.log(15 / 16)  # 35 -> 36 clicks, T_r 16.0 -> 15.0
        rwanda = math.log(9 / 11) / 2  # 28 -> 30 clicks, T_r 11.0 -> 9.0
        self.assertAlmostEqual(slope, (brazil + rwanda) / 2, places=6)
        # Four of the six pooled pairs are cross-bean and all four come out
        # positive, so pooling them returned +0.046 -- not a shallow slope but
        # the wrong sign, which is the channeling signature, not a grinder.
        self.assertLess(slope, -0.05)

    def test_a_mixed_history_fits_the_grinder_not_the_gap_between_bags(self) -> None:
        calibration = fit_setup(
            REPORTED, "espresso", K6, beta_prior("espresso", K6), bean_id=RWANDA
        )
        # The regression this guards: the pooled median was +0.046, so the
        # sign check in fit_setup threw the fit away and quietly returned the
        # untouched prior at zero confidence -- on a history with four shots
        # across two settings per bag, which is enough to fit.
        self.assertEqual(calibration.beta_source, "shrunk")
        assert calibration.beta is not None
        self.assertLess(calibration.beta, -0.08)

    def test_one_shot_per_coffee_is_no_evidence_about_the_grinder(self) -> None:
        """Regression: with no same-coffee pair, fit_setup fell back to pooling
        every pair -- the cross-bean comparison the fit exists to avoid."""
        # Three coffees, one setting each. Read as one curve the slope even has
        # the physical sign, but its size is the gap between the bags.
        one_each = [_shot(1, 28.0, 40.0), _shot(2, 32.0, 36.0), _shot(3, 36.0, 20.0)]
        self.assertIsNone(theil_sen_comparable(one_each))
        calibration = fit_setup(one_each, "espresso", K6, beta_prior("espresso", K6))
        self.assertEqual(calibration.beta_source, "prior")
        self.assertEqual(calibration.beta, beta_prior("espresso", K6))

    def test_shots_with_no_bean_recorded_still_pair_together(self) -> None:
        """Bean-less records are one pool -- the simulator tests rely on it."""
        anonymous = [
            ShotRecord(
                method="espresso",
                dose_g=18.0,
                grind_clicks=clicks,
                yield_g=36.0,
                time_s=time_s,
            )
            for clicks, time_s in ((28.0, 32.0), (32.0, 26.0), (36.0, 22.0))
        ]
        self.assertIsNotNone(theil_sen_comparable(anonymous))


class TestBorrowingForANewCoffee(unittest.TestCase):
    RWANDA_FEATURES = BeanFeatures(roast_level_ord=2, process="Washed", origin="Rwanda")
    BRAZIL_FEATURES = BeanFeatures(
        roast_level_ord=4, process="Natural", origin="Brazil"
    )

    def _features(self) -> dict[int, BeanFeatures]:
        return {RWANDA: self.RWANDA_FEATURES, BRAZIL: self.BRAZIL_FEATURES}

    def test_a_similar_coffee_dominates_an_unrelated_one(self) -> None:
        """A new washed Kenyan should lean on the Rwanda, not the Brazil."""
        kenyan = BeanFeatures(roast_level_ord=2, process="Washed", origin="Kenya")
        delta, borrowed = borrow_bean_offset(
            kenyan, {RWANDA: -0.10, BRAZIL: 0.40}, self._features()
        )
        self.assertEqual(borrowed, 1)
        self.assertAlmostEqual(delta, -0.10, places=6)

    def test_nothing_similar_enough_borrows_nothing(self) -> None:
        stranger = BeanFeatures(
            roast_level_ord=5, process="Anaerobic", origin="Vietnam"
        )
        self.assertEqual(
            borrow_bean_offset(stranger, {RWANDA: -0.10}, self._features()),
            (0.0, 0),
        )

    def test_an_offset_without_features_is_skipped(self) -> None:
        self.assertEqual(
            borrow_bean_offset(self.RWANDA_FEATURES, {99: 0.5}, self._features()),
            (0.0, 0),
        )

    def test_the_borrowed_offset_moves_the_starting_dial(self) -> None:
        """A slower-running coffee must start coarser, not at the same click."""
        alpha, beta = 6.0, -0.12
        assert TARGET.tr_lo is not None and TARGET.tr_hi is not None
        tr_aim = (TARGET.tr_lo + TARGET.tr_hi) / 2.0

        neutral = clicks_for_target(alpha, beta, tr_aim, 0.0)
        slower = clicks_for_target(alpha, beta, tr_aim, 0.30)
        assert neutral is not None and slower is not None
        self.assertFalse(
            is_finer(slower, neutral, K6),
            "a coffee that runs slow at a given setting wants a coarser dial",
        )


class TestGrindLawInversion(unittest.TestCase):
    def test_it_inverts_the_correction(self) -> None:
        """Solving for c must land where a shot at c would actually run."""
        alpha, beta = 6.0, -0.12
        clicks = clicks_for_target(alpha, beta, 13.75)
        assert clicks is not None
        self.assertAlmostEqual(math.exp(alpha + beta * clicks), 13.75, places=6)

    def test_it_abstains_without_a_law(self) -> None:
        self.assertIsNone(clicks_for_target(None, -0.12, 13.75))
        self.assertIsNone(clicks_for_target(6.0, None, 13.75))
        self.assertIsNone(clicks_for_target(6.0, 0.0, 13.75), "moka has no slope")
        self.assertIsNone(clicks_for_target(6.0, -0.12, 0.0))

    def test_the_law_agrees_with_what_the_shots_measured(self) -> None:
        """Fit a setup, then ask it where a bean's own shots already sit."""
        shots = [_shot(RWANDA, c, time_s=t) for c, t in ((28.0, 22.0), (34.0, 46.0))]
        shots.append(_shot(RWANDA, 31.0, time_s=32.0))
        calibration = fit_setup(
            shots, "espresso", K6, beta_prior("espresso", K6), bean_id=RWANDA
        )
        middle = shots[2]
        tr = normalised_time(middle)
        assert tr is not None
        predicted = clicks_for_target(
            calibration.alpha, calibration.beta, tr, calibration.delta_bean
        )
        assert predicted is not None and middle.grind_clicks is not None
        self.assertLess(abs(predicted - middle.grind_clicks), 3.0)


if __name__ == "__main__":
    unittest.main()
