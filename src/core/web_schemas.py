from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, model_validator

# Names typed by a person: a coffee, a roaster, a grinder, a setup. The cap is
# far above anything real and only stops a runaway paste reaching the table.
Name = Annotated[str, Field(max_length=200)]
PositiveGrams = Annotated[float, Field(gt=0)]


class FeedbackRequest(BaseModel):
    coffee_data: dict[str, Any]
    actual_grind: str | None = None
    dose_g: float | None = None
    image_name: str | None = None
    # Measured outcome. All optional, and absent means unmeasured -- never
    # substituted with a default, because calibration reads these as truth.
    yield_g: float | None = None
    water_g: float | None = None
    # A float, even though the column is whole seconds: the wizard's timer
    # reports tenths, and an int here rejected every timed shot outright.
    # Rounding to the second happens on the way into the row.
    time_s: float | None = None
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
    dose_g: PositiveGrams | None = None
    # Gemini writes the prose only for the first recipe on a coffee (a scan,
    # or opening it from the library). Dose changes, setup switches and the
    # refresh after a shot send False and get the deterministic template:
    # every number is the same either way, and those are the waits that
    # matter most. Defaults to True so an older cached client keeps working.
    explain: bool = True

    @model_validator(mode="after")
    def _needs_a_subject(self) -> RecommendationRequest:
        if self.coffee_data is None and self.bean_id is None:
            raise ValueError("coffee_data or bean_id is required")
        return self


class DoseUpdate(BaseModel):
    dose_g: PositiveGrams


class SetupInput(BaseModel):
    name: Name
    grinder_id: int
    machine_id: int
    # Drives the target bands and which levers the engine may move. Left
    # unset, it is inferred from the brewer.
    method: Literal["espresso", "pourover", "moka"] | None = None


class SetupSelectInput(BaseModel):
    setup_id: int


class EquipmentInput(BaseModel):
    """An equipment entry, and what the hardware can physically do.

    The capabilities are all optional. Where the engine has no capability
    data it abstains from recommending a value rather than guessing one, so a
    blank field is a safe answer -- but spec_source should carry a citation
    whenever the numbers are filled in, since an uncited capability row is a
    guess.
    """

    type: Literal["grinder", "espresso_machine", "filter", "other"]
    brand: Name
    model: Name
    grind_min_clicks: float | None = None
    grind_max_clicks: float | None = None
    grind_step_clicks: float | None = None
    grind_um_per_click: float | None = None
    finer_direction: Literal["lower_is_finer", "higher_is_finer"] | None = None
    burr_type: Name | None = None
    basket_size_g: float | None = None
    temp_min_c: float | None = None
    temp_max_c: float | None = None
    temp_controllable: bool | None = None
    spec_source: Annotated[str, Field(max_length=2000)] | None = None


class LogDetailsInput(BaseModel):
    grind_setting: str | None = None
    dose_g: float | None = None
    yield_g: float | None = None
    # Float for the same reason as FeedbackRequest.time_s: a typed "27.5"
    # must not be a validation error.
    time_s: float | None = None
    rating: int | None = None
    tasting_notes: str | None = None


class BeanRecordInput(BaseModel):
    roaster: Name
    name: Name
    origin: Name
    process: Name
    roast_level: Name
    log: LogDetailsInput | None = None
