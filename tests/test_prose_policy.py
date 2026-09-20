"""When the app is allowed to spend a Gemini call on prose, and when not.

The decision has three steps in a fixed order -- have we already written
this, is this owner allowed one, and only then what does the model say --
and each step has a different failure mode. These pin the order and the
outcomes; the SQL underneath is exercised through the routes in CI.

Degrading is always safe here, which is the point: `render_template`
produces the same explanation deterministically and the numbers are
identical either way, because the engine fixes every one of them.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from ai.rationale import Rationale
from core import prose
from core.brewing import Recipe
from core.quota import AiCall, Allowance

_DB = object()  # never touched: every DB helper is patched out.


def _recipe() -> Recipe:
    return Recipe(
        method="espresso",
        dose_g=18.0,
        grind_clicks=22.5,
        yield_g=38.0,
        brew_temp_c=93.5,
        target_time_s=28.0,
    )


def _written() -> Rationale:
    return Rationale(
        headline="Two clicks finer.",
        why="Your last shot ran fast.",
        what_to_watch="If it chokes, come back one click.",
    )


def _allowance(limit: int | None, used: int = 0) -> Allowance:
    return Allowance(kind=AiCall.RATIONALE, used=used, limit=limit)


class TestProsePolicy(unittest.TestCase):
    def test_a_cache_hit_never_reaches_the_model(self) -> None:
        cached = (_written(), "gemini-3.8-flash")
        with (
            patch.object(prose, "_lookup", return_value=cached) as lookup,
            patch.object(prose, "write_rationale") as write,
            patch.object(prose, "consume") as consume,
        ):
            rationale, model = prose.rationale_for(_DB, "owner", _recipe(), "label")

        lookup.assert_called_once()
        write.assert_not_called()
        consume.assert_not_called()
        self.assertEqual(rationale, cached[0])
        self.assertEqual(model, "gemini-3.8-flash")

    def test_exhausted_quota_degrades_to_the_template_rather_than_failing(self) -> None:
        """The recipe is the product; the prose is the garnish. Over quota
        the user still gets a recommendation."""
        with (
            patch.object(prose, "_lookup", return_value=None),
            patch.object(prose, "allowance", return_value=_allowance(0)),
            patch.object(prose, "write_rationale") as write,
            patch.object(prose, "consume") as consume,
            patch.object(prose, "_store") as store,
        ):
            rationale, model = prose.rationale_for(_DB, "owner", _recipe(), "label")

        write.assert_not_called()
        consume.assert_not_called()
        store.assert_not_called()
        self.assertIsNone(model)
        # Still a real explanation, and it still carries the engine's numbers.
        self.assertIn("18", rationale.headline)
        self.assertIn("22.5", rationale.headline)

    def test_a_successful_call_is_charged_and_cached(self) -> None:
        with (
            patch.object(prose, "_lookup", return_value=None),
            patch.object(prose, "allowance", return_value=_allowance(None)),
            patch.object(
                prose, "write_rationale", return_value=(_written(), "gemini-3.8-flash")
            ),
            patch.object(prose, "consume") as consume,
            patch.object(prose, "_store") as store,
        ):
            rationale, model = prose.rationale_for(_DB, "owner", _recipe(), "label")

        consume.assert_called_once_with(_DB, "owner", AiCall.RATIONALE)
        store.assert_called_once()
        self.assertEqual(model, "gemini-3.8-flash")
        self.assertEqual(rationale.headline, "Two clicks finer.")

    def test_a_model_that_fell_back_is_neither_charged_nor_cached(self) -> None:
        """write_rationale returns the template with a None model name when
        the model was unreachable or invented a number. Charging for that
        would bill the user for nothing, and caching it would pin the
        template in place of prose they are entitled to."""
        template = _written()
        with (
            patch.object(prose, "_lookup", return_value=None),
            patch.object(prose, "allowance", return_value=_allowance(None)),
            patch.object(prose, "write_rationale", return_value=(template, None)),
            patch.object(prose, "consume") as consume,
            patch.object(prose, "_store") as store,
        ):
            rationale, model = prose.rationale_for(_DB, "owner", _recipe(), "label")

        consume.assert_not_called()
        store.assert_not_called()
        self.assertIsNone(model)
        self.assertEqual(rationale, template)

    def test_the_cache_key_follows_the_prompt_not_just_the_numbers(self) -> None:
        """A different history context must not serve another user's prose,
        and a reworded prompt must invalidate everything written under the
        old wording."""
        recipe = _recipe()
        first = prose.prompt_fingerprint(recipe, "label", "Tier B, 6 shots")
        same = prose.prompt_fingerprint(recipe, "label", "Tier B, 6 shots")
        other_context = prose.prompt_fingerprint(recipe, "label", "Tier A, 1 shot")
        other_label = prose.prompt_fingerprint(recipe, "different", "Tier B, 6 shots")

        self.assertEqual(first, same)
        self.assertNotEqual(first, other_context)
        self.assertNotEqual(first, other_label)
        self.assertEqual(len(first), 64)


if __name__ == "__main__":
    unittest.main()
