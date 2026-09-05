from __future__ import annotations

import logging
import os
import re
import tempfile
import uuid
from typing import Any

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ai.vision import analyze_coffee_bag, get_last_vision_error
from database.models import Bean, BrewSetup, DialInLog, Equipment, Recommendation

from .brewing import normalised_time, target_for
from .db_session import get_db
from .engine import (
    ENGINE_VERSION,
    persist_recommendation,
    recommend,
    render_legacy_text,
    serialize_result,
)
from .retrieval import get_active_setup_method, to_shot_record
from .web_helpers import (
    as_non_empty_text,
    bean_coffee_data,
    find_existing_bean,
    get_active_setup,
    get_default_dose_g,
    get_grind_offset_clicks,
    parse_roast_date,
    read_asset_version,
    resolve_log_values,
    roast_level_ordinal,
    save_dial_in_log,
    serialize_equipment,
    serialize_setup,
    set_default_dose_g,
    set_grind_offset_clicks,
    set_setting,
)
from .web_schemas import (
    BeanRecordInput,
    DoseUpdate,
    EquipmentLibraryCreateInput,
    EquipmentLibraryUpdateInput,
    EquipmentUpdate,
    FeedbackRequest,
    GrindOffsetUpdate,
    RecommendationRequest,
    SetupInput,
    SetupSelectInput,
)

logger = logging.getLogger("wcda.routes")

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
_ALLOWED_IMAGE_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
}
_ALLOWED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}

_EQUIPMENT_TYPES = {"grinder", "espresso_machine", "filter", "other"}


def _as_float(value: Any) -> float | None:
    """Numeric columns come back as Decimal; the API speaks floats."""
    return None if value is None else float(value)


def _server_error(exc: Exception, action: str) -> HTTPException:
    """Log the real error server-side, return a generic message to the client."""
    logger.exception("Error while %s: %s", action, exc)
    return HTTPException(status_code=500, detail=f"Could not {action}.")


_POUROVER_MODELS = re.compile(r"v60|kalita|chemex|origami|switch|dripper", re.I)
_MOKA_MODELS = re.compile(r"moka|kotyog|bialetti|brikka", re.I)


def _infer_method(machine: Equipment) -> str:
    """Best guess at brew method from the paired brewer.

    Only a default: the user can override it in Settings, and the engine's
    target bands and available levers follow whatever is stored.
    """
    if machine.type == "espresso_machine":
        return "espresso"
    if _MOKA_MODELS.search(machine.model or ""):
        return "moka"
    if machine.type == "filter" or _POUROVER_MODELS.search(machine.model or ""):
        return "pourover"
    return "espresso"


_CAPABILITY_FIELDS = (
    "grind_min_clicks",
    "grind_max_clicks",
    "grind_step_clicks",
    "grind_um_per_click",
    "finer_direction",
    "burr_type",
    "basket_size_g",
    "temp_min_c",
    "temp_max_c",
    "temp_controllable",
    "spec_source",
)


def _apply_capabilities(item: Equipment, body: Any) -> None:
    """Copy any supplied capability values onto the equipment row.

    Only fields actually sent are written, so a partially-filled form does
    not blank out values that were already known.
    """
    for field_name in _CAPABILITY_FIELDS:
        value = getattr(body, field_name, None)
        if value is not None:
            setattr(item, field_name, value)


def _bean_for(db: Session, coffee_data: dict[str, Any]) -> Bean | None:
    """The stored bean if we have brewed it, otherwise a transient stand-in.

    An unsaved Bean still carries roast level, process and origin, which is
    what similarity scoring needs -- so a coffee scanned for the first time
    still gets sensible retrieval rather than none.
    """
    name = as_non_empty_text(coffee_data.get("name"))
    roaster = as_non_empty_text(coffee_data.get("roaster"))
    origin = as_non_empty_text(coffee_data.get("origin"))
    process = as_non_empty_text(coffee_data.get("process"))
    roast_level = as_non_empty_text(coffee_data.get("roast_level"))

    existing = find_existing_bean(
        db, name=name, roaster=roaster, origin=origin, process=process
    )
    if existing is not None:
        return existing

    return Bean(
        roaster=roaster,
        name=name,
        origin=origin,
        process=process,
        roast_level=roast_level,
        roast_date=parse_roast_date(coffee_data.get("roast_date")),
        roast_level_ord=roast_level_ordinal(roast_level),
    )


def _engine_recommendation(
    db: Session, coffee_data: dict[str, Any], bean: Bean | None = None
) -> dict[str, Any]:
    """Run the deterministic engine and shape the API response.

    The response is a superset: `recipe` and `rationale` are the real
    contract, while the legacy `recommendation` string is rendered *from* the
    structured result so older PWA clients keep working for one release. The
    number in that prose is the engine's number, not one parsed back out of
    generated text.

    `bean` is passed in when the caller already has the real row (recommending
    for a saved coffee); otherwise one is found or fabricated from coffee_data.
    """
    setup = get_active_setup(db)
    if bean is None:
        bean = _bean_for(db, coffee_data)
    dose = coffee_data.get("preferred_dose_g") or get_default_dose_g(db)

    result = recommend(db, setup, bean, float(dose))

    recommendation_id: int | None = None
    if bean is not None and bean.id is not None:
        # Only persist against a bean that actually exists; a transient
        # stand-in has no row to reference.
        recommendation_id = persist_recommendation(db, result, setup, bean)

    payload = serialize_result(result)
    payload["recommendation"] = render_legacy_text(result)
    payload["recommendation_id"] = recommendation_id
    return payload


def register_routes(app: FastAPI, static_dir: str) -> None:
    uploads_dir = os.getenv(
        "LOG_IMAGES_DIR",
        os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "..", "data", "log_images")
        ),
    )
    try:
        os.makedirs(uploads_dir, exist_ok=True)
    except OSError:
        fallback_dir = os.path.join(tempfile.gettempdir(), "wcda_log_images")
        try:
            os.makedirs(fallback_dir, exist_ok=True)
            uploads_dir = fallback_dir
        except OSError:
            uploads_dir = ""

    def _index() -> FileResponse:
        return FileResponse(os.path.join(static_dir, "index.html"))

    @app.get("/", include_in_schema=False)
    def root() -> FileResponse:
        return _index()

    # Legacy paths kept for bookmarks / the service-worker precache.
    @app.get("/mobile", include_in_schema=False)
    def mobile_ui() -> FileResponse:
        return _index()

    @app.get("/desktop", include_in_schema=False)
    def desktop_ui() -> FileResponse:
        return _index()

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    # Parsed once at startup: the prod container is read-only, so the file
    # cannot change under a running process, and this keeps it off the
    # request path.
    asset_version = read_asset_version(static_dir)

    @app.get("/api/version")
    def get_version() -> dict[str, Any]:
        """What the server is currently serving.

        The client compares this against the version its own bundle was
        loaded with, so the user can tell whether a deploy actually reached
        their phone or they are looking at a cached one.
        """
        return {
            "asset_version": asset_version,
            "engine_version": ENGINE_VERSION,
        }

    @app.get("/sw.js", include_in_schema=False)
    def service_worker() -> FileResponse:
        return FileResponse(
            os.path.join(static_dir, "sw.js"),
            media_type="application/javascript",
            headers={
                "Service-Worker-Allowed": "/",
                "Cache-Control": "no-cache, no-store, must-revalidate",
            },
        )

    @app.post("/api/analyze")
    def analyze_image(
        file: UploadFile = File(...),
        db: Session = Depends(get_db),
    ) -> dict[str, Any]:
        content_type = (file.content_type or "").lower()
        if content_type not in _ALLOWED_IMAGE_TYPES:
            raise HTTPException(
                status_code=400,
                detail="File must be a JPEG, PNG, WebP or HEIC image.",
            )

        suffix = ".jpg"
        if file.filename and "." in file.filename:
            candidate = os.path.splitext(file.filename)[1].lower()
            if candidate in _ALLOWED_IMAGE_EXTS:
                suffix = candidate

        content = file.file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Image exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.",
            )

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            coffee_data = analyze_coffee_bag(tmp_path)
        finally:
            os.unlink(tmp_path)

        if not coffee_data:
            detail = get_last_vision_error() or "Failed to extract data from image."
            raise HTTPException(status_code=422, detail=detail)

        image_name: str | None = None
        if uploads_dir:
            image_name = f"{uuid.uuid4().hex}{suffix}"
            saved_image_path = os.path.join(uploads_dir, image_name)
            try:
                with open(saved_image_path, "wb") as image_file:
                    image_file.write(content)
            except OSError:
                logger.warning("Could not persist uploaded image to %s", uploads_dir)
                image_name = None

        coffee_data["preferred_dose_g"] = get_default_dose_g(db)
        coffee_data["preferred_grind_offset_clicks"] = get_grind_offset_clicks(db)
        if image_name:
            coffee_data["image_name"] = image_name

        payload = _engine_recommendation(db, coffee_data)
        return {"coffee_data": coffee_data, **payload}

    @app.post("/api/recommendation")
    def refresh_recommendation(
        body: RecommendationRequest, db: Session = Depends(get_db)
    ) -> dict[str, Any]:
        """Regenerate the recipe for a scanned bag or a coffee already saved.

        Called when the dose changes, when the active setup changes, and when
        the user opens one of their existing coffees to fine-tune it. Passing
        `bean_id` uses the stored row, so the engine sees the real roast date
        and roast level rather than re-parsing strings, and the resulting
        recommendation is recorded against that bean.
        """
        if body.dose_g is not None and body.dose_g <= 0:
            raise HTTPException(status_code=400, detail="Dose must be positive.")

        bean: Bean | None = None
        if body.bean_id is not None:
            bean = db.query(Bean).filter(Bean.id == body.bean_id).first()
            if bean is None:
                raise HTTPException(status_code=404, detail="Coffee not found")
            coffee_data = bean_coffee_data(bean)
        else:
            coffee_data = dict(body.coffee_data or {})

        if body.dose_g is not None:
            coffee_data["preferred_dose_g"] = body.dose_g
        else:
            coffee_data.setdefault("preferred_dose_g", get_default_dose_g(db))
        # Grind offset is a server-side preference, never trusted from the client.
        coffee_data["preferred_grind_offset_clicks"] = get_grind_offset_clicks(db)

        try:
            payload = _engine_recommendation(db, coffee_data, bean=bean)
        except Exception as exc:
            raise _server_error(exc, "refresh recommendation") from exc
        # Echo the profile back so the client renders one shape from either
        # entrance, exactly as /api/analyze does.
        payload["coffee_data"] = coffee_data
        return payload

    @app.post("/api/feedback")
    def save_feedback(body: FeedbackRequest) -> dict[str, str]:
        try:
            save_dial_in_log(
                body.coffee_data,
                body.recommendation,
                actual_grind=body.actual_grind,
                dose_g=body.dose_g,
                image_name=body.image_name,
                yield_g=body.yield_g,
                water_g=body.water_g,
                time_s=body.time_s,
                taste_axis=body.taste_axis,
                astringent=body.astringent,
                brew_temp_c=body.brew_temp_c,
                preinfusion_s=body.preinfusion_s,
                pause_s=body.pause_s,
                recommendation_id=body.recommendation_id,
            )
        except Exception as exc:
            raise _server_error(exc, "save feedback") from exc
        return {"status": "saved"}

    @app.get("/api/log-images/{image_name}")
    def get_log_image(image_name: str) -> FileResponse:
        if not uploads_dir:
            raise HTTPException(status_code=404, detail="Image storage is unavailable")

        safe_name = os.path.basename(image_name)
        if not safe_name or safe_name != image_name:
            raise HTTPException(status_code=400, detail="Invalid image name")

        file_path = os.path.join(uploads_dir, safe_name)
        if not os.path.isfile(file_path):
            raise HTTPException(status_code=404, detail="Image not found")
        return FileResponse(file_path)

    @app.get("/api/equipment")
    def get_equipment(db: Session = Depends(get_db)) -> dict[str, Any]:
        setup = get_active_setup(db)
        grinder = setup.grinder
        machine = setup.machine
        return {
            "grinder": {"brand": grinder.brand, "model": grinder.model}
            if grinder
            else None,
            "machine": {"brand": machine.brand, "model": machine.model}
            if machine
            else None,
        }

    @app.put("/api/equipment/grinder")
    def update_grinder(
        body: EquipmentUpdate, db: Session = Depends(get_db)
    ) -> dict[str, str]:
        try:
            setup = get_active_setup(db)
            setup.grinder.brand = body.brand
            setup.grinder.model = body.model
            db.commit()
        except Exception as exc:
            db.rollback()
            raise _server_error(exc, "update grinder") from exc
        return {"status": "updated"}

    @app.put("/api/equipment/machine")
    def update_machine(
        body: EquipmentUpdate, db: Session = Depends(get_db)
    ) -> dict[str, str]:
        try:
            setup = get_active_setup(db)
            setup.machine.brand = body.brand
            setup.machine.model = body.model
            db.commit()
        except Exception as exc:
            db.rollback()
            raise _server_error(exc, "update machine") from exc
        return {"status": "updated"}

    @app.get("/api/settings")
    def get_settings(db: Session = Depends(get_db)) -> dict[str, float]:
        return {
            "dose_g": get_default_dose_g(db),
            "grind_offset_clicks": get_grind_offset_clicks(db),
        }

    @app.get("/api/logs")
    def get_logs(
        limit: int = 20, db: Session = Depends(get_db)
    ) -> dict[str, list[dict[str, Any]]]:
        safe_limit = max(1, min(limit, 50))
        # Order by when a coffee was last brewed, not when it was created --
        # otherwise a bag added months ago and brewed this morning falls off
        # the end of the list. selectinload avoids an N+1 over bean.logs.
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
            .outerjoin(last_brew, last_brew.c.bean_id == Bean.id)
            .options(selectinload(Bean.logs))
            .order_by(last_brew.c.last_at.desc().nullslast(), Bean.id.desc())
            .limit(safe_limit)
            .all()
        )

        entries: list[dict[str, Any]] = []
        for bean in beans:
            latest_log = None
            if bean.logs:
                latest_log = max(bean.logs, key=lambda log: log.created_at)

            entries.append(
                {
                    "bean_id": bean.id,
                    "bean_name": bean.name,
                    "roaster": bean.roaster,
                    "origin": bean.origin,
                    "process": bean.process,
                    "roast_level": bean.roast_level,
                    "roast_date": bean.roast_date.isoformat()
                    if bean.roast_date
                    else None,
                    "last_brewed_at": latest_log.created_at.isoformat()
                    if latest_log
                    else None,
                    "logs_count": len(bean.logs),
                    "latest_log": {
                        "id": latest_log.id,
                        "created_at": latest_log.created_at.isoformat(),
                        "grinder": latest_log.grinder.brand
                        + " "
                        + latest_log.grinder.model,
                        "machine": latest_log.machine.brand
                        + " "
                        + latest_log.machine.model,
                        "grind_setting": latest_log.grind_setting,
                        "dose_g": latest_log.dose_g,
                        "yield_g": latest_log.yield_g,
                        "time_s": latest_log.time_s,
                        "rating": latest_log.rating,
                        "tasting_notes": latest_log.tasting_notes,
                        "image_name": latest_log.image_path,
                        "image_url": f"/api/log-images/{latest_log.image_path}"
                        if latest_log.image_path
                        else None,
                    }
                    if latest_log
                    else None,
                }
            )

        return {"entries": entries}

    # Literal paths before parameterised siblings: if an /api/beans/<literal>
    # route is ever added it must be declared above this one.
    @app.get("/api/beans/{bean_id}/shots")
    def get_bean_shots(
        bean_id: int, limit: int = 5, db: Session = Depends(get_db)
    ) -> dict[str, Any]:
        """Recent shots on one coffee, with each judged against its target.

        The band verdict is computed here rather than in the browser because
        the engine compares *normalised* time (time / brew ratio), not raw
        seconds. Re-deriving that in JavaScript would drift from brewing.py
        the first time the target bands change.
        """
        bean = db.query(Bean).filter(Bean.id == bean_id).first()
        if bean is None:
            raise HTTPException(status_code=404, detail="Coffee not found")

        safe_limit = max(1, min(limit, 20))
        logs = (
            db.query(DialInLog)
            .filter(DialInLog.bean_id == bean_id)
            .order_by(DialInLog.created_at.desc())
            .limit(safe_limit)
            .all()
        )

        suggested: dict[int, Any] = {}
        wanted = [log.recommendation_id for log in logs if log.recommendation_id]
        if wanted:
            for rec in (
                db.query(Recommendation).filter(Recommendation.id.in_(wanted)).all()
            ):
                suggested[rec.id] = rec.grind_clicks

        setup = get_active_setup(db)
        active_method = get_active_setup_method(setup)
        target = target_for(active_method)

        shots: list[dict[str, Any]] = []
        for index, log in enumerate(logs):
            method = log.brew_method or active_method
            record = to_shot_record(log, bean, method)  # type: ignore[arg-type]
            tr = normalised_time(record)

            band: str | None = None
            shot_target = target_for(method)  # type: ignore[arg-type]
            if tr is not None and shot_target.tr_lo is not None:
                hi = shot_target.tr_hi
                if hi is not None:
                    band = (
                        "in"
                        if shot_target.tr_lo <= tr <= hi
                        else ("long" if tr > hi else "fast")
                    )

            # A click delta only means something within one setup.
            older = logs[index + 1] if index + 1 < len(logs) else None
            same_setup = bool(older and older.setup_id == log.setup_id)
            delta = None
            if (
                same_setup
                and older is not None
                and log.grind_clicks is not None
                and older.grind_clicks is not None
            ):
                delta = float(log.grind_clicks) - float(older.grind_clicks)

            shots.append(
                {
                    "id": log.id,
                    "created_at": log.created_at.isoformat(),
                    "setup_id": log.setup_id,
                    "method": method,
                    "grind_clicks": _as_float(log.grind_clicks),
                    "grind_setting": log.grind_setting,
                    "dose_g": log.dose_g,
                    "yield_g": log.yield_g,
                    "water_g": _as_float(log.water_g),
                    "time_s": log.time_s,
                    "taste_axis": log.taste_axis,
                    "astringent": log.astringent,
                    "rating": log.rating,
                    "data_quality": log.data_quality,
                    "tr": round(tr, 2) if tr is not None else None,
                    "band": band,
                    "delta_clicks": delta,
                    "same_setup_as_prev": same_setup,
                    "suggested_grind_clicks": _as_float(
                        suggested.get(log.recommendation_id or -1)
                    ),
                }
            )

        return {
            "bean": {
                "id": bean.id,
                "name": bean.name,
                "roaster": bean.roaster,
            },
            "target": {
                "tr_lo": target.tr_lo,
                "tr_hi": target.tr_hi,
                "time_lo": target.time_lo,
                "time_hi": target.time_hi,
                "ratio_aim": target.ratio_aim,
            },
            "shots": shots,
        }

    @app.get("/api/equipment/library")
    def get_equipment_library(
        db: Session = Depends(get_db),
    ) -> dict[str, list[dict[str, Any]]]:
        items = (
            db.query(Equipment)
            .order_by(
                Equipment.type.asc(), Equipment.brand.asc(), Equipment.model.asc()
            )
            .all()
        )
        grinders = [
            serialize_equipment(item) for item in items if item.type == "grinder"
        ]
        machines = [
            serialize_equipment(item) for item in items if item.type != "grinder"
        ]
        return {"grinders": grinders, "machines": machines}

    @app.post("/api/equipment/library")
    def create_equipment_library_item(
        body: EquipmentLibraryCreateInput, db: Session = Depends(get_db)
    ) -> dict[str, Any]:
        eq_type = as_non_empty_text(body.type).lower()
        if eq_type not in _EQUIPMENT_TYPES:
            raise HTTPException(status_code=400, detail="Invalid equipment type")

        try:
            item = Equipment(
                type=eq_type,
                brand=as_non_empty_text(body.brand),
                model=as_non_empty_text(body.model),
            )
            _apply_capabilities(item, body)
            db.add(item)
            db.commit()
            db.refresh(item)
        except Exception as exc:
            db.rollback()
            raise _server_error(exc, "create equipment") from exc
        return {"status": "created", "equipment": serialize_equipment(item)}

    @app.put("/api/equipment/library/{equipment_id}")
    def update_equipment_library_item(
        equipment_id: int,
        body: EquipmentLibraryUpdateInput,
        db: Session = Depends(get_db),
    ) -> dict[str, Any]:
        item = db.query(Equipment).filter(Equipment.id == equipment_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="Equipment not found")

        eq_type = as_non_empty_text(body.type).lower()
        if eq_type not in _EQUIPMENT_TYPES:
            raise HTTPException(status_code=400, detail="Invalid equipment type")

        if eq_type == "grinder":
            setup_refs = (
                db.query(BrewSetup).filter(BrewSetup.machine_id == equipment_id).count()
            )
            log_refs = (
                db.query(DialInLog).filter(DialInLog.machine_id == equipment_id).count()
            )
        else:
            setup_refs = (
                db.query(BrewSetup).filter(BrewSetup.grinder_id == equipment_id).count()
            )
            log_refs = (
                db.query(DialInLog).filter(DialInLog.grinder_id == equipment_id).count()
            )

        if setup_refs > 0 or log_refs > 0:
            raise HTTPException(
                status_code=400,
                detail="Cannot change equipment category while it is referenced",
            )

        try:
            item.type = eq_type
            item.brand = as_non_empty_text(body.brand)
            item.model = as_non_empty_text(body.model)
            _apply_capabilities(item, body)
            db.commit()
            db.refresh(item)
        except Exception as exc:
            db.rollback()
            raise _server_error(exc, "update equipment") from exc
        return {"status": "updated", "equipment": serialize_equipment(item)}

    @app.delete("/api/equipment/library/{equipment_id}")
    def delete_equipment_library_item(
        equipment_id: int, db: Session = Depends(get_db)
    ) -> dict[str, str]:
        item = db.query(Equipment).filter(Equipment.id == equipment_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="Equipment not found")

        setup_refs = (
            db.query(BrewSetup)
            .filter(
                (BrewSetup.grinder_id == equipment_id)
                | (BrewSetup.machine_id == equipment_id)
            )
            .count()
        )
        log_refs = (
            db.query(DialInLog)
            .filter(
                (DialInLog.grinder_id == equipment_id)
                | (DialInLog.machine_id == equipment_id)
            )
            .count()
        )

        if setup_refs > 0 or log_refs > 0:
            raise HTTPException(
                status_code=400,
                detail="Equipment is in use by setups/logs and cannot be deleted",
            )

        try:
            db.delete(item)
            db.commit()
        except Exception as exc:
            db.rollback()
            raise _server_error(exc, "delete equipment") from exc
        return {"status": "deleted"}

    @app.get("/api/setups")
    def get_setups(db: Session = Depends(get_db)) -> dict[str, Any]:
        active = get_active_setup(db)
        setups = (
            db.query(BrewSetup).order_by(BrewSetup.name.asc(), BrewSetup.id.asc()).all()
        )
        return {
            "active_setup_id": active.id,
            "setups": [serialize_setup(item) for item in setups],
        }

    @app.post("/api/setups")
    def create_setup(body: SetupInput, db: Session = Depends(get_db)) -> dict[str, Any]:
        grinder = (
            db.query(Equipment)
            .filter(Equipment.id == body.grinder_id, Equipment.type == "grinder")
            .first()
        )
        machine = (
            db.query(Equipment)
            .filter(Equipment.id == body.machine_id, Equipment.type != "grinder")
            .first()
        )
        if not grinder or not machine:
            raise HTTPException(status_code=400, detail="Selected equipment not found")

        try:
            setup = BrewSetup(
                name=as_non_empty_text(body.name),
                grinder_id=grinder.id,
                machine_id=machine.id,
                method=body.method or _infer_method(machine),
            )
            db.add(setup)
            db.commit()
            db.refresh(setup)
        except Exception as exc:
            db.rollback()
            raise _server_error(exc, "create setup") from exc
        return {"status": "created", "setup": serialize_setup(setup)}

    @app.put("/api/setups/active")
    def select_setup(
        body: SetupSelectInput, db: Session = Depends(get_db)
    ) -> dict[str, Any]:
        # Declared before "/api/setups/{setup_id}" so the literal "active" path
        # is not captured as an integer setup_id path parameter.
        selected_id = body.setup_id or body.active_setup_id
        if not selected_id:
            raise HTTPException(status_code=422, detail="setup_id is required")

        setup = db.query(BrewSetup).filter(BrewSetup.id == selected_id).first()
        if not setup:
            raise HTTPException(status_code=404, detail="Setup not found")
        set_setting(db, "active_setup_id", str(setup.id))
        return {"status": "selected", "setup_id": setup.id}

    @app.put("/api/setups/{setup_id}")
    def update_setup(
        setup_id: int, body: SetupInput, db: Session = Depends(get_db)
    ) -> dict[str, Any]:
        setup = db.query(BrewSetup).filter(BrewSetup.id == setup_id).first()
        if not setup:
            raise HTTPException(status_code=404, detail="Setup not found")

        grinder = (
            db.query(Equipment)
            .filter(Equipment.id == body.grinder_id, Equipment.type == "grinder")
            .first()
        )
        machine = (
            db.query(Equipment)
            .filter(Equipment.id == body.machine_id, Equipment.type != "grinder")
            .first()
        )
        if not grinder or not machine:
            raise HTTPException(status_code=400, detail="Selected equipment not found")

        try:
            setup.name = as_non_empty_text(body.name)
            setup.grinder_id = grinder.id
            setup.machine_id = machine.id
            setup.method = body.method or setup.method or _infer_method(machine)
            db.commit()
            db.refresh(setup)
        except Exception as exc:
            db.rollback()
            raise _server_error(exc, "update setup") from exc
        return {"status": "updated", "setup": serialize_setup(setup)}

    @app.delete("/api/setups/{setup_id}")
    def delete_setup(setup_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
        setup = db.query(BrewSetup).filter(BrewSetup.id == setup_id).first()
        if not setup:
            raise HTTPException(status_code=404, detail="Setup not found")
        if db.query(BrewSetup).count() <= 1:
            raise HTTPException(
                status_code=400, detail="At least one setup must remain"
            )

        try:
            db.delete(setup)
            db.commit()

            next_setup = db.query(BrewSetup).order_by(BrewSetup.id.asc()).first()
            if next_setup:
                set_setting(db, "active_setup_id", str(next_setup.id))
        except Exception as exc:
            db.rollback()
            raise _server_error(exc, "delete setup") from exc
        return {"status": "deleted"}

    @app.post("/api/logs/manual")
    def create_manual_log(
        body: BeanRecordInput, db: Session = Depends(get_db)
    ) -> dict[str, Any]:
        try:
            bean = Bean(
                roaster=as_non_empty_text(body.roaster),
                name=as_non_empty_text(body.name),
                origin=as_non_empty_text(body.origin),
                process=as_non_empty_text(body.process),
                roast_level=as_non_empty_text(body.roast_level),
            )
            db.add(bean)
            db.commit()
            db.refresh(bean)

            active_setup = get_active_setup(db)
            grinder, machine = active_setup.grinder, active_setup.machine
            values = resolve_log_values(body.log, db)
            db.add(
                DialInLog(
                    bean_id=bean.id,
                    grinder_id=grinder.id,
                    machine_id=machine.id,
                    setup_id=active_setup.id,
                    brew_method=active_setup.method,
                    grind_setting=values["grind_setting"],
                    grind_clicks=values["grind_clicks"],
                    dose_g=values["dose_g"],
                    yield_g=values["yield_g"],
                    time_s=values["time_s"],
                    rating=values["rating"],
                    tasting_notes=values["tasting_notes"],
                    data_quality=values["data_quality"],
                )
            )
            db.commit()
        except Exception as exc:
            db.rollback()
            raise _server_error(exc, "create log") from exc
        return {"status": "created", "bean_id": bean.id}

    @app.put("/api/logs/{bean_id}")
    def update_log_record(
        bean_id: int, body: BeanRecordInput, db: Session = Depends(get_db)
    ) -> dict[str, Any]:
        bean = db.query(Bean).filter(Bean.id == bean_id).first()
        if not bean:
            raise HTTPException(status_code=404, detail="Bean not found")

        try:
            bean.roaster = as_non_empty_text(body.roaster)
            bean.name = as_non_empty_text(body.name)
            bean.origin = as_non_empty_text(body.origin)
            bean.process = as_non_empty_text(body.process)
            bean.roast_level = as_non_empty_text(body.roast_level)

            latest_log = None
            if bean.logs:
                latest_log = max(bean.logs, key=lambda log: log.created_at)

            values = resolve_log_values(body.log, db)
            if latest_log is None:
                active_setup = get_active_setup(db)
                grinder, machine = active_setup.grinder, active_setup.machine
                db.add(
                    DialInLog(
                        bean_id=bean.id,
                        grinder_id=grinder.id,
                        machine_id=machine.id,
                        setup_id=active_setup.id,
                        brew_method=active_setup.method,
                        grind_setting=values["grind_setting"],
                        grind_clicks=values["grind_clicks"],
                        dose_g=values["dose_g"],
                        yield_g=values["yield_g"],
                        time_s=values["time_s"],
                        rating=values["rating"],
                        tasting_notes=values["tasting_notes"],
                        data_quality=values["data_quality"],
                    )
                )
            else:
                latest_log.grind_setting = values["grind_setting"]
                latest_log.grind_clicks = values["grind_clicks"]
                latest_log.dose_g = values["dose_g"]
                latest_log.yield_g = values["yield_g"]
                latest_log.time_s = values["time_s"]
                latest_log.rating = values["rating"]
                latest_log.tasting_notes = values["tasting_notes"]
                # An edit that adds the missing measurements promotes the row
                # out of 'partial'; one that removes them demotes it again.
                latest_log.data_quality = values["data_quality"]

            db.commit()
        except Exception as exc:
            db.rollback()
            raise _server_error(exc, "update log") from exc
        return {"status": "updated", "bean_id": bean.id}

    @app.delete("/api/logs/{bean_id}")
    def delete_log_record(
        bean_id: int, db: Session = Depends(get_db)
    ) -> dict[str, str]:
        bean = db.query(Bean).filter(Bean.id == bean_id).first()
        if not bean:
            raise HTTPException(status_code=404, detail="Bean not found")

        try:
            # Order matters: dial_in_logs point at recommendations, and
            # recommendations point at the bean. Clearing only the logs left
            # the recommendations behind, and the foreign key then refused the
            # bean delete -- which is why a coffee became undeletable as soon
            # as it had been opened for a recommendation.
            db.query(DialInLog).filter(DialInLog.bean_id == bean_id).delete(
                synchronize_session=False
            )
            doomed = [
                row.id
                for row in db.query(Recommendation.id)
                .filter(Recommendation.bean_id == bean_id)
                .all()
            ]
            if doomed:
                # A shot on another coffee could reference one of these; drop
                # the link rather than the shot.
                db.query(DialInLog).filter(
                    DialInLog.recommendation_id.in_(doomed)
                ).update({DialInLog.recommendation_id: None}, synchronize_session=False)
                db.query(Recommendation).filter(
                    Recommendation.bean_id == bean_id
                ).delete(synchronize_session=False)
            db.delete(bean)
            db.commit()
        except Exception as exc:
            db.rollback()
            raise _server_error(exc, "delete log") from exc
        return {"status": "deleted"}

    @app.put("/api/settings/dose")
    def update_dose(body: DoseUpdate, db: Session = Depends(get_db)) -> dict[str, Any]:
        if body.dose_g <= 0:
            raise HTTPException(status_code=400, detail="Dose must be positive.")
        try:
            set_default_dose_g(db, body.dose_g)
        except Exception as exc:
            db.rollback()
            raise _server_error(exc, "update dose") from exc
        return {"status": "updated", "dose_g": body.dose_g}

    @app.put("/api/settings/grind-offset")
    def update_grind_offset(
        body: GrindOffsetUpdate, db: Session = Depends(get_db)
    ) -> dict[str, Any]:
        try:
            set_grind_offset_clicks(db, body.offset_clicks)
        except Exception as exc:
            db.rollback()
            raise _server_error(exc, "update grind offset") from exc
        return {"status": "updated", "offset_clicks": body.offset_clicks}
