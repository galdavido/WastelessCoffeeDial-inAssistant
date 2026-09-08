"""Usage aggregates for the admin dashboard.

Everything here is derived from rows the app already writes: ``DialInLog`` and
``Recommendation`` both carry ``created_at`` and an indexed ``owner``, so the
numbers reach back over the whole history rather than starting the day a
dashboard shipped. Nothing new is collected about anyone.

What is deliberately *not* here: tasting notes, ratings, bean names, photos --
anything that says what a person drinks rather than whether they are using the
app. The per-owner scoping in the rest of the app exists to keep that private
and the dashboard does not undo it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Select, case, distinct, func, select
from sqlalchemy.orm import Session

from database.models import Bean, DialInLog, Recommendation

# A recommendation is "followed through" when a shot was later logged against
# it. It is the one number that says whether someone actually pulls the shot
# after asking, rather than just browsing.
_FOLLOWED = DialInLog.recommendation_id.isnot(None)


def _since(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


def _pct(part: int, whole: int) -> float | None:
    """Percentage, or ``None`` when there is nothing to take a share of."""
    if whole <= 0:
        return None
    return round(100.0 * part / whole, 1)


def _scalar_int(db: Session, stmt: Select[Any]) -> int:
    return int(db.execute(stmt).scalar_one() or 0)


def fleet_summary(db: Session, days: int) -> dict[str, Any]:
    """Headline numbers across everyone."""
    since = _since(days)
    prev_since = _since(days * 2)

    owners_total = _scalar_int(
        db, select(func.count(distinct(Bean.owner)))
    ) or _scalar_int(db, select(func.count(distinct(DialInLog.owner))))

    active_7d = _scalar_int(
        db,
        select(func.count(distinct(DialInLog.owner))).where(
            DialInLog.created_at >= _since(7)
        ),
    )
    shots = _scalar_int(
        db,
        select(func.count())
        .select_from(DialInLog)
        .where(DialInLog.created_at >= since),
    )
    shots_prev = _scalar_int(
        db,
        select(func.count())
        .select_from(DialInLog)
        .where(DialInLog.created_at >= prev_since, DialInLog.created_at < since),
    )
    recs = _scalar_int(
        db,
        select(func.count())
        .select_from(Recommendation)
        .where(Recommendation.created_at >= since),
    )
    # Recommendations in the window that a shot was later logged against.
    followed = _scalar_int(
        db,
        select(func.count(distinct(DialInLog.recommendation_id))).where(
            _FOLLOWED,
            DialInLog.recommendation_id.in_(
                select(Recommendation.id).where(Recommendation.created_at >= since)
            ),
        ),
    )

    change = None
    if shots_prev > 0:
        change = round(100.0 * (shots - shots_prev) / shots_prev, 1)

    return {
        "days": days,
        "owners_total": owners_total,
        "active_7d": active_7d,
        "shots": shots,
        "shots_change_pct": change,
        "recommendations": recs,
        "recommendations_per_day": round(recs / days, 1) if days else None,
        "follow_through_pct": _pct(followed, recs),
    }


def weekly_activity(db: Session, weeks: int = 12) -> list[dict[str, Any]]:
    """Shots, recipes and distinct people per calendar week."""
    since = _since(weeks * 7)
    week = func.date_trunc("week", DialInLog.created_at).label("week")
    rows = db.execute(
        select(
            week,
            func.count().label("shots"),
            func.count(distinct(DialInLog.owner)).label("people"),
        )
        .where(DialInLog.created_at >= since)
        .group_by(week)
        .order_by(week)
    ).all()

    rec_week = func.date_trunc("week", Recommendation.created_at).label("week")
    rec_rows: dict[datetime, int] = {
        wk: int(count)
        for wk, count in db.execute(
            select(rec_week, func.count())
            .where(Recommendation.created_at >= since)
            .group_by(rec_week)
        ).all()
    }

    return [
        {
            "week": r.week.date().isoformat(),
            "shots": int(r.shots),
            "people": int(r.people),
            "recommendations": int(rec_rows.get(r.week, 0)),
        }
        for r in rows
    ]


def method_mix(db: Session, days: int) -> list[dict[str, Any]]:
    """Share of logged shots by brew method."""
    since = _since(days)
    rows = db.execute(
        select(DialInLog.brew_method, func.count())
        .where(DialInLog.created_at >= since)
        .group_by(DialInLog.brew_method)
        .order_by(func.count().desc())
    ).all()
    total = sum(int(c) for _, c in rows)
    return [
        {
            "method": method or "unspecified",
            "shots": int(count),
            "share_pct": _pct(int(count), total),
        }
        for method, count in rows
    ]


def feature_usage(db: Session, days: int) -> dict[str, Any]:
    """How the app is used, not just how much.

    Each of these is inferred from a column the app already fills in: a shot
    that went through the wizard's timer has a pre-infusion or pause reading, a
    bag that was scanned has a photo, and a measured shot has a yield.
    """
    since = _since(days)
    row = db.execute(
        select(
            func.count().label("shots"),
            func.count(
                case(
                    (
                        DialInLog.preinfusion_s.isnot(None)
                        | DialInLog.pause_s.isnot(None),
                        1,
                    )
                )
            ).label("timed"),
            func.count(case((DialInLog.yield_g.isnot(None), 1))).label("measured"),
            func.count(case((_FOLLOWED, 1))).label("from_recipe"),
        ).where(DialInLog.created_at >= since)
    ).one()

    scanned = _scalar_int(
        db,
        select(func.count(distinct(DialInLog.bean_id))).where(
            DialInLog.created_at >= since, DialInLog.image_path.isnot(None)
        ),
    )
    bags = _scalar_int(
        db,
        select(func.count(distinct(DialInLog.bean_id))).where(
            DialInLog.created_at >= since
        ),
    )

    shots = int(row.shots)
    return {
        "timer_pct": _pct(int(row.timed), shots),
        "measured_pct": _pct(int(row.measured), shots),
        "from_recipe_pct": _pct(int(row.from_recipe), shots),
        "scanned_pct": _pct(scanned, bags),
    }


def per_owner(db: Session, days: int) -> list[dict[str, Any]]:
    """One row per person: activity only, never content."""
    since = _since(days)

    logs = db.execute(
        select(
            DialInLog.owner,
            func.count().label("shots"),
            func.min(DialInLog.created_at).label("first_seen"),
            func.max(DialInLog.created_at).label("last_seen"),
            func.count(distinct(func.date(DialInLog.created_at))).label("active_days"),
            func.count(
                case(
                    (
                        DialInLog.preinfusion_s.isnot(None)
                        | DialInLog.pause_s.isnot(None),
                        1,
                    )
                )
            ).label("timed"),
            func.count(distinct(DialInLog.recommendation_id)).label("followed"),
        )
        .where(DialInLog.created_at >= since)
        .group_by(DialInLog.owner)
    ).all()

    recs: dict[str, int] = {
        owner: int(count)
        for owner, count in db.execute(
            select(Recommendation.owner, func.count())
            .where(Recommendation.created_at >= since)
            .group_by(Recommendation.owner)
        ).all()
    }
    coffees: dict[str, int] = {
        owner: int(count)
        for owner, count in db.execute(
            select(Bean.owner, func.count()).group_by(Bean.owner)
        ).all()
    }

    # Per-person weekly shot counts, for the sparklines.
    week = func.date_trunc("week", DialInLog.created_at).label("week")
    spark: dict[str, dict[str, int]] = {}
    for owner, wk, count in db.execute(
        select(DialInLog.owner, week, func.count())
        .where(DialInLog.created_at >= _since(84))
        .group_by(DialInLog.owner, week)
        .order_by(week)
    ).all():
        spark.setdefault(owner, {})[wk.date().isoformat()] = int(count)

    out: list[dict[str, Any]] = []
    for r in logs:
        rec_count = recs.get(r.owner, 0)
        out.append(
            {
                "owner": r.owner,
                "shots": int(r.shots),
                "coffees": coffees.get(r.owner, 0),
                "recommendations": rec_count,
                "first_seen": r.first_seen.date().isoformat() if r.first_seen else None,
                "last_seen": r.last_seen.isoformat() if r.last_seen else None,
                "active_days": int(r.active_days),
                "timer_pct": _pct(int(r.timed), int(r.shots)),
                "follow_through_pct": _pct(int(r.followed), rec_count),
                "weekly": spark.get(r.owner, {}),
            }
        )

    # People who asked for recipes in the window but never logged a shot would
    # otherwise vanish from the table entirely, which is exactly the drop-off
    # worth seeing.
    for owner, count in recs.items():
        if not any(row["owner"] == owner for row in out):
            out.append(
                {
                    "owner": owner,
                    "shots": 0,
                    "coffees": coffees.get(owner, 0),
                    "recommendations": count,
                    "first_seen": None,
                    "last_seen": None,
                    "active_days": 0,
                    "timer_pct": None,
                    "follow_through_pct": 0.0,
                    "weekly": {},
                }
            )

    out.sort(key=lambda row: row["shots"], reverse=True)
    return out


def dashboard(db: Session, days: int) -> dict[str, Any]:
    return {
        "summary": fleet_summary(db, days),
        "weekly": weekly_activity(db),
        "methods": method_mix(db, days),
        "usage": feature_usage(db, days),
        "people": per_owner(db, days),
        "generated_at": datetime.now(UTC).isoformat(),
    }
