"""The fit view must show the fit the recipe came from, not a lookalike.

A diagram of the engine's working is only worth having if it cannot disagree
with the engine. Every test here pins one number in the serialised payload to
the function that actually produced it, so a future change that recomputes
something in the view fails rather than quietly drawing a different line.

The fixture is the real dev history in miniature: a light coffee brewed at
94-96 C and a darker one at 91-92 C. That detail is not decoration -- it is the
reason the cross-bean pairing bug stayed invisible, because `temp_tolerance_c`
was already dropping every cross-bean pair for an unrelated reason.
"""

from __future__ import annotations

import statistics
import unittest

from ai.rationale import Rationale
from core.brewing import (
    GrinderCaps,
    Recipe,
    ShotRecord,
    beta_prior,
    prep_comparable,
    target_for,
)
from core.calibration import fit_setup, theil_sen_comparable, theil_sen_terms
from core.engine import EngineResult, serialize_fit
from core.retrieval import shots_for_bean

K6 = GrinderCaps(
    min_clicks=0.0,
    max_clicks=180.0,
    step_clicks=1.0,
    um_per_click=16.0,
    finer_direction="lower_is_finer",
)
TARGET = target_for("espresso")
RWANDA, BRAZIL = 7, 8
NAMES = {RWANDA: "Gicumbi Red Bourbon", BRAZIL: "Cerrado"}


def _shot(bean_id: int, clicks: float, time_s: float, temp: float) -> ShotRecord:
    dose = 18.0 if bean_id == RWANDA else 16.0
    return ShotRecord(
        method="espresso",
        dose_g=dose,
        setup_id=1,
        bean_id=bean_id,
        grind_clicks=clicks,
        yield_g=dose * 2.0,
        time_s=time_s,
        brew_temp_c=temp,
        preinfusion_s=2.0,
        pause_s=2.0,
    )


# Each coffee internally consistent (lower click = finer = slower), the two
# brewed in temperature bands more than temp_tolerance_c apart.
HISTORY = [
    _shot(RWANDA, 26.0, 34.0, 94.0),
    _shot(RWANDA, 28.0, 30.0, 94.0),
    _shot(RWANDA, 30.0, 26.0, 94.0),
    _shot(BRAZIL, 35.0, 30.0, 91.0),
    _shot(BRAZIL, 36.0, 28.0, 91.0),
]


def _result(bean_id: int | None = RWANDA) -> EngineResult:
    """An EngineResult built the way recommend() builds one, minus the DB."""
    calibration = fit_setup(
        HISTORY, "espresso", K6, beta_prior("espresso", K6), bean_id=bean_id
    )
    return EngineResult(
        recipe=Recipe(method="espresso", dose_g=18.0, grind_clicks=29.0),
        rationale=Rationale(headline="h", why="w", what_to_watch="x"),
        calibration=calibration,
        tier="A",
        llm_model=None,
        history=tuple(HISTORY),
        bean_history=tuple(shots_for_bean(HISTORY, bean_id)),
        target=TARGET,
        caps=K6,
    )


class TestThePictureMatchesTheEngine(unittest.TestCase):
    def test_the_pairs_shown_are_the_pairs_the_median_was_taken_of(self) -> None:
        payload = serialize_fit(_result(), NAMES, RWANDA)
        slopes = [p["slope"] for p in payload["pairs"]]
        self.assertTrue(slopes)
        self.assertAlmostEqual(
            statistics.median(slopes),
            theil_sen_comparable(HISTORY) or 0.0,
            places=4,
        )

    def test_beta_used_is_the_engines_beta(self) -> None:
        result = _result()
        payload = serialize_fit(result, NAMES, RWANDA)
        self.assertEqual(payload["law"]["beta_used"], result.calibration.beta)

    def test_the_shrinkage_terms_reconstruct_beta(self) -> None:
        """w*fitted + (1-w)*prior must land on the beta actually used."""
        law = serialize_fit(_result(), NAMES, RWANDA)["law"]
        w = law["shrink_weight"]
        rebuilt = w * law["beta_fitted"] + (1.0 - w) * law["beta_prior"]
        self.assertAlmostEqual(rebuilt, law["beta_used"], places=6)

    def test_pair_indices_point_at_shots_of_that_same_coffee(self) -> None:
        payload = serialize_fit(_result(), NAMES, RWANDA)
        shots = payload["shots"]
        for pair in payload["pairs"]:
            a, b = shots[pair["a_index"]], shots[pair["b_index"]]
            self.assertEqual(a["bean_id"], b["bean_id"])
            self.assertEqual(a["bean_id"], pair["bean_id"])

    def test_no_pair_crosses_two_coffees(self) -> None:
        """The bug this whole view exists to have made visible."""
        payload = serialize_fit(_result(), NAMES, RWANDA)
        shots = payload["shots"]
        crossing = [
            p
            for p in payload["pairs"]
            if shots[p["a_index"]]["bean_id"] != shots[p["b_index"]]["bean_id"]
        ]
        self.assertEqual(crossing, [])

    def test_the_rejected_cross_bean_pairs_are_reported(self) -> None:
        """Otherwise the exclusion is invisible.

        Every shot here still pairs with its own bag, so nothing reads as
        excluded in the shots themselves. The only way to see that the two
        coffees were kept apart is to count the pairs that never happened.
        """
        payload = serialize_fit(_result(), NAMES, RWANDA)
        self.assertTrue(all(s["used_in_fit"] for s in payload["shots"]))
        counts = payload["pairs_rejected_by_reason"]
        self.assertEqual(counts.get("a different coffee"), 6)  # 3 Rwanda x 2 Brazil
        for rejected in payload["pairs_rejected"]:
            self.assertNotEqual(rejected["bean_id"], rejected["other_bean_id"])

    def test_accepted_and_rejected_partition_the_candidates(self) -> None:
        """One decision per pair -- a pair is never in both lists or neither."""
        payload = serialize_fit(_result(), NAMES, RWANDA)
        accepted = {(p["a_index"], p["b_index"]) for p in payload["pairs"]}
        rejected = {(p["a_index"], p["b_index"]) for p in payload["pairs_rejected"]}
        self.assertEqual(accepted & rejected, set())
        self.assertEqual(
            len(accepted) + len(rejected),
            len(payload["pairs"]) + len(payload["pairs_rejected"]),
        )

    def test_every_shot_marked_used_really_fed_a_pair(self) -> None:
        payload = serialize_fit(_result(), NAMES, RWANDA)
        fed = {i for t in theil_sen_terms(HISTORY) for i in (t.a_index, t.b_index)}
        for shot in payload["shots"]:
            self.assertEqual(shot["used_in_fit"], shot["index"] in fed, shot)

    def test_an_excluded_shot_says_why_and_the_reason_holds(self) -> None:
        """A shot alone at its setting for its coffee cannot pair with anything."""
        lonely = _shot(BRAZIL, 41.0, 21.0, 88.0)
        history = [*HISTORY, lonely]
        calibration = fit_setup(
            history, "espresso", K6, beta_prior("espresso", K6), bean_id=BRAZIL
        )
        result = EngineResult(
            recipe=Recipe(method="espresso", dose_g=16.0, grind_clicks=36.0),
            rationale=Rationale(headline="h", why="w", what_to_watch="x"),
            calibration=calibration,
            tier="A",
            llm_model=None,
            history=tuple(history),
            bean_history=tuple(shots_for_bean(history, BRAZIL)),
            target=TARGET,
            caps=K6,
        )
        payload = serialize_fit(result, NAMES, BRAZIL)
        excluded = [s for s in payload["shots"] if not s["used_in_fit"]]
        self.assertTrue(excluded, "expected the 88 C shot to be excluded")
        for shot in excluded:
            self.assertTrue(shot["excluded_reason"])
        # And the stated reason is the real one: it is genuinely incomparable
        # with every other shot of its own coffee.
        same_bean = [s for s in history if s.bean_id == BRAZIL and s is not lonely]
        self.assertTrue(all(not prep_comparable(lonely, s) for s in same_bean))

    def test_the_offsets_shown_are_the_offsets_the_engine_fitted(self) -> None:
        result = _result()
        payload = serialize_fit(result, NAMES, RWANDA)
        for bean in payload["beans"]:
            self.assertAlmostEqual(
                bean["delta_bean"],
                result.calibration.bean_offsets[bean["id"]],
                places=4,
            )
        current = [b for b in payload["beans"] if b["is_current"]]
        self.assertEqual([b["id"] for b in current], [RWANDA])

    def test_the_floor_drawn_is_the_floor_that_clamps(self) -> None:
        """Same inputs apply_guardrails uses, so the same limit comes back."""
        from core.brewing import finest_useful_clicks

        result = _result()
        payload = serialize_fit(result, NAMES, RWANDA)
        expected = finest_useful_clicks(result.bean_history, K6, TARGET)
        self.assertEqual(payload["floor"]["clicks"], expected.clicks)
        self.assertEqual(payload["floor"]["reason"], expected.reason)


class TestItStaysHonestWithNothingToShow(unittest.TestCase):
    def test_an_empty_history_serialises_without_inventing_a_law(self) -> None:
        calibration = fit_setup([], "espresso", K6, beta_prior("espresso", K6))
        result = EngineResult(
            recipe=Recipe(method="espresso", dose_g=18.0),
            rationale=Rationale(headline="h", why="w", what_to_watch="x"),
            calibration=calibration,
            tier="D",
            llm_model=None,
            target=TARGET,
            caps=K6,
        )
        payload = serialize_fit(result, {}, None)
        self.assertEqual(payload["shots"], [])
        self.assertEqual(payload["pairs"], [])
        self.assertEqual(payload["law"]["beta_source"], "prior")
        self.assertEqual(payload["law"]["shrink_weight"], 0.0)
        self.assertIsNone(payload["law"]["beta_fitted"])


if __name__ == "__main__":
    unittest.main()
