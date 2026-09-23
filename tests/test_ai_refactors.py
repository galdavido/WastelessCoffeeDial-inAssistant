from __future__ import annotations

import os
import threading
import time
import unittest

from ai.model_selection import (
    DEFAULT_ATTEMPT_TIMEOUT_S,
    GEMINI_MODEL_CANDIDATES,
    VISION_BUDGET_S,
    resolve_budget_s,
    should_try_next_model,
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

    def test_an_unreadable_image_raises_rather_than_setting_shared_state(self) -> None:
        """The failure travels with the call, so concurrent scans cannot swap it."""
        import ai.vision as vision

        with self.assertRaises(vision.VisionError) as ctx:
            vision.analyze_coffee_bag(b"not an image")
        self.assertIn("Failed to read image", str(ctx.exception))
        self.assertFalse(hasattr(vision, "get_last_vision_error"))


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

    def test_the_shared_config_only_sends_thinking_where_accepted(self) -> None:
        from google.genai import types

        from ai.model_selection import json_config
        from ai.rationale import Rationale

        new = json_config("gemini-3.8-flash", Rationale, temperature=0.2)
        assert new.thinking_config is not None
        self.assertEqual(new.thinking_config.thinking_level, types.ThinkingLevel.LOW)
        self.assertEqual(new.response_mime_type, "application/json")

        old = json_config("gemini-2.5-flash", Rationale, temperature=0.2)
        self.assertIsNone(old.thinking_config)


class TestChainIsBounded(unittest.TestCase):
    """The recommendation wait must not be governed by the API's mood.

    Regression for a live fault: gemini-3.8-flash and gemini-3.7-flash sat at
    the head of the chain returning 503 "high demand", and one call hung 56.9s
    before the error arrived. POST /api/recommendation was measured at 29.7s,
    41.1s and 55.5s, and the frontend surfaced that as a load error.
    """

    def test_a_hanging_model_does_not_outlast_the_budget(self) -> None:
        def hangs(model_name: str) -> str:
            time.sleep(30)
            return "never observed"

        started = time.monotonic()
        result, error = try_model_candidates(
            ("slow-model",),
            call_model=hangs,
            evaluate_result=lambda r: (True, None),
            budget_s=0.5,
        )
        elapsed = time.monotonic() - started

        self.assertIsNone(result)
        self.assertIsNotNone(error)
        # Generously above the budget and far below the call: the point is
        # that the caller is released, not that the thread was killed.
        self.assertLess(elapsed, 5.0)

    def test_the_budget_covers_the_chain_not_each_attempt(self) -> None:
        """Three slow models must not cost three budgets."""

        def slow(model_name: str) -> str:
            time.sleep(10)
            return "never observed"

        started = time.monotonic()
        try_model_candidates(
            ("a", "b", "c"),
            call_model=slow,
            evaluate_result=lambda r: (True, None),
            budget_s=0.5,
        )
        self.assertLess(time.monotonic() - started, 5.0)

    def test_a_working_model_still_returns_its_answer(self) -> None:
        result, error = try_model_candidates(
            ("quick",),
            call_model=lambda name: f"answer from {name}",
            evaluate_result=lambda r: (True, None),
            budget_s=5.0,
        )
        self.assertEqual(result, "answer from quick")
        self.assertIsNone(error)


class TestDeadModelsAreSkippedNotFatal(unittest.TestCase):
    """A name that no longer resolves costs that name its turn, nothing more.

    gemini-2.5-flash-lite began returning 404 "no longer available" while
    still appearing in models.list. The old chain treated that as fatal and
    stopped, so gemini-flash-lite-latest -- which answers in 0.6s -- was never
    reached and the request fell back to the template anyway.
    """

    def test_a_retired_model_falls_through_to_the_next(self) -> None:
        seen: list[str] = []

        def call(model_name: str) -> str:
            seen.append(model_name)
            if model_name == "dead":
                raise RuntimeError(
                    "404 NOT_FOUND. This model models/dead is no longer available."
                )
            return "ok"

        result, _ = try_model_candidates(
            ("dead", "alive"),
            call_model=call,
            evaluate_result=lambda r: (True, None),
            budget_s=5.0,
        )
        self.assertEqual(result, "ok")
        self.assertEqual(seen, ["dead", "alive"])

    def test_an_overloaded_model_falls_through_too(self) -> None:
        self.assertTrue(
            should_try_next_model(
                RuntimeError(
                    "503 UNAVAILABLE. This model is currently experiencing high demand."
                )
            )
        )

    def test_a_bad_api_key_stops_the_chain(self) -> None:
        """Every candidate would fail the same way, so trying them is waste."""
        seen: list[str] = []

        def call(model_name: str) -> str:
            seen.append(model_name)
            raise RuntimeError("401 UNAUTHENTICATED. API key not valid.")

        try_model_candidates(
            ("first", "second", "third"),
            call_model=call,
            evaluate_result=lambda r: (True, None),
            budget_s=5.0,
        )
        self.assertEqual(seen, ["first"])


class TestBudgetOverride(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = os.environ.pop("WCDA_LLM_BUDGET_S", None)

    def tearDown(self) -> None:
        os.environ.pop("WCDA_LLM_BUDGET_S", None)
        if self._saved is not None:
            os.environ["WCDA_LLM_BUDGET_S"] = self._saved

    def test_the_default_keeps_the_request_under_five_seconds(self) -> None:
        self.assertLess(resolve_budget_s(), 5.0)

    def test_the_env_override_wins(self) -> None:
        os.environ["WCDA_LLM_BUDGET_S"] = "2.5"
        self.assertEqual(resolve_budget_s(), 2.5)

    def test_nonsense_falls_back_to_the_default(self) -> None:
        os.environ["WCDA_LLM_BUDGET_S"] = "soon"
        self.assertLess(resolve_budget_s(), 5.0)

    def test_each_call_site_reads_its_own_variable(self) -> None:
        """The vision budget must not be dragged down by the prose budget."""
        os.environ["WCDA_LLM_BUDGET_S"] = "2.5"
        self.assertEqual(resolve_budget_s(20.0, "WCDA_VISION_BUDGET_S"), 20.0)


class TestCandidateOrdering(unittest.TestCase):
    """The chain is ordered by measured latency, not by model tier."""

    def test_a_slow_model_does_not_lead(self) -> None:
        """gemini-2.5-flash took 6.7-13.7s on the real rationale prompt.

        Leading with it would spend the whole budget before the first answer,
        which is how the 30-55s waits happened in the first place.
        """
        self.assertEqual(GEMINI_MODEL_CANDIDATES[0], "gemini-flash-lite-latest")

    def test_no_known_dead_name_is_shipped(self) -> None:
        """Each of these took a live call down. Re-add only after calling
        them again, not after seeing them in models.list -- 2.5-flash-lite was
        listed and dead at the same time."""
        dead = {
            "gemini-2.0-flash",
            "gemini-2.0-flash-lite",
            "gemini-2.5-flash-lite",
            "gemini-3.8-flash",
            "gemini-3.7-flash",
        }
        self.assertEqual(set(GEMINI_MODEL_CANDIDATES) & dead, set())

    def test_there_is_something_to_fall_back_to(self) -> None:
        self.assertGreater(len(GEMINI_MODEL_CANDIDATES), 1)


class TestVisionBudgetIsNotTheRationaleBudget(unittest.TestCase):
    """Bag OCR must not inherit the recommendation's hurry.

    A single successful bag reading measured 12.6-19.3s, and failing means the
    user retypes the bag by hand rather than losing a sentence of prose.
    """

    def test_vision_gets_room_for_a_retry_after_a_bad_candidate(self) -> None:
        self.assertGreater(VISION_BUDGET_S, 2 * 19.3)

    def test_vision_is_far_slower_than_the_rationale_budget(self) -> None:
        self.assertGreater(VISION_BUDGET_S, resolve_budget_s())


class TestOneSickModelDoesNotCostTheChain(unittest.TestCase):
    """A hanging lead model must not spend the budget the others need.

    gemini-flash-lite-latest answers in 1.2-1.9s when healthy but
    intermittently hangs to the server's own ~14.5s deadline. With a single
    worker and a break-on-timeout chain, that turned every such hang into a
    template fallback even though the next candidate was fine.
    """

    def test_the_chain_moves_on_after_an_attempt_hangs(self) -> None:
        def call(model_name: str) -> str:
            if model_name == "hangs":
                time.sleep(30)
                return "never observed"
            return "answer"

        started = time.monotonic()
        result, _ = try_model_candidates(
            ("hangs", "healthy"),
            call_model=call,
            evaluate_result=lambda r: (True, None),
            budget_s=4.0,
            attempt_timeout_s=0.5,
        )
        elapsed = time.monotonic() - started

        self.assertEqual(result, "answer")
        # The hang cost one attempt cap, not the whole budget.
        self.assertLess(elapsed, 3.0)

    def test_a_second_attempt_is_not_queued_behind_the_abandoned_one(self) -> None:
        """The abandoned attempt keeps its worker, so the next needs its own."""
        running: list[str] = []

        def call(model_name: str) -> str:
            running.append(model_name)
            if model_name == "hangs":
                time.sleep(5)
            return model_name

        try_model_candidates(
            ("hangs", "healthy"),
            call_model=call,
            evaluate_result=lambda r: (True, None),
            budget_s=4.0,
            attempt_timeout_s=0.4,
        )
        self.assertIn("healthy", running)

    def test_the_attempt_cap_leaves_room_for_a_retry(self) -> None:
        from ai.model_selection import resolve_budget_s as _budget

        self.assertLess(DEFAULT_ATTEMPT_TIMEOUT_S * 2, _budget() + 0.001)


class TestTheClientOutlivesAnAbandonedAttempt(unittest.TestCase):
    """Closing the shared client under a live request is a use-after-free.

    The caller's `finally: client.close()` fired the moment the chain gave up,
    while the abandoned attempt was still mid-request; the worker then died
    with "[Errno 9] Bad file descriptor".
    """

    def test_close_is_withheld_until_the_abandoned_attempt_finishes(self) -> None:
        closed = threading.Event()
        release = threading.Event()

        def call(model_name: str) -> str:
            release.wait(timeout=10)
            return "late"

        try_model_candidates(
            ("slow",),
            call_model=call,
            evaluate_result=lambda r: (True, None),
            budget_s=0.3,
            attempt_timeout_s=0.3,
            on_all_done=closed.set,
        )

        # The chain has returned, but the attempt is still in flight.
        self.assertFalse(closed.is_set())
        release.set()
        self.assertTrue(closed.wait(timeout=10))

    def test_close_happens_promptly_when_nothing_was_abandoned(self) -> None:
        closed = threading.Event()
        try_model_candidates(
            ("quick",),
            call_model=lambda name: "answer",
            evaluate_result=lambda r: (True, None),
            budget_s=4.0,
            on_all_done=closed.set,
        )
        self.assertTrue(closed.is_set())


if __name__ == "__main__":
    unittest.main()
