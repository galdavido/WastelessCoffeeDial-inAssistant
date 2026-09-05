"""The language model must not be able to introduce a number.

These cover layers 2 and 3 of the guarantee in ai/rationale.py: the numeric
allow-list, and the deterministic template that keeps the recommendation path
working when the LLM is unavailable or misbehaving.
"""

from __future__ import annotations

import unittest

from ai.rationale import Rationale, render_template, scrub_numerals
from core.brewing import Recipe

RECIPE = Recipe(
    method="espresso",
    dose_g=18.0,
    grind_clicks=33.0,
    yield_g=36.0,
    target_time_s=28.0,
    confidence=0.4,
)
ALLOWED = frozenset(RECIPE.numeric_tokens())


class TestScrubNumerals(unittest.TestCase):
    def test_text_with_only_approved_numbers_passes(self) -> None:
        text = "Grind at 33 and pull 18 g into 36 g."
        self.assertEqual(scrub_numerals(text, ALLOWED), text)

    def test_an_invented_grind_setting_is_rejected(self) -> None:
        # The exact failure this whole design exists to prevent.
        self.assertIsNone(scrub_numerals("Try 27 clicks instead.", ALLOWED))

    def test_an_invented_temperature_is_rejected(self) -> None:
        self.assertIsNone(scrub_numerals("Brew this at 94 C.", ALLOWED))

    def test_an_invented_extraction_yield_is_rejected(self) -> None:
        # Unmeasurable without a refractometer, so it must never be stated.
        self.assertIsNone(scrub_numerals("You are extracting at 19.5%.", ALLOWED))

    def test_prose_free_of_numbers_passes(self) -> None:
        text = "Go a little coarser and watch how it pours."
        self.assertEqual(scrub_numerals(text, ALLOWED), text)

    def test_small_integers_are_allowed_for_ordinary_prose(self) -> None:
        text = "Give it 2 or 3 shots to settle."
        self.assertIsNotNone(scrub_numerals(text, ALLOWED))

    def test_decimal_forms_of_an_approved_number_pass(self) -> None:
        self.assertIsNotNone(scrub_numerals("Dose 18.0 g.", ALLOWED))

    def test_comma_decimals_are_normalised(self) -> None:
        # Hungarian locale writes 18,0 -- same number, still approved.
        self.assertIsNotNone(scrub_numerals("Dose 18,0 g.", ALLOWED))


class TestTemplate(unittest.TestCase):
    def test_template_mentions_the_engine_numbers(self) -> None:
        rationale = render_template(RECIPE, "Low - based on general guidance")
        self.assertIn("33", rationale.headline)
        self.assertIn("18", rationale.headline)
        self.assertIn("36", rationale.headline)

    def test_template_output_passes_its_own_guard(self) -> None:
        """Whatever the fallback writes must satisfy the same rule."""
        rationale = render_template(RECIPE, "Low - based on general guidance")
        for field in (rationale.headline, rationale.why, rationale.what_to_watch):
            self.assertIsNotNone(
                scrub_numerals(field, ALLOWED),
                f"template produced an unapproved number: {field!r}",
            )

    def test_template_carries_the_confidence_statement(self) -> None:
        label = "First shot - this is a starting bracket to measure from"
        rationale = render_template(RECIPE, label)
        self.assertIn(label, rationale.why)

    def test_template_without_a_grind_asks_for_a_measurement(self) -> None:
        """Tier E: no click number invented, and it says what to do instead."""
        recipe = Recipe(method="espresso", dose_g=18.0, grind_clicks=None)
        rationale = render_template(recipe, "First shot")
        self.assertNotIn("grind ", rationale.headline)
        self.assertIn("tastes", rationale.what_to_watch)


class TestRationaleSchema(unittest.TestCase):
    def test_schema_declares_no_numeric_fields(self) -> None:
        """Layer 1: structured output cannot emit a field that isn't declared."""
        for field in Rationale.model_fields.values():
            self.assertIs(field.annotation, str)


if __name__ == "__main__":
    unittest.main()
