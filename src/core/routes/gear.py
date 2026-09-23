"""Equipment, setups (a grinder paired with a brewer), and settings."""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from database.models import BrewSetup, DialInLog, Equipment, Recommendation

from ..auth import get_owner
from ..db_session import get_db
from ..web_helpers import (
    as_non_empty_text,
    get_default_dose_g,
    serialize_equipment,
    serialize_setup,
    set_default_dose_g,
    set_setting,
)
from ..web_schemas import (
    DoseUpdate,
    EquipmentInput,
    SetupInput,
    SetupSelectInput,
)
from .common import active_setup, server_error

router = APIRouter()

_POUROVER_MODELS = re.compile(r"v60|kalita|chemex|origami|switch|dripper", re.I)
_MOKA_MODELS = re.compile(r"moka|kotyog|bialetti|brikka", re.I)

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


def _apply_equipment_fields(item: Equipment, body: EquipmentInput) -> None:
    """Copy the form onto the row.

    Capability values are copied only when sent, so a partially-filled form
    does not blank out values that were already known.
    """
    item.type = body.type
    item.brand = as_non_empty_text(body.brand)
    item.model = as_non_empty_text(body.model)
    for field_name in _CAPABILITY_FIELDS:
        value = getattr(body, field_name)
        if value is not None:
            setattr(item, field_name, value)


def _editable_equipment(db: Session, equipment_id: int, owner: str) -> Equipment:
    """An equipment row this user may change, or the reason they may not.

    Everyone can pick any entry for a setup, but an entry's capability data
    bounds every recommendation made on it -- so only whoever added it may
    change it, and the shared baseline entries (no owner) are read-only.
    """
    item = db.get(Equipment, equipment_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Equipment not found")
    if item.owner is None:
        raise HTTPException(
            status_code=403,
            detail="Shared equipment can't be changed. Add your own entry instead.",
        )
    if item.owner != owner:
        raise HTTPException(
            status_code=403,
            detail="Only the person who added this can change it. "
            "Add your own entry instead.",
        )
    return item


def _in_use(
    db: Session, equipment_id: int, *, as_grinder: bool, as_brewer: bool
) -> bool:
    """Whether any setup or shot refers to this entry in the given role(s)."""
    for model in (BrewSetup, DialInLog):
        roles = []
        if as_grinder:
            roles.append(model.grinder_id == equipment_id)
        if as_brewer:
            roles.append(model.machine_id == equipment_id)
        if db.query(model.id).filter(or_(*roles)).first() is not None:
            return True
    return False


def _setup_equipment(db: Session, body: SetupInput) -> tuple[Equipment, Equipment]:
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
    if grinder is None or machine is None:
        raise HTTPException(status_code=400, detail="Selected equipment not found")
    return grinder, machine


def _owned_setup(db: Session, setup_id: int, owner: str) -> BrewSetup:
    setup = (
        db.query(BrewSetup)
        .filter(BrewSetup.id == setup_id, BrewSetup.owner == owner)
        .first()
    )
    if setup is None:
        raise HTTPException(status_code=404, detail="Setup not found")
    return setup


# --- equipment ---------------------------------------------------------------


@router.get("/api/equipment")
def get_active_equipment(setup: BrewSetup = Depends(active_setup)) -> dict[str, Any]:
    """The grinder and brewer of the active setup, by name."""
    return {
        "grinder": {"brand": setup.grinder.brand, "model": setup.grinder.model},
        "machine": {"brand": setup.machine.brand, "model": setup.machine.model},
    }


@router.get("/api/equipment/library")
def get_equipment_library(
    db: Session = Depends(get_db),
    owner: str = Depends(get_owner),
) -> dict[str, list[dict[str, Any]]]:
    items = (
        db.query(Equipment)
        .order_by(Equipment.type.asc(), Equipment.brand.asc(), Equipment.model.asc())
        .all()
    )
    return {
        "grinders": [
            serialize_equipment(item, owner) for item in items if item.type == "grinder"
        ],
        "machines": [
            serialize_equipment(item, owner) for item in items if item.type != "grinder"
        ],
    }


@router.post("/api/equipment/library")
def create_equipment(
    body: EquipmentInput,
    db: Session = Depends(get_db),
    owner: str = Depends(get_owner),
) -> dict[str, Any]:
    try:
        item = Equipment(owner=owner)
        _apply_equipment_fields(item, body)
        db.add(item)
        db.commit()
        db.refresh(item)
    except Exception as exc:
        db.rollback()
        raise server_error(exc, "create equipment") from exc
    return {"status": "created", "equipment": serialize_equipment(item, owner)}


@router.put("/api/equipment/library/{equipment_id}")
def update_equipment(
    equipment_id: int,
    body: EquipmentInput,
    db: Session = Depends(get_db),
    owner: str = Depends(get_owner),
) -> dict[str, Any]:
    item = _editable_equipment(db, equipment_id, owner)
    # A grinder cannot become a brewer while a setup or shot uses it as a
    # grinder, and vice versa.
    becomes_grinder = body.type == "grinder"
    if _in_use(
        db, equipment_id, as_grinder=not becomes_grinder, as_brewer=becomes_grinder
    ):
        raise HTTPException(
            status_code=400,
            detail="Cannot change equipment category while it is referenced",
        )
    try:
        _apply_equipment_fields(item, body)
        db.commit()
        db.refresh(item)
    except Exception as exc:
        db.rollback()
        raise server_error(exc, "update equipment") from exc
    return {"status": "updated", "equipment": serialize_equipment(item, owner)}


@router.delete("/api/equipment/library/{equipment_id}")
def delete_equipment(
    equipment_id: int,
    db: Session = Depends(get_db),
    owner: str = Depends(get_owner),
) -> dict[str, str]:
    item = _editable_equipment(db, equipment_id, owner)
    if _in_use(db, equipment_id, as_grinder=True, as_brewer=True):
        raise HTTPException(
            status_code=400,
            detail="Equipment is in use by setups/logs and cannot be deleted",
        )
    try:
        db.delete(item)
        db.commit()
    except Exception as exc:
        db.rollback()
        raise server_error(exc, "delete equipment") from exc
    return {"status": "deleted"}


# --- setups ------------------------------------------------------------------


@router.get("/api/setups")
def get_setups(
    db: Session = Depends(get_db),
    owner: str = Depends(get_owner),
    active: BrewSetup = Depends(active_setup),
) -> dict[str, Any]:
    setups = (
        db.query(BrewSetup)
        .filter(BrewSetup.owner == owner)
        .order_by(BrewSetup.name.asc(), BrewSetup.id.asc())
        .all()
    )
    return {
        "active_setup_id": active.id,
        "setups": [serialize_setup(item) for item in setups],
    }


@router.post("/api/setups")
def create_setup(
    body: SetupInput,
    db: Session = Depends(get_db),
    owner: str = Depends(get_owner),
) -> dict[str, Any]:
    grinder, machine = _setup_equipment(db, body)
    try:
        setup = BrewSetup(
            owner=owner,
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
        raise server_error(exc, "create setup") from exc
    return {"status": "created", "setup": serialize_setup(setup)}


# Declared before "/api/setups/{setup_id}": FastAPI matches in definition
# order, so otherwise the literal "active" is parsed as a setup id.
@router.put("/api/setups/active")
def select_setup(
    body: SetupSelectInput,
    db: Session = Depends(get_db),
    owner: str = Depends(get_owner),
) -> dict[str, Any]:
    setup = _owned_setup(db, body.setup_id, owner)
    set_setting(db, owner, "active_setup_id", str(setup.id))
    return {"status": "selected", "setup_id": setup.id}


@router.put("/api/setups/{setup_id}")
def update_setup(
    setup_id: int,
    body: SetupInput,
    db: Session = Depends(get_db),
    owner: str = Depends(get_owner),
) -> dict[str, Any]:
    setup = _owned_setup(db, setup_id, owner)
    grinder, machine = _setup_equipment(db, body)
    try:
        setup.name = as_non_empty_text(body.name)
        setup.grinder_id = grinder.id
        setup.machine_id = machine.id
        setup.method = body.method or setup.method or _infer_method(machine)
        db.commit()
        db.refresh(setup)
    except Exception as exc:
        db.rollback()
        raise server_error(exc, "update setup") from exc
    return {"status": "updated", "setup": serialize_setup(setup)}


@router.delete("/api/setups/{setup_id}")
def delete_setup(
    setup_id: int,
    db: Session = Depends(get_db),
    owner: str = Depends(get_owner),
) -> dict[str, str]:
    setup = _owned_setup(db, setup_id, owner)
    if db.query(BrewSetup).filter(BrewSetup.owner == owner).count() <= 1:
        raise HTTPException(status_code=400, detail="At least one setup must remain")
    # Shots and recommendations keep their setup: it is what makes a click
    # number mean anything, and calibration reads shots by setup. So a setup
    # with history stays, rather than failing on the foreign key with a 500.
    for model in (DialInLog, Recommendation):
        if db.query(model.id).filter(model.setup_id == setup_id).first() is not None:
            raise HTTPException(
                status_code=400,
                detail="This setup has shots logged on it, so it can't be "
                "deleted -- they are what its recommendations are learned from.",
            )
    try:
        db.delete(setup)
        db.commit()
        next_setup = (
            db.query(BrewSetup)
            .filter(BrewSetup.owner == owner)
            .order_by(BrewSetup.id.asc())
            .first()
        )
        if next_setup:
            set_setting(db, owner, "active_setup_id", str(next_setup.id))
    except Exception as exc:
        db.rollback()
        raise server_error(exc, "delete setup") from exc
    return {"status": "deleted"}


# --- settings ----------------------------------------------------------------


@router.get("/api/settings")
def get_settings(
    db: Session = Depends(get_db), owner: str = Depends(get_owner)
) -> dict[str, float]:
    return {"dose_g": get_default_dose_g(db, owner)}


@router.put("/api/settings/dose")
def update_dose(
    body: DoseUpdate,
    db: Session = Depends(get_db),
    owner: str = Depends(get_owner),
) -> dict[str, Any]:
    try:
        set_default_dose_g(db, owner, body.dose_g)
    except Exception as exc:
        db.rollback()
        raise server_error(exc, "update dose") from exc
    return {"status": "updated", "dose_g": body.dose_g}
