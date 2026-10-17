"""The model-agnostic ln(T_r) back-test and the challengers it scores.

Simulated histories again: the harness has to be right about leakage and
abstention before any number it prints about real shots means anything.
"""

from __future__ import annotations

import math
import random
import re
import unittest
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from _sim import BedParams, simulate_shot
from core.brewing import GrinderCaps, ShotRecord
from core.eval_harness import (
    MIN_SHOTS_FOR_PREDICTION,
    MIN_TRAIN_SHOTS,
    compare_models,
    held_out_predictions,
)
from core.time_models import (
    BeanMeanTimeModel,
    EngineTimeModel,
    Predictor,
    log_time,
)

K6 = GrinderCaps(
    min_clicks=0.0,
    max_clicks=180.0,
    step_clicks=1.0,
    um_per_click=16.0,
    finer_direction="lower_is_finer",
)
SRC = Path(__file__).resolve().parent.parent / "src"


def _history(n: int, beans: int = 2, seed: int = 0) -> list[ShotRecord]:
    """Varied grind, dose and coffee, with a little shot-to-shot noise."""
    rng = random.Random(seed)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    out: list[ShotRecord] = []
    for i in range(n):
        bean = i % beans
        dose = rng.choice([17.0, 18.0, 19.0])
        clicks = rng.randrange(26, 42)
        sim = simulate_shot(
            clicks, K6, BedParams(dose_g=dose), 2 * dose, c0_clicks=31 + 3 * bean
        )
        out.append(
            ShotRecord(
                dose_g=dose,
                setup_id=1,
                bean_id=bean + 1,
                grind_clicks=float(clicks),
                yield_g=2 * dose,
                time_s=sim.time_s * rng.lognormvariate(0, 0.05),
                roast_level_ord=2 + bean,
                created_at=base + timedelta(hours=i),
            )
        )
    # The database hands history over newest first.
    return out[::-1]


@dataclass
class SpyModel:
    """Records every training set it is given; predicts the training mean."""

    name: str = "spy"
    seen: list[tuple[ShotRecord, ...]] = field(
        default_factory=list[tuple[ShotRecord, ...]]
    )
    abstain_on: frozenset[int] = frozenset()

    def fit(self, train: Sequence[ShotRecord]) -> Predictor | None:
        self.seen.append(tuple(train))
        ys = [y for s in train if (y := log_time(s)) is not None]
        mean = sum(ys) / len(ys)

        def predict(shot: ShotRecord) -> float | None:
            return None if id(shot) in self.abstain_on else mean

        return predict


class TestHeldOutSchemes(unittest.TestCase):
    def test_walk_forward_never_trains_on_a_later_shot(self) -> None:
        shots = _history(12)
        spy = SpyModel()
        points = held_out_predictions(shots, [spy], "walk_forward")

        self.assertEqual(len(points), 12 - MIN_TRAIN_SHOTS)
        for point, train in zip(points, spy.seen, strict=True):
            held_at = point.shot.created_at
            assert held_at is not None
            self.assertTrue(all(s.created_at and s.created_at < held_at for s in train))
            # Newest first, as the engine gets it from the database.
            # Every one is set: the assertion above checked.
            stamps = [s.created_at for s in train if s.created_at is not None]
            self.assertEqual(stamps, sorted(stamps, reverse=True))

    def test_leave_one_out_trains_on_everything_else(self) -> None:
        shots = _history(8)
        spy = SpyModel()
        points = held_out_predictions(shots, [spy], "loo")

        self.assertEqual(len(points), 8)
        for point, train in zip(points, spy.seen, strict=True):
            self.assertNotIn(point.shot, train)
            self.assertEqual(len(train), 7)

    def test_unmeasured_shots_are_neither_held_out_nor_trained_on(self) -> None:
        shots = _history(6)
        shots.append(ShotRecord(dose_g=18.0, grind_clicks=30.0))
        spy = SpyModel()
        points = held_out_predictions(shots, [spy], "loo")

        self.assertEqual(len(points), 6)
        self.assertTrue(all(len(train) == 5 for train in spy.seen))


class TestCompareModels(unittest.TestCase):
    def test_too_few_shots_says_so_instead_of_ranking(self) -> None:
        result = compare_models(_history(6), [BeanMeanTimeModel()])
        self.assertFalse(result.sufficient)
        self.assertIn("INSUFFICIENT DATA", result.render())

    def test_scored_on_the_common_set_with_abstentions_counted(self) -> None:
        shots = _history(MIN_SHOTS_FOR_PREDICTION + 5)
        dodger = SpyModel(name="dodger", abstain_on=frozenset({id(shots[0])}))
        result = compare_models(shots, [dodger, BeanMeanTimeModel()])

        self.assertEqual(result.n, len(shots) - 1)
        scores = {s.name: s for s in result.scores}
        self.assertEqual(scores["dodger"].abstained, 1)
        self.assertEqual(scores["bean_mean"].abstained, 0)
        self.assertIn("abstained on 1", result.render())

    def test_engine_beats_ignoring_the_grinder_on_simulated_shots(self) -> None:
        """The simulator's grind matters, so a law that reads it must win."""
        shots = _history(30)
        models = [EngineTimeModel(K6), BeanMeanTimeModel()]
        for scheme in ("loo", "walk_forward"):
            result = compare_models(shots, models, scheme)
            scores = {s.name: s.mae for s in result.scores}
            assert scores["engine"] is not None and scores["bean_mean"] is not None
            self.assertLess(scores["engine"], scores["bean_mean"], scheme)

    def test_a_coffees_first_shot_is_scored_apart(self) -> None:
        """Walk-forward meets each bag's first pull once; LOO almost never."""
        shots = _history(MIN_SHOTS_FOR_PREDICTION + 5, beans=1)
        newcomer = _history(1, beans=1, seed=7)[0]
        newcomer = replace(newcomer, bean_id=42, created_at=datetime.now(UTC))
        points = held_out_predictions([newcomer, *shots], [BeanMeanTimeModel()], "loo")
        flagged = [p.shot.bean_id for p in points if p.new_coffee]
        self.assertEqual(flagged, [42])

        result = compare_models([newcomer, *shots], [BeanMeanTimeModel()], "loo")
        self.assertEqual(result.n_new, 1)
        score = result.scores[0]
        self.assertIsNotNone(score.mae_known)
        self.assertIsNotNone(score.mae_new)
        self.assertIn("new = a coffee's first shot, n=1", result.render())

    def test_gaps_are_paired_against_the_first_model(self) -> None:
        shots = _history(MIN_SHOTS_FOR_PREDICTION + 5)
        models = [EngineTimeModel(K6), BeanMeanTimeModel()]
        result = compare_models(shots, models)
        engine, bean_mean = result.scores

        self.assertIsNone(engine.diff)
        assert bean_mean.diff is not None and bean_mean.diff_se is not None
        assert engine.mae is not None and bean_mean.mae is not None
        # On the common set the mean paired gap is exactly the MAE gap.
        self.assertAlmostEqual(bean_mean.diff, bean_mean.mae - engine.mae)
        self.assertGreater(bean_mean.diff_se, 0.0)
        self.assertIn("vs engine", result.render())


class TestChallengers(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            from core.challengers import challengers
        except ImportError:
            raise unittest.SkipTest("scikit-learn not installed ('.[ml]')") from None
        cls.models = challengers()

    def test_each_fits_and_predicts_a_finite_ln_time(self) -> None:
        shots = _history(15)
        unseen = ShotRecord(
            dose_g=18.0,
            bean_id=99,
            grind_clicks=33.0,
            yield_g=36.0,
            time_s=30.0,
        )
        for model in self.models:
            predictor = model.fit(shots)
            assert predictor is not None, model.name
            for shot in (shots[0], unseen):
                value = predictor(shot)
                assert value is not None, model.name
                self.assertTrue(math.isfinite(value), model.name)
                # ln T_r of an espresso is ~2.5-3.5; anything wild is a bug.
                self.assertLess(abs(value - 2.7), 2.0, model.name)

    def test_a_shot_without_a_grind_is_abstained_on(self) -> None:
        shot = ShotRecord(dose_g=18.0, yield_g=36.0, time_s=28.0)
        for model in self.models:
            predictor = model.fit(_history(10))
            assert predictor is not None
            self.assertIsNone(predictor(shot), model.name)

    def test_ranked_alongside_the_engine(self) -> None:
        models = [EngineTimeModel(K6), *self.models]
        result = compare_models(_history(20), models, "walk_forward")
        self.assertTrue(result.sufficient)
        self.assertTrue(all(s.mae is not None for s in result.scores))


class TestChallengersStayOffline(unittest.TestCase):
    def test_only_offline_tools_import_scikit_learn(self) -> None:
        """The web image carries no scikit-learn; a route importing it is a 500."""
        allowed = {"challengers.py", "backtest_cli.py"}
        pattern = re.compile(r"^\s*(from|import)\s+(sklearn|\S*challengers)\b", re.M)
        offenders = [
            str(path.relative_to(SRC))
            for path in SRC.rglob("*.py")
            if path.name not in allowed and pattern.search(path.read_text())
        ]
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
