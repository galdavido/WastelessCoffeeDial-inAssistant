from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, model_validator


class FeedbackRequest(BaseModel):
    coffee_data: dict[str, Any]
    recommendation: str
    actual_grind: str | None = None
    dose_g: float | None = None
    image_name: str | None = None
    # Measured outcome. All optional, and absent means unmeasured -- never
    # substituted with a default, because calibration reads these as truth.
    yield_g: float | None = None
    water_g: float | None = None
    time_s: int | None = None
    taste_axis: (
        Literal["very_sour", "sour", "balanced", "bitter", "very_bitter"] | None
    ) = None
    astringent: bool | None = None
    brew_temp_c: float | None = None
    # Pre-infusion duration and the rest before the pull. Covariates, not
    # part of time_s -- see docs/science.md#preinfusion.
    preinfusion_s: float | None = None
    pause_s: float | None = None
    recommendation_id: int | None = None


class RecommendationRequest(BaseModel):
    """Ask for a recipe, either for a scanned bag or one already saved.

    `bean_id` is what makes fine-tuning possible: the engine then works from
    the real Bean row, so roast date and roast level are populated and the
    resulting recommendation is stored against a real bean.
    """

    coffee_data: dict[str, Any] | None = None
    bean_id: int | None = None
    dose_g: float | None = None

    @model_validator(mode="after")
    def _needs_a_subject(self) -> RecommendationRequest:
        if self.coffee_data is None and self.bean_id is None:
            raise ValueError("coffee_data or bean_id is required")
        return self


class EquipmentUpdate(BaseModel):
    brand: str
    model: str


class DoseUpdate(BaseModel):
    dose_g: float


class GrindOffsetUpdate(BaseModel):
    offset_clicks: float


class SetupInput(BaseModel):
    name: str
    grinder_id: int
    machine_id: int
    # Drives the target bands and which levers the engine may move. Left
    # unset, the engine falls back to espresso.
    method: Literal["espresso", "pourover", "moka"] | None = None


class SetupSelectInput(BaseModel):
    setup_id: int | None = None
    active_setup_id: int | None = None


class EquipmentCapabilityFields(BaseModel):
    """What the hardware can physically do.

    All optional. Where the engine has no capability data it abstains from
    recommending a value rather than guessing one, so a blank field is a
    safe answer -- but spec_source should carry a citation whenever the
    numbers are filled in, since an uncited capability row is a guess.
    """

    grind_min_clicks: float | None = None
    grind_max_clicks: float | None = None
    grind_step_clicks: float | None = None
    grind_um_per_click: float | None = None
    finer_direction: Literal["lower_is_finer", "higher_is_finer"] | None = None
    burr_type: str | None = None
    basket_size_g: float | None = None
    temp_min_c: float | None = None
    temp_max_c: float | None = None
    temp_controllable: bool | None = None
    spec_source: str | None = None


class EquipmentLibraryCreateInput(EquipmentCapabilityFields):
    type: str
    brand: str
    model: str


class EquipmentLibraryUpdateInput(EquipmentCapabilityFields):
    type: str
    brand: str
    model: str


class LogDetailsInput(BaseModel):
    grind_setting: str | None = None
    dose_g: float | None = None
    yield_g: float | None = None
    time_s: int | None = None
    rating: int | None = None
    tasting_notes: str | None = None


class BeanRecordInput(BaseModel):
    roaster: str
    name: str
    origin: str
    process: str
    roast_level: str
    log: LogDetailsInput | None = None
