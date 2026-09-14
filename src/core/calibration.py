"""Fit the grind law to the user's own shots.

Pure functions over ShotRecord lists -- no database, no network, so this stays
in the DB-free test path.

Two design choices carry most of the weight here:

* **Theil-Sen, not least squares.** With four to eight shots a single
  mis-logged one (forgot to tare, stopped the timer late) drags an OLS fit
  badly. Theil-Sen takes the median of pairwise slopes and tolerates roughly
  29% bad points, needs no distributional assumptions, and is ten lines of
  stdlib.

* **The slope is a property of the grinder, the intercept of the bean.**
  beta (how much a click moves the time) is fitted across every bean on a
  setup, where data accumulates fastest; delta_bean is a single scalar offset
  per coffee. So one shot on a new bag is immediately useful while beta keeps
  improving globally -- which is the only way this works at the handful of
  shots per bean a real person logs.

Shrinkage starts at 100% prior, which is the correct state for a user who has
logged nothing yet. See docs/science.md#shrinkage.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field

from .brewing import (
    GrinderCaps,
    Method,
    ShotRecord,
    normalised_time,
    prep_comparable,
    value_of,
)


@dataclass(frozen=True)
class Calibration:
    """A fitted (or wholly prior) grind law for one setup."""

    beta: float | None
    beta_source: str  # 'prior' | 'shrunk' | 'none'
    alpha: float | None = None
    delta_bean: float = 0.0
    n_eff: int = 0
    click_span: float = 0.0
    confidence: float = 0.0
    # Every bean on this setup, not just the one asked about: a coffee with no
    # shots of its own is started from the offsets of the ones that resemble it.
    bean_offsets: dict[int, float] = field(default_factory=dict)

    @property
    def is_fitted(self) -> bool:
        return self.beta_source == "shrunk"


def theil_sen_slope(points: Sequence[tuple[float, float]]) -> float | None:
    """Median of pairwise slopes. Robust to a minority of bad measurements."""
    slopes = [
        (y2 - y1) / (x2 - x1)
        for i, (x1, y1) in enumerate(points)
        for (x2, y2) in points[i + 1 :]
        if x2 != x1
    ]
    if not slopes:
        return None
    return statistics.median(slopes)


def theil_sen_comparable(shots: Sequence[ShotRecord]) -> float | None:
    """Theil-Sen over shot pairs that were actually prepared the same way.

    Because the estimator is built from pairwise slopes, excluding an
    incomparable pair is exactly one term dropped -- no reweighting, no model
    change. A pair whose pre-infusion differs measures preparation as much as
    grind, and including it would put that difference into the slope.

    Pairs must also stay within one coffee. delta_bean is precisely the
    statement that two bags sit at different intercepts, so a cross-bean pair's
    rise is the grind difference *plus* that gap -- and where one coffee runs
    faster than the other, that gap can outweigh the grind term and invert the
    sign, which makes fit_setup discard the whole fit. Beta is still fitted
    across every bag: each coffee contributes its own pairs to the same median.
    """
    slopes: list[float] = []
    usable = [
        (s, normalised_time(s))
        for s in shots
        if s.grind_clicks is not None and normalised_time(s) not in (None, 0)
    ]
    for i, (a, tr_a) in enumerate(usable):
        for b, tr_b in usable[i + 1 :]:
            if a.grind_clicks is None or b.grind_clicks is None:
                continue
            if a.grind_clicks == b.grind_clicks:
                continue
            if a.bean_id != b.bean_id:
                continue
            if not prep_comparable(a, b):
                continue
            if tr_a is None or tr_b is None or tr_a <= 0 or tr_b <= 0:
                continue
            slopes.append(
                (math.log(tr_b) - math.log(tr_a)) / (b.grind_clicks - a.grind_clicks)
            )
    if not slopes:
        return None
    return statistics.median(slopes)


def _usable(shots: Sequence[ShotRecord]) -> list[tuple[float, float]]:
    """(clicks, ln T_r) for shots that carry both."""
    out: list[tuple[float, float]] = []
    for shot in shots:
        tr = normalised_time(shot)
        if shot.grind_clicks is None or tr is None or tr <= 0:
            continue
        out.append((shot.grind_clicks, math.log(tr)))
    return out


def bean_offsets(
    shots: Sequence[ShotRecord], alpha: float | None, beta: float | None
) -> dict[int, float]:
    """The per-bean intercept offset delta_bean, for every bean in `shots`.

    This is the term that makes one coffee sit finer or coarser than another
    on the same grinder at the same target -- see docs/science.md#beta-law. A
    positive offset means the coffee runs slower than the setup's average at a
    given setting, so it wants a coarser dial.

    Shrunk toward zero on the same argument as beta: one shot on a new bag
    should nudge the offset, not define it.
    """
    if alpha is None or not beta:
        return {}

    residuals: dict[int, list[float]] = {}
    for shot in shots:
        tr = normalised_time(shot)
        if shot.bean_id is None or shot.grind_clicks is None or tr is None or tr <= 0:
            continue
        residuals.setdefault(shot.bean_id, []).append(
            math.log(tr) - (alpha + beta * shot.grind_clicks)
        )

    kappa_bean = value_of("kappa_bean")
    return {
        bean_id: (len(rs) / (len(rs) + kappa_bean)) * statistics.median(rs)
        for bean_id, rs in residuals.items()
    }


def fit_setup(
    shots: Sequence[ShotRecord],
    method: Method,
    caps: GrinderCaps,
    beta_prior_value: float | None,
    bean_id: int | None = None,
) -> Calibration:
    """Fit the grind law for one setup, shrunk toward the physical prior."""
    if beta_prior_value is None:
        # Moka: brew time is stove heat, not permeability. There is no grind
        # law to fit and pretending otherwise would invent a lever.
        return Calibration(beta=None, beta_source="none", confidence=0.0)

    points = _usable(shots)
    distinct = sorted({clicks for clicks, _ in points})
    # Shots at one setting carry no slope information however many there are.
    n_eff = len(distinct)
    span = (distinct[-1] - distinct[0]) if len(distinct) >= 2 else 0.0

    kappa = value_of("kappa_espresso" if method == "espresso" else "kappa_pourover")

    fitted: float | None = None
    min_span = 3.0 * (caps.step_clicks or 1.0)
    if n_eff >= 3 and span >= min_span:
        # Prefer the prep-aware fit; fall back to the plain one when nothing
        # records pre-infusion, where every pair counts as comparable anyway.
        fitted = theil_sen_comparable(shots) or theil_sen_slope(points)
        # A fit whose sign disagrees with the physics is not a better estimate
        # of the slope -- it is the channeling signature. Discard it and let
        # the guardrail in brewing.finest_useful_clicks deal with it.
        if fitted is not None and fitted * beta_prior_value <= 0:
            fitted = None

    if fitted is None:
        beta, source, weight = beta_prior_value, "prior", 0.0
    else:
        weight = n_eff / (n_eff + kappa)
        beta = weight * fitted + (1.0 - weight) * beta_prior_value
        source = "shrunk"

    alpha = None
    if points and beta:
        alpha = statistics.median(y - beta * x for x, y in points)

    offsets = bean_offsets(shots, alpha, beta)
    delta = offsets.get(bean_id, 0.0) if bean_id is not None else 0.0

    cap = 1.0
    if method == "pourover":
        cap = value_of("confidence_cap_pourover")
    elif method == "moka":
        cap = value_of("confidence_cap_moka")
    confidence = weight * min(1.0, n_eff / 8.0) * cap

    return Calibration(
        beta=beta,
        beta_source=source,
        alpha=alpha,
        delta_bean=delta,
        n_eff=n_eff,
        click_span=span,
        confidence=round(confidence, 2),
        bean_offsets=offsets,
    )


def confidence_label(calibration: Calibration) -> str:
    """Plain-language confidence, shown next to the numbers.

    Saying "based on general guidance, not your history" when that is the
    truth matters more than sounding certain.
    """
    c = calibration.confidence
    if c <= 0.0:
        return "First shot - this is a starting bracket to measure from"
    if c < 0.3:
        return "Low - based on general guidance rather than your own shots"
    if c < 0.6:
        return f"Medium - learning from {calibration.n_eff} settings on this setup"
    return (
        f"Good - calibrated to your grinder across {calibration.n_eff} "
        f"different settings"
    )
