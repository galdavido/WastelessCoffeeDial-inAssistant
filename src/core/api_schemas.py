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

from typing import Literal

from pydantic import BaseModel, ConfigDict

from .brewing import Basis, Method


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StatusOut(_Strict):
    status: str


# --- Recommendation ---------------------------------------------------------


class RecipeOut(_Strict):
    """Every number on the recipe card; all of them decided by the engine."""

    method: Method
    grind_clicks: float | None
    dose_g: float
    yield_g: float | None
    water_g: float | None
    brew_temp_c: float | None
    target_time_lo_s: float | None
    target_time_s: float | None
    preinfusion_s: float | None
    pause_s: float | None
    basis: Basis
    confidence: float
    guardrails_hit: list[str]


class RationaleOut(_Strict):
    headline: str
    why: str
    what_to_watch: str


class SuggestionOut(_Strict):
    """Cameron's use-less-coffee move, offered beside the recipe."""

    kind: Literal["use_less_coffee"]
    dose_g: float
    yield_g: float | None
    grind_clicks: float | None
    channeled_shots: int
    note: str


class CoffeeDataOut(BaseModel):
    """The coffee the recipe is for -- the one deliberately loose model.

    ``POST /api/recommendation`` echoes back whatever ``coffee_data`` the client
    sent and bag OCR's keys are not fixed, so unknown keys are kept and the
    bean fields may be absent. Only the two keys the server always sets are
    required.
    """

    model_config = ConfigDict(extra="allow")

    preferred_dose_g: float
    dose_from_roast: bool
    bean_id: int | None = None
    image_name: str | None = None
    name: str | None = None
    roaster: str | None = None
    origin: str | None = None
    process: str | None = None
    roast_level: str | None = None
    roast_date: str | None = None


class RecommendationOut(_Strict):
    """``POST /api/analyze`` and ``POST /api/recommendation``."""

    coffee_data: CoffeeDataOut
    recommendation_id: int | None
    recipe: RecipeOut
    rationale: RationaleOut
    confidence_label: str
    tier: str
    protocol: str | None
    suggestion: SuggestionOut | None


class BeanSavedOut(_Strict):
    status: str
    bean_id: int


# --- Fit view (GET /api/fit, engine.serialize_fit) ---------------------------


class TargetOut(_Strict):
    """A target band, raw and as normalised time (time / brew ratio)."""

    tr_lo: float | None
    tr_hi: float | None
    time_lo: float | None
    time_hi: float | None
    ratio_aim: float


class LawOut(_Strict):
    alpha: float | None
    alpha_reference_dose: float | None
    gamma: float
    gamma_prior: float
    gamma_fitted: float | None
    gamma_weight: float
    n_dose_pairs: int
    dose_ref_g: float | None
    beta_used: float | None
    beta_fitted: float | None
    beta_prior: float | None
    beta_source: str
    shrink_weight: float
    kappa: float
    n_eff: int
    click_span: float
    confidence: float
    confidence_label: str
    tier: str


class FitBeanOut(_Strict):
    id: int
    name: str
    delta_bean: float
    is_current: bool


class FitShotOut(_Strict):
    """One shot of the history; ``index`` is what the pairs point at."""

    index: int
    bean_id: int | None
    clicks: float | None
    tr: float | None
    tr_measured: float | None
    time_s: float | None
    dose_g: float
    yield_g: float | None
    water_g: float | None
    brew_temp_c: float | None
    preinfusion_s: float | None
    pause_s: float | None
    taste_axis: str | None
    rating: int | None
    created_at: str | None
    used_in_fit: bool
    excluded_reason: str | None


class PairOut(_Strict):
    slope: float | None
    a_index: int
    b_index: int
    bean_id: int | None


class RejectedPairOut(_Strict):
    a_index: int
    b_index: int
    bean_id: int | None
    other_bean_id: int | None
    reason: str


class ClicksReasonOut(_Strict):
    """The hard floor, or the softer warning line; both null when absent."""

    clicks: float | None
    reason: str | None


class GrinderCapsOut(_Strict):
    min_clicks: float | None
    max_clicks: float | None
    step_clicks: float
    um_per_click: float | None
    finer_direction: str


class FitRecipeOut(_Strict):
    grind_clicks: float | None
    basis: Basis
    guardrails_hit: list[str]


class FitOut(_Strict):
    law: LawOut
    beans: list[FitBeanOut]
    shots: list[FitShotOut]
    pairs: list[PairOut]
    pairs_rejected: list[RejectedPairOut]
    pairs_rejected_by_reason: dict[str, int]
    target: TargetOut
    floor: ClicksReasonOut
    warning: ClicksReasonOut
    grinder: GrinderCapsOut
    recipe: FitRecipeOut


# --- Coffee library (routes/coffees.py) --------------------------------------


class LatestLogOut(_Strict):
    id: int
    created_at: str
    grinder: str
    machine: str
    grind_setting: str
    dose_g: float
    yield_g: float | None
    time_s: int | None
    rating: int | None
    tasting_notes: str | None
    # The bag photo, which lives on an older log than this one after shot one.
    image_name: str | None
    image_url: str | None


class CoffeeEntryOut(_Strict):
    bean_id: int
    bean_name: str
    roaster: str
    origin: str
    process: str
    roast_level: str
    roast_date: str | None
    last_brewed_at: str | None
    logs_count: int
    latest_log: LatestLogOut | None


class CoffeeListOut(_Strict):
    """``GET /api/logs``: the coffees, most recently brewed first."""

    entries: list[CoffeeEntryOut]


class BeanRefOut(_Strict):
    id: int
    name: str
    roaster: str


class BeanShotOut(_Strict):
    """One shot, judged against its band on the server, not in the browser."""

    id: int
    created_at: str
    setup_id: int | None
    method: str
    grind_clicks: float | None
    grind_setting: str
    dose_g: float
    yield_g: float | None
    water_g: float | None
    time_s: int | None
    taste_axis: str | None
    astringent: bool | None
    rating: int | None
    data_quality: str
    tr: float | None
    band: Literal["in", "fast", "long"] | None
    tasted_right: bool
    delta_clicks: float | None
    direction: Literal["finer", "coarser"] | None
    same_setup_as_prev: bool
    suggested_grind_clicks: float | None


class BeanShotsOut(_Strict):
    """``GET /api/beans/{bean_id}/shots``."""

    bean: BeanRefOut
    target: TargetOut
    shots: list[BeanShotOut]


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
