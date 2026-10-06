"""Bag OCR (ai.vision): payload validation and failure reporting."""

from __future__ import annotations

import unittest

from ai.vision import _parse_coffee_data_response


class TestVision(unittest.TestCase):
    def test_parse_coffee_data_response_validates_payload(self) -> None:
        valid_json = (
            '{"roaster":"Demo","name":"Lot 1","origin":"Ethiopia",'
            '"process":"Washed","roast_level":"Light","roast_date":"2026-05-01"}'
        )
        invalid_json = '{"name":"Only Name"}'

        parsed_valid = _parse_coffee_data_response(valid_json)
        parsed_invalid = _parse_coffee_data_response(invalid_json)

        self.assertIsNotNone(parsed_valid)
        self.assertEqual(parsed_valid["origin"], "Ethiopia")
        self.assertIsNone(parsed_invalid)

    def test_an_unreadable_image_raises_rather_than_setting_shared_state(self) -> None:
        """The failure travels with the call, so concurrent scans cannot swap it."""
        import ai.vision as vision

        with self.assertRaises(vision.VisionError) as ctx:
            vision.analyze_coffee_bag(b"not an image")
        self.assertIn("Failed to read image", str(ctx.exception))
        self.assertFalse(hasattr(vision, "get_last_vision_error"))


if __name__ == "__main__":
    unittest.main()
