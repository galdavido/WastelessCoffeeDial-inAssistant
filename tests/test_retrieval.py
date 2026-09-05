"""Tests for structured similarity and the cold-start cascade.

Scoring and tier classification are pure functions, so they are tested
directly; the SQL that feeds them needs a live Postgres and is exercised in
the integration path.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from core.brewing import ShotRecord
from core.retrieval import (
    BeanFeatures,
    canonical_process,
    classify_tier,
    recency_factor,
    similarity,
)


class TestSimilarity(unittest.TestCase):
    def test_same_setup_dominates(self) -> None:
        """A click number from another grinder is nearly meaningless."""
        a = BeanFeatures(roast_level_ord=3, process="Washed", origin="Kenya")
        same = similarity(a, a, same_setup=True)
        other = similarity(a, a, same_setup=False)
        self.assertGreater(same - other, 0.35)

    def test_identical_bean_on_same_setup_scores_near_one(self) -> None:
        a = BeanFeatures(
            roast_level_ord=2, process="Washed", origin="Kenya", days_since_roast=10
        )
        self.assertAlmostEqual(similarity(a, a, same_setup=True), 1.0, places=6)

    def test_roast_distance_reduces_the_score(self) -> None:
        light = BeanFeatures(roast_level_ord=1)
        dark = BeanFeatures(roast_level_ord=5)
        medium = BeanFeatures(roast_level_ord=3)
        self.assertGreater(
            similarity(light, medium, False), similarity(light, dark, False)
        )

    def test_regional_origins_partially_match(self) -> None:
        kenya = BeanFeatures(origin="Kenya")
        ethiopia = BeanFeatures(origin="Ethiopia")
        brazil = BeanFeatures(origin="Brazil")
        self.assertGreater(
            similarity(kenya, ethiopia, False), similarity(kenya, brazil, False)
        )

    def test_process_aliases_are_canonicalised(self) -> None:
        self.assertEqual(canonical_process("Fully Washed"), "washed")
        self.assertEqual(canonical_process("natural"), "natural")
        self.assertEqual(canonical_process("Pulped Natural"), "honey")
        self.assertIsNone(canonical_process("Who knows"))

    def test_unknown_fields_never_award_credit(self) -> None:
        """Missing data must not look like agreement."""
        known = BeanFeatures(roast_level_ord=3, process="Washed", origin="Kenya")
        unknown = BeanFeatures()
        self.assertEqual(similarity(known, unknown, same_setup=False), 0.0)


class TestRecency(unittest.TestCase):
    def test_recent_shots_are_undiscounted(self) -> None:
        now = datetime.now(UTC)
        self.assertAlmostEqual(recency_factor(now, now), 1.0, places=3)

    def test_old_shots_decay_but_never_to_zero(self) -> None:
        now = datetime.now(UTC)
        old = now - timedelta(weeks=52)
        factor = recency_factor(old, now)
        self.assertLess(factor, 1.0)
        self.assertGreaterEqual(factor, 0.7)


class TestColdStartCascade(unittest.TestCase):
    def _shot(self, clicks: float, bean_id: int = 1) -> ShotRecord:
        return ShotRecord(
            method="espresso",
            dose_g=18.0,
            bean_id=bean_id,
            grind_clicks=clicks,
            yield_g=36.0,
            time_s=28.0,
        )

    def test_no_data_and_no_hardware_is_tier_e(self) -> None:
        """The state every one of this user's setups is in today."""
        self.assertEqual(classify_tier([], bean_id=1, has_hardware_caps=False), "E")

    def test_no_data_but_known_hardware_is_tier_d(self) -> None:
        self.assertEqual(classify_tier([], bean_id=1, has_hardware_caps=True), "D")

    def test_one_shot_is_tier_c(self) -> None:
        self.assertEqual(
            classify_tier([self._shot(33)], bean_id=1, has_hardware_caps=True), "C"
        )

    def test_three_shots_on_other_beans_is_tier_b(self) -> None:
        shots = [self._shot(33, 2), self._shot(35, 3), self._shot(37, 4)]
        self.assertEqual(classify_tier(shots, bean_id=1, has_hardware_caps=True), "B")

    def test_three_shots_on_this_bean_at_two_settings_is_tier_a(self) -> None:
        shots = [self._shot(33, 1), self._shot(35, 1), self._shot(35, 1)]
        self.assertEqual(classify_tier(shots, bean_id=1, has_hardware_caps=True), "A")

    def test_repeats_at_one_setting_do_not_reach_tier_a(self) -> None:
        # Three shots, all at the same click: no slope information.
        shots = [self._shot(33, 1) for _ in range(3)]
        self.assertEqual(classify_tier(shots, bean_id=1, has_hardware_caps=True), "B")

    def test_incomplete_shots_are_ignored(self) -> None:
        partial = ShotRecord(method="espresso", dose_g=18.0, grind_clicks=33.0)
        self.assertEqual(
            classify_tier([partial], bean_id=1, has_hardware_caps=False), "E"
        )


if __name__ == "__main__":
    unittest.main()
