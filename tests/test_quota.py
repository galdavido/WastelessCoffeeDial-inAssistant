"""The AI spending limits, and who they apply to.

DB-free: everything the policy actually decides -- what a tier is allowed,
who counts as paid, which month a call lands in -- is a pure function over
environment and arguments. Only the counter itself needs Postgres, and that
is exercised through the routes in CI.
"""

from __future__ import annotations

import os
import unittest
from contextlib import contextmanager
from datetime import UTC, datetime

from core.quota import (
    AiCall,
    Allowance,
    current_period,
    is_entitled,
    is_metered,
    limit_for,
    resets_on,
)


@contextmanager
def env(**values: str | None):
    """Set env vars for one block, restoring whatever was there."""
    previous = {key: os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, was in previous.items():
            if was is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = was


class TestPeriod(unittest.TestCase):
    def test_period_is_the_calendar_month_in_utc(self) -> None:
        self.assertEqual(
            current_period(datetime(2026, 9, 20, 10, 0, tzinfo=UTC)), "2026-09"
        )
        self.assertEqual(
            current_period(datetime(2026, 1, 1, 0, 0, tzinfo=UTC)), "2026-01"
        )

    def test_reset_date_rolls_over_the_year(self) -> None:
        self.assertEqual(resets_on(datetime(2026, 9, 20, tzinfo=UTC)), "2026-10-01")
        # December must not produce month 13.
        self.assertEqual(
            resets_on(datetime(2026, 12, 31, 23, 59, tzinfo=UTC)), "2027-01-01"
        )


class TestLimits(unittest.TestCase):
    def test_defaults_match_the_advertised_tiers(self) -> None:
        with env(
            WCDA_FREE_SCANS_PER_MONTH=None,
            WCDA_PAID_SCANS_PER_MONTH=None,
            WCDA_FREE_PROSE_PER_MONTH=None,
            WCDA_PAID_PROSE_PER_MONTH=None,
        ):
            self.assertEqual(limit_for(AiCall.VISION, entitled=False), 5)
            self.assertEqual(limit_for(AiCall.VISION, entitled=True), 100)
            # Zero, not None: the free tier never makes the call, which is
            # how it gets template prose without a special case.
            self.assertEqual(limit_for(AiCall.RATIONALE, entitled=False), 0)
            # Negative means unlimited, and unlimited is None rather than a
            # large number so the UI can say so.
            self.assertIsNone(limit_for(AiCall.RATIONALE, entitled=True))

    def test_env_overrides_each_tier_independently(self) -> None:
        with env(WCDA_FREE_SCANS_PER_MONTH="2", WCDA_PAID_SCANS_PER_MONTH="500"):
            self.assertEqual(limit_for(AiCall.VISION, entitled=False), 2)
            self.assertEqual(limit_for(AiCall.VISION, entitled=True), 500)

    def test_unlimited_is_expressed_as_a_negative_limit(self) -> None:
        with env(WCDA_FREE_SCANS_PER_MONTH="-1"):
            self.assertIsNone(limit_for(AiCall.VISION, entitled=False))

    def test_junk_falls_back_to_the_default_rather_than_crashing(self) -> None:
        # A typo in a compose file must not take the app down, and must not
        # silently mean "unlimited" either.
        with env(WCDA_FREE_SCANS_PER_MONTH="five"):
            self.assertEqual(limit_for(AiCall.VISION, entitled=False), 5)


class TestEntitlement(unittest.TestCase):
    def test_single_user_mode_is_never_rationed(self) -> None:
        """That instance is the owner's own machine using the owner's own
        key. A quota there is the app rationing its operator."""
        with env(WCDA_AUTH_MODE="single", WCDA_ENTITLED_OWNERS=None):
            self.assertTrue(is_entitled("owner"))
            self.assertFalse(is_metered("owner"))

    def test_shared_instances_are_metered(self) -> None:
        with env(WCDA_AUTH_MODE="tailscale", WCDA_ENTITLED_OWNERS=None):
            self.assertTrue(is_metered("someone@example.com"))
            self.assertFalse(is_entitled("someone@example.com"))

    def test_allowlist_grants_the_paid_tier(self) -> None:
        with env(
            WCDA_AUTH_MODE="tailscale",
            WCDA_ENTITLED_OWNERS=" Friend@Example.com , other@example.com ",
        ):
            # Matching ignores case and padding: the list is hand-edited in a
            # compose file, and a stray space must not silently downgrade
            # someone who is paying.
            self.assertTrue(is_entitled("friend@example.com"))
            self.assertTrue(is_entitled("other@example.com"))
            self.assertFalse(is_entitled("stranger@example.com"))


class TestAllowance(unittest.TestCase):
    def test_remaining_counts_down_and_floors_at_zero(self) -> None:
        self.assertEqual(Allowance(AiCall.VISION, used=2, limit=5).remaining, 3)
        # Over the line (a limit lowered mid-month) must read as 0, not -2.
        self.assertEqual(Allowance(AiCall.VISION, used=7, limit=5).remaining, 0)

    def test_exhausted_is_inclusive_of_the_limit(self) -> None:
        self.assertFalse(Allowance(AiCall.VISION, used=4, limit=5).exhausted)
        self.assertTrue(Allowance(AiCall.VISION, used=5, limit=5).exhausted)

    def test_a_zero_limit_is_exhausted_from_the_start(self) -> None:
        self.assertTrue(Allowance(AiCall.RATIONALE, used=0, limit=0).exhausted)

    def test_unlimited_never_exhausts_and_has_no_remaining_count(self) -> None:
        unlimited = Allowance(AiCall.RATIONALE, used=9_999, limit=None)
        self.assertFalse(unlimited.exhausted)
        self.assertIsNone(unlimited.remaining)


if __name__ == "__main__":
    unittest.main()
