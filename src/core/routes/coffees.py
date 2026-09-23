"""The library of coffees, and the shot history of each.

The /api/logs paths are keyed by *coffee* (bean) id, not by shot: a "log" in
the library is a coffee card showing its latest shot. The names predate that
and are kept so cached clients keep working.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from database.models import Bean, BrewSetup, DialInLog, Recommendation, as_float

from ..auth import get_owner
from ..brewing import is_finer, normalised_time, target_for
from ..db_session import get_db
from ..engine import grinder_caps
from ..retrieval import get_active_setup_method, to_shot_record
from ..web_helpers import (
    as_non_empty_text,
    latest_photo_log,
    new_shot,
    resolve_log_values,
    roast_level_ordinal,
)
from ..web_schemas import BeanRecordInput
from .common import active_setup, server_error

router = APIRouter()


def _owned_bean(db: Session, bean_id: int, owner: str) -> Bean:
    bean = db.query(Bean).filter(Bean.id == bean_id, Bean.owner == owner).first()
    if bean is None:
        raise HTTPException(status_code=404, detail="Coffee not found")
    return bean


def _apply_bean_fields(bean: Bean, body: BeanRecordInput) -> None:
    bean.roaster = as_non_empty_text(body.roaster)
    bean.name = as_non_empty_text(body.name)
    bean.origin = as_non_empty_text(body.origin)
    bean.process = as_non_empty_text(body.process)
    bean.roast_level = as_non_empty_text(body.roast_level)
    # The ordinal is what the engine reads (temperature band, coffee
    # similarity), so it must follow the label on every write.
    bean.roast_level_ord = roast_level_ordinal(bean.roast_level)


@router.get("/api/logs")
def list_coffees(
    limit: int = 20,
    db: Session = Depends(get_db),
    owner: str = Depends(get_owner),
) -> dict[str, list[dict[str, Any]]]:
    """The user's coffees, most recently brewed first, each with its last shot."""
    # Order by when a coffee was last brewed, not when it was created --
    # otherwise a bag added months ago and brewed this morning falls off the
    # end of the list. selectinload avoids an N+1 over bean.logs.
    last_brew = (
        select(
            DialInLog.bean_id.label("bean_id"),
            func.max(DialInLog.created_at).label("last_at"),
        )
        .group_by(DialInLog.bean_id)
        .subquery()
    )
    beans = (
        db.query(Bean)
        .filter(Bean.owner == owner)
        .outerjoin(last_brew, last_brew.c.bean_id == Bean.id)
        .options(selectinload(Bean.logs))
        .order_by(last_brew.c.last_at.desc().nullslast(), Bean.id.desc())
        .limit(max(1, min(limit, 50)))
        .all()
    )

    entries: list[dict[str, Any]] = []
    for bean in beans:
        latest = max(bean.logs, key=lambda log: log.created_at, default=None)
        # The bag photo is taken once, on the first shot of a coffee, so it
        # lives on an older log than `latest` as soon as a second shot is
        # recorded. Look past `latest` for it, or the card loses the photo.
        bag_log = latest_photo_log(bean.logs)
        entries.append(
            {
                "bean_id": bean.id,
                "bean_name": bean.name,
                "roaster": bean.roaster,
                "origin": bean.origin,
                "process": bean.process,
                "roast_level": bean.roast_level,
                "roast_date": bean.roast_date.isoformat() if bean.roast_date else None,
                "last_brewed_at": latest.created_at.isoformat() if latest else None,
                "logs_count": len(bean.logs),
                "latest_log": {
                    "id": latest.id,
                    "created_at": latest.created_at.isoformat(),
                    "grinder": f"{latest.grinder.brand} {latest.grinder.model}",
                    "machine": f"{latest.machine.brand} {latest.machine.model}",
                    "grind_setting": latest.grind_setting,
                    "dose_g": latest.dose_g,
                    "yield_g": latest.yield_g,
                    "time_s": latest.time_s,
                    "rating": latest.rating,
                    "tasting_notes": latest.tasting_notes,
                    "image_name": bag_log.image_path if bag_log else None,
                    "image_url": f"/api/log-images/{bag_log.image_path}"
                    if bag_log
                    else None,
                }
                if latest
                else None,
            }
        )
    return {"entries": entries}


@router.get("/api/beans/{bean_id}/shots")
def get_bean_shots(
    bean_id: int,
    limit: int = 5,
    db: Session = Depends(get_db),
    owner: str = Depends(get_owner),
    setup: BrewSetup = Depends(active_setup),
) -> dict[str, Any]:
    """Recent shots on one coffee, with each judged against its target.

    The band verdict is computed here rather than in the browser because the
    engine compares *normalised* time (time / brew ratio), not raw seconds.
    Re-deriving that in JavaScript would drift from brewing.py the first time
    the target bands change.
    """
    bean = _owned_bean(db, bean_id, owner)
    logs = (
        db.query(DialInLog)
        .filter(DialInLog.bean_id == bean_id, DialInLog.owner == owner)
        .order_by(DialInLog.created_at.desc())
        .limit(max(1, min(limit, 20)))
        .all()
    )

    wanted = [log.recommendation_id for log in logs if log.recommendation_id]
    suggested = {
        rec.id: rec.grind_clicks
        for rec in db.query(Recommendation)
        .filter(Recommendation.id.in_(wanted), Recommendation.owner == owner)
        .all()
    }

    active_method = get_active_setup_method(setup)
    target = target_for(active_method)

    shots: list[dict[str, Any]] = []
    for index, log in enumerate(logs):
        method = log.brew_method or active_method
        tr = normalised_time(to_shot_record(log, bean, method))  # type: ignore[arg-type]

        band: str | None = None
        shot_target = target_for(method)  # type: ignore[arg-type]
        if tr is not None and shot_target.tr_lo is not None and shot_target.tr_hi:
            if tr > shot_target.tr_hi:
                band = "long"
            elif tr < shot_target.tr_lo:
                band = "fast"
            else:
                band = "in"

        # A click delta only means something within one setup.
        older = logs[index + 1] if index + 1 < len(logs) else None
        same_setup = older is not None and older.setup_id == log.setup_id
        delta = direction = None
        if (
            older is not None
            and same_setup
            and log.grind_clicks is not None
            and older.grind_clicks is not None
        ):
            delta = float(log.grind_clicks) - float(older.grind_clicks)
            if delta:
                # Which way the dial runs is the grinder's, not a sign
                # convention: higher is finer on some grinders.
                finer = is_finer(
                    float(log.grind_clicks),
                    float(older.grind_clicks),
                    grinder_caps(log.grinder),
                )
                direction = "finer" if finer else "coarser"

        shots.append(
            {
                "id": log.id,
                "created_at": log.created_at.isoformat(),
                "setup_id": log.setup_id,
                "method": method,
                "grind_clicks": as_float(log.grind_clicks),
                "grind_setting": log.grind_setting,
                "dose_g": log.dose_g,
                "yield_g": log.yield_g,
                "water_g": as_float(log.water_g),
                "time_s": log.time_s,
                "taste_axis": log.taste_axis,
                "astringent": log.astringent,
                "rating": log.rating,
                "data_quality": log.data_quality,
                "tr": round(tr, 2) if tr is not None else None,
                "band": band,
                "delta_clicks": delta,
                "direction": direction,
                "same_setup_as_prev": same_setup,
                "suggested_grind_clicks": as_float(
                    suggested.get(log.recommendation_id or -1)
                ),
            }
        )

    return {
        "bean": {"id": bean.id, "name": bean.name, "roaster": bean.roaster},
        "target": {
            "tr_lo": target.tr_lo,
            "tr_hi": target.tr_hi,
            "time_lo": target.time_lo,
            "time_hi": target.time_hi,
            "ratio_aim": target.ratio_aim,
        },
        "shots": shots,
    }


@router.post("/api/logs/manual")
def create_coffee(
    body: BeanRecordInput,
    db: Session = Depends(get_db),
    owner: str = Depends(get_owner),
    setup: BrewSetup = Depends(active_setup),
) -> dict[str, Any]:
    """Add a coffee by hand, with one shot on the active setup. All or nothing."""
    try:
        bean = Bean(owner=owner)
        _apply_bean_fields(bean, body)
        db.add(bean)
        db.flush()
        db.add(
            new_shot(owner, bean.id, setup, **resolve_log_values(body.log, db, owner))
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        raise server_error(exc, "create log") from exc
    return {"status": "created", "bean_id": bean.id}


@router.put("/api/logs/{bean_id}")
def update_coffee(
    bean_id: int,
    body: BeanRecordInput,
    db: Session = Depends(get_db),
    owner: str = Depends(get_owner),
    setup: BrewSetup = Depends(active_setup),
) -> dict[str, Any]:
    """Edit a coffee and its latest shot (or give it one, if it has none)."""
    bean = _owned_bean(db, bean_id, owner)
    try:
        _apply_bean_fields(bean, body)
        values = resolve_log_values(body.log, db, owner)
        latest = max(bean.logs, key=lambda log: log.created_at, default=None)
        if latest is None:
            db.add(new_shot(owner, bean.id, setup, **values))
        else:
            # An edit that adds the missing measurements promotes the row out
            # of 'partial'; one that removes them demotes it again.
            for field, value in values.items():
                setattr(latest, field, value)
        db.commit()
    except Exception as exc:
        db.rollback()
        raise server_error(exc, "update log") from exc
    return {"status": "updated", "bean_id": bean.id}


@router.delete("/api/logs/{bean_id}")
def delete_coffee(
    bean_id: int,
    db: Session = Depends(get_db),
    owner: str = Depends(get_owner),
) -> dict[str, str]:
    bean = _owned_bean(db, bean_id, owner)
    try:
        # Order matters: dial_in_logs point at recommendations, and
        # recommendations point at the bean. Clearing only the logs left the
        # recommendations behind, and the foreign key then refused the bean
        # delete -- which is why a coffee became undeletable as soon as it
        # had been opened for a recommendation.
        db.query(DialInLog).filter(DialInLog.bean_id == bean_id).delete(
            synchronize_session=False
        )
        doomed = select(Recommendation.id).where(Recommendation.bean_id == bean_id)
        # A shot on another coffee could reference one of these; drop the
        # link rather than the shot.
        db.query(DialInLog).filter(DialInLog.recommendation_id.in_(doomed)).update(
            {DialInLog.recommendation_id: None}, synchronize_session=False
        )
        db.query(Recommendation).filter(Recommendation.bean_id == bean_id).delete(
            synchronize_session=False
        )
        db.delete(bean)
        db.commit()
    except Exception as exc:
        db.rollback()
        raise server_error(exc, "delete log") from exc
    return {"status": "deleted"}
