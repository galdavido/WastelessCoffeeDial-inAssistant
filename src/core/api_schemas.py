"""What the API sends back: one model per JSON object a route returns.

Requests are modelled in web_schemas.py; these are the responses, attached to
each route with ``response_model=`` so the generated schema
(``docs/openapi.json``) describes both directions.

The routes and serializers still build plain dicts; FastAPI validates them
against these models on the way out. Every model forbids unknown keys and
requires every field, so a serializer key missing from its model is a 500
naming the field -- in tests first -- rather than a field FastAPI silently
filters out of what app.js receives. Types describe today's JSON: timestamps
stay ``str`` because the serializers already send ``isoformat()``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StatusOut(_Strict):
    status: str


# --- Gear -------------------------------------------------------------------


class EquipmentOut(_Strict):
    """``setups.serialize_equipment``. Null capabilities are meaningful gaps."""

    id: int
    type: str
    brand: str
    model: str
    shared: bool
    editable: bool
    grind_min_clicks: float | None
    grind_max_clicks: float | None
    grind_step_clicks: float | None
    grind_um_per_click: float | None
    finer_direction: str | None
    burr_type: str | None
    basket_size_g: float | None
    temp_min_c: float | None
    temp_max_c: float | None
    temp_controllable: bool
    spec_source: str | None


class SetupOut(_Strict):
    id: int
    name: str
    method: str | None
    grinder: EquipmentOut
    machine: EquipmentOut


class EquipmentNameOut(_Strict):
    brand: str
    model: str


class ActiveEquipmentOut(_Strict):
    grinder: EquipmentNameOut
    machine: EquipmentNameOut


class EquipmentLibraryOut(_Strict):
    grinders: list[EquipmentOut]
    machines: list[EquipmentOut]


class EquipmentSavedOut(_Strict):
    status: str
    equipment: EquipmentOut


class SetupsOut(_Strict):
    active_setup_id: int
    setups: list[SetupOut]


class SetupSavedOut(_Strict):
    status: str
    setup: SetupOut


class SetupSelectedOut(_Strict):
    status: str
    setup_id: int


class DoseOut(_Strict):
    dose_g: float


class DoseSavedOut(_Strict):
    status: str
    dose_g: float


# --- Meta -------------------------------------------------------------------


class VersionOut(_Strict):
    asset_version: int | None
    engine_version: str


class WhoamiOut(_Strict):
    owner: str
    auth_mode: str
