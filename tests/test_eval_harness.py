"""Backtest the engine against simulated histories.

Runs in CI with no database: the simulator supplies histories that a real
user has not logged yet, so the harness itself is verified before there is
anything real to measure.

The most important assertions here are the ones about *insufficient* data.
A metric that quietly reports a number computed from three shots would be
worse than useless -- it would look like evidence.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from core.brewing import GrinderCaps, MachineCaps, ShotRecord, target_for
from core.eval_harness import (
    MIN_PAIRS_FOR_DIRECTION,
    MIN_SHOTS_FOR_PREDICTION,
    backtest,
    cold_start_abstention,
    guardrail_violations,
    held_out_time_error,
)
from core.sim import BedParams, simulate_shot

K6 = GrinderCaps(
    min_clicks=0.0,
    max_clicks=180.0,
    step_clicks=1.0,
    um_per_click=16.0,
    finer_direction="lower_is_finer",
)
MACHINE = MachineCaps(basket_size_g=18.0, temp_controllable=False)
TARGET = target_for("espresso")


def _history(clicks: list[float]) -> list[ShotRecord]:
    """A plausible measured history at the given settings."""
    base = datetime(2026, 1, 1, tzinfo=UTC)
    bed = BedParams(dose_g=18.0)
    out = []
    for i, c in enumerate(clicks):
        sim = simulate_shot(c, K6, bed, target_yield_g=36.0)
        out.append(
            ShotRecord(
                method="espresso",
                dose_g=18.0,
                setup_id=1,
                bean_id=1,
                grind_clicks=c,
                yield_g=36.0,
                time_s=sim.time_s,
                taste_axis=sim.taste_axis,
                rating=4 if sim.taste_axis == "balanced" else 2,
                created_at=base + timedelta(days=i),
            )
        )
    return out


class TestDataGating(unittest.TestCase):
    def test_empty_history_reports_insufficient_not_zero(self) -> None:
        """Today's real state. Reporting 0.0 here would look like a result."""
        report = backtest([], TARGET, K6, MACHINE)
        rendered = report.render()
        self.assertIn("INSUFFICIENT DATA", rendered)
        for metric in report.metrics:
            if metric.name.startswith(("M1", "M2", "M3")):
                self.assertFalse(metric.sufficient, metric.name)

    def test_a_handful_of_shots_is_still_insufficient(self) -> None:
        report = backtest(_history([30, 33, 36]), TARGET, K6, MACHINE)
        m3 = next(m for m in report.metrics if m.name.startswith("M3"))
        self.assertFalse(m3.sufficient)
        self.assertIn("INSUFFICIENT DATA", m3.render())

    def test_thresholds_are_honest_about_what_they_need(self) -> None:
        report = backtest(_history([30, 33, 36]), TARGET, K6, MACHINE)
        m1 = next(m for m in report.metrics if m.name.startswith("M1"))
        m3 = next(m for m in report.metrics if m.name.startswith("M3"))
        self.assertEqual(m1.required, MIN_PAIRS_FOR_DIRECTION)
        self.assertEqual(m3.required, MIN_SHOTS_FOR_PREDICTION)


class TestPredictionMetric(unittest.TestCase):
    def test_enough_shots_unlocks_the_prediction_metric(self) -> None:
        # M3 needs no ratings and no taste, so it goes green first.
        history = _history([float(c) for c in range(28, 50)])
        metric = held_out_time_error(history, "espresso", K6)
        self.assertTrue(metric.sufficient, metric.render())
        assert metric.value is not None
        # Predicting log-time to within ~0.5 nats is a loose but real bar.
        self.assertLess(metric.value, 0.5)

    def test_prediction_beats_the_unfitted_prior(self) -> None:
        """If calibration does not beat its own prior, it earns nothing."""
        history = _history([float(c) for c in range(28, 50)])
        metric = held_out_time_error(history, "espresso", K6)
        if metric.baselines.get("prior_only") is not None:
            assert metric.value is not None
            self.assertLessEqual(metric.value, metric.baselines["prior_only"])


class TestInvariantMetrics(unittest.TestCase):
    def test_guardrail_violations_are_zero(self) -> None:
        """M4 is a regression test: any violation is a bug, not a score."""
        history = _history([float(c) for c in range(20, 50, 2)])
        metric = guardrail_violations(history, TARGET, K6, MACHINE, "espresso")
        self.assertTrue(metric.sufficient)
        self.assertEqual(metric.value, 0.0)

    def test_engine_abstains_when_it_cannot_locate_the_dial(self) -> None:
        """M5 must be 1.0: no micron-per-click means no invented number."""
        unlocatable = GrinderCaps(min_clicks=0.0, max_clicks=100.0)
        metric = cold_start_abstention([unlocatable], "espresso")
        self.assertEqual(metric.value, 1.0)


class TestReportRendering(unittest.TestCase):
    def test_report_renders_every_metric(self) -> None:
        report = backtest(_history([30, 33, 36]), TARGET, K6, MACHINE)
        rendered = report.render()
        for prefix in ("M1", "M2", "M3", "M4", "M5"):
            self.assertIn(prefix, rendered)


if __name__ == "__main__":
    unittest.main()
