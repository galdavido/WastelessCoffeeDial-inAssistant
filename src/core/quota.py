"""How much Gemini an owner is allowed to spend, and what has been spent.

The API key is one shared credential with a daily ceiling. Before this
existed nothing counted what the app spent against it, so a single
enthusiastic user -- or anyone who found the endpoint -- could exhaust it
for everybody, and the first symptom would be bag scans quietly failing.

Two call kinds are metered, and they fail very differently on purpose:

* ``VISION`` reads a coffee bag. There is no non-AI way to do it, so over
  quota this **blocks** with a 429.
* ``RATIONALE`` writes the prose around a recipe. ``ai.rationale`` already
  has a deterministic template for it, so over quota this **degrades** and
  the user still gets a recipe. The numbers are identical either way --
  the engine fixes every one of them and ``scrub_numerals`` rejects any
  figure the model invents -- so nothing is lost but the phrasing.

Entitlement is deliberately dumb for now: an env allowlist. It is the seam
a real subscription entitlement table replaces later, and nothing above
``is_entitled`` needs to know which it is.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from database.models import AiUsage

from .auth import auth_mode


class AiCall(StrEnum):
    VISION = "vision"
    RATIONALE = "rationale"


# Defaults, all overridable. A negative limit means unlimited; zero means the
# call is never made on that tier, which is how the free tier gets template
# prose without a special case anywhere.
_DEFAULT_LIMITS: dict[tuple[AiCall, bool], int] = {
    (AiCall.VISION, False): 5,
    (AiCall.VISION, True): 100,
    (AiCall.RATIONALE, False): 0,
    (AiCall.RATIONALE, True): -1,
}

_LIMIT_ENV: dict[tuple[AiCall, bool], str] = {
    (AiCall.VISION, False): "WCDA_FREE_SCANS_PER_MONTH",
    (AiCall.VISION, True): "WCDA_PAID_SCANS_PER_MONTH",
    (AiCall.RATIONALE, False): "WCDA_FREE_PROSE_PER_MONTH",
    (AiCall.RATIONALE, True): "WCDA_PAID_PROSE_PER_MONTH",
}


@dataclass(frozen=True)
class Allowance:
    """What is left of one call kind this month."""

    kind: AiCall
    used: int
    # None means unlimited, which is not the same as a large number: the UI
    # should say "unlimited" rather than count down from it.
    limit: int | None

    @property
    def remaining(self) -> int | None:
        if self.limit is None:
            return None
        return max(0, self.limit - self.used)

    @property
    def exhausted(self) -> bool:
        return self.limit is not None and self.used >= self.limit


def current_period(now: datetime | None = None) -> str:
    """The calendar month a call counts against, in UTC."""
    moment = now or datetime.now(UTC)
    return f"{moment.year:04d}-{moment.month:02d}"


def resets_on(now: datetime | None = None) -> str:
    """First day of next month, for telling the user when they get more."""
    moment = now or datetime.now(UTC)
    year, month = moment.year, moment.month
    if month == 12:
        year, month = year + 1, 1
    else:
        month += 1
    return f"{year:04d}-{month:02d}-01"


def _entitled_owners() -> set[str]:
    raw = os.getenv("WCDA_ENTITLED_OWNERS", "")
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def is_entitled(owner: str) -> bool:
    """Whether this owner is on the paid tier.

    ``single`` mode is always entitled and unmetered: that instance is the
    owner's own machine using the owner's own key, and a quota there would
    be the app rationing its operator against themselves.

    Everywhere else this is the env allowlist, which is the seam a real
    subscription entitlement lookup replaces.
    """
    if auth_mode() == "single":
        return True
    return owner.strip().lower() in _entitled_owners()


def is_metered(owner: str) -> bool:
    """Whether this owner's calls are counted at all."""
    return auth_mode() != "single"


def limit_for(kind: AiCall, *, entitled: bool) -> int | None:
    env_name = _LIMIT_ENV[(kind, entitled)]
    raw = os.getenv(env_name, "").strip()
    if raw:
        try:
            configured = int(raw)
        except ValueError:
            configured = _DEFAULT_LIMITS[(kind, entitled)]
    else:
        configured = _DEFAULT_LIMITS[(kind, entitled)]
    return None if configured < 0 else configured


def used(db: Session, owner: str, kind: AiCall, *, period: str | None = None) -> int:
    total = db.execute(
        select(func.coalesce(func.sum(AiUsage.count), 0)).where(
            AiUsage.owner == owner,
            AiUsage.period == (period or current_period()),
            AiUsage.kind == kind.value,
        )
    ).scalar_one()
    return int(total or 0)


def allowance(db: Session, owner: str, kind: AiCall) -> Allowance:
    if not is_metered(owner):
        return Allowance(kind=kind, used=0, limit=None)
    entitled = is_entitled(owner)
    return Allowance(
        kind=kind, used=used(db, owner, kind), limit=limit_for(kind, entitled=entitled)
    )


def consume(db: Session, owner: str, kind: AiCall, *, commit: bool = False) -> int:
    """Record one call and return the owner's new total for the month.

    ``commit`` exists for the vision path, which spends the quota *before*
    calling Gemini. Left in the caller's transaction, a later failure would
    roll the counter back and hand out a free call -- which is exactly the
    hole an attacker would use, by uploading something that always fails.
    """
    if not is_metered(owner):
        return 0

    statement = (
        pg_insert(AiUsage)
        .values(owner=owner, period=current_period(), kind=kind.value, count=1)
        .on_conflict_do_update(
            constraint="uq_ai_usage_owner_period_kind",
            set_={"count": AiUsage.__table__.c.count + 1, "updated_at": func.now()},
        )
        .returning(AiUsage.__table__.c.count)
    )
    total = db.execute(statement).scalar_one()
    if commit:
        db.commit()
    return int(total)


def report(db: Session, owner: str) -> dict[str, Any]:
    """What `GET /api/usage` returns, and what a paywall would read."""
    entitled = is_entitled(owner)
    allowances = {kind: allowance(db, owner, kind) for kind in AiCall}
    return {
        "entitled": entitled,
        "metered": is_metered(owner),
        "period": current_period(),
        "resets_on": resets_on(),
        "calls": {
            kind.value: {
                "used": item.used,
                "limit": item.limit,
                "remaining": item.remaining,
                "exhausted": item.exhausted,
            }
            for kind, item in allowances.items()
        },
    }
