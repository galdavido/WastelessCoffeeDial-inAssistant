"""The recents list must keep showing a coffee's bag photo after later shots.

The photo is captured once, on the first shot after a scan; every later shot
is logged with no image. `GET /api/logs` used to read the photo from each
coffee's newest log, so a coffee's card lost its bag photo the moment a second
shot was recorded. `latest_photo_log` is what looks past the newest log to the
most recent one that actually carries a photo.

DB-free, following the pattern in test_web_app.py.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from core.web_helpers import latest_photo_log


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


if __name__ == "__main__":
    unittest.main()
