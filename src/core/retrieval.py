"""Find the past shots worth learning from.

Replaces the exact-string matching that used to live in ai/rag.py
(`Bean.process == x OR Bean.origin == y`, filtered to `rating >= 4`), which
returned nothing at all for a coffee the user had not brewed before -- the
common case -- and conflated two different questions.

Those questions are kept apart here:

* **Calibration shots** answer "how does this grinder behave?". Physics does
  not care whether a shot tasted nice, so there is deliberately no rating
  filter -- only a completeness one. A bad-tasting shot with a recorded time
  is excellent calibration data.
* **Exemplars** answer "what worked on a coffee like this one?" and are
  ranked by a structured, explainable similarity score.

Both read only `data_quality = 'measured'`, so the fabricated rows quarantined
by migration 0003 can never come back.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import Bean, BrewSetup, DialInLog

from .brewing import Method, ShotRecord, value_of

# Coarse regional buckets, so a Kenyan bean is a partial match for an
# Ethiopian one but not for a Brazilian.
_REGIONS: dict[str, set[str]] = {
    "east_africa": {"ethiopia", "kenya", "rwanda", "burundi", "tanzania", "uganda"},
    "central_america": {
        "guatemala",
        "costa rica",
        "honduras",
        "nicaragua",
        "el salvador",
        "mexico",
        "panama",
    },
    "south_america": {"brazil", "colombia", "peru", "bolivia", "ecuador"},
    "asia_pacific": {"indonesia", "vietnam", "india", "papua new guinea", "sumatra"},
}

_PROCESS_ALIASES: dict[str, str] = {
    "washed": "washed",
    "wet": "washed",
    "fully washed": "washed",
    "natural": "natural",
    "dry": "natural",
    "honey": "honey",
    "pulped natural": "honey",
    "anaerobic": "anaerobic",
}

CalibrationTier = Literal["A", "B", "C", "D", "E"]


@dataclass(frozen=True)
class BeanFeatures:
    roast_level_ord: int | None = None
    process: str | None = None
    origin: str | None = None
    days_since_roast: int | None = None


def canonical_process(value: str | None) -> str | None:
    if not value:
        return None
    return _PROCESS_ALIASES.get(value.strip().lower())


def _region_of(origin: str | None) -> str | None:
    if not origin:
        return None
    key = origin.strip().lower()
    for region, countries in _REGIONS.items():
        if any(country in key for country in countries):
            return region
    return None


def similarity(
    target: BeanFeatures, candidate: BeanFeatures, same_setup: bool
) -> float:
    """How much this past shot should inform the current coffee.

    Deterministic and explainable by design: the user can be told exactly why
    a shot was considered relevant, which an embedding cannot do.
    """
    score = 0.0

    if same_setup:
        # Dominant: a click number from a different grinder means very little.
        score += value_of("similarity_setup")

    if target.roast_level_ord is not None and candidate.roast_level_ord is not None:
        closeness = 1.0 - abs(target.roast_level_ord - candidate.roast_level_ord) / 4.0
        score += value_of("similarity_roast") * max(0.0, closeness)

    t_proc = canonical_process(target.process)
    c_proc = canonical_process(candidate.process)
    if t_proc and c_proc and t_proc == c_proc:
        score += value_of("similarity_process")

    if target.origin and candidate.origin:
        if target.origin.strip().lower() == candidate.origin.strip().lower():
            score += value_of("similarity_origin")
        else:
            t_region, c_region = _region_of(target.origin), _region_of(candidate.origin)
            if t_region and t_region == c_region:
                score += value_of("similarity_origin") * 0.5

    if target.days_since_roast is not None and candidate.days_since_roast is not None:
        delta = min(abs(target.days_since_roast - candidate.days_since_roast), 21)
        score += value_of("similarity_freshness") * (1.0 - delta / 21.0)

    return score


def recency_factor(created_at: datetime | None, now: datetime | None = None) -> float:
    """Older shots count for less: burrs wear, retention changes, palates shift."""
    if created_at is None:
        return 1.0
    now = now or datetime.now(UTC)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    weeks = max(0.0, (now - created_at).days / 7.0)
    return max(0.7, value_of("similarity_recency_decay") ** weeks)


def to_shot_record(log: DialInLog, bean: Bean | None, method: Method) -> ShotRecord:
    days = None
    if bean is not None and bean.roast_date is not None and log.created_at is not None:
        days = (log.created_at.date() - bean.roast_date).days
    return ShotRecord(
        method=method,
        dose_g=float(log.dose_g),
        setup_id=log.setup_id,
        bean_id=log.bean_id,
        grind_clicks=float(log.grind_clicks) if log.grind_clicks is not None else None,
        yield_g=float(log.yield_g) if log.yield_g is not None else None,
        water_g=float(log.water_g) if log.water_g is not None else None,
        time_s=float(log.time_s) if log.time_s is not None else None,
        taste_axis=log.taste_axis,  # type: ignore[arg-type]
        astringent=log.astringent,
        brew_temp_c=float(log.brew_temp_c) if log.brew_temp_c is not None else None,
        preinfusion_s=(
            float(log.preinfusion_s) if log.preinfusion_s is not None else None
        ),
        pause_s=float(log.pause_s) if log.pause_s is not None else None,
        rating=log.rating,
        days_since_roast=days,
        created_at=log.created_at,
    )


def fetch_calibration_shots(
    db: Session, setup_id: int | None, method: Method
) -> list[ShotRecord]:
    """Shots usable for fitting the grind law.

    No rating filter on purpose: a shot that tasted terrible but has a
    recorded grind and time is perfectly good physics.
    """
    if setup_id is None:
        return []
    stmt = (
        select(DialInLog, Bean)
        .join(Bean, DialInLog.bean_id == Bean.id)
        .where(DialInLog.setup_id == setup_id)
        .where(DialInLog.data_quality == "measured")
        .where(DialInLog.grind_clicks.is_not(None))
        .where(DialInLog.time_s.is_not(None))
        .order_by(DialInLog.created_at.desc())
    )
    return [
        to_shot_record(log, bean, method) for log, bean in db.execute(stmt).tuples()
    ]


def fetch_exemplars(
    db: Session,
    target: BeanFeatures,
    setup_id: int | None,
    method: Method,
    limit: int = 8,
) -> list[tuple[ShotRecord, float]]:
    """Well-rated past shots on similar coffee, best match first."""
    stmt = (
        select(DialInLog, Bean)
        .join(Bean, DialInLog.bean_id == Bean.id)
        .where(DialInLog.data_quality == "measured")
        .where(DialInLog.rating.is_not(None))
        .where(DialInLog.rating >= 4)
    )
    scored: list[tuple[ShotRecord, float]] = []
    floor = value_of("similarity_floor")
    for log, bean in db.execute(stmt).tuples():
        candidate = BeanFeatures(
            roast_level_ord=bean.roast_level_ord,
            process=bean.process,
            origin=bean.origin,
        )
        score = similarity(target, candidate, same_setup=log.setup_id == setup_id)
        score *= recency_factor(log.created_at)
        if score >= floor:
            scored.append((to_shot_record(log, bean, method), score))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:limit]


def classify_tier(
    calibration_shots: Sequence[ShotRecord],
    bean_id: int | None,
    has_hardware_caps: bool,
) -> CalibrationTier:
    """Which cold-start tier this recommendation falls into.

    Tier E is the honest one: with no measured shots *and* no hardware range,
    there is genuinely no information from which to name a click number, so
    the engine says so and asks for one measurement instead of inventing a
    starting point.
    """
    usable = [
        s
        for s in calibration_shots
        if s.grind_clicks is not None and s.time_s is not None
    ]
    same_bean = [s for s in usable if bean_id is not None and s.bean_id == bean_id]

    if len(same_bean) >= 3 and len({s.grind_clicks for s in same_bean}) >= 2:
        return "A"
    if len(usable) >= 3:
        return "B"
    if len(usable) >= 1:
        return "C"
    return "D" if has_hardware_caps else "E"


CALIBRATION_PROTOCOL = (
    "I don't know this grinder's range yet, so any click number I gave you "
    "would be invented. Set it to the middle of its range, pull {dose:g} g in "
    "to {yield_:g} g out, and note the time and how it tastes -- one measured "
    "shot is all I need to solve the next setting properly."
)


def get_active_setup_method(setup: BrewSetup | Any | None) -> Method:
    """Brew method for a setup, defaulting to espresso when unset."""
    method = getattr(setup, "method", None)
    if method == "pourover":
        return "pourover"
    if method == "moka":
        return "moka"
    return "espresso"
