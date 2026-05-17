from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import unittest

from ai.model_selection import try_model_candidates
from ai.rag import _rank_similar_logs_for_active_setup
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

    def test_rank_similar_logs_prefers_active_setup_equipment(self) -> None:
        now = datetime.now(timezone.utc)
        active_grinder = SimpleNamespace(brand="Kingrinder", model="K6")
        active_machine = SimpleNamespace(brand="AVX", model="Hero Plus 2024")

        matching_row = (
            SimpleNamespace(created_at=now),
            SimpleNamespace(),
            SimpleNamespace(brand="Kingrinder", model="K6"),
            SimpleNamespace(brand="AVX", model="Hero Plus 2024"),
        )
        newer_non_matching_row = (
            SimpleNamespace(created_at=now.replace(year=now.year + 1)),
            SimpleNamespace(),
            SimpleNamespace(brand="Other", model="GX"),
            SimpleNamespace(brand="Other", model="MX"),
        )

        ranked = _rank_similar_logs_for_active_setup(
            [newer_non_matching_row, matching_row],
            grinder=active_grinder,
            machine=active_machine,
        )

        self.assertIs(ranked[0], matching_row)

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


if __name__ == "__main__":
    unittest.main()
