from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


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
    recommendation_id: int | None = None


class RecommendationRequest(BaseModel):
    coffee_data: dict[str, Any]
    dose_g: float | None = None


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


class SetupSelectInput(BaseModel):
    setup_id: int | None = None
    active_setup_id: int | None = None


class EquipmentLibraryCreateInput(BaseModel):
    type: str
    brand: str
    model: str


class EquipmentLibraryUpdateInput(BaseModel):
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
