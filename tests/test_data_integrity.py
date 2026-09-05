"""Regression tests for the log data-integrity rules.

Older builds fabricated measurements the user never took: yield_g = dose*2,
time_s = 28, rating = 5, plus the LLM's own recommendation prose written into
tasting_notes. Those rows were then retrieved as "past successful shots" and
fed back into the next prompt, so the system trained on its own output.

These tests pin the rules that stop that happening again. They are DB-free,
following the pattern in test_web_app.py.
"""

from __future__ import annotations

import unittest

from core.web_helpers import (
    classify_data_quality,
    parse_grind_clicks,
    roast_level_ordinal,
)
from core.web_schemas import LogDetailsInput


class _FakeDB:
    """Stands in for a Session: resolve_log_values only reads the dose setting."""

    def query(self, *_args: object, **_kwargs: object) -> _FakeDB:
        return self

    def filter(self, *_args: object, **_kwargs: object) -> _FakeDB:
        return self

    def first(self) -> None:
        return None


class TestParseGrindClicks(unittest.TestCase):
    def test_parses_plain_and_suffixed_numbers(self) -> None:
        self.assertEqual(parse_grind_clicks("38"), 38.0)
        self.assertEqual(parse_grind_clicks("33 clicks"), 33.0)
        self.assertEqual(parse_grind_clicks("2,5"), 2.5)
        self.assertEqual(parse_grind_clicks(34), 34.0)

    def test_unparseable_grind_stays_none(self) -> None:
        # A missing grind value must never become a number.
        self.assertIsNone(parse_grind_clicks("Unknown"))
        self.assertIsNone(parse_grind_clicks(""))
        self.assertIsNone(parse_grind_clicks(None))


class TestRoastLevelOrdinal(unittest.TestCase):
    def test_all_spellings_of_medium_light_agree(self) -> None:
        # Production contains all three of these for the same roast.
        for label in ("Medium-light", "Medium Light", "Medium-Light"):
            self.assertEqual(roast_level_ordinal(label), 2, label)

    def test_scale_runs_light_to_dark(self) -> None:
        self.assertEqual(roast_level_ordinal("Light"), 1)
        self.assertEqual(roast_level_ordinal("Medium"), 3)
        self.assertEqual(roast_level_ordinal("Medium-Dark"), 4)
        self.assertEqual(roast_level_ordinal("Dark"), 5)

    def test_unknown_label_is_none(self) -> None:
        self.assertIsNone(roast_level_ordinal("Rocket Fuel"))
        self.assertIsNone(roast_level_ordinal(None))


class TestClassifyDataQuality(unittest.TestCase):
    def test_complete_shot_is_measured(self) -> None:
        self.assertEqual(
            classify_data_quality(
                grind_clicks=33.0,
                time_s=27,
                yield_g=32.0,
                water_g=None,
                rating=4,
                taste_axis=None,
            ),
            "measured",
        )

    def test_taste_axis_alone_satisfies_the_outcome_requirement(self) -> None:
        self.assertEqual(
            classify_data_quality(
                grind_clicks=33.0,
                time_s=27,
                yield_g=None,
                water_g=250.0,
                rating=None,
                taste_axis="sour",
            ),
            "measured",
        )

    def test_missing_measurements_downgrade_to_partial(self) -> None:
        # Each of these alone is enough to keep a row out of calibration.
        for kwargs in (
            {"grind_clicks": None},
            {"time_s": None},
            {"yield_g": None, "water_g": None},
            {"rating": None, "taste_axis": None},
        ):
            base = {
                "grind_clicks": 33.0,
                "time_s": 27,
                "yield_g": 32.0,
                "water_g": None,
                "rating": 4,
                "taste_axis": None,
            }
            base.update(kwargs)
            self.assertEqual(classify_data_quality(**base), "partial", kwargs)


class TestResolveLogValuesDoesNotFabricate(unittest.TestCase):
    def test_absent_measurements_stay_none(self) -> None:
        from core.web_helpers import resolve_log_values

        values = resolve_log_values(LogDetailsInput(), _FakeDB())

        # The exact fabrications this project used to write.
        self.assertIsNone(values["yield_g"], "yield_g must not default to dose*2")
        self.assertIsNone(values["time_s"], "time_s must not default to 28")
        self.assertIsNone(values["rating"], "rating must not default to 5")
        self.assertEqual(values["data_quality"], "partial")

    def test_dose_still_falls_back_to_the_stored_preference(self) -> None:
        # The dose default is a real user preference, not a guessed outcome.
        from core.web_helpers import resolve_log_values

        values = resolve_log_values(LogDetailsInput(), _FakeDB())
        self.assertEqual(values["dose_g"], 16.0)

    def test_supplied_measurements_are_kept_and_marked_measured(self) -> None:
        from core.web_helpers import resolve_log_values

        values = resolve_log_values(
            LogDetailsInput(
                grind_setting="33",
                dose_g=18.0,
                yield_g=36.0,
                time_s=29,
                rating=4,
            ),
            _FakeDB(),
        )
        self.assertEqual(values["yield_g"], 36.0)
        self.assertEqual(values["time_s"], 29)
        self.assertEqual(values["grind_clicks"], 33.0)
        self.assertEqual(values["data_quality"], "measured")


if __name__ == "__main__":
    unittest.main()
