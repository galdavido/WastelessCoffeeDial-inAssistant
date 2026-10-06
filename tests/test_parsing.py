"""Text, date, grind and roast-level parsing (core.parsing).

A missing or misread value must stay missing: it may never be turned into a
number the user did not give. DB-free.
"""

from __future__ import annotations

import unittest
from datetime import date, timedelta

from core.parsing import (
    parse_grind_clicks,
    parse_roast_date,
    plausible_roast_date,
    roast_level_ordinal,
)


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

    def test_trade_names_and_a_trailing_roast_are_understood(self) -> None:
        self.assertEqual(roast_level_ordinal("Light Roast"), 1)
        self.assertEqual(roast_level_ordinal("Nordic"), 1)
        self.assertEqual(roast_level_ordinal("Medium Dark Roast"), 4)
        self.assertEqual(roast_level_ordinal("French roast"), 5)


class TestParseRoastDate(unittest.TestCase):
    """A misread year must not reach the engine as days-since-roast."""

    def test_recent_dates_parse_in_the_usual_formats(self) -> None:
        recent = date.today() - timedelta(days=10)
        for text in (recent.isoformat(), recent.strftime("%d.%m.%Y")):
            self.assertEqual(parse_roast_date(text), recent)

    def test_a_year_misread_into_the_past_is_dropped(self) -> None:
        # The Nicaragua bag: roasted 2026, scanned as 2023.
        self.assertIsNone(parse_roast_date("2023-09-20"))

    def test_a_date_in_the_future_is_dropped(self) -> None:
        later = date.today() + timedelta(days=30)
        self.assertIsNone(parse_roast_date(later.isoformat()))

    def test_the_plausible_window(self) -> None:
        today = date(2026, 10, 2)
        self.assertTrue(plausible_roast_date(today, today))
        self.assertTrue(plausible_roast_date(date(2026, 10, 3), today))
        self.assertTrue(plausible_roast_date(date(2025, 10, 2), today))
        self.assertFalse(plausible_roast_date(date(2025, 10, 1), today))
        self.assertFalse(plausible_roast_date(date(2026, 10, 4), today))


if __name__ == "__main__":
    unittest.main()
