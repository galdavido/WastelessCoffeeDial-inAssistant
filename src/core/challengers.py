"""Statistical challengers to the engine's grind law, for back-testing only.

Each one learns ln T_r from the same shots the engine sees, with none of its
physics: no Darcy slope, no prior, no dose exponent -- only the raw inputs.
The point is to measure what that physics buys on real data, not to replace
it. They are scored by ``eval_harness.compare_models`` exactly as the engine
is.

Needs scikit-learn (``pip install -e '.[ml]'``), which the web image does not
carry: import this module only from offline tools, never from a route.

All four are deliberately small. With a few dozen shots a large model only
memorises them, and the walk-forward score says so.
"""

from __future__ import annotations

import math
import warnings
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.exceptions import ConvergenceWarning
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import RBF, ConstantKernel, WhiteKernel
from sklearn.linear_model import RidgeCV
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .brewing import ShotRecord
from .time_models import Predictor, TimeModel, log_time

# Roast is optional on a bean; the middle of the 1..5 scale is the least
# wrong fill for a model that cannot take a missing value.
DEFAULT_ROAST = 3


def _base_row(shot: ShotRecord) -> list[float]:
    """The inputs the engine's law reads, as plain numbers."""
    return [
        shot.grind_clicks if shot.grind_clicks is not None else math.nan,
        math.log(shot.dose_g) if shot.dose_g and shot.dose_g > 0 else math.nan,
        float(shot.roast_level_ord or DEFAULT_ROAST),
        shot.preinfusion_s or 0.0,
    ]


@dataclass(frozen=True)
class Features:
    """Shot -> feature row, with the coffee one-hot encoded.

    The bean columns are fixed at fit time. A coffee the model never saw gets
    all zeros, which is the model's "average coffee" -- the same thing the
    engine does when it has no offset for a bag.
    """

    beans: tuple[int | None, ...]

    @classmethod
    def learn(cls, train: Sequence[ShotRecord]) -> Features:
        return cls(tuple(dict.fromkeys(s.bean_id for s in train)))

    def row(self, shot: ShotRecord) -> list[float]:
        onehot = [1.0 if shot.bean_id == b else 0.0 for b in self.beans]
        return _base_row(shot) + onehot

    def matrix(self, shots: Sequence[ShotRecord]) -> np.ndarray:
        return np.array([self.row(s) for s in shots], dtype=float)


@dataclass(frozen=True)
class SklearnTimeModel:
    """Wrap any scikit-learn regressor factory as a TimeModel."""

    name: str
    factory: Callable[[int], Any]

    def fit(self, train: Sequence[ShotRecord]) -> Predictor | None:
        rows = [(s, t) for s in train if (t := log_time(s)) is not None]
        if not rows:
            return None
        features = Features.learn([s for s, _ in rows])
        x = features.matrix([s for s, _ in rows])
        target = np.array([t for _, t in rows])
        keep = ~np.isnan(x).any(axis=1)
        if keep.sum() < 2:
            return None
        model = self.factory(int(keep.sum()))
        with warnings.catch_warnings():
            # A GP's optimiser and lbfgs both complain on tiny, noisy data.
            # The held-out score is the judge of whether the fit was any good.
            warnings.simplefilter("ignore", ConvergenceWarning)
            model.fit(x[keep], target[keep])

        def predict(shot: ShotRecord) -> float | None:
            row = np.array([features.row(shot)])
            if np.isnan(row).any():
                return None
            return float(model.predict(row)[0])

        return predict


def _ridge(n: int) -> Any:
    # RidgeCV's default is efficient leave-one-out over the alphas, so it
    # picks its own shrinkage even on a dozen shots.
    return make_pipeline(StandardScaler(), RidgeCV(alphas=np.logspace(-3, 3, 13)))


def _gp(n: int) -> Any:
    kernel = ConstantKernel(1.0, (1e-2, 1e2)) * RBF(
        length_scale=1.0, length_scale_bounds=(1e-1, 1e2)
    ) + WhiteKernel(noise_level=0.05, noise_level_bounds=(1e-4, 1.0))
    return make_pipeline(
        StandardScaler(),
        GaussianProcessRegressor(
            kernel=kernel, normalize_y=True, n_restarts_optimizer=2, random_state=0
        ),
    )


def _gbt(n: int) -> Any:
    return GradientBoostingRegressor(
        n_estimators=100,
        max_depth=2,
        learning_rate=0.05,
        min_samples_leaf=max(1, min(3, n // 5)),
        random_state=0,
    )


def _mlp(n: int) -> Any:
    # lbfgs, not adam: it is the solver that behaves on tens of samples.
    return make_pipeline(
        StandardScaler(),
        MLPRegressor(
            hidden_layer_sizes=(16,),
            alpha=1e-1,
            solver="lbfgs",
            max_iter=5000,
            random_state=0,
        ),
    )


def challengers() -> list[TimeModel]:
    """Ridge, a Gaussian process, boosted trees and a one-layer MLP."""
    return [
        SklearnTimeModel("ridge", _ridge),
        SklearnTimeModel("gp", _gp),
        SklearnTimeModel("gbt", _gbt),
        SklearnTimeModel("mlp", _mlp),
    ]
