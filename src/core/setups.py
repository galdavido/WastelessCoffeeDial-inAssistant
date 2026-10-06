"""Per-user settings, default equipment and brew setups, and their JSON shapes."""

from __future__ import annotations

from typing import Any

from database.models import AppSetting, BrewSetup, Equipment, as_float

DEFAULT_DOSE_G = 16.0


def get_default_dose_g(db: Any, owner: str) -> float:
    """The user's stored default dose, or 16 g."""
    try:
        dose = float(get_setting(db, owner, "default_dose_g") or DEFAULT_DOSE_G)
    except ValueError:
        return DEFAULT_DOSE_G
    return dose if dose > 0 else DEFAULT_DOSE_G


def set_default_dose_g(db: Any, owner: str, dose: float) -> None:
    set_setting(db, owner, "default_dose_g", str(dose))


def ensure_default_equipment(db: Any) -> tuple[Any, Any]:
    # Shared entries only: a new user's default setup points at the seeded
    # baseline hardware, never at something another friend added.
    shared = db.query(Equipment).filter(Equipment.owner.is_(None))
    grinder = shared.filter(Equipment.type == "grinder").order_by(Equipment.id).first()
    machine = shared.filter(Equipment.type != "grinder").order_by(Equipment.id).first()
    if not grinder:
        grinder = Equipment(type="grinder", brand="Unknown", model="Unknown")
        db.add(grinder)
    if not machine:
        machine = Equipment(type="espresso_machine", brand="Unknown", model="Unknown")
        db.add(machine)
    db.commit()
    db.refresh(grinder)
    db.refresh(machine)
    return grinder, machine


def serialize_equipment(item: Equipment, owner: str | None = None) -> dict[str, Any]:
    return {
        "id": item.id,
        "type": item.type,
        "brand": item.brand,
        "model": item.model,
        # Only whoever added an entry may change it; shared ones are read-only.
        "shared": item.owner is None,
        "editable": owner is not None and item.owner == owner,
        # Capability data. Nulls are meaningful: where these are unknown the
        # engine abstains rather than guessing, so the UI shows them as gaps
        # worth filling rather than hiding them.
        "grind_min_clicks": as_float(item.grind_min_clicks),
        "grind_max_clicks": as_float(item.grind_max_clicks),
        "grind_step_clicks": as_float(item.grind_step_clicks),
        "grind_um_per_click": as_float(item.grind_um_per_click),
        "finer_direction": item.finer_direction,
        "burr_type": item.burr_type,
        "basket_size_g": as_float(item.basket_size_g),
        "temp_min_c": as_float(item.temp_min_c),
        "temp_max_c": as_float(item.temp_max_c),
        "temp_controllable": bool(item.temp_controllable),
        "spec_source": item.spec_source,
    }


def get_setting(db: Any, owner: str, key: str) -> str | None:
    setting = (
        db.query(AppSetting)
        .filter(AppSetting.owner == owner, AppSetting.key == key)
        .first()
    )
    return setting.value if setting else None


def set_setting(db: Any, owner: str, key: str, value: str) -> None:
    setting = (
        db.query(AppSetting)
        .filter(AppSetting.owner == owner, AppSetting.key == key)
        .first()
    )
    if setting:
        setting.value = value
    else:
        db.add(AppSetting(owner=owner, key=key, value=value))
    db.commit()


def ensure_default_setup(db: Any, owner: str) -> BrewSetup:
    setup = (
        db.query(BrewSetup)
        .filter(BrewSetup.owner == owner)
        .order_by(BrewSetup.id.asc())
        .first()
    )
    if setup:
        return setup

    # Equipment is a shared catalogue, so a new user's first setup points at
    # whatever baseline hardware already exists rather than owning its own.
    grinder, machine = ensure_default_equipment(db)
    setup = BrewSetup(
        owner=owner,
        name="Default Setup",
        grinder_id=grinder.id,
        machine_id=machine.id,
    )
    db.add(setup)
    db.commit()
    db.refresh(setup)
    return setup


def get_active_setup(db: Any, owner: str) -> BrewSetup:
    """The setup recipes are computed for and new shots are logged on.

    The one chosen in the app, else the user's oldest. It only writes the
    first time a user is ever seen, to give them a default setup.
    """
    chosen = get_setting(db, owner, "active_setup_id")
    if chosen and chosen.isdigit():
        setup = (
            db.query(BrewSetup)
            .filter(BrewSetup.id == int(chosen), BrewSetup.owner == owner)
            .first()
        )
        if setup is not None:
            return setup
    return ensure_default_setup(db, owner)


def serialize_setup(setup: BrewSetup) -> dict[str, Any]:
    return {
        "id": setup.id,
        "name": setup.name,
        "method": setup.method,
        "grinder": serialize_equipment(setup.grinder),
        "machine": serialize_equipment(setup.machine),
    }
