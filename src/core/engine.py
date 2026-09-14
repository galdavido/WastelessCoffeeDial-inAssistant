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

from collections.abc import Sequence
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
    ShotRecord,
    Target,
    apply_guardrails,
    beta_prior,
    clicks_for_target,
    cold_start_clicks,
    correct,
    finest_useful_clicks,
    normalised_time,
    prep_advice,
    prep_incomparable_reason,
    resistance_disagreement,
    snap_to_step,
    target_for,
    temp_band_for_roast,
)
from .calibration import (
    Calibration,
    confidence_label,
    fit_setup,
    theil_sen_terms,
)
from .retrieval import (
    CALIBRATION_PROTOCOL,
    BeanFeatures,
    borrow_bean_offset,
    classify_tier,
    fetch_bean_features,
    fetch_calibration_shots,
    fetch_exemplars,
    get_active_setup_method,
    shots_for_bean,
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
    # The inputs this pass actually used, kept so a view can show the working
    # without re-running retrieval and drifting from the numbers above.
    history: tuple[ShotRecord, ...] = ()
    bean_history: tuple[ShotRecord, ...] = ()
    target: Target | None = None
    caps: GrinderCaps | None = None


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
    owner: str,
    setup: BrewSetup | None,
    bean: Bean | None,
    dose_g: float,
    style: str | None = None,
    explain: bool = True,
) -> EngineResult:
    """Produce a recommendation for the active setup and this coffee.

    Every shot the engine learns from is scoped to ``owner`` so users on the
    same instance never inform each other's numbers or rationale.

    ``explain=False`` swaps the language model for the deterministic template.
    Every number is unaffected -- only the prose around them changes -- which
    is what lets the fit view show this same pass without a model call.
    """
    method: Method = get_active_setup_method(setup)
    grinder = setup.grinder if setup else None
    machine = setup.machine if setup else None
    caps = _grinder_caps(grinder)
    machine_caps = _machine_caps(machine)
    target = target_for(method, style)

    setup_id = setup.id if setup else None
    bean_id = bean.id if bean else None
    history = fetch_calibration_shots(db, owner, setup_id, method)
    # The two roles of history, kept apart. beta is a property of the grinder,
    # so it is fitted across every bean on the setup, where data accumulates
    # fastest. The shot a correction is anchored on is a property of the
    # *coffee*, so it is drawn only from this bag -- anchoring on the last
    # thing pulled on the machine took the previous coffee's grind, dose,
    # temperature and taste and applied them to this one.
    bean_history = shots_for_bean(history, bean_id)
    tier = classify_tier(history, bean_id, caps.has_range)

    prior = beta_prior(method, caps)
    calibration = fit_setup(history, method, caps, prior, bean_id=bean_id)
    label = confidence_label(calibration)

    days = _days_since_roast(bean.roast_date if bean else None)
    roast_ord = bean.roast_level_ord if bean else None

    target_features = BeanFeatures(
        roast_level_ord=roast_ord,
        process=bean.process if bean else None,
        origin=bean.origin if bean else None,
        days_since_roast=days,
    )
    exemplars = fetch_exemplars(db, owner, target_features, setup_id, method)

    protocol: str | None = None
    if bean_history:
        # Correct from the most recent measured shot of this coffee.
        recipe = correct(
            bean_history[0],
            target,
            calibration.beta,
            caps,
            machine_caps,
            days_since_roast=days,
            roast_level_ord=roast_ord,
        )
        basis = "calibrated" if calibration.is_fitted else "history"
    else:
        # No shots on this coffee yet. Where the setup has a fitted law, solve
        # it for the target rather than correcting from a different coffee,
        # seeding the per-bean offset from the coffees this one resembles.
        notes: list[str] = []
        tr_aim = (
            (target.tr_lo + target.tr_hi) / 2.0
            if target.tr_lo is not None and target.tr_hi is not None
            else None
        )
        delta, borrowed = borrow_bean_offset(
            target_features,
            calibration.bean_offsets,
            fetch_bean_features(db, owner, calibration.bean_offsets),
        )
        grind = (
            clicks_for_target(calibration.alpha, calibration.beta, tr_aim, delta)
            if tr_aim is not None
            else None
        )
        if grind is not None:
            grind = snap_to_step(grind, caps)
            basis = "setup_law"
            notes.append(
                "this is your first shot on this coffee, so the setting comes "
                "from how your grinder has behaved"
                + (
                    ", nudged toward the similar coffees you have brewed"
                    if borrowed
                    else " across everything you have brewed on it"
                )
                + " rather than from a correction to another coffee"
            )
        else:
            # Cold start. Everything but the grind comes from the target band;
            # the grind number comes from hardware midpoint, or not at all.
            # Estimate the dial position for the reference particle size rather
            # than taking the middle of the hardware range -- that range spans
            # espresso to French press, so its midpoint is far too coarse.
            basis = "prior"
            grind = cold_start_clicks(caps, method)
            if grind is None:
                # Tier E: nothing measured and no way to locate the dial. Any
                # click number here would be invented, so ask for one
                # measurement.
                protocol = CALIBRATION_PROTOCOL.format(
                    dose=dose_g, yield_=round(dose_g * target.ratio_aim, 1)
                )
                notes.append(protocol)
        recipe = Recipe(
            method=method,
            # The caller's dose, not whatever was in the basket for a
            # different coffee.
            dose_g=dose_g,
            grind_clicks=grind,
            yield_g=round(dose_g * target.ratio_aim, 1)
            if method == "espresso"
            else None,
            water_g=round(dose_g * target.ratio_aim, 1)
            if method != "espresso"
            else None,
            # A first shot still deserves a temperature to aim at, from the
            # roast-level band. Suppressed by the guardrails when the machine
            # cannot hold one.
            brew_temp_c=(
                round(sum(temp_band_for_roast(roast_ord)) / 2.0, 1)
                if machine_caps.temp_controllable
                else None
            ),
            target_time_s=target.time_hi,
            notes=tuple(notes),
        )

    recipe = Recipe(
        **{
            **recipe.__dict__,
            "basis": basis,
            "confidence": calibration.confidence,
        }
    )
    # The channeling floor is bean-scoped for the same reason the anchor is.
    # Its triggers compare normalised times against each other ("a finer
    # setting that ran no slower means the water channeled") and read the
    # finest setting that has *tasted* right -- and delta_bean is precisely
    # the statement that those are not comparable across coffees. A dense
    # natural at 36 would otherwise hold a washed Ethiopian at a floor it has
    # no reason to obey. A coffee with no shots of its own falls back to the
    # setup, which is the conservative direction: more triggers, not fewer.
    recipe = apply_guardrails(
        recipe, caps, machine_caps, bean_history or history, target
    )

    # Pre-infusion: a second resistance reading, and advice once there is
    # enough of it to say anything honest.
    prep_notes: list[str] = []
    if bean_history:
        # The reading is about this coffee's puck, so the shot examined is
        # this coffee's. The peers it is compared against stay setup-wide on
        # purpose: the comparison needs shots at the *same click number*, and
        # what it detects -- distribution, tamp, channeling -- is a property
        # of how the puck was prepared rather than of the bean.
        disagreement = resistance_disagreement(bean_history[0], history)
        if disagreement:
            prep_notes.append(disagreement)
    pi_s, pause_s, prep_note = prep_advice(history)
    prep_notes.append(prep_note)

    recipe = Recipe(
        **{
            **recipe.__dict__,
            "preinfusion_s": pi_s,
            "pause_s": pause_s,
            "notes": recipe.notes + tuple(prep_notes),
        }
    )

    context_lines = [
        f"Tier {tier} ({len(history)} measured shots on this setup, "
        f"{len(bean_history)} of them on this coffee)."
    ]
    context_lines.extend(recipe.notes)
    if exemplars:
        context_lines.append(
            f"{len(exemplars)} similar well-rated shots informed this."
        )
    if explain:
        rationale, llm_model = write_rationale(recipe, label, "\n".join(context_lines))
    else:
        # The fit view wants the arithmetic, not prose, and is opened often
        # enough that paying for a model call each time would be waste.
        rationale, llm_model = render_template(recipe, label), None

    return EngineResult(
        recipe=recipe,
        rationale=rationale,
        calibration=calibration,
        tier=tier,
        llm_model=llm_model,
        protocol=protocol,
        history=tuple(history),
        bean_history=tuple(bean_history),
        target=target,
        caps=caps,
    )


def persist_recommendation(
    db: Session,
    owner: str,
    result: EngineResult,
    setup: BrewSetup | None,
    bean: Bean | None,
) -> int | None:
    """Store the engine's output so proposed-vs-actual can be back-tested."""
    recipe = result.recipe
    row = Recommendation(
        owner=owner,
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
            "preinfusion_s": recipe.preinfusion_s,
            "pause_s": recipe.pause_s,
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


def _exclusion_reason(
    shot: ShotRecord, index: int, history: Sequence[ShotRecord]
) -> str:
    """Why this shot fed no pairwise slope.

    Answered against the same predicates the fit used, so the explanation can
    never contradict the decision. A shot pairs with nothing for one of three
    reasons: it carries no usable measurement, every other shot sits at its
    exact setting, or each candidate partner was ruled out.
    """
    if shot.grind_clicks is None or not normalised_time(shot):
        return "no grind setting or no time recorded"

    reasons: list[str] = []
    for other_index, other in enumerate(history):
        if other_index == index:
            continue
        if other.grind_clicks is None or not normalised_time(other):
            continue
        if other.grind_clicks == shot.grind_clicks:
            continue
        if other.bean_id != shot.bean_id:
            reasons.append("a different coffee")
            continue
        prep = prep_incomparable_reason(shot, other)
        reasons.append(prep if prep else "comparable")

    if not reasons:
        return "no other shot of this coffee at a different setting yet"
    # One distinct reason is worth naming; a mixture is not.
    distinct = set(reasons)
    if len(distinct) == 1:
        return f"every other shot it could pair with is {reasons[0]}"
    return "not comparable with any other shot of this coffee"


def serialize_fit(
    result: EngineResult,
    bean_names: dict[int, str],
    bean_id: int | None,
) -> dict[str, Any]:
    """The working behind the recipe: the shots, the terms, and the law.

    Everything here is read off the pass that produced the recipe rather than
    recomputed, so the picture cannot drift from the numbers the user was
    given. `theil_sen_terms()` is the same list `theil_sen_comparable()` took
    the median of, and the shot indices point into `history` in this order.
    """
    calibration = result.calibration
    history = list(result.history)
    target = result.target
    caps = result.caps or GrinderCaps()

    terms = theil_sen_terms(history)
    used = {index for term in terms for index in (term.a_index, term.b_index)}

    # Same arguments apply_guardrails used, so the floor drawn is the floor
    # that actually clamped the recipe.
    floor = finest_useful_clicks(result.bean_history or result.history, caps, target)

    shots = []
    for index, shot in enumerate(history):
        tr = normalised_time(shot)
        shots.append(
            {
                "index": index,
                "bean_id": shot.bean_id,
                "clicks": shot.grind_clicks,
                "tr": round(tr, 3) if tr else None,
                "time_s": shot.time_s,
                "dose_g": shot.dose_g,
                "yield_g": shot.yield_g,
                "water_g": shot.water_g,
                "brew_temp_c": shot.brew_temp_c,
                "preinfusion_s": shot.preinfusion_s,
                "pause_s": shot.pause_s,
                "taste_axis": shot.taste_axis,
                "rating": shot.rating,
                "created_at": shot.created_at.isoformat() if shot.created_at else None,
                "used_in_fit": index in used,
                "excluded_reason": None
                if index in used
                else _exclusion_reason(shot, index, history),
            }
        )

    return {
        "law": {
            "alpha": calibration.alpha,
            "beta_used": calibration.beta,
            "beta_fitted": calibration.beta_fitted,
            "beta_prior": calibration.beta_prior_value,
            "beta_source": calibration.beta_source,
            # Not rounded: the view reconstructs beta_used from this, and a
            # display-rounded weight breaks that identity by ~1e-6.
            "shrink_weight": calibration.shrink_weight,
            "kappa": calibration.kappa,
            "n_eff": calibration.n_eff,
            "click_span": calibration.click_span,
            "confidence": calibration.confidence,
            "confidence_label": confidence_label(calibration),
            "tier": result.tier,
        },
        "beans": [
            {
                "id": candidate_id,
                "name": bean_names.get(candidate_id, f"Coffee {candidate_id}"),
                "delta_bean": round(offset, 4),
                "shots_used": sum(1 for s in history if s.bean_id == candidate_id),
                "is_current": candidate_id == bean_id,
            }
            for candidate_id, offset in sorted(calibration.bean_offsets.items())
        ],
        "shots": shots,
        "pairs": [
            {
                "slope": round(term.slope, 5),
                "a_index": term.a_index,
                "b_index": term.b_index,
                "bean_id": term.bean_id,
            }
            for term in terms
        ],
        "target": {
            "tr_lo": target.tr_lo if target else None,
            "tr_hi": target.tr_hi if target else None,
            "time_lo": target.time_lo if target else None,
            "time_hi": target.time_hi if target else None,
            "ratio_aim": target.ratio_aim if target else None,
        },
        "floor": {"clicks": floor.clicks, "reason": floor.reason},
        "grinder": {
            "min_clicks": caps.min_clicks,
            "max_clicks": caps.max_clicks,
            "step_clicks": caps.step_clicks,
            "um_per_click": caps.um_per_click,
            "finer_direction": caps.finer_direction,
        },
        "recipe": {
            "grind_clicks": result.recipe.grind_clicks,
            "basis": result.recipe.basis,
            "guardrails_hit": list(result.recipe.guardrails_hit),
        },
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
