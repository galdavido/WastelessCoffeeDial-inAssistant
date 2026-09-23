"""Scan a bag, get a recipe, log the shot you pulled."""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ai.vision import VisionError, analyze_coffee_bag
from database.models import Bean, BrewSetup

from ..auth import get_owner
from ..db_session import get_db
from ..engine import persist_recommendation, recommend, serialize_result
from ..web_helpers import (
    as_non_empty_text,
    bean_coffee_data,
    find_existing_bean,
    get_default_dose_g,
    parse_roast_date,
    roast_level_ordinal,
    save_shot,
    starting_dose_for_roast,
)
from ..web_schemas import FeedbackRequest, RecommendationRequest
from .common import active_setup, server_error, uploads_dir

logger = logging.getLogger("wcda.routes")

router = APIRouter()

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
# What Pillow can decode as installed. HEIC/HEIF used to be listed here too,
# but with no HEIF plugin every such upload failed at decode; phones convert
# HEIC to JPEG for a web upload anyway.
_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
_ALLOWED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def _bean_for(db: Session, owner: str, coffee_data: dict[str, Any]) -> Bean:
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
        db, owner, name=name, roaster=roaster, origin=origin, process=process
    )
    if existing is not None:
        return existing

    return Bean(
        owner=owner,
        roaster=roaster,
        name=name,
        origin=origin,
        process=process,
        roast_level=roast_level,
        roast_date=parse_roast_date(coffee_data.get("roast_date")),
        roast_level_ord=roast_level_ordinal(roast_level),
    )


def _recommend(
    db: Session,
    owner: str,
    setup: BrewSetup,
    coffee_data: dict[str, Any],
    bean: Bean | None = None,
    dose_g: float | None = None,
) -> dict[str, Any]:
    """Run the engine and shape the response both recipe routes return.

    The numbers are in `recipe` and the prose in `rationale`, kept apart so
    nothing ever parses a number back out of generated text.

    `bean` is passed when the caller already has the real row; otherwise one
    is found, or stood in for, from coffee_data. `dose_g` is a dose the user
    explicitly asked for. Without one the engine picks: this coffee's last
    dose, or a roast-aware starting dose for a coffee with no shots. Either
    way coffee_data comes back carrying the dose the recipe is for, so the
    dose field on screen always matches the recipe under it -- and the
    coffee's id whenever it is already in the library.
    """
    if bean is None:
        bean = _bean_for(db, owner, coffee_data)

    roast_dose = starting_dose_for_roast(bean.roast_level_ord)
    result = recommend(
        db,
        owner,
        setup,
        bean,
        dose_g,
        default_dose_g=roast_dose or get_default_dose_g(db, owner),
    )
    coffee_data["preferred_dose_g"] = result.recipe.dose_g
    coffee_data["dose_from_roast"] = (
        dose_g is None
        and roast_dose is not None
        and result.recipe.basis in ("prior", "setup_law")
    )

    recommendation_id: int | None = None
    if bean.id is not None:
        coffee_data["bean_id"] = bean.id
        # Only persist against a bean that actually exists; a transient
        # stand-in has no row to reference.
        recommendation_id = persist_recommendation(db, owner, result, setup, bean)

    return {
        "coffee_data": coffee_data,
        "recommendation_id": recommendation_id,
        **serialize_result(result),
    }


@router.post("/api/analyze")
def analyze_image(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    owner: str = Depends(get_owner),
    setup: BrewSetup = Depends(active_setup),
) -> dict[str, Any]:
    content_type = (file.content_type or "").lower()
    if content_type not in _ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400, detail="File must be a JPEG, PNG or WebP image."
        )

    suffix = os.path.splitext(file.filename or "")[1].lower()
    if suffix not in _ALLOWED_IMAGE_EXTS:
        suffix = ".jpg"

    # One byte past the limit is enough to know it is too big, without
    # reading an arbitrarily large upload into memory first.
    content = file.file.read(MAX_UPLOAD_BYTES + 1)
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Image exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.",
        )

    try:
        coffee_data = analyze_coffee_bag(content)
    except VisionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    folder = uploads_dir()
    if folder is not None:
        image_name = f"{uuid.uuid4().hex}{suffix}"
        try:
            (folder / image_name).write_bytes(content)
            coffee_data["image_name"] = image_name
        except OSError:
            logger.warning("Could not persist uploaded image to %s", folder)

    return _recommend(db, owner, setup, coffee_data)


@router.post("/api/recommendation")
def refresh_recommendation(
    body: RecommendationRequest,
    db: Session = Depends(get_db),
    owner: str = Depends(get_owner),
    setup: BrewSetup = Depends(active_setup),
) -> dict[str, Any]:
    """Regenerate the recipe for a scanned bag or a coffee already saved.

    Called when the dose changes, when the active setup changes, and when the
    user opens one of their existing coffees to fine-tune it. Passing
    `bean_id` uses the stored row, so the engine sees the real roast date and
    roast level rather than re-parsing strings, and the resulting
    recommendation is recorded against that bean.
    """
    bean: Bean | None = None
    if body.bean_id is not None:
        bean = (
            db.query(Bean).filter(Bean.id == body.bean_id, Bean.owner == owner).first()
        )
        if bean is None:
            raise HTTPException(status_code=404, detail="Coffee not found")
        coffee_data = bean_coffee_data(bean)
    else:
        coffee_data = dict(body.coffee_data or {})

    try:
        return _recommend(db, owner, setup, coffee_data, bean=bean, dose_g=body.dose_g)
    except Exception as exc:
        raise server_error(exc, "refresh recommendation") from exc


@router.post("/api/feedback")
def save_feedback(
    body: FeedbackRequest,
    db: Session = Depends(get_db),
    owner: str = Depends(get_owner),
    setup: BrewSetup = Depends(active_setup),
) -> dict[str, Any]:
    """Log a shot. Returns the coffee's id, which is new on a bag's first shot."""
    try:
        bean = save_shot(db, owner, setup, body)
    except Exception as exc:
        db.rollback()
        raise server_error(exc, "save feedback") from exc
    return {"status": "saved", "bean_id": bean.id}


@router.get("/api/log-images/{image_name}")
def get_log_image(image_name: str) -> FileResponse:
    folder = uploads_dir()
    if folder is None:
        raise HTTPException(status_code=404, detail="Image storage is unavailable")
    if not image_name or os.path.basename(image_name) != image_name:
        raise HTTPException(status_code=400, detail="Invalid image name")
    path = folder / image_name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(path)
