"""Bean helpers (core.beans): recents photo, transient beans, starting dose.

The recents list must keep showing a coffee's bag photo after later shots.

The photo is captured once, on the first shot after a scan; every later shot
is logged with no image. `GET /api/logs` used to read the photo from each
coffee's newest log, so a coffee's card lost its bag photo the moment a second
shot was recorded. `latest_photo_log` is what looks past the newest log to the
most recent one that actually carries a photo.

DB-free.
"""

from __future__ import annotations

import unittest
from datetime import UTC, date, datetime, timedelta

from core.beans import latest_photo_log, starting_dose_for_roast, transient_bean
from core.parsing import roast_level_ordinal


class _FakeLog:
    def __init__(self, created_at: datetime, image_path: str | None) -> None:
        self.created_at = created_at
        self.image_path = image_path


_T0 = datetime(2026, 9, 6, 8, 0, tzinfo=UTC)


class TestLatestPhotoLog(unittest.TestCase):
    def test_returns_none_when_no_log_has_a_photo(self) -> None:
        logs = [_FakeLog(_T0, None), _FakeLog(_T0 + timedelta(days=1), None)]
        self.assertIsNone(latest_photo_log(logs))

    def test_returns_none_for_a_coffee_with_no_shots(self) -> None:
        self.assertIsNone(latest_photo_log([]))

    def test_finds_the_photo_on_an_older_shot(self) -> None:
        first = _FakeLog(_T0, "abc.jpg")
        second = _FakeLog(_T0 + timedelta(days=1), None)
        third = _FakeLog(_T0 + timedelta(days=2), None)
        self.assertIs(latest_photo_log([third, first, second]), first)

    def test_prefers_the_most_recent_photo_when_several_shots_have_one(self) -> None:
        older = _FakeLog(_T0, "old.jpg")
        newer = _FakeLog(_T0 + timedelta(days=3), "new.jpg")
        between = _FakeLog(_T0 + timedelta(days=1), None)
        self.assertIs(latest_photo_log([older, between, newer]), newer)


class TestTransientBean(unittest.TestCase):
    def test_transient_bean_carries_roast_fields(self) -> None:
        bean = transient_bean(
            "me",
            {"name": "X", "roast_level": "Medium-dark", "roast_date": "2026-09-01"},
        )
        self.assertEqual(bean.roast_level_ord, roast_level_ordinal("Medium-dark"))
        self.assertEqual(bean.roast_date, date(2026, 9, 1))
        self.assertEqual(bean.owner, "me")
        self.assertEqual(bean.origin, "Unknown")


class TestStartingDose(unittest.TestCase):
    def test_lighter_roasts_start_with_more_coffee(self) -> None:
        doses = [starting_dose_for_roast(o) for o in (1, 2, 3, 4, 5)]
        self.assertEqual(doses, sorted(doses, reverse=True))
        self.assertIsNone(starting_dose_for_roast(None))

    def test_without_a_basket_it_is_the_old_18_g_table(self) -> None:
        doses = [starting_dose_for_roast(o) for o in (1, 2, 3, 4, 5)]
        self.assertEqual(doses, [18.5, 18.5, 17.5, 17.0, 16.5])

    def test_it_scales_with_the_brewers_basket(self) -> None:
        # A 14 g basket: light 14.42 -> 14.5, dark 12.88 -> 13.0.
        self.assertEqual(starting_dose_for_roast(1, 14.0), 14.5)
        self.assertEqual(starting_dose_for_roast(5, 14.0), 13.0)
        # A 22 g basket: light 22.66 -> 22.5.
        self.assertEqual(starting_dose_for_roast(1, 22.0), 22.5)


if __name__ == "__main__":
    unittest.main()
