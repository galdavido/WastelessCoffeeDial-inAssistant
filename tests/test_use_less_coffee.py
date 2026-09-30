"""Cameron's use-less-coffee suggestion, docs/science.md#dose-reduction."""

from __future__ import annotations

import unittest
from dataclasses import replace

from core.brewing import (
    GrinderCaps,
    MachineCaps,
    Recipe,
    ShotRecord,
    channeled_shots,
    dose_reduction,
    is_finer,
    target_for,
)

K6 = GrinderCaps(
    min_clicks=0.0,
    max_clicks=90.0,
    step_clicks=1.0,
    um_per_click=16.0,
    finer_direction="lower_is_finer",
)
MACHINE = MachineCaps(basket_size_g=18.0)
TARGET = target_for("espresso")


def _shot(clicks: float, time_s: float, dose: float = 18.0, taste: str = "balanced"):
    return ShotRecord(
        method="espresso",
        dose_g=dose,
        bean_id=1,
        grind_clicks=clicks,
        yield_g=dose * 2.0,
        time_s=time_s,
        taste_axis=taste,  # type: ignore[arg-type]
    )


# Finer and finer, and each finer shot ran no slower: the channeling signature.
CHANNELING = [_shot(30.0, 26.0), _shot(28.0, 24.0), _shot(26.0, 23.0)]
STUCK = Recipe(
    method="espresso",
    dose_g=18.0,
    grind_clicks=30.0,
    yield_g=36.0,
    guardrails_hit=("grind_channeling_floor",),
)


class TestWhenItIsOffered(unittest.TestCase):
    def test_repeated_channeling_with_the_grind_stuck_suggests_less_coffee(
        self,
    ) -> None:
        suggestion = dose_reduction(CHANNELING, STUCK, K6, MACHINE, TARGET)
        assert suggestion is not None
        self.assertEqual(suggestion.dose_g, 14.5)  # 18 g less 20%, to 0.5 g
        self.assertEqual(suggestion.yield_g, 36.0)  # the same drink
        assert suggestion.grind_clicks is not None
        self.assertTrue(is_finer(30.0, suggestion.grind_clicks, K6), "coarser")
        self.assertEqual(suggestion.channeled_shots, 2)
        self.assertIn("14.5 g", suggestion.note)

    def test_the_basket_sets_a_floor_on_the_smaller_dose(self) -> None:
        small = MachineCaps(basket_size_g=19.0)  # fill floor 14.25 -> 14.5
        heavy = replace(STUCK, dose_g=18.0)
        suggestion = dose_reduction(CHANNELING, heavy, K6, small, TARGET)
        assert suggestion is not None
        self.assertEqual(suggestion.dose_g, 14.5)

        tiny = MachineCaps(basket_size_g=24.0)  # floor 18 g: no room to go lighter
        self.assertIsNone(dose_reduction(CHANNELING, heavy, K6, tiny, TARGET))


class TestWhenItHoldsBack(unittest.TestCase):
    def test_not_while_grinding_can_still_fix_it(self) -> None:
        free = replace(STUCK, guardrails_hit=())
        self.assertIsNone(dose_reduction(CHANNELING, free, K6, MACHINE, TARGET))

    def test_not_on_a_single_bad_puck(self) -> None:
        once = [_shot(30.0, 26.0), _shot(28.0, 24.0)]
        self.assertEqual(len(channeled_shots(once, K6, TARGET)), 1)
        self.assertIsNone(dose_reduction(once, STUCK, K6, MACHINE, TARGET))

    def test_not_from_shots_at_another_dose(self) -> None:
        other = [replace(s, dose_g=16.0, yield_g=32.0) for s in CHANNELING]
        self.assertIsNone(dose_reduction(other, STUCK, K6, MACHINE, TARGET))

    def test_not_once_a_lighter_dose_has_been_tried(self) -> None:
        tried = [*CHANNELING, _shot(31.0, 22.0, dose=15.0)]
        self.assertIsNone(dose_reduction(tried, STUCK, K6, MACHINE, TARGET))

    def test_not_for_other_methods(self) -> None:
        pourover = replace(STUCK, method="pourover")
        self.assertIsNone(dose_reduction(CHANNELING, pourover, K6, MACHINE, TARGET))

    def test_prep_differences_are_not_channeling(self) -> None:
        """A longer pre-infusion runs faster; that is not a finer shot channeling."""
        prepped = [
            replace(CHANNELING[0], preinfusion_s=2.0),
            replace(CHANNELING[1], preinfusion_s=8.0),
            replace(CHANNELING[2], preinfusion_s=14.0),
        ]
        self.assertEqual(channeled_shots(prepped, K6, TARGET), [])


class TestLongAndSour(unittest.TestCase):
    def test_a_long_shot_that_tasted_sour_counts(self) -> None:
        shots = [_shot(28.0, 60.0, taste="sour"), _shot(27.0, 62.0, taste="very_sour")]
        self.assertEqual(len(channeled_shots(shots, K6, TARGET)), 2)


if __name__ == "__main__":
    unittest.main()
