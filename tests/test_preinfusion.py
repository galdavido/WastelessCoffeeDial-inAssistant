"""Pre-infusion as a covariate, not as part of the shot time.

The load-bearing test here is
test_preinfusion_difference_does_not_fake_channeling: an unrecorded
preparation difference produces a finer-but-faster pair, which is exactly the
channeling fingerprint, and would otherwise stop the engine grinding finer
when nothing is wrong.
"""

from __future__ import annotations

import unittest

from core.brewing import (
    GrinderCaps,
    ShotRecord,
    finest_useful_clicks,
    normalised_time,
    preinfusion_experiment,
    prep_advice,
    prep_comparable,
    resistance_disagreement,
    target_for,
    value_of,
)
from core.calibration import theil_sen_comparable

K6 = GrinderCaps(
    min_clicks=0.0,
    max_clicks=180.0,
    step_clicks=1.0,
    um_per_click=16.0,
    finer_direction="lower_is_finer",
)
TARGET = target_for("espresso")


def _shot(
    clicks: float,
    time_s: float,
    *,
    preinfusion_s: float | None = None,
    pause_s: float | None = None,
    taste: str | None = None,
    rating: int | None = None,
    brew_temp_c: float | None = None,
) -> ShotRecord:
    return ShotRecord(
        method="espresso",
        dose_g=18.0,
        grind_clicks=clicks,
        yield_g=36.0,
        time_s=time_s,
        preinfusion_s=preinfusion_s,
        pause_s=pause_s,
        brew_temp_c=brew_temp_c,
        taste_axis=taste,  # type: ignore[arg-type]
        rating=rating,
    )


class TestPreinfusionExperiment(unittest.TestCase):
    """The way out of the dead end where the grind lever is gone.

    Once the channeling floor binds, the engine may not grind finer. Before
    this, prep_advice went on reporting the user's own usual pre-infusion back
    to them while its note told them to try a longer one -- so the advice and
    the number contradicted each other and nothing ever moved.
    """

    def _habitual(self, n: int = 8, pi: float = 2.0) -> list[ShotRecord]:
        """A user who has always pre-infused for the same short time."""
        return [
            _shot(28 + i % 3, 16.0, preinfusion_s=pi, pause_s=2.0) for i in range(n)
        ]

    def test_it_fires_when_the_grind_is_stuck(self) -> None:
        got = preinfusion_experiment(self._habitual(), "espresso", grind_is_stuck=True)
        assert got is not None
        self.assertGreater(got.preinfusion_s, 2.0)

    def test_it_does_not_override_the_guardrailed_grind(self) -> None:
        """Holding the grind means leaving it alone, not re-pointing it.

        The experiment only runs because the channeling floor clamped the
        grind, so carrying a grind number of its own could land finer than
        that floor and silently undo the clamp.
        """
        got = preinfusion_experiment(self._habitual(), "espresso", grind_is_stuck=True)
        assert got is not None
        self.assertFalse(hasattr(got, "grind_clicks"))

    def test_it_reaches_the_duration_that_earns_channeling_relief(self) -> None:
        """The target is not arbitrary: at this duration the engine already
        credits pre-infusion with allowing a finer grind."""
        got = preinfusion_experiment(self._habitual(), "espresso", grind_is_stuck=True)
        assert got is not None
        self.assertGreaterEqual(
            got.preinfusion_s, value_of("preinfusion_min_for_relief_s")
        )

    def test_the_new_duration_is_not_grind_evidence_against_the_old(self) -> None:
        """It must clear prep_tolerance_s, or the experiment's shots would be
        paired with the old ones and the change would land in the slope."""
        got = preinfusion_experiment(self._habitual(), "espresso", grind_is_stuck=True)
        assert got is not None
        self.assertGreater(got.preinfusion_s - 2.0, value_of("prep_tolerance_s"))

    def test_it_stays_quiet_while_the_grind_still_has_room(self) -> None:
        got = preinfusion_experiment(self._habitual(), "espresso", grind_is_stuck=False)
        self.assertIsNone(got)

    def test_it_stays_quiet_on_pourover(self) -> None:
        """A bloom is a different mechanism with a different purpose."""
        shots = [
            ShotRecord(
                method="pourover",
                dose_g=18.0,
                grind_clicks=60.0,
                water_g=288.0,
                time_s=180.0,
                preinfusion_s=2.0,
            )
            for _ in range(8)
        ]
        got = preinfusion_experiment(shots, "pourover", grind_is_stuck=True)
        self.assertIsNone(got)

    def test_it_stays_quiet_when_the_user_already_preinfuses_long(self) -> None:
        """Nothing to test: this puck is already being mitigated."""
        long_pi = value_of("preinfusion_min_for_relief_s") + 1.0
        got = preinfusion_experiment(
            self._habitual(pi=long_pi),
            "espresso",
            grind_is_stuck=True,
        )
        self.assertIsNone(got)

    def test_it_stays_quiet_without_enough_history(self) -> None:
        got = preinfusion_experiment(
            self._habitual(n=2), "espresso", grind_is_stuck=True
        )
        self.assertIsNone(got)

    def test_it_keeps_asking_until_the_new_duration_has_enough_shots(self) -> None:
        """One shot at a new setting is an anecdote, not a comparison."""
        shots = self._habitual()
        target = preinfusion_experiment(shots, "espresso", grind_is_stuck=True)
        assert target is not None
        needed = int(value_of("min_shots_at_new_prep"))

        for done in range(1, needed):
            trial = shots + [
                _shot(28, 20.0, preinfusion_s=target.preinfusion_s, pause_s=2.0)
                for _ in range(done)
            ]
            self.assertIsNotNone(
                preinfusion_experiment(trial, "espresso", grind_is_stuck=True),
                f"should still be running after {done} shot(s)",
            )

    def test_it_stops_once_the_comparison_can_be_made(self) -> None:
        shots = self._habitual()
        target = preinfusion_experiment(shots, "espresso", grind_is_stuck=True)
        assert target is not None
        gathered = shots + [
            _shot(28, 20.0, preinfusion_s=target.preinfusion_s, pause_s=2.0)
            for _ in range(int(value_of("min_shots_at_new_prep")))
        ]
        self.assertIsNone(
            preinfusion_experiment(gathered, "espresso", grind_is_stuck=True)
        )

    def test_the_target_does_not_creep_while_the_experiment_runs(self) -> None:
        """The baseline is the habitual duration, not a running median that
        the experiment's own long shots would drag upward."""
        shots = self._habitual()
        first = preinfusion_experiment(shots, "espresso", grind_is_stuck=True)
        assert first is not None
        mid = shots + [_shot(28, 20.0, preinfusion_s=first.preinfusion_s, pause_s=2.0)]
        second = preinfusion_experiment(mid, "espresso", grind_is_stuck=True)
        assert second is not None
        self.assertEqual(first.preinfusion_s, second.preinfusion_s)

    def test_the_note_tells_the_user_to_change_nothing_else(self) -> None:
        got = preinfusion_experiment(self._habitual(), "espresso", grind_is_stuck=True)
        assert got is not None
        self.assertIn("nothing else", got.note.lower())


class TestShotTimeExcludesPreinfusion(unittest.TestCase):
    def test_preinfusion_is_not_added_to_normalised_time(self) -> None:
        """T_r is the pressurised pull only -- the grind law is Darcy's law."""
        without = _shot(33, 28.0)
        with_pi = _shot(33, 28.0, preinfusion_s=8.0, pause_s=5.0)
        self.assertEqual(normalised_time(without), normalised_time(with_pi))
        self.assertEqual(normalised_time(with_pi), 14.0)


class TestComparability(unittest.TestCase):
    def test_same_routine_is_comparable(self) -> None:
        a = _shot(33, 28.0, preinfusion_s=8.0, pause_s=5.0)
        b = _shot(35, 24.0, preinfusion_s=8.5, pause_s=5.0)
        self.assertTrue(prep_comparable(a, b))

    def test_different_preinfusion_is_not_comparable(self) -> None:
        a = _shot(33, 28.0, preinfusion_s=3.0)
        b = _shot(35, 24.0, preinfusion_s=12.0)
        self.assertFalse(prep_comparable(a, b))

    def test_different_pause_is_not_comparable(self) -> None:
        a = _shot(33, 28.0, preinfusion_s=8.0, pause_s=2.0)
        b = _shot(35, 24.0, preinfusion_s=8.0, pause_s=15.0)
        self.assertFalse(prep_comparable(a, b))

    def test_unknown_counts_as_comparable(self) -> None:
        """Otherwise nothing compares for a user who doesn't record it."""
        a = _shot(33, 28.0)
        b = _shot(35, 24.0, preinfusion_s=8.0)
        self.assertTrue(prep_comparable(a, b))

    def test_different_brew_temperature_is_not_comparable(self) -> None:
        """Hotter water extracts faster, which is not the grinder's doing."""
        a = _shot(33, 28.0, brew_temp_c=92.0)
        b = _shot(35, 24.0, brew_temp_c=96.0)
        self.assertFalse(prep_comparable(a, b))

    def test_small_temperature_differences_still_compare(self) -> None:
        """Without a PID the figure is what you set, not what reached the
        coffee, so treating half a degree as meaningful is false precision."""
        a = _shot(33, 28.0, brew_temp_c=93.0)
        b = _shot(35, 24.0, brew_temp_c=93.5)
        self.assertTrue(prep_comparable(a, b))

    def test_unknown_temperature_counts_as_comparable(self) -> None:
        a = _shot(33, 28.0, brew_temp_c=93.0)
        b = _shot(35, 24.0)
        self.assertTrue(prep_comparable(a, b))


class TestFalseChannelingSignature(unittest.TestCase):
    def test_preinfusion_difference_does_not_fake_channeling(self) -> None:
        """The bug this whole change exists to prevent.

        30 clicks is finer than 34 yet ran faster -- but only because it was
        pre-infused for far longer, arriving at pressure already saturated.
        That is preparation, not channeling, and must not floor the grind.
        """
        history = [
            _shot(34, 30.0, preinfusion_s=3.0, pause_s=2.0),
            _shot(30, 22.0, preinfusion_s=14.0, pause_s=8.0),
        ]
        limit = finest_useful_clicks(history, K6, TARGET)
        self.assertIsNone(
            limit.clicks,
            "an unrecorded prep difference was mistaken for channeling",
        )

    def test_same_routine_still_detects_real_channeling(self) -> None:
        """With prep held constant, the detector must still fire."""
        history = [
            _shot(34, 30.0, preinfusion_s=8.0, pause_s=5.0),
            _shot(30, 22.0, preinfusion_s=8.0, pause_s=5.0),
        ]
        limit = finest_useful_clicks(history, K6, TARGET)
        self.assertIsNotNone(limit.clicks)

    def test_consistent_preinfusion_relaxes_the_floor(self) -> None:
        """A saturated puck tolerates a finer grind than a dry one."""
        consistent = [
            _shot(34, 30.0, preinfusion_s=8.0, pause_s=5.0),
            _shot(30, 22.0, preinfusion_s=8.0, pause_s=5.0),
        ]
        no_preinfusion = [
            _shot(34, 30.0),
            _shot(30, 22.0),
        ]
        with_relief = finest_useful_clicks(consistent, K6, TARGET)
        without = finest_useful_clicks(no_preinfusion, K6, TARGET)
        assert with_relief.clicks is not None and without.clicks is not None
        # Lower clicks are finer on this grinder.
        self.assertLess(with_relief.clicks, without.clicks)
        assert with_relief.reason is not None
        self.assertIn("pre-infusion", with_relief.reason)


class TestSlopeExcludesIncomparablePairs(unittest.TestCase):
    def test_mismatched_prep_pair_is_dropped_from_the_fit(self) -> None:
        clean = [
            _shot(30, 34.0, preinfusion_s=8.0),
            _shot(34, 26.0, preinfusion_s=8.0),
            _shot(38, 20.0, preinfusion_s=8.0),
        ]
        polluted = [*clean, _shot(32, 12.0, preinfusion_s=20.0)]
        slope_clean = theil_sen_comparable(clean)
        slope_polluted = theil_sen_comparable(polluted)
        assert slope_clean is not None and slope_polluted is not None
        self.assertAlmostEqual(slope_clean, slope_polluted, places=6)

    def test_returns_none_when_nothing_is_comparable(self) -> None:
        shots = [
            _shot(30, 34.0, preinfusion_s=2.0),
            _shot(34, 26.0, preinfusion_s=20.0),
        ]
        self.assertIsNone(theil_sen_comparable(shots))


class TestResistanceCorroboration(unittest.TestCase):
    def test_slow_pull_with_normal_pressure_build_points_at_prep(self) -> None:
        """Resistance that appears only after wetting is not the grind."""
        peers = [
            _shot(33, 28.0, preinfusion_s=8.0),
            _shot(33, 27.0, preinfusion_s=8.0),
        ]
        odd = _shot(33, 52.0, preinfusion_s=8.0)
        note = resistance_disagreement(odd, [odd, *peers])
        self.assertIsNotNone(note)
        assert note is not None
        self.assertIn("tamp", note)

    def test_both_readings_moving_together_is_not_flagged(self) -> None:
        """A genuinely finer puck is slower to pressurise and slower to pull."""
        peers = [
            _shot(33, 28.0, preinfusion_s=8.0),
            _shot(33, 27.0, preinfusion_s=8.0),
        ]
        finer = _shot(33, 40.0, preinfusion_s=13.0)
        self.assertIsNone(resistance_disagreement(finer, [finer, *peers]))

    def test_no_preinfusion_recorded_means_no_second_opinion(self) -> None:
        peers = [_shot(33, 28.0), _shot(33, 27.0)]
        odd = _shot(33, 52.0)
        self.assertIsNone(resistance_disagreement(odd, [odd, *peers]))


class TestPrepAdvice(unittest.TestCase):
    def test_nothing_recorded_explains_why_it_matters(self) -> None:
        pi, pause, note = prep_advice([_shot(33, 28.0)])
        self.assertIsNone(pi)
        self.assertIsNone(pause)
        self.assertIn("not recorded", note)

    def test_sparse_data_echoes_the_users_own_routine(self) -> None:
        shots = [_shot(33, 28.0, preinfusion_s=8.0, pause_s=5.0) for _ in range(3)]
        pi, pause, note = prep_advice(shots)
        self.assertEqual(pi, 8.0)
        self.assertEqual(pause, 5.0)
        self.assertIn("comparable", note)

    def test_one_duration_only_asks_for_variation(self) -> None:
        shots = [_shot(33, 28.0, preinfusion_s=8.0) for _ in range(10)]
        _, _, note = prep_advice(shots)
        self.assertIn("nothing to compare", note)

    def test_with_variation_it_reports_the_best_rated_routine(self) -> None:
        shots = [
            *[_shot(33, 28.0, preinfusion_s=4.0, rating=2) for _ in range(5)],
            *[
                _shot(33, 28.0, preinfusion_s=12.0, pause_s=6.0, rating=5)
                for _ in range(5)
            ],
        ]
        pi, pause, note = prep_advice(shots)
        self.assertEqual(pi, 12.0)
        self.assertEqual(pause, 6.0)
        self.assertIn("best-rated", note)


if __name__ == "__main__":
    unittest.main()
