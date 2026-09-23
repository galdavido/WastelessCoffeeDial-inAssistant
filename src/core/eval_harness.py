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

from .brewing import (
    GrinderCaps,
    MachineCaps,
    Method,
    ShotRecord,
    Target,
    apply_guardrails,
    beta_prior,
    cold_start_clicks,
    correct,
    dose_log,
    normalised_time,
)
from .calibration import fit_setup

# Below these, a metric reports INSUFFICIENT DATA rather than a number.
MIN_SHOTS_FOR_PREDICTION = 15
MIN_PAIRS_FOR_DIRECTION = 20


@dataclass
class Metric:
    name: str
    value: float | None = None
    n: int = 0
    required: int = 0
    baselines: dict[str, float] = field(default_factory=dict)

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

    @property
    def any_sufficient(self) -> bool:
        return any(metric.sufficient for metric in self.metrics)


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
    if (
        tr_before is not None
        and tr_after is not None
        and target.tr_lo is not None
        and target.tr_hi is not None
    ):
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
    method: Method,
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
        if not _improved(before, after, target):
            continue
        pairs += 1

        prior = beta_prior(method, caps)
        fit = fit_setup([before], method, caps, prior)
        # Asked at the dose the next shot was actually pulled at, as the app
        # would be when the user changes it.
        recipe = correct(
            before,
            target,
            fit.beta,
            caps,
            machine,
            dose_g=after.dose_g,
            gamma=fit.gamma,
        )
        recipe = apply_guardrails(recipe, caps, machine, [before], target)
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


def held_out_time_error(
    shots: Sequence[ShotRecord], method: Method, caps: GrinderCaps
) -> Metric:
    """M3: leave-one-out prediction of ln T_r.

    Needs neither ratings nor taste, so every measured shot counts -- which is
    why this goes green long before M1 has enough pairs.
    """
    measured = _measured(shots)
    prior = beta_prior(method, caps)
    errors: list[float] = []
    prior_errors: list[float] = []

    for i, held in enumerate(measured):
        rest = measured[:i] + measured[i + 1 :]
        if len(rest) < 3:
            continue
        tr = normalised_time(held)
        if tr is None or held.grind_clicks is None:
            continue

        fitted = fit_setup(rest, method, caps, prior, bean_id=held.bean_id)
        if fitted.beta is None or fitted.alpha is None:
            continue
        # The whole law, as the engine uses it: the coffee's own offset
        # included. Leaving delta_bean out scored the law on a question it
        # never answers, and made any term that moves the bean offsets look
        # worse than it is.
        predicted = (
            fitted.alpha
            + fitted.delta_bean
            + fitted.beta * held.grind_clicks
            + fitted.gamma * dose_log(held.dose_g)
        )
        errors.append(abs(predicted - math.log(tr)))

        # Same intercept, unfitted slope: isolates what calibration adds.
        if prior is not None:
            prior_fit = fit_setup(rest[:1], method, caps, prior, bean_id=held.bean_id)
            if prior_fit.alpha is not None and prior_fit.beta is not None:
                prior_pred = (
                    prior_fit.alpha
                    + prior_fit.delta_bean
                    + prior_fit.beta * held.grind_clicks
                    + prior_fit.gamma * dose_log(held.dose_g)
                )
                prior_errors.append(abs(prior_pred - math.log(tr)))

    return Metric(
        "M3 held-out ln(T_r) MAE",
        statistics.fmean(errors) if errors else None,
        len(errors),
        MIN_SHOTS_FOR_PREDICTION,
        {"prior_only": statistics.fmean(prior_errors)} if prior_errors else {},
    )


def guardrail_violations(
    shots: Sequence[ShotRecord],
    target: Target,
    caps: GrinderCaps,
    machine: MachineCaps,
    method: Method,
) -> Metric:
    """M4: must be exactly zero. Any output outside the hardware is a bug."""
    measured = _measured(shots)
    violations = 0
    checked = 0
    prior = beta_prior(method, caps)

    for shot in measured:
        fit = fit_setup(measured, method, caps, prior)
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


def cold_start_abstention(caps_list: Sequence[GrinderCaps], method: Method) -> Metric:
    """M5: with no way to locate the dial, the engine must decline to guess."""
    unlocatable = [c for c in caps_list if c.um_per_click is None]
    if not unlocatable:
        return Metric("M5 cold-start abstention", None, 0, 1)
    abstained = sum(1 for c in unlocatable if cold_start_clicks(c, method) is None)
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
    method: Method = "espresso",
) -> BacktestReport:
    """Run every metric over one setup's measured history."""
    m1, m2 = direction_agreement(shots, target, caps, machine, method)
    return BacktestReport(
        [
            m1,
            m2,
            held_out_time_error(shots, method, caps),
            guardrail_violations(shots, target, caps, machine, method),
            cold_start_abstention(
                [caps, GrinderCaps(min_clicks=0, max_clicks=100)], method
            ),
        ]
    )
