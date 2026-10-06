"""The language model must not be able to introduce a number.

These cover layers 2 and 3 of the guarantee in ai/rationale.py: the numeric
allow-list, and the deterministic template that keeps the recommendation path
working when the LLM is unavailable or misbehaving.
"""

from __future__ import annotations

import json
import os
import unittest
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock, patch

from ai.rationale import (
    Rationale,
    _allowed_tokens,
    render_template,
    scrub_numerals,
    write_rationale,
)
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


LABEL = "Low - based on general guidance"


def reply(headline: str, why: str, watch: str) -> Any:
    """A stand-in for a Gemini response carrying structured JSON."""
    return MagicMock(
        text=json.dumps({"headline": headline, "why": why, "what_to_watch": watch})
    )


class TestWriteRationale(unittest.TestCase):
    """The orchestration around the model: the template is the safety net.

    ``write_rationale`` returns ``(rationale, model)``; a model of ``None``
    means the deterministic template was used. The Gemini client is replaced
    wholesale, so nothing here touches the network.
    """

    TEMPLATE = render_template(RECIPE, LABEL)

    def setUp(self) -> None:
        env = patch.dict(
            os.environ,
            {"WCDA_GEMINI_MODELS": "model-a,model-b", "WCDA_LLM_BUDGET_S": "5"},
        )
        env.start()
        self.addCleanup(env.stop)
        self.calls: list[str] = []

    def run_with(self, behaviour: Callable[[str], Any]) -> tuple[Rationale, str | None]:
        def generate_content(model: str, **_: Any) -> Any:
            self.calls.append(model)
            return behaviour(model)

        client = MagicMock()
        client.models.generate_content.side_effect = generate_content
        with patch("ai.rationale.genai.Client", return_value=client):
            return write_rationale(RECIPE, LABEL)

    def assert_is_template(self, result: tuple[Rationale, str | None]) -> None:
        rationale, model = result
        self.assertIsNone(model)
        self.assertEqual(rationale, self.TEMPLATE)

    def test_a_clean_answer_is_used_and_names_its_model(self) -> None:
        good = reply(
            "Grind at 33, pull 18 g into 36 g.", "A touch slower.", "Watch it."
        )

        rationale, model = self.run_with(lambda _: good)

        self.assertEqual(model, "model-a")
        self.assertEqual(rationale.headline, "Grind at 33, pull 18 g into 36 g.")
        self.assertEqual(self.calls, ["model-a"])

    def test_an_invented_number_falls_through_to_the_next_model(self) -> None:
        bad = reply("Try 27 clicks instead.", "Finer.", "Watch.")
        good = reply("Stay at 33.", "Steady.", "Watch.")

        rationale, model = self.run_with(lambda m: bad if m == "model-a" else good)

        self.assertEqual(model, "model-b")
        self.assertEqual(rationale.headline, "Stay at 33.")

    def test_when_every_model_invents_a_number_the_template_is_returned(self) -> None:
        bad = reply("Brew at 94 C.", "Hotter.", "Watch.")

        result = self.run_with(lambda _: bad)

        self.assert_is_template(result)
        self.assertEqual(self.calls, ["model-a", "model-b"])

    def test_the_template_contains_no_numeral_outside_the_allow_list(self) -> None:
        result = self.run_with(lambda _: reply("Brew at 94 C.", "x", "y"))

        self.assert_is_template(result)
        rationale = result[0]
        allowed = _allowed_tokens(RECIPE, LABEL, "", str(RECIPE))
        for field in (rationale.headline, rationale.why, rationale.what_to_watch):
            self.assertIsNotNone(scrub_numerals(field, allowed), field)

    def test_an_empty_response_is_rejected(self) -> None:
        self.assert_is_template(self.run_with(lambda _: MagicMock(text="")))

    def test_a_response_that_is_not_the_schema_is_rejected(self) -> None:
        self.assert_is_template(self.run_with(lambda _: MagicMock(text="{not json")))

    def test_a_retired_model_is_skipped_for_the_next_one(self) -> None:
        good = reply("Stay at 33.", "Steady.", "Watch.")

        def behaviour(model: str) -> Any:
            if model == "model-a":
                raise RuntimeError("404 NOT_FOUND: model is no longer available")
            return good

        _, model = self.run_with(behaviour)

        self.assertEqual(model, "model-b")

    def test_a_bad_api_key_stops_the_chain_and_returns_the_template(self) -> None:
        def behaviour(model: str) -> Any:
            raise RuntimeError("403 PERMISSION_DENIED: API key not valid")

        self.assert_is_template(self.run_with(behaviour))
        self.assertEqual(self.calls, ["model-a"])

    def test_no_client_at_all_still_gives_a_complete_answer(self) -> None:
        with patch("ai.rationale.genai.Client", side_effect=ValueError("no key")):
            result = write_rationale(RECIPE, LABEL)

        self.assert_is_template(result)

    def test_a_failure_inside_the_chain_is_not_raised(self) -> None:
        with (
            patch("ai.rationale.genai.Client", return_value=MagicMock()),
            patch("ai.rationale.try_model_candidates", side_effect=RuntimeError("x")),
        ):
            result = write_rationale(RECIPE, LABEL)

        self.assert_is_template(result)


class TestRationaleSchema(unittest.TestCase):
    def test_schema_declares_no_numeric_fields(self) -> None:
        """Layer 1: structured output cannot emit a field that isn't declared."""
        for field in Rationale.model_fields.values():
            self.assertIs(field.annotation, str)


class TestEngineSuppliedNumbersAreAllowed(unittest.TestCase):
    """Quoting the engine back is not inventing a number.

    Regression for a live fault: the allow-list was built from
    ``recipe.numeric_tokens()`` alone, but the prompt also shows the model the
    engine's notes and confidence label, which name past grind settings and
    shot counts, and invites it to explain them. A good recommendation was
    discarded for saying "going finer to 26 clicks caused channeling" -- 26
    being a setting the engine itself had just described. The whole response
    was rejected, an extra model call was spent, and the user got the template.

    The guarantee is unchanged in substance: a number the engine never
    produced appears in none of these sources and is still refused.
    """

    CONTEXT = (
        "Tier A (7 measured shots on this setup, 3 of them on this coffee).\n"
        "Going finer to 26 did not slow the shot relative to 28, "
        "which is the channeling signature."
    )
    LABEL = "Medium - learning from 7 settings on this setup"

    def setUp(self) -> None:
        self.allowed = _allowed_tokens(RECIPE, self.LABEL, self.CONTEXT, str(RECIPE))

    def test_a_setting_from_the_engines_notes_is_allowed(self) -> None:
        text = "Going finer to 26 clicks caused channeling, so we stay at 33."
        self.assertEqual(scrub_numerals(text, self.allowed), text)

    def test_a_shot_count_from_the_confidence_label_is_allowed(self) -> None:
        text = "This is drawn from 7 settings you have already measured."
        self.assertEqual(scrub_numerals(text, self.allowed), text)

    def test_an_invented_number_is_still_rejected(self) -> None:
        """The layer still has to do its job."""
        for invented in (
            "Try 41 clicks instead.",
            "Brew this at 93 C.",
            "You are extracting at 21.5%.",
            "Pull it to 52 g.",
        ):
            self.assertIsNone(scrub_numerals(invented, self.allowed), invented)

    def test_recipe_numbers_survive_the_widening(self) -> None:
        text = "Grind at 33 and pull 18 g into 36 g."
        self.assertEqual(scrub_numerals(text, self.allowed), text)


if __name__ == "__main__":
    unittest.main()
