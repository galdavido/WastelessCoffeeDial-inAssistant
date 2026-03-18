import unittest

from ai.vision import CoffeeData
from scraping.scraper import EquipmentData


class TestSchemaModels(unittest.TestCase):
    def test_coffee_data_schema_accepts_expected_fields(self) -> None:
        payload = {
            "roaster": "Demo Roaster",
            "name": "Kenya Lot 12",
            "origin": "Kenya",
            "process": "Washed",
            "roast_level": "Light",
            "roast_date": "2026-03-01",
        }
        model = CoffeeData(**payload)
        self.assertEqual(model.roaster, "Demo Roaster")
        self.assertEqual(model.origin, "Kenya")

    def test_equipment_data_schema_accepts_expected_fields(self) -> None:
        payload = {
            "brand": "AVX",
            "model": "NB64V",
            "equipment_type": "grinder",
            "burr_size_mm": 64,
            "burr_type": "Flat",
            "boiler_type": None,
            "key_features": ["Single dose", "Variable RPM"],
        }
        model = EquipmentData(**payload)
        self.assertEqual(model.equipment_type, "grinder")
        self.assertEqual(model.burr_size_mm, 64)


if __name__ == "__main__":
    unittest.main()
