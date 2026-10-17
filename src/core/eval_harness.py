"""Measure whether the engine's advice is actually any good.

Pure functions over ShotRecord lists, so this runs against simulated
histories in CI and against the real database from the wcda-backtest CLI.

The honest starting position: with no measured shots every metric reports
INSUFFICIENT DATA, and that is the correct output rather than a reassuring
number computed from nothing. Metrics unlock as real shots accumulate.

Metrics
-------
M1  direction agreement -- when the user's next shot went better, did the
    engine point the same way they actually moved? The headline metric, but
    it needs pairs of shots, so it unlocks last.
M2  magnitude error -- how far off, in clicks, against "just repeat the last
    setting".
M3  held-out time prediction -- leave one measured shot out, predict its
    ln T_r from the rest. The strongest signal on sparse data because it
    needs no ratings and no taste at all: every measured shot contributes.
M4  guardrail violations -- must be exactly zero. A regression test, not a
    quality score.
M5  cold-start abstention -- when the engine cannot locate the dial, does it
    correctly decline to name a number? Guards against a future change
    quietly re-introducing invented values.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from .brewing import (
    GrinderCaps,
    MachineCaps,
    ShotRecord,
    Target,
    apply_guardrails,
    beta_prior,
    cold_start_clicks,
    correct,
    for_roast,
    normalised_time,
)
from .calibration import fit_setup
from .time_models import (
    EngineTimeModel,
    PriorOnlyTimeModel,
    TimeModel,
    log_time,
)

# Below these, a metric reports INSUFFICIENT DATA rather than a number.
MIN_SHOTS_FOR_PREDICTION = 15
MIN_PAIRS_FOR_DIRECTION = 20


@dataclass
class Metric:
    name: str
    value: float | None = None
    n: int = 0
    required: int = 0
    baselines: dict[str, float] = field(default_factory=dict[str, float])

    @property
    def sufficient(self) -> bool:
        return self.n >= self.required and self.value is not None

    def render(self) -> str:
        if not self.sufficient:
            return f"{self.name}: INSUFFICIENT DATA (n={self.n}, need {self.required})"
        line = f"{self.name}: {self.value:.3f} (n={self.n})"
        if self.baselines:
            comparisons = ", ".join(
                f"{k}={v:.3f}" for k, v in sorted(self.baselines.items())
            )
            line += f"  [baselines: {comparisons}]"
        return line


@dataclass
class BacktestReport:
    metrics: list[Metric]

    def render(self) -> str:
        return "\n".join(metric.render() for metric in self.metrics)


def _measured(shots: Sequence[ShotRecord]) -> list[ShotRecord]:
    return [
        s
        for s in shots
        if s.grind_clicks is not None and normalised_time(s) is not None
    ]


def _improved(before: ShotRecord, after: ShotRecord, target: Target) -> bool:
    """Did the second shot actually turn out better than the first?"""
    if (
        before.rating is not None
        and after.rating is not None
        and after.rating > before.rating
    ):
        return True
    tr_before, tr_after = normalised_time(before), normalised_time(after)
    if tr_before is not None and tr_after is not None:
        was_out = not (target.tr_lo <= tr_before <= target.tr_hi)
        now_in = target.tr_lo <= tr_after <= target.tr_hi
        if was_out and now_in:
            return True
    return False


def direction_agreement(
    shots: Sequence[ShotRecord],
    target: Target,
    caps: GrinderCaps,
    machine: MachineCaps,
) -> tuple[Metric, Metric]:
    """M1 and M2, over consecutive shots that led to an improvement."""
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    measured = sorted(_measured(shots), key=lambda s: s.created_at or epoch)
    agree = 0
    errors: list[float] = []
    repeat_errors: list[float] = []
    always_finer_agree = 0
    pairs = 0

    for before, after in zip(measured, measured[1:], strict=False):
        if before.grind_clicks is None or after.grind_clicks is None:
            continue
        # Judged by the band the engine would have used for this coffee.
        bean_target = for_roast(target, before.roast_level_ord)
        if not _improved(before, after, bean_target):
            continue
        pairs += 1

        prior = beta_prior(caps)
        fit = fit_setup([before], caps, prior)
        # Asked at the dose the next shot was actually pulled at, as the app
        # would be when the user changes it.
        recipe = correct(
            before,
            bean_target,
            fit.beta,
            caps,
            machine,
            dose_g=after.dose_g,
            gamma=fit.gamma,
        )
        recipe = apply_guardrails(recipe, caps, machine, [before], bean_target)
        if recipe.grind_clicks is None:
            continue

        actual_move = after.grind_clicks - before.grind_clicks
        engine_move = recipe.grind_clicks - before.grind_clicks
        if _same_direction(engine_move, actual_move):
            agree += 1
        # The reflex the old prompt encoded: always go finer.
        if _same_direction(caps.finer_sign, actual_move):
            always_finer_agree += 1

        errors.append(abs(recipe.grind_clicks - after.grind_clicks))
        repeat_errors.append(abs(before.grind_clicks - after.grind_clicks))

    m1 = Metric(
        "M1 direction agreement",
        (agree / pairs) if pairs else None,
        pairs,
        MIN_PAIRS_FOR_DIRECTION,
        {"always_finer": (always_finer_agree / pairs) if pairs else 0.0},
    )
    m2 = Metric(
        "M2 magnitude MAE (clicks)",
        statistics.fmean(errors) if errors else None,
        len(errors),
        MIN_PAIRS_FOR_DIRECTION,
        {"repeat_last": statistics.fmean(repeat_errors) if repeat_errors else 0.0},
    )
    return m1, m2


def _same_direction(a: float, b: float) -> bool:
    if a == 0 and b == 0:
        return True
    return a * b > 0


Scheme = Literal["loo", "walk_forward"]

# A model is never asked to predict from fewer shots than this.
MIN_TRAIN_SHOTS = 3


@dataclass
class HeldOut:
    """One shot held out, its measured ln T_r and what each model said."""

    shot: ShotRecord
    actual: float
    predicted: dict[str, float | None]
    # No shot of this coffee in the training set: the bag's first pull, where
    # a model can only carry what it learned from *other* coffees across.
    new_coffee: bool = False


def held_out_predictions(
    shots: Sequence[ShotRecord],
    models: Sequence[TimeModel],
    scheme: Scheme = "loo",
) -> list[HeldOut]:
    """Ask every model for each measured shot it was not trained on.

    ``loo`` trains on every other shot -- the most data, but it lets a model
    see shots pulled *after* the one it predicts. ``walk_forward`` trains only
    on what came before, which is the question the app actually faces when it
    recommends the next shot. Training sets are passed newest first, as the
    database hands them to the engine.
    """
    measured = _measured(shots)
    if scheme == "walk_forward":
        epoch = datetime(1970, 1, 1, tzinfo=UTC)
        measured = sorted(measured, key=lambda s: s.created_at or epoch)

    out: list[HeldOut] = []
    for i, held in enumerate(measured):
        if scheme == "loo":
            train = measured[:i] + measured[i + 1 :]
        else:
            train = measured[:i][::-1]
        actual = log_time(held)
        if len(train) < MIN_TRAIN_SHOTS or actual is None:
            continue
        predicted: dict[str, float | None] = {}
        for model in models:
            predictor = model.fit(train)
            value = predictor(held) if predictor is not None else None
            predicted[model.name] = (
                value if value is not None and math.isfinite(value) else None
            )
        new_coffee = all(s.bean_id != held.bean_id for s in train)
        out.append(HeldOut(held, actual, predicted, new_coffee))
    return out


def _mae(points: Sequence[HeldOut], name: str) -> float | None:
    errors = [
        abs(value - p.actual)
        for p in points
        if (value := p.predicted.get(name)) is not None
    ]
    return statistics.fmean(errors) if errors else None


def held_out_time_error(shots: Sequence[ShotRecord], caps: GrinderCaps) -> Metric:
    """M3: leave-one-out prediction of ln T_r.

    Needs neither ratings nor taste, so every measured shot counts -- which is
    why this goes green long before M1 has enough pairs.
    """
    engine = EngineTimeModel(caps)
    # Same intercept, unfitted slope: isolates what calibration adds.
    prior = PriorOnlyTimeModel(caps)
    points = [
        p
        for p in held_out_predictions(shots, [engine, prior])
        if p.predicted[engine.name] is not None
    ]
    prior_mae = _mae(points, prior.name)
    return Metric(
        "M3 held-out ln(T_r) MAE",
        _mae(points, engine.name),
        len(points),
        MIN_SHOTS_FOR_PREDICTION,
        {prior.name: prior_mae} if prior_mae is not None else {},
    )


@dataclass
class ModelScore:
    name: str
    mae: float | None
    abstained: int
    # The same error split by whether the coffee had shots to learn from.
    mae_known: float | None = None
    mae_new: float | None = None
    # Paired against the first model on the same shots: mean of
    # (this error - its error) and that mean's standard error. A gap inside
    # about two standard errors is not a finding.
    diff: float | None = None
    diff_se: float | None = None


@dataclass
class Comparison:
    """Every model scored on the same held-out shots under one scheme."""

    scheme: Scheme
    n: int
    required: int
    scores: list[ModelScore]
    n_new: int = 0

    @property
    def sufficient(self) -> bool:
        return self.n >= self.required

    def render(self) -> str:
        title = {
            "loo": "leave-one-out",
            "walk_forward": "walk-forward (past shots only)",
        }[self.scheme]
        if not self.sufficient:
            return (
                f"ln(T_r) MAE, {title}: INSUFFICIENT DATA "
                f"(n={self.n}, need {self.required})"
            )

        def cell(value: float | None) -> str:
            return "      -" if value is None else f"{value:7.3f}"

        lines = [f"ln(T_r) MAE, {title} (n={self.n}):"]
        split = self.n_new > 0
        if split:
            lines.append(
                f"  {'':<12} {'all':>7} {'known':>7} {'new':>7}"
                f"   (new = a coffee's first shot, n={self.n_new})"
            )
        ranked = sorted(self.scores, key=lambda s: math.inf if s.mae is None else s.mae)
        reference = self.scores[0].name if self.scores else ""
        for score in ranked:
            if score.mae is None:
                row = "abstained"
            elif split:
                row = cell(score.mae) + cell(score.mae_known) + cell(score.mae_new)
            else:
                row = cell(score.mae)
            if score.diff is not None and score.diff_se is not None:
                row += f"   vs {reference} {score.diff:+.3f} ± {score.diff_se:.3f}"
            note = f"  (abstained on {score.abstained})" if score.abstained else ""
            lines.append(f"  {score.name:<12}{row}{note}")
        return "\n".join(lines)


def _paired(
    points: Sequence[HeldOut], name: str, reference: str
) -> tuple[float | None, float | None]:
    """Mean paired error difference against ``reference``, and its SE."""
    if name == reference or len(points) < 2:
        return None, None
    diffs: list[float] = []
    for p in points:
        value, ref = p.predicted[name], p.predicted[reference]
        if value is None or ref is None:
            continue
        diffs.append(abs(value - p.actual) - abs(ref - p.actual))
    if len(diffs) < 2:
        return None, None
    return statistics.fmean(diffs), statistics.stdev(diffs) / math.sqrt(len(diffs))


def compare_models(
    shots: Sequence[ShotRecord],
    models: Sequence[TimeModel],
    scheme: Scheme = "loo",
) -> Comparison:
    """Score every model on the shots *all* of them answered.

    A model that abstains on the hard shots would otherwise look better for
    it, so abstentions are counted and reported, and the MAE is taken over
    the common set only.
    """
    points = held_out_predictions(shots, models, scheme)
    common = [p for p in points if all(v is not None for v in p.predicted.values())]
    known = [p for p in common if not p.new_coffee]
    new = [p for p in common if p.new_coffee]
    scores = [
        ModelScore(
            model.name,
            _mae(common, model.name),
            sum(1 for p in points if p.predicted[model.name] is None),
            _mae(known, model.name),
            _mae(new, model.name),
            *_paired(common, model.name, models[0].name),
        )
        for model in models
    ]
    return Comparison(
        scheme, len(common), MIN_SHOTS_FOR_PREDICTION, scores, n_new=len(new)
    )


def guardrail_violations(
    shots: Sequence[ShotRecord],
    target: Target,
    caps: GrinderCaps,
    machine: MachineCaps,
) -> Metric:
    """M4: must be exactly zero. Any output outside the hardware is a bug."""
    measured = _measured(shots)
    violations = 0
    checked = 0
    prior = beta_prior(caps)

    for shot in measured:
        fit = fit_setup(measured, caps, prior)
        recipe = correct(shot, target, fit.beta, caps, machine, gamma=fit.gamma)
        recipe = apply_guardrails(recipe, caps, machine, measured, target)
        checked += 1
        clicks = recipe.grind_clicks
        if clicks is None:
            continue
        if (
            caps.min_clicks is not None
            and clicks < caps.min_clicks
            or caps.max_clicks is not None
            and clicks > caps.max_clicks
        ):
            violations += 1

    return Metric(
        "M4 guardrail violations",
        (violations / checked) if checked else None,
        checked,
        1,
    )


def cold_start_abstention(caps_list: Sequence[GrinderCaps]) -> Metric:
    """M5: with no way to locate the dial, the engine must decline to guess."""
    unlocatable = [c for c in caps_list if c.um_per_click is None]
    if not unlocatable:
        return Metric("M5 cold-start abstention", None, 0, 1)
    abstained = sum(1 for c in unlocatable if cold_start_clicks(c) is None)
    return Metric(
        "M5 cold-start abstention",
        abstained / len(unlocatable),
        len(unlocatable),
        1,
    )


def backtest(
    shots: Sequence[ShotRecord],
    target: Target,
    caps: GrinderCaps,
    machine: MachineCaps,
) -> BacktestReport:
    """Run every metric over one setup's measured history."""
    m1, m2 = direction_agreement(shots, target, caps, machine)
    return BacktestReport(
        [
            m1,
            m2,
            held_out_time_error(shots, caps),
            guardrail_violations(shots, target, caps, machine),
            cold_start_abstention([caps, GrinderCaps(min_clicks=0, max_clicks=100)]),
        ]
    )
