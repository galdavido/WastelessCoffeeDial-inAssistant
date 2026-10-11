"""The response models must describe what the serializers actually send.

Every model in core/api_schemas.py forbids unknown keys and requires every
field, so a serializer that grows or loses a key fails here -- or as a 500 in
tests/test_api_flows.py -- instead of quietly changing what app.js receives.
These tests feed the real serializers' output through the models without a
database.
"""

from __future__ import annotations

import unittest
from typing import Any

from pydantic import ValidationError

from core.api_schemas import EquipmentOut, SetupOut
from core.setups import serialize_equipment, serialize_setup
from database.models import BrewSetup, Equipment


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


if __name__ == "__main__":
    unittest.main()
