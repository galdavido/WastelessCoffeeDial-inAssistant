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
    CoffeeDataOut,
    EquipmentOut,
    RecommendationOut,
    SetupOut,
)
from core.brewing import DoseReduction, GrinderCaps, Recipe, beta_prior, target_for
from core.calibration import fit_setup
from core.engine import EngineResult, serialize_result
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
    calibration = fit_setup([], "espresso", K6, beta_prior("espresso", K6))
    return EngineResult(
        recipe=Recipe(method="espresso", dose_g=18.0, grind_clicks=29.0),
        rationale=Rationale(headline="h", why="w", what_to_watch="x"),
        calibration=calibration,
        tier="D",
        llm_model=None,
        target=target_for("espresso"),
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


if __name__ == "__main__":
    unittest.main()
