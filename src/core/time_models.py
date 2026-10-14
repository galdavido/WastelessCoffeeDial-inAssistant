"""Models of ln T_r that the eval harness can score side by side.

The engine's grind law is one answer to "how long will this shot run?";
anything else that answers it -- a dumb baseline, a statistical model, a
neural network -- can be held to exactly the same test. A model is anything
with a ``name`` and a ``fit(train)`` that returns a predictor, or None when it
declines to predict from that history at all. A predictor returns ln T_r for
one shot, or None to abstain on that shot.

Nothing here touches the database, and nothing here needs more than the
standard library: the scikit-learn challengers live in ``challengers.py`` so
that the web image never imports them.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from .brewing import (
    GrinderCaps,
    Method,
    ShotRecord,
    beta_prior,
    dose_term,
    normalised_time,
)
from .calibration import Calibration, fit_setup

Predictor = Callable[[ShotRecord], float | None]


class TimeModel(Protocol):
    @property
    def name(self) -> str: ...

    def fit(self, train: Sequence[ShotRecord]) -> Predictor | None: ...


def log_time(shot: ShotRecord) -> float | None:
    """The quantity every model predicts: ln T_r, or None if unmeasured."""
    tr = normalised_time(shot)
    return math.log(tr) if tr is not None and tr > 0 else None


def _law(fit: Calibration, shot: ShotRecord) -> float | None:
    """The engine's grind law evaluated at one shot, bean offset included."""
    if fit.beta is None or fit.alpha is None or shot.grind_clicks is None:
        return None
    return (
        fit.alpha
        + fit.delta_bean
        + fit.beta * shot.grind_clicks
        + dose_term(shot.dose_g, shot.roast_level_ord, fit.gamma)
    )


@dataclass(frozen=True)
class EngineTimeModel:
    """The calibrated grind law, as `fit_setup` fits it for the engine.

    The coffee's own offset is part of the prediction: leaving delta_bean out
    would score the law on a question it never answers.
    """

    method: Method
    caps: GrinderCaps
    name: str = "engine"

    def fit(self, train: Sequence[ShotRecord]) -> Predictor | None:
        prior = beta_prior(self.method, self.caps)
        fits: dict[int | None, Calibration] = {}

        def predict(shot: ShotRecord) -> float | None:
            # bean_offsets are fitted per call, so fit once per coffee asked.
            if shot.bean_id not in fits:
                fits[shot.bean_id] = fit_setup(
                    train, self.method, self.caps, prior, bean_id=shot.bean_id
                )
            return _law(fits[shot.bean_id], shot)

        return predict


@dataclass(frozen=True)
class PriorOnlyTimeModel:
    """The physical prior slope, anchored on the most recent shot only.

    Same intercept machinery, no calibration: isolates what fitting adds.
    Expects ``train`` newest first, the order the database returns it in.
    """

    method: Method
    caps: GrinderCaps
    name: str = "prior_only"

    def fit(self, train: Sequence[ShotRecord]) -> Predictor | None:
        prior = beta_prior(self.method, self.caps)
        if prior is None:
            return None
        return EngineTimeModel(self.method, self.caps).fit(train[:1])


@dataclass(frozen=True)
class BeanMeanTimeModel:
    """Ignore the grinder entirely: the coffee's average ln T_r so far.

    The floor any model has to clear. Falls back to the whole history's mean
    for a coffee with no shots of its own.
    """

    name: str = "bean_mean"

    def fit(self, train: Sequence[ShotRecord]) -> Predictor | None:
        by_bean: dict[int | None, list[float]] = {}
        every: list[float] = []
        for shot in train:
            y = log_time(shot)
            if y is not None:
                by_bean.setdefault(shot.bean_id, []).append(y)
                every.append(y)
        if not every:
            return None
        means = {bean: statistics.fmean(ys) for bean, ys in by_bean.items()}
        overall = statistics.fmean(every)
        return lambda shot: means.get(shot.bean_id, overall)
