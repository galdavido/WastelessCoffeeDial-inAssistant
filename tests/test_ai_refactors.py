from __future__ import annotations

import os
import unittest

from ai.model_selection import (
    GEMINI_MODEL_CANDIDATES,
    thinking_level_for,
    try_model_candidates,
)
from ai.vision import _parse_coffee_data_response


class TestAiRefactors(unittest.TestCase):
    def test_try_model_candidates_returns_first_success(self) -> None:
        attempts: list[str] = []

        def call_model(model_name: str) -> str:
            attempts.append(model_name)
            if model_name == "m1":
                raise Exception("service unavailable")
            if model_name == "m2":
                return ""
            return "ok"

        def evaluate_result(value: str) -> tuple[bool, str | None]:
            return (bool(value), None if value else "empty response")

        result, error = try_model_candidates(
            ("m1", "m2", "m3"),
            call_model=call_model,
            evaluate_result=evaluate_result,
        )

        self.assertEqual(result, "ok")
        self.assertIsNone(error)
        self.assertEqual(attempts, ["m1", "m2", "m3"])

    def test_try_model_candidates_stops_on_non_transient_error(self) -> None:
        attempts: list[str] = []

        def call_model(model_name: str) -> str:
            attempts.append(model_name)
            if model_name == "m1":
                raise Exception("invalid api key")
            return "ok"

        result, error = try_model_candidates(
            ("m1", "m2"),
            call_model=call_model,
            evaluate_result=lambda value: (True, None),
        )

        self.assertIsNone(result)
        self.assertEqual(error, "m1: invalid api key")
        self.assertEqual(attempts, ["m1"])

    # The old _rank_similar_logs_for_active_setup test lived here. That
    # ranking moved into core.retrieval.similarity(), where "same setup"
    # is an explicit, weighted term -- see test_retrieval.py.

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


class TestThinkingLevel(unittest.TestCase):
    """Only Gemini 3.x takes thinking_level, and sending it elsewhere aborts.

    try_model_candidates treats an unrecognised-parameter error as
    non-transient and stops the chain, so the version gate has to hold for
    every fallback entry, not just the ones we expect to be reached.
    """

    def setUp(self) -> None:
        self._saved = os.environ.pop("WCDA_GEMINI_THINKING", None)

    def tearDown(self) -> None:
        os.environ.pop("WCDA_GEMINI_THINKING", None)
        if self._saved is not None:
            os.environ["WCDA_GEMINI_THINKING"] = self._saved

    def test_pre_3x_models_never_get_the_parameter(self) -> None:
        for model in (
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
            "gemini-flash-lite-latest",
        ):
            self.assertIsNone(thinking_level_for(model), model)

    def test_3x_models_default_to_low(self) -> None:
        self.assertEqual(thinking_level_for("gemini-3.8-flash"), "low")

    def test_the_env_override_wins_on_3x(self) -> None:
        os.environ["WCDA_GEMINI_THINKING"] = "high"
        self.assertEqual(thinking_level_for("gemini-3.8-flash"), "high")
        # ...but cannot force it onto a model that would reject it.
        self.assertIsNone(thinking_level_for("gemini-2.5-flash"))

    def test_off_disables_it(self) -> None:
        os.environ["WCDA_GEMINI_THINKING"] = "off"
        self.assertIsNone(thinking_level_for("gemini-3.8-flash"))

    def test_an_unrecognised_value_falls_back_to_the_default(self) -> None:
        os.environ["WCDA_GEMINI_THINKING"] = "maximum"
        self.assertEqual(thinking_level_for("gemini-3.8-flash"), "low")

    def test_every_shipped_candidate_is_classified(self) -> None:
        """No candidate may sit in the gap between the two rules."""
        for model in GEMINI_MODEL_CANDIDATES:
            self.assertIn(thinking_level_for(model), (None, "low", "high"), model)


if __name__ == "__main__":
    unittest.main()
