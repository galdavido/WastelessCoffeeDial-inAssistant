"""Orchestrates a recommendation: retrieve, calibrate, correct, guard, explain.

This is the only place the pieces meet. The order matters and is the whole
design: every number is settled by arithmetic before the language model is
given anything to say about it.

    retrieval  -> which past shots count
    calibration -> how this grinder behaves (prior until data says otherwise)
    correction  -> what to change, one lever at a time
    guardrails  -> clamp to hardware and to the anti-channeling floor
    rationale   -> prose, checked against the numbers above
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from ai.rationale import Rationale, render_template, write_rationale
from database.models import Bean, BrewSetup, Equipment, Recommendation

from .brewing import (
    GrinderCaps,
    MachineCaps,
    Method,
    Recipe,
    apply_guardrails,
    beta_prior,
    correct,
    target_for,
)
from .calibration import Calibration, confidence_label, fit_setup
from .retrieval import (
    CALIBRATION_PROTOCOL,
    BeanFeatures,
    classify_tier,
    fetch_calibration_shots,
    fetch_exemplars,
    get_active_setup_method,
)

ENGINE_VERSION = "1.0.0"


@dataclass(frozen=True)
class EngineResult:
    recipe: Recipe
    rationale: Rationale
    calibration: Calibration
    tier: str
    llm_model: str | None
    protocol: str | None = None


def _grinder_caps(grinder: Equipment | None) -> GrinderCaps:
    if grinder is None:
        return GrinderCaps()
    direction = grinder.finer_direction or "lower_is_finer"
    return GrinderCaps(
        min_clicks=_as_float(grinder.grind_min_clicks),
        max_clicks=_as_float(grinder.grind_max_clicks),
        step_clicks=_as_float(grinder.grind_step_clicks) or 1.0,
        um_per_click=_as_float(grinder.grind_um_per_click),
        finer_direction="higher_is_finer"
        if direction == "higher_is_finer"
        else "lower_is_finer",
    )


def _machine_caps(machine: Equipment | None) -> MachineCaps:
    if machine is None:
        return MachineCaps()
    return MachineCaps(
        basket_size_g=_as_float(machine.basket_size_g),
        temp_min_c=_as_float(machine.temp_min_c),
        temp_max_c=_as_float(machine.temp_max_c),
        temp_controllable=bool(machine.temp_controllable),
    )


def _as_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _days_since_roast(roast_date: date | None, today: date | None = None) -> int | None:
    if roast_date is None:
        return None
    return ((today or date.today()) - roast_date).days


def recommend(
    db: Session,
    setup: BrewSetup | None,
    bean: Bean | None,
    dose_g: float,
    style: str | None = None,
) -> EngineResult:
    """Produce a recommendation for the active setup and this coffee."""
    method: Method = get_active_setup_method(setup)
    grinder = setup.grinder if setup else None
    machine = setup.machine if setup else None
    caps = _grinder_caps(grinder)
    machine_caps = _machine_caps(machine)
    target = target_for(method, style)

    setup_id = setup.id if setup else None
    history = fetch_calibration_shots(db, setup_id, method)
    tier = classify_tier(history, bean.id if bean else None, caps.has_range)

    prior = beta_prior(method, caps)
    calibration = fit_setup(
        history, method, caps, prior, bean_id=bean.id if bean else None
    )
    label = confidence_label(calibration)

    days = _days_since_roast(bean.roast_date if bean else None)
    roast_ord = bean.roast_level_ord if bean else None

    exemplars = fetch_exemplars(
        db,
        BeanFeatures(
            roast_level_ord=roast_ord,
            process=bean.process if bean else None,
            origin=bean.origin if bean else None,
            days_since_roast=days,
        ),
        setup_id,
        method,
    )

    protocol: str | None = None
    if history:
        # Correct from the most recent measured shot.
        recipe = correct(
            history[0],
            target,
            calibration.beta,
            caps,
            machine_caps,
            days_since_roast=days,
            roast_level_ord=roast_ord,
        )
        basis = "calibrated" if calibration.is_fitted else "history"
    else:
        # Cold start. Everything but the grind comes from the target band;
        # the grind number comes from hardware midpoint, or not at all.
        grind = None
        if (
            caps.has_range
            and caps.min_clicks is not None
            and caps.max_clicks is not None
        ):
            grind = round((caps.min_clicks + caps.max_clicks) / 2.0)
        else:
            # Tier E: no measured shots and no known range. Any click number
            # here would be invented, so ask for one measurement instead.
            protocol = CALIBRATION_PROTOCOL.format(
                dose=dose_g, yield_=round(dose_g * target.ratio_aim, 1)
            )
        recipe = Recipe(
            method=method,
            dose_g=dose_g,
            grind_clicks=grind,
            yield_g=round(dose_g * target.ratio_aim, 1)
            if method == "espresso"
            else None,
            water_g=round(dose_g * target.ratio_aim, 1)
            if method != "espresso"
            else None,
            brew_temp_c=None,
            target_time_s=target.time_hi,
            notes=(protocol,) if protocol else (),
        )
        basis = "prior"

    recipe = Recipe(
        **{
            **recipe.__dict__,
            "basis": basis,
            "confidence": calibration.confidence,
        }
    )
    recipe = apply_guardrails(recipe, caps, machine_caps, history, target)

    context_lines = [f"Tier {tier} ({len(history)} measured shots on this setup)."]
    context_lines.extend(recipe.notes)
    if exemplars:
        context_lines.append(
            f"{len(exemplars)} similar well-rated shots informed this."
        )
    rationale, llm_model = write_rationale(recipe, label, "\n".join(context_lines))

    return EngineResult(
        recipe=recipe,
        rationale=rationale,
        calibration=calibration,
        tier=tier,
        llm_model=llm_model,
        protocol=protocol,
    )


def persist_recommendation(
    db: Session,
    result: EngineResult,
    setup: BrewSetup | None,
    bean: Bean | None,
) -> int | None:
    """Store the engine's output so proposed-vs-actual can be back-tested."""
    recipe = result.recipe
    row = Recommendation(
        setup_id=setup.id if setup else None,
        bean_id=bean.id if bean else None,
        engine_version=ENGINE_VERSION,
        method=recipe.method,
        grind_clicks=recipe.grind_clicks,
        dose_g=recipe.dose_g,
        yield_g=recipe.yield_g,
        water_g=recipe.water_g,
        brew_temp_c=recipe.brew_temp_c,
        target_time_s=recipe.target_time_s,
        basis=recipe.basis,
        confidence=recipe.confidence,
        inputs_json={
            "tier": result.tier,
            "n_eff": result.calibration.n_eff,
            "beta": result.calibration.beta,
            "beta_source": result.calibration.beta_source,
            "guardrails_hit": list(recipe.guardrails_hit),
        },
        rationale_text=result.rationale.why,
        llm_model=result.llm_model,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row.id


def serialize_result(result: EngineResult) -> dict[str, Any]:
    """The API shape: numbers and prose kept in separate fields."""
    recipe = result.recipe
    return {
        "recipe": {
            "method": recipe.method,
            "grind_clicks": recipe.grind_clicks,
            "dose_g": recipe.dose_g,
            "yield_g": recipe.yield_g,
            "water_g": recipe.water_g,
            "brew_temp_c": recipe.brew_temp_c,
            "target_time_s": recipe.target_time_s,
            "basis": recipe.basis,
            "confidence": recipe.confidence,
            "guardrails_hit": list(recipe.guardrails_hit),
        },
        "rationale": {
            "headline": result.rationale.headline,
            "why": result.rationale.why,
            "what_to_watch": result.rationale.what_to_watch,
        },
        "confidence_label": confidence_label(result.calibration),
        "tier": result.tier,
        "protocol": result.protocol,
    }


def render_legacy_text(result: EngineResult) -> str:
    """The old free-text field, kept one release for stale PWA clients.

    Built from the structured result rather than parsed back out of it, so the
    number in the prose is the engine's number.
    """
    rationale = result.rationale or render_template(result.recipe, "")
    lines = [rationale.headline, "", rationale.why, "", rationale.what_to_watch]
    if result.recipe.grind_clicks is not None:
        lines.append("")
        lines.append(f"Suggested Grind Setting: {result.recipe.grind_clicks:g} clicks")
    return "\n".join(lines)
