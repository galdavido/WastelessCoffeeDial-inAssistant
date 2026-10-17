"""The confidence label must not call the tenth shot the first.

Confidence is zero whenever the slope is still the physical prior, and that
outlives the first shot: two coffees at two settings give no comparable pair.
A friend's prod history did exactly that and was told "First shot" three
shots in.
"""

from __future__ import annotations

import unittest

from _fixtures import K6
from core.brewing import ShotRecord, beta_prior
from core.calibration import confidence_label, fit_setup

COFFEE_A, COFFEE_B = 1, 2


def _shot(bean_id: int, clicks: float, yield_g: float, time_s: float) -> ShotRecord:
    return ShotRecord(
        dose_g=17.0,
        setup_id=6,
        bean_id=bean_id,
        grind_clicks=clicks,
        yield_g=yield_g,
        time_s=time_s,
    )


class TestConfidenceLabel(unittest.TestCase):
    def test_nothing_measured_is_a_first_shot(self) -> None:
        calibration = fit_setup([], K6, beta_prior(K6))
        self.assertTrue(confidence_label(calibration).startswith("First shot"))

    def test_shots_without_a_fitted_slope_are_not_a_first_shot(self) -> None:
        # The shape of the history that was mislabelled: one shot of one
        # coffee, two of the next, the grind moved only across coffees.
        history = [
            _shot(COFFEE_A, 25.0, 34.0, 15.0),
            _shot(COFFEE_B, 23.0, 22.0, 19.0),
            _shot(COFFEE_B, 23.0, 45.0, 27.0),
        ]
        calibration = fit_setup(history, K6, beta_prior(K6), bean_id=COFFEE_B)
        self.assertEqual(calibration.confidence, 0.0)
        label = confidence_label(calibration)
        self.assertFalse(label.startswith("First shot"), label)
        self.assertTrue(label.startswith("Low"), label)


if __name__ == "__main__":
    unittest.main()
