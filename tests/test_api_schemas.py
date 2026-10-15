"""The response models must describe what the serializers actually send.

Every model in core/api_schemas.py forbids unknown keys and requires every
field, so a serializer that grows or loses a key fails here -- or as a 500 in
tests/test_api_flows.py -- instead of quietly changing what app.js receives.
These tests feed the real serializers' output through the models without a
database.
"""

from __future__ import annotations

import dataclasses
import unittest
from typing import Any

from pydantic import ValidationError

from ai.rationale import Rationale
from core.api_schemas import (
    BeanShotOut,
    CoffeeDataOut,
    CoffeeEntryOut,
    EquipmentOut,
    FitOut,
    RecommendationOut,
    SetupOut,
)
from core.brewing import (
    DoseReduction,
    GrinderCaps,
    Recipe,
    ShotRecord,
    beta_prior,
    target_for,
)
from core.calibration import fit_setup
from core.engine import EngineResult, serialize_fit, serialize_result
from core.retrieval import shots_for_bean
from core.setups import serialize_equipment, serialize_setup
from database.models import BrewSetup, Equipment

K6 = GrinderCaps(
    min_clicks=0.0,
    max_clicks=180.0,
    step_clicks=1.0,
    um_per_click=16.0,
    finer_direction="lower_is_finer",
)


def _grinder(**overrides: Any) -> Equipment:
    fields: dict[str, Any] = {
        "id": 1,
        "owner": "me",
        "type": "grinder",
        "brand": "Kingrinder",
        "model": "K6",
        "grind_min_clicks": 0,
        "grind_max_clicks": 240,
        "grind_step_clicks": 1,
        "grind_um_per_click": 16,
        "finer_direction": "lower_is_finer",
        "burr_type": "conical",
        "basket_size_g": None,
        "temp_min_c": None,
        "temp_max_c": None,
        "temp_controllable": False,
        "spec_source": "https://example.com/k6",
    }
    fields.update(overrides)
    return Equipment(**fields)


def _machine() -> Equipment:
    return Equipment(
        id=2,
        owner=None,
        type="espresso_machine",
        brand="Gaggia",
        model="Classic",
        basket_size_g=18,
        temp_min_c=88,
        temp_max_c=96,
        temp_controllable=True,
    )


class TestGearSerializersMatchTheirModels(unittest.TestCase):
    def test_equipment_serializer_matches_model(self) -> None:
        EquipmentOut.model_validate(serialize_equipment(_grinder(), "me"))
        EquipmentOut.model_validate(serialize_equipment(_machine(), "me"))

    def test_equipment_with_unknown_capabilities_matches_model(self) -> None:
        bare = _grinder(
            grind_min_clicks=None,
            grind_max_clicks=None,
            grind_step_clicks=None,
            grind_um_per_click=None,
            finer_direction=None,
            burr_type=None,
            spec_source=None,
        )
        EquipmentOut.model_validate(serialize_equipment(bare))

    def test_setup_serializer_matches_model(self) -> None:
        setup = BrewSetup(id=5, owner="me", name="Home", method="espresso")
        setup.grinder = _grinder()
        setup.machine = _machine()
        SetupOut.model_validate(serialize_setup(setup))


class TestTheModelsAreStrict(unittest.TestCase):
    def test_strict_models_reject_unknown_keys(self) -> None:
        valid = serialize_equipment(_grinder(), "me")
        with self.assertRaises(ValidationError):
            EquipmentOut.model_validate({**valid, "surprise": 1})

    def test_strict_models_reject_missing_keys(self) -> None:
        valid = serialize_equipment(_grinder(), "me")
        del valid["spec_source"]
        with self.assertRaises(ValidationError):
            EquipmentOut.model_validate(valid)


def _engine_result() -> EngineResult:
    """A first-shot EngineResult, built the way recommend() builds one."""
    calibration = fit_setup([], K6, beta_prior(K6))
    return EngineResult(
        recipe=Recipe(dose_g=18.0, grind_clicks=29.0),
        rationale=Rationale(headline="h", why="w", what_to_watch="x"),
        calibration=calibration,
        tier="D",
        llm_model=None,
        target=target_for(),
        caps=K6,
    )


class TestRecommendationMatchesItsModel(unittest.TestCase):
    def test_recommendation_payload_validates(self) -> None:
        RecommendationOut.model_validate(
            {
                "coffee_data": {
                    "preferred_dose_g": 18.0,
                    "dose_from_roast": False,
                    "bean_id": 7,
                },
                "recommendation_id": 3,
                **serialize_result(_engine_result()),
            }
        )

    def test_suggestion_branch_validates(self) -> None:
        result = dataclasses.replace(
            _engine_result(),
            suggestion=DoseReduction(
                dose_g=16.0,
                yield_g=32.0,
                grind_clicks=31.0,
                channeled_shots=2,
                note="n",
            ),
        )
        payload = RecommendationOut.model_validate(
            {
                "coffee_data": {"preferred_dose_g": 16.0, "dose_from_roast": False},
                "recommendation_id": 3,
                **serialize_result(result),
            }
        )
        assert payload.suggestion is not None
        self.assertEqual(payload.suggestion.kind, "use_less_coffee")

    def test_transient_bean_payload_validates(self) -> None:
        """A new bag with no library match: no recommendation row, no bean id."""
        RecommendationOut.model_validate(
            {
                "coffee_data": {
                    "name": "Gicumbi",
                    "roaster": None,
                    "origin": "Rwanda",
                    "process": None,
                    "roast_level": "light",
                    "roast_date": None,
                    "preferred_dose_g": 18.0,
                    "dose_from_roast": True,
                },
                "recommendation_id": None,
                **serialize_result(_engine_result()),
            }
        )

    def test_coffee_data_keeps_unknown_keys_and_tolerates_missing_ones(self) -> None:
        dumped = CoffeeDataOut.model_validate(
            {
                "preferred_dose_g": 18.0,
                "dose_from_roast": True,
                "name": "X",
                "varietal": "Bourbon",
            }
        ).model_dump()
        self.assertEqual(dumped["varietal"], "Bourbon")
        self.assertIsNone(dumped["origin"])
        with self.assertRaises(ValidationError):
            CoffeeDataOut.model_validate({"dose_from_roast": True})


RWANDA, BRAZIL = 7, 8
NAMES = {RWANDA: "Gicumbi Red Bourbon", BRAZIL: "Cerrado"}


def _shot(bean_id: int, clicks: float, time_s: float, temp: float) -> ShotRecord:
    dose = 18.0 if bean_id == RWANDA else 16.0
    return ShotRecord(
        dose_g=dose,
        setup_id=1,
        bean_id=bean_id,
        grind_clicks=clicks,
        yield_g=dose * 2.0,
        time_s=time_s,
        brew_temp_c=temp,
        preinfusion_s=2.0,
        pause_s=2.0,
    )


# The fixture of tests/test_fit_view.py: two coffees, each internally
# consistent, brewed in temperature bands too far apart to pair.
HISTORY = [
    _shot(RWANDA, 26.0, 34.0, 94.0),
    _shot(RWANDA, 28.0, 30.0, 94.0),
    _shot(RWANDA, 30.0, 26.0, 94.0),
    _shot(BRAZIL, 35.0, 30.0, 91.0),
    _shot(BRAZIL, 36.0, 28.0, 91.0),
]


def _fit_result(history: list[ShotRecord], bean_id: int | None) -> EngineResult:
    calibration = fit_setup(history, K6, beta_prior(K6), bean_id=bean_id)
    return EngineResult(
        recipe=Recipe(dose_g=18.0, grind_clicks=29.0),
        rationale=Rationale(headline="h", why="w", what_to_watch="x"),
        calibration=calibration,
        tier="A" if history else "D",
        llm_model=None,
        history=tuple(history),
        bean_history=tuple(shots_for_bean(history, bean_id)),
        target=target_for(),
        caps=K6,
    )


class TestFitMatchesItsModel(unittest.TestCase):
    def test_fit_payload_validates(self) -> None:
        FitOut.model_validate(
            serialize_fit(_fit_result(HISTORY, RWANDA), NAMES, RWANDA)
        )

    def test_fit_payload_with_an_excluded_shot_validates(self) -> None:
        lonely = _shot(BRAZIL, 41.0, 21.0, 88.0)
        payload = FitOut.model_validate(
            serialize_fit(_fit_result([*HISTORY, lonely], BRAZIL), NAMES, BRAZIL)
        )
        reasons = [s.excluded_reason for s in payload.shots if not s.used_in_fit]
        self.assertTrue(reasons and all(reasons))

    def test_empty_history_fit_validates(self) -> None:
        FitOut.model_validate(serialize_fit(_fit_result([], None), {}, None))

    def test_populated_warning_validates(self) -> None:
        payload = serialize_fit(_fit_result(HISTORY, RWANDA), NAMES, RWANDA)
        payload["warning"] = {"clicks": 27.0, "reason": "one channeling sign"}
        FitOut.model_validate(payload)


def _bean_shot(**overrides: Any) -> dict[str, Any]:
    """One shot as get_bean_shots builds it."""
    shot: dict[str, Any] = {
        "id": 1,
        "created_at": "2026-10-11T08:00:00",
        "setup_id": 5,
        "grind_clicks": 28.0,
        "grind_setting": "28",
        "dose_g": 18.0,
        "yield_g": 36.0,
        "time_s": 30,
        "taste_axis": "balanced",
        "astringent": False,
        "rating": 4,
        "data_quality": "complete",
        "tr": 15.0,
        "band": "in",
        "tasted_right": True,
        "delta_clicks": -2.0,
        "direction": "finer",
        "same_setup_as_prev": True,
        "suggested_grind_clicks": 28.0,
    }
    shot.update(overrides)
    return shot


class TestLibraryModels(unittest.TestCase):
    """These dicts are built inline in routes/coffees.py, so their end-to-end
    check is tests/test_api_flows.py; this pins the loose ends."""

    def test_coffee_entry_without_shots_validates(self) -> None:
        CoffeeEntryOut.model_validate(
            {
                "bean_id": 1,
                "bean_name": "Kochere",
                "roaster": "Test Roasters",
                "origin": "Ethiopia",
                "process": "Washed",
                "roast_level": "Light",
                "roast_date": None,
                "last_brewed_at": None,
                "logs_count": 0,
                "latest_log": None,
            }
        )

    def test_bean_shot_rejects_an_unknown_band(self) -> None:
        BeanShotOut.model_validate(_bean_shot())
        BeanShotOut.model_validate(_bean_shot(band=None, direction=None, tr=None))
        with self.assertRaises(ValidationError):
            BeanShotOut.model_validate(_bean_shot(band="slow"))


if __name__ == "__main__":
    unittest.main()
