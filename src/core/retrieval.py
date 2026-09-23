"""Find the past shots worth learning from.

Replaces the exact-string matching the first version used
(`Bean.process == x OR Bean.origin == y`, filtered to `rating >= 4`), which
returned nothing at all for a coffee the user had not brewed before -- the
common case -- and conflated two different questions.

What is here instead:

* **Calibration shots** answer "how does this grinder behave?". Physics does
  not care whether a shot tasted nice, so there is deliberately no rating
  filter -- only a completeness one. A bad-tasting shot with a recorded time
  is excellent calibration data. Only `data_quality = 'measured'` rows are
  read, so the fabricated rows quarantined by migration 0003 never come back.
* **Bean similarity** answers "which coffees does this new one resemble?",
  with a structured, explainable score, so a coffee with no shots of its own
  can borrow the per-bean offset of the ones it resembles.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
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


def similarity(target: BeanFeatures, candidate: BeanFeatures) -> float:
    """How closely one coffee resembles another, from 0 up to 0.60.

    Deterministic and explainable by design: the user can be told exactly why
    a coffee was considered similar, which an embedding cannot do.
    """
    score = 0.0

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
    db: Session, owner: str, setup_id: int | None, method: Method
) -> list[ShotRecord]:
    """Shots usable for fitting the grind law.

    No rating filter on purpose: a shot that tasted terrible but has a
    recorded grind and time is perfectly good physics.

    Scoped to ``owner`` as well as the setup: a setup id already belongs to one
    user, but filtering on both keeps the isolation explicit and index-backed.
    """
    if setup_id is None:
        return []
    stmt = (
        select(DialInLog, Bean)
        .join(Bean, DialInLog.bean_id == Bean.id)
        .where(DialInLog.owner == owner)
        .where(DialInLog.setup_id == setup_id)
        .where(DialInLog.data_quality == "measured")
        .where(DialInLog.grind_clicks.is_not(None))
        .where(DialInLog.time_s.is_not(None))
        .order_by(DialInLog.created_at.desc())
    )
    return [
        to_shot_record(log, bean, method) for log, bean in db.execute(stmt).tuples()
    ]


def shots_for_bean(
    shots: Sequence[ShotRecord], bean_id: int | None
) -> list[ShotRecord]:
    """The part of a setup's history that is *this* coffee, newest first.

    The shot a correction is anchored on has to be the same coffee. Dose,
    brew temperature, ratio and taste axis are all read off that anchor, so
    anchoring on the last thing pulled on the machine gets every one of them
    from the wrong bag.

    An empty list is the right answer for a coffee scanned for the first time:
    `web_routes._bean_for` hands the engine a transient Bean with no id, and
    the caller falls through to solving the grind law instead.
    """
    if bean_id is None:
        return []
    return [shot for shot in shots if shot.bean_id == bean_id]


def fetch_bean_features(
    db: Session, owner: str, bean_ids: Iterable[int]
) -> dict[int, BeanFeatures]:
    """Roast, process and origin for the beans behind a setup's history.

    ``ShotRecord`` deliberately carries no bean attributes -- it is the physics
    row -- so scoring one bean against another needs this lookup.
    """
    ids = {bean_id for bean_id in bean_ids if bean_id is not None}
    if not ids:
        return {}
    stmt = select(Bean).where(Bean.owner == owner).where(Bean.id.in_(ids))
    return {
        bean.id: BeanFeatures(
            roast_level_ord=bean.roast_level_ord,
            process=bean.process,
            origin=bean.origin,
        )
        for bean in db.execute(stmt).scalars()
    }


def borrow_bean_offset(
    target: BeanFeatures,
    offsets: Mapping[int, float],
    features: Mapping[int, BeanFeatures],
    floor: float | None = None,
) -> tuple[float, int]:
    """Seed a new coffee's delta_bean from the coffees that resemble it.

    Every candidate is already on this setup, so only the bean terms --
    roast level, process, origin, freshness -- carry information here.

    Returns the weighted offset and how many coffees contributed, so the
    rationale can say whether it borrowed anything. ``(0.0, 0)`` means nothing
    cleared the floor, which degrades to the setup's average bean -- still a
    far better starting point than another coffee's last shot.
    """
    threshold = value_of("bean_offset_floor") if floor is None else floor
    weighted = 0.0
    total = 0.0
    used = 0
    for bean_id, delta in offsets.items():
        candidate = features.get(bean_id)
        if candidate is None:
            continue
        score = similarity(target, candidate)
        if score < threshold:
            continue
        weighted += score * delta
        total += score
        used += 1
    if total <= 0:
        return 0.0, 0
    return weighted / total, used


def classify_tier(
    calibration_shots: Sequence[ShotRecord],
    bean_id: int | None,
    has_hardware_caps: bool,
) -> CalibrationTier:
    """How much of this recommendation rests on the user's own shots.

    A (this coffee, several settings) down to D (nothing measured, hardware
    range known) and E (nothing measured, no hardware range either). Recorded
    with every recommendation for back-testing. Whether a first grind setting
    can be named at all is a separate question, answered by
    brewing.cold_start_clicks; when it cannot, calibration_protocol says so.
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


def calibration_protocol(method: Method, dose_g: float, out_g: float) -> str:
    """What to do when the engine cannot name a first grind setting.

    Said instead of a number, never alongside an invented one. For espresso and
    pour-over the dial cannot be located without the grinder's microns per
    click (docs/science.md#cold-start) -- the middle of the range is *not* a
    stand-in, because that range spans espresso to French press. For moka there
    is no grind law to solve at all: the stove sets the brew time.
    """
    if method == "moka":
        return (
            f"A moka pot's grind isn't solved from brew time -- the stove sets "
            f"that, not the grind -- so there is no setting to calculate. Use a "
            f"grind a little coarser than espresso that doesn't pack when you "
            f"fill the basket, brew {dose_g:g} g with {out_g:g} g of water, and "
            f"note how it tastes."
        )
    brew = (
        f"pull {dose_g:g} g in to {out_g:g} g out"
        if method == "espresso"
        else f"brew {dose_g:g} g with {out_g:g} g of water"
    )
    return (
        "I can't place this grinder's dial yet -- that needs its microns per "
        "click, which isn't recorded -- so any setting I gave you would be "
        f"invented. Start where you normally would, {brew}, and note the "
        "setting, the time and how it tastes: one measured shot is all I need "
        "to solve the next setting properly. Adding your grinder's microns per "
        "click under Equipment gets you a starting number next time."
    )


def get_active_setup_method(setup: BrewSetup | Any | None) -> Method:
    """Brew method for a setup, defaulting to espresso when unset."""
    method = getattr(setup, "method", None)
    if method == "pourover":
        return "pourover"
    if method == "moka":
        return "moka"
    return "espresso"
