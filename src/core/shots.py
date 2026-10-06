"""Turning a logged shot into a stored row: normalising values, quality, saving."""

from __future__ import annotations

import os
from typing import Any

from database.models import Bean, BrewSetup, DialInLog, Recommendation

from .beans import match_bean, transient_bean
from .parsing import parse_grind_clicks
from .setups import get_default_dose_g
from .web_schemas import FeedbackRequest, LogDetailsInput


def classify_data_quality(
    *,
    grind_clicks: float | None,
    time_s: int | None,
    yield_g: float | None,
    water_g: float | None,
    rating: int | None,
    taste_axis: str | None,
) -> str:
    """'measured' only when the engine has what it needs to learn from a shot.

    Calibration reads 'measured' rows exclusively, so this is the gate that
    keeps guessed or half-filled shots out of the physics.
    """
    has_outcome = rating is not None or taste_axis is not None
    complete = (
        grind_clicks is not None
        and time_s is not None
        and (yield_g is not None or water_g is not None)
        and has_outcome
    )
    return "measured" if complete else "partial"


def resolve_log_values(
    log: LogDetailsInput | None, db: Any, owner: str
) -> dict[str, Any]:
    """Normalise a log payload without inventing measurements.

    Anything the user did not supply stays None. Before this, absent values
    were filled with yield_g = dose*2, time_s = 28 and rating = 5, and those
    fabricated rows were later retrieved as real successful shots -- the
    system learned from its own defaults. The dose default is retained
    because it is a stored user preference, not a guess about an outcome.
    """
    dose = get_default_dose_g(db, owner)
    if log and log.dose_g is not None and log.dose_g > 0:
        dose = float(log.dose_g)

    yield_g = (
        float(log.yield_g)
        if log and log.yield_g is not None and log.yield_g > 0
        else None
    )
    time_s = (
        round(log.time_s) if log and log.time_s is not None and log.time_s > 0 else None
    )
    rating = max(1, min(5, int(log.rating))) if log and log.rating is not None else None

    grind_setting = "Unknown"
    if log and log.grind_setting:
        grind_setting = log.grind_setting.strip() or "Unknown"
    grind_clicks = parse_grind_clicks(grind_setting)

    notes = None
    if log and log.tasting_notes:
        notes = log.tasting_notes.strip() or None

    return {
        "dose_g": dose,
        "yield_g": yield_g,
        "time_s": time_s,
        "rating": rating,
        "grind_setting": grind_setting,
        "grind_clicks": grind_clicks,
        "tasting_notes": notes,
        "data_quality": classify_data_quality(
            grind_clicks=grind_clicks,
            time_s=time_s,
            yield_g=yield_g,
            water_g=None,
            rating=rating,
            taste_axis=None,
        ),
    }


def new_shot(owner: str, bean_id: int, setup: BrewSetup, **fields: Any) -> DialInLog:
    """A shot row logged on `setup`: its equipment and method are the setup's."""
    return DialInLog(
        owner=owner,
        bean_id=bean_id,
        grinder_id=setup.grinder_id,
        machine_id=setup.machine_id,
        setup_id=setup.id,
        brew_method=setup.method,
        **fields,
    )


def _bean_for_shot(db: Any, owner: str, coffee_data: dict[str, Any]) -> Bean:
    """The coffee a shot belongs to, created on its first shot.

    An explicit id beats the fuzzy name match: find_existing_bean's 0.9
    similarity threshold is a good guess at identity but is not identity, so a
    shot logged against a known bean must never land on a similarly-named one.
    """
    explicit_id = coffee_data.get("bean_id")
    if isinstance(explicit_id, int) or (
        isinstance(explicit_id, str) and explicit_id.isdigit()
    ):
        bean = db.get(Bean, int(explicit_id))
        # A bean_id from another user's library must not attach a shot.
        if bean is not None and bean.owner == owner:
            return bean

    existing = match_bean(db, owner, coffee_data)
    if existing is not None:
        return existing

    bean = transient_bean(owner, coffee_data)
    db.add(bean)
    db.flush()
    return bean


def save_shot(db: Any, owner: str, setup: BrewSetup, body: FeedbackRequest) -> Bean:
    """Record a shot from the wizard, and return the coffee it was logged on.

    One transaction: a first shot on a new bag creates the coffee and the shot
    together, or neither.
    """
    bean = _bean_for_shot(db, owner, body.coffee_data)

    # The grind value comes from what the user actually set. It is never
    # recovered by parsing the LLM's prose -- that round-trip is what fed
    # generated numbers back in as if they were measurements.
    grind_setting = body.actual_grind.strip() if body.actual_grind else "Unknown"
    grind_clicks = parse_grind_clicks(grind_setting)
    # The wizard's timer measures tenths; the column is whole seconds.
    time_s = None if body.time_s is None else round(body.time_s)
    image_name = body.image_name or body.coffee_data.get("image_name")

    # The client echoes the id of the recommendation it was shown. Only link
    # it if it is this user's: otherwise any id would attach a stranger's
    # recommendation to this shot, and the shot history would then show their
    # suggested grind.
    recommendation_id = body.recommendation_id
    if recommendation_id is not None:
        owned = (
            db.query(Recommendation.id)
            .filter(
                Recommendation.id == recommendation_id,
                Recommendation.owner == owner,
            )
            .first()
        )
        if owned is None:
            recommendation_id = None

    db.add(
        new_shot(
            owner,
            bean.id,
            setup,
            grind_setting=grind_setting,
            grind_clicks=grind_clicks,
            dose_g=body.dose_g
            if body.dose_g is not None
            else get_default_dose_g(db, owner),
            # Whatever the user actually measured; anything they left blank
            # stays None rather than being filled with a default.
            yield_g=body.yield_g,
            water_g=body.water_g,
            time_s=time_s,
            taste_axis=body.taste_axis,
            astringent=body.astringent,
            brew_temp_c=body.brew_temp_c,
            preinfusion_s=body.preinfusion_s,
            pause_s=body.pause_s,
            recommendation_id=recommendation_id,
            data_quality=classify_data_quality(
                grind_clicks=grind_clicks,
                time_s=time_s,
                yield_g=body.yield_g,
                water_g=body.water_g,
                rating=None,
                taste_axis=body.taste_axis,
            ),
            image_path=os.path.basename(str(image_name)) if image_name else None,
        )
    )
    db.commit()
    return bean
