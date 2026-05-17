import unittest

from ai.vision import CoffeeData


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


if __name__ == "__main__":
    unittest.main()
