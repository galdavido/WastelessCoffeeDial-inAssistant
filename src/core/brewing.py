"""Deterministic brewing engine: constants, derived metrics and target bands.

Pure domain logic. This module must not import SQLAlchemy, the database, or
the Gemini client -- it has to stay importable with no database and no network
so it is covered by the DB-free test path, and so the numbers it produces can
never come from a language model.

Every numeric constant lives in CONSTANTS with a `kind` and an `anchor` into
docs/science.md; tests/test_science_doc.py enforces that the anchors resolve.
See docs/science.md for the derivations and the honest limits.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

Method = Literal["espresso", "pourover", "moka"]
TasteAxis = Literal["very_sour", "sour", "balanced", "bitter", "very_bitter"]
ConstantKind = Literal["PHYSICS", "LITERATURE", "CALIBRATED", "HEURISTIC"]

# Taste axis as a signed scale, so "how far from balanced, and which way" is
# arithmetic rather than a chain of if-statements.
TASTE_SCALE: dict[str, int] = {
    "very_sour": -2,
    "sour": -1,
    "balanced": 0,
    "bitter": 1,
    "very_bitter": 2,
}


@dataclass(frozen=True)
class Constant:
    """A number with provenance. See docs/science.md for what each kind means."""

    value: float
    unit: str
    kind: ConstantKind
    anchor: str
    note: str = ""


CONSTANTS: dict[str, Constant] = {
    # --- physics ---------------------------------------------------------
    "kozeny_carman_exponent": Constant(
        2.0,
        "dimensionless",
        "PHYSICS",
        "#kozeny",
        "k proportional to d^2; used only for the local slope, never absolutely",
    ),
    "kozeny_carman_denominator": Constant(180.0, "dimensionless", "PHYSICS", "#kozeny"),
    # --- literature: espresso -------------------------------------------
    "espresso_ratio_aim": Constant(2.0, "ratio", "LITERATURE", "#ratio-espresso"),
    "espresso_ratio_lo": Constant(1.8, "ratio", "LITERATURE", "#ratio-espresso"),
    "espresso_ratio_hi": Constant(2.5, "ratio", "LITERATURE", "#ratio-espresso"),
    "espresso_time_lo": Constant(25.0, "s", "LITERATURE", "#ratio-espresso"),
    "espresso_time_hi": Constant(30.0, "s", "LITERATURE", "#ratio-espresso"),
    "espresso_temp_lo": Constant(90.5, "C", "LITERATURE", "#ratio-espresso"),
    "espresso_temp_hi": Constant(96.0, "C", "LITERATURE", "#ratio-espresso"),
    "ristretto_ratio_aim": Constant(1.25, "ratio", "LITERATURE", "#ratio-ristretto"),
    "ristretto_ratio_lo": Constant(1.0, "ratio", "LITERATURE", "#ratio-ristretto"),
    "ristretto_ratio_hi": Constant(1.5, "ratio", "LITERATURE", "#ratio-ristretto"),
    "ristretto_time_lo": Constant(20.0, "s", "LITERATURE", "#ratio-ristretto"),
    "ristretto_time_hi": Constant(28.0, "s", "LITERATURE", "#ratio-ristretto"),
    "lungo_ratio_aim": Constant(2.75, "ratio", "LITERATURE", "#ratio-lungo"),
    "lungo_ratio_lo": Constant(2.5, "ratio", "LITERATURE", "#ratio-lungo"),
    "lungo_ratio_hi": Constant(3.0, "ratio", "LITERATURE", "#ratio-lungo"),
    "lungo_time_lo": Constant(28.0, "s", "LITERATURE", "#ratio-lungo"),
    "lungo_time_hi": Constant(36.0, "s", "LITERATURE", "#ratio-lungo"),
    # --- literature: pour-over and moka ----------------------------------
    "pourover_ratio_aim": Constant(16.0, "ratio", "LITERATURE", "#ratio-pourover"),
    "pourover_ratio_lo": Constant(15.0, "ratio", "LITERATURE", "#ratio-pourover"),
    "pourover_ratio_hi": Constant(17.0, "ratio", "LITERATURE", "#ratio-pourover"),
    "pourover_time_lo": Constant(165.0, "s", "LITERATURE", "#ratio-pourover"),
    "pourover_time_hi": Constant(195.0, "s", "LITERATURE", "#ratio-pourover"),
    "pourover_temp_lo": Constant(92.0, "C", "LITERATURE", "#ratio-pourover"),
    "pourover_temp_hi": Constant(96.0, "C", "LITERATURE", "#ratio-pourover"),
    "moka_ratio_aim": Constant(8.0, "ratio", "LITERATURE", "#ratio-moka"),
    "moka_ratio_lo": Constant(7.0, "ratio", "LITERATURE", "#ratio-moka"),
    "moka_ratio_hi": Constant(10.0, "ratio", "LITERATURE", "#ratio-moka"),
    "moka_temp_lo": Constant(90.0, "C", "LITERATURE", "#ratio-moka"),
    "moka_temp_hi": Constant(96.0, "C", "LITERATURE", "#ratio-moka"),
    "moka_choked_time_s": Constant(
        480.0, "s", "LITERATURE", "#ratio-moka", "beyond this the pot is choked"
    ),
    # --- literature: other ------------------------------------------------
    "degas_rest_days": Constant(7.0, "days", "LITERATURE", "#degassing"),
    "cameron_dose_reduction": Constant(
        0.20,
        "fraction",
        "LITERATURE",
        "#cameron-reproducibility",
        "20 g -> 15 g in the paper's protocol",
    ),
    "cameron_dose_reduction_max": Constant(
        0.25, "fraction", "LITERATURE", "#cameron-reproducibility"
    ),
    "temp_light_lo": Constant(94.0, "C", "LITERATURE", "#temp-by-roast"),
    "temp_light_hi": Constant(96.0, "C", "LITERATURE", "#temp-by-roast"),
    "temp_medium_lo": Constant(92.0, "C", "LITERATURE", "#temp-by-roast"),
    "temp_medium_hi": Constant(94.0, "C", "LITERATURE", "#temp-by-roast"),
    "temp_dark_lo": Constant(90.5, "C", "LITERATURE", "#temp-by-roast"),
    "temp_dark_hi": Constant(92.5, "C", "LITERATURE", "#temp-by-roast"),
    "tds_plausible_lo": Constant(6.0, "percent", "LITERATURE", "#sca-bands"),
    "tds_plausible_hi": Constant(14.0, "percent", "LITERATURE", "#sca-bands"),
    # --- calibrated -------------------------------------------------------
    "d_ref_espresso_um": Constant(300.0, "um", "CALIBRATED", "#beta-prior"),
    "d_ref_pourover_um": Constant(700.0, "um", "CALIBRATED", "#beta-prior"),
    "beta_prior_unknown_grinder": Constant(
        -0.06,
        "per_click",
        "CALIBRATED",
        "#beta-prior",
        "used when um-per-click is unknown; confidence is capped low",
    ),
    "k6_um_per_click": Constant(16.0, "um", "CALIBRATED", "#k6-caps"),
    # --- heuristics -------------------------------------------------------
    "kappa_espresso": Constant(4.0, "shots", "HEURISTIC", "#shrinkage"),
    "kappa_pourover": Constant(8.0, "shots", "HEURISTIC", "#shrinkage"),
    "kappa_bean": Constant(2.0, "shots", "HEURISTIC", "#shrinkage"),
    "similarity_setup": Constant(0.40, "weight", "HEURISTIC", "#similarity"),
    "similarity_roast": Constant(0.25, "weight", "HEURISTIC", "#similarity"),
    "similarity_process": Constant(0.15, "weight", "HEURISTIC", "#similarity"),
    "similarity_origin": Constant(0.10, "weight", "HEURISTIC", "#similarity"),
    "similarity_freshness": Constant(0.10, "weight", "HEURISTIC", "#similarity"),
    "similarity_floor": Constant(0.45, "score", "HEURISTIC", "#similarity"),
    "similarity_recency_decay": Constant(0.97, "per_week", "HEURISTIC", "#similarity"),
    "bean_offset_floor": Constant(
        0.25,
        "score",
        "HEURISTIC",
        "#similarity",
        "bean-only similarity, so the 0.40 setup term is excluded and 0.60 is "
        "the ceiling; below this an offset is not worth borrowing",
    ),
    "roast_time_modifier_s": Constant(1.0, "s", "HEURISTIC", "#roast-time-modifier"),
    "fresh_band_widening": Constant(2.0, "factor", "HEURISTIC", "#fresh-band"),
    "fresh_correction_damping": Constant(0.5, "factor", "HEURISTIC", "#fresh-band"),
    "channeling_variance_ratio": Constant(
        2.0, "ratio", "HEURISTIC", "#channeling-detection"
    ),
    "channeling_min_shots": Constant(
        6.0, "shots", "HEURISTIC", "#channeling-detection"
    ),
    "max_steps_finer_than_best": Constant(
        2.0, "steps", "HEURISTIC", "#channeling-detection"
    ),
    "max_move_fraction": Constant(
        0.25, "fraction", "HEURISTIC", "#channeling-detection"
    ),
    "temp_tolerance_c": Constant(
        1.0,
        "C",
        "HEURISTIC",
        "#temp-covariate",
        "brew-temperature difference beyond which two shots stop being "
        "comparable as grind evidence",
    ),
    "prep_tolerance_s": Constant(
        2.0,
        "s",
        "HEURISTIC",
        "#preinfusion",
        "pre-infusion/pause difference beyond which two shots stop being "
        "comparable as grind evidence",
    ),
    "preinfusion_channeling_relief": Constant(
        1.0,
        "steps",
        "HEURISTIC",
        "#preinfusion",
        "grinder steps of extra fineness a consistently pre-infused puck tolerates",
    ),
    "preinfusion_min_for_relief_s": Constant(4.0, "s", "HEURISTIC", "#preinfusion"),
    "resistance_disagreement_ratio": Constant(
        1.6,
        "ratio",
        "HEURISTIC",
        "#preinfusion",
        "gap between pull-time and time-to-pressure resistance beyond which "
        "the cause is prep rather than grind",
    ),
    "min_shots_for_prep_advice": Constant(8.0, "shots", "HEURISTIC", "#preinfusion"),
    "dose_min_g": Constant(12.0, "g", "HEURISTIC", "#limits"),
    "dose_max_g": Constant(22.0, "g", "HEURISTIC", "#limits"),
    "basket_fill_lo": Constant(0.75, "fraction", "HEURISTIC", "#limits"),
    "basket_fill_hi": Constant(1.05, "fraction", "HEURISTIC", "#limits"),
    "confidence_cap_pourover": Constant(0.6, "fraction", "HEURISTIC", "#method-levers"),
    "confidence_cap_moka": Constant(0.4, "fraction", "HEURISTIC", "#method-levers"),
}


def value_of(name: str) -> float:
    """Look up a constant's value. Fails loudly on an undeclared name."""
    return CONSTANTS[name].value


# --------------------------------------------------------------------------
# Hardware capability and shot records
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class GrinderCaps:
    """What the grinder can physically do.

    All optional: when the range is unknown the engine abstains from
    recommending a click number rather than guessing one.
    """

    min_clicks: float | None = None
    max_clicks: float | None = None
    step_clicks: float = 1.0
    um_per_click: float | None = None
    finer_direction: Literal["lower_is_finer", "higher_is_finer"] = "lower_is_finer"

    @property
    def has_range(self) -> bool:
        return self.min_clicks is not None and self.max_clicks is not None

    @property
    def finer_sign(self) -> int:
        """+1 if increasing the dial makes it finer, -1 if decreasing does."""
        return 1 if self.finer_direction == "higher_is_finer" else -1


@dataclass(frozen=True)
class MachineCaps:
    basket_size_g: float | None = None
    temp_min_c: float | None = None
    temp_max_c: float | None = None
    temp_controllable: bool = False


@dataclass(frozen=True)
class ShotRecord:
    """One measured shot, method-normalised. Only 'measured' rows belong here."""

    method: Method
    dose_g: float
    setup_id: int | None = None
    bean_id: int | None = None
    grind_clicks: float | None = None
    yield_g: float | None = None
    water_g: float | None = None
    time_s: float | None = None
    taste_axis: TasteAxis | None = None
    astringent: bool | None = None
    brew_temp_c: float | None = None
    rating: int | None = None
    days_since_roast: int | None = None
    created_at: datetime | None = None
    # Pre-infusion duration and the rest before the pull. Deliberately not
    # part of time_s -- see docs/science.md#preinfusion. They are covariates:
    # two shots are only comparable as grind evidence if these match.
    preinfusion_s: float | None = None
    pause_s: float | None = None


@dataclass(frozen=True)
class Target:
    """Target band for one method/style."""

    ratio_lo: float
    ratio_hi: float
    ratio_aim: float
    time_lo: float | None
    time_hi: float | None
    temp_lo: float
    temp_hi: float
    source_anchor: str

    @property
    def tr_lo(self) -> float | None:
        """Target band expressed as normalised time. See docs/science.md#normalised-time."""
        return None if self.time_lo is None else self.time_lo / self.ratio_aim

    @property
    def tr_hi(self) -> float | None:
        return None if self.time_hi is None else self.time_hi / self.ratio_aim


TARGETS: dict[str, Target] = {
    "espresso": Target(
        value_of("espresso_ratio_lo"),
        value_of("espresso_ratio_hi"),
        value_of("espresso_ratio_aim"),
        value_of("espresso_time_lo"),
        value_of("espresso_time_hi"),
        value_of("espresso_temp_lo"),
        value_of("espresso_temp_hi"),
        "#ratio-espresso",
    ),
    "ristretto": Target(
        value_of("ristretto_ratio_lo"),
        value_of("ristretto_ratio_hi"),
        value_of("ristretto_ratio_aim"),
        value_of("ristretto_time_lo"),
        value_of("ristretto_time_hi"),
        value_of("espresso_temp_lo"),
        value_of("espresso_temp_hi"),
        "#ratio-ristretto",
    ),
    "lungo": Target(
        value_of("lungo_ratio_lo"),
        value_of("lungo_ratio_hi"),
        value_of("lungo_ratio_aim"),
        value_of("lungo_time_lo"),
        value_of("lungo_time_hi"),
        value_of("espresso_temp_lo"),
        value_of("espresso_temp_hi"),
        "#ratio-lungo",
    ),
    "pourover": Target(
        value_of("pourover_ratio_lo"),
        value_of("pourover_ratio_hi"),
        value_of("pourover_ratio_aim"),
        value_of("pourover_time_lo"),
        value_of("pourover_time_hi"),
        value_of("pourover_temp_lo"),
        value_of("pourover_temp_hi"),
        "#ratio-pourover",
    ),
    # Moka has no target time: brew time is set by stove heat input, not by
    # bed permeability, so claiming one would be dishonest.
    "moka": Target(
        value_of("moka_ratio_lo"),
        value_of("moka_ratio_hi"),
        value_of("moka_ratio_aim"),
        None,
        None,
        value_of("moka_temp_lo"),
        value_of("moka_temp_hi"),
        "#ratio-moka",
    ),
}


def target_for(method: Method, style: str | None = None) -> Target:
    """Target band for a method, optionally an espresso style (ristretto/lungo)."""
    if method == "espresso" and style in ("ristretto", "lungo"):
        return TARGETS[style]
    return TARGETS[method]


# --------------------------------------------------------------------------
# Derived metrics -- arithmetic on measurements, no inference
# --------------------------------------------------------------------------


def brew_ratio(shot: ShotRecord) -> float | None:
    """Beverage-out per dry gram for espresso; water-in per dry gram otherwise."""
    if shot.dose_g <= 0:
        return None
    numerator = shot.yield_g if shot.method == "espresso" else shot.water_g
    # Fall back to whichever mass was actually recorded.
    if numerator is None:
        numerator = shot.water_g if shot.method == "espresso" else shot.yield_g
    if numerator is None or numerator <= 0:
        return None
    return numerator / shot.dose_g


def flow_rate_gps(shot: ShotRecord) -> float | None:
    """Average mass flow in g/s."""
    if not shot.time_s or shot.time_s <= 0:
        return None
    mass = shot.yield_g if shot.method == "espresso" else shot.water_g
    if mass is None:
        mass = shot.water_g if shot.method == "espresso" else shot.yield_g
    if mass is None or mass <= 0:
        return None
    return mass / shot.time_s


def normalised_time(shot: ShotRecord) -> float | None:
    """T_r = time / brew_ratio -- see docs/science.md#normalised-time.

    Shot time alone is not comparable across ratios; this is.
    """
    ratio = brew_ratio(shot)
    if ratio is None or ratio <= 0 or not shot.time_s or shot.time_s <= 0:
        return None
    return shot.time_s / ratio


def taste_offset(taste: TasteAxis | None) -> int | None:
    """Signed distance from balanced: negative sour, positive bitter."""
    return None if taste is None else TASTE_SCALE[taste]


def extraction_yield_pct(shot: ShotRecord, tds_pct: float | None) -> float | None:
    """EY% = beverage x TDS / dose -- only when a TDS measurement exists.

    Returns None without a refractometer reading, and callers must render that
    as "not measured" rather than substituting a guess. See
    docs/science.md#limits.
    """
    if tds_pct is None or shot.dose_g <= 0:
        return None
    beverage = shot.yield_g if shot.yield_g is not None else shot.water_g
    if beverage is None or beverage <= 0:
        return None
    return beverage * tds_pct / shot.dose_g


# --------------------------------------------------------------------------
# The grind law
# --------------------------------------------------------------------------


def beta_prior(method: Method, caps: GrinderCaps) -> float | None:
    """d ln(T_r) / d click, from Darcy + Kozeny-Carman.

    None for moka: brew time there is set by stove heat, not permeability, so
    grind must never be solved from time. See docs/science.md#beta-law.
    """
    if method == "moka":
        return None
    if caps.um_per_click is None:
        # Magnitude only; the dial direction supplies the sign, as below.
        return abs(value_of("beta_prior_unknown_grinder")) * caps.finer_sign
    d_ref = value_of(
        "d_ref_espresso_um" if method == "espresso" else "d_ref_pourover_um"
    )
    exponent = value_of("kozeny_carman_exponent")
    magnitude = exponent * caps.um_per_click / d_ref
    # Sign follows the dial: on a 'lower_is_finer' grinder, turning the number
    # up coarsens the grind and shortens T_r, so beta is negative. On a
    # 'higher_is_finer' grinder it is positive. finer_sign encodes exactly that.
    return magnitude * caps.finer_sign


def cold_start_clicks(caps: GrinderCaps, method: Method) -> float | None:
    """Where to start on a grinder we have never measured a shot on.

    Hand grinders are zeroed at burr contact, so the dial reads out roughly
    linearly in particle diameter and clicks ~= d / (um per click). For a
    16 um/click grinder that puts espresso near 19 clicks -- which is a
    physical estimate, and lands inside the published espresso range for such
    grinders.

    The midpoint of the hardware range is *not* a substitute: that range spans
    espresso to French press, so its centre is far too coarse. Without
    um_per_click there is no way to locate the dial, so this returns None and
    the caller abstains rather than guessing. See docs/science.md#cold-start.
    """
    if method == "moka" or caps.um_per_click is None or caps.um_per_click <= 0:
        return None
    d_ref = value_of(
        "d_ref_espresso_um" if method == "espresso" else "d_ref_pourover_um"
    )
    estimate = d_ref / caps.um_per_click
    if caps.finer_sign > 0:
        # On a higher-is-finer dial the scale runs the other way.
        if caps.max_clicks is None:
            return None
        estimate = caps.max_clicks - estimate
    if caps.min_clicks is not None:
        estimate = max(estimate, caps.min_clicks)
    if caps.max_clicks is not None:
        estimate = min(estimate, caps.max_clicks)
    return snap_to_step(estimate, caps)


def solve_grind(
    current_clicks: float,
    tr_observed: float,
    tr_target: float,
    beta: float,
) -> float:
    """The one correction the engine makes. See docs/science.md#beta-law.

    c* = c + (ln T_r_target - ln T_r_observed) / beta
    """
    if tr_observed <= 0 or tr_target <= 0 or beta == 0:
        return current_clicks
    return current_clicks + (math.log(tr_target) - math.log(tr_observed)) / beta


def clicks_for_target(
    alpha: float | None,
    beta: float | None,
    tr_target: float,
    delta_bean: float = 0.0,
) -> float | None:
    """Where to set the dial for a coffee with no shots of its own.

    Solves docs/science.md#beta-law for c rather than correcting from a
    measured shot:

        c = (ln T_r_target - alpha - delta_bean) / beta

    This is the honest answer for a new bag on a calibrated setup. Correcting
    from the last shot would be correcting from a *different* coffee, which is
    what made every bean on a setup come back with the same number.

    Returns None when the setup has no fitted intercept or no slope -- moka,
    or a grinder nothing has been measured on -- so the caller can fall back
    to the cold start instead of solving with a term it does not have.
    """
    if alpha is None or not beta or tr_target <= 0:
        return None
    return (math.log(tr_target) - alpha - delta_bean) / beta


def snap_to_step(clicks: float, caps: GrinderCaps) -> float:
    """Round to something the grinder can actually be set to."""
    step = caps.step_clicks or 1.0
    if step <= 0:
        return clicks
    return round(clicks / step) * step


def prep_comparable(a: ShotRecord, b: ShotRecord) -> bool:
    """Can these two shots be compared as evidence about grind?

    Only if they were prepared the same way. A shot with longer pre-infusion
    arrives at full pressure with the bed already saturated and runs faster
    once pulling, so comparing it against a shorter one attributes a
    preparation difference to the grinder.

    That is not merely noise: a finer shot that ran *faster* is exactly the
    channeling fingerprint, so an unrecorded pre-infusion difference can fake
    it and make the engine refuse to go finer for no reason. See
    docs/science.md#preinfusion.

    Unknown on either side counts as comparable -- otherwise nothing would
    ever be comparable for a user who does not record it.
    """
    tolerance = value_of("prep_tolerance_s")
    for lhs, rhs in ((a.preinfusion_s, b.preinfusion_s), (a.pause_s, b.pause_s)):
        if lhs is not None and rhs is not None and abs(lhs - rhs) > tolerance:
            return False

    # Temperature is a covariate for the same reason. Hotter water is less
    # viscous and extracts faster, so it shortens the shot and shifts the
    # taste independently of the grind. Comparing shots pulled at different
    # temperatures puts that difference into the grind slope.
    temp_tolerance = value_of("temp_tolerance_c")
    return not (
        a.brew_temp_c is not None
        and b.brew_temp_c is not None
        and abs(a.brew_temp_c - b.brew_temp_c) > temp_tolerance
    )


def is_finer(a: float, b: float, caps: GrinderCaps) -> bool:
    """True when setting `a` grinds finer than setting `b` on this grinder."""
    return (a - b) * caps.finer_sign > 0


def finer_by(clicks: float, steps: float, caps: GrinderCaps) -> float:
    """The setting `steps` grinder steps finer than `clicks`."""
    return clicks + steps * caps.step_clicks * caps.finer_sign


# --------------------------------------------------------------------------
# The anti-channeling floor -- docs/science.md#cameron
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class FinenessLimit:
    """The finest setting the engine is willing to recommend, and why."""

    clicks: float | None
    reason: str | None


def finest_useful_clicks(
    history: Sequence[ShotRecord],
    caps: GrinderCaps,
    target: Target | None = None,
) -> FinenessLimit:
    """Where to stop grinding finer.

    Extraction yield peaks and then *declines* at fine settings, because flow
    goes inhomogeneous (docs/science.md#cameron). Past that peak, "the shot
    ran long, grind finer" makes extraction worse and less repeatable -- and
    that reflex was hardcoded into this app's previous prompt.

    Five independent triggers, all deterministic and all derived from the
    user's own shots or their hardware. The finest of the resulting limits
    wins, i.e. the most permissive bound that every trigger agrees on.
    """
    candidates: list[tuple[float, str]] = []

    measured = [
        s
        for s in history
        if s.grind_clicks is not None and normalised_time(s) is not None
    ]

    # 1. Empirical peak. Under homogeneous flow a finer grind is always
    #    slower. A finer setting that ran *faster* means flow bypassed the
    #    bed. Two shots are enough to catch it.
    for a in measured:
        for b in measured:
            if a is b or a.grind_clicks is None or b.grind_clicks is None:
                continue
            if not is_finer(a.grind_clicks, b.grind_clicks, caps):
                continue
            # Only compare shots prepared the same way. Otherwise a longer
            # pre-infusion -- which saturates the bed and speeds up the pull --
            # is mistaken for channeling.
            if not prep_comparable(a, b):
                continue
            tr_a, tr_b = normalised_time(a), normalised_time(b)
            if tr_a is None or tr_b is None:
                continue
            if tr_a <= tr_b:
                candidates.append(
                    (
                        b.grind_clicks,
                        f"at {a.grind_clicks:g} the shot ran no slower than at "
                        f"{b.grind_clicks:g}, which means the water is finding "
                        f"a channel rather than soaking the puck evenly",
                    )
                )

    # 2. Reproducibility collapse: variance of ln(T_r) blowing up on the fine
    #    side. Needs a real spread of data before it can say anything.
    if len(measured) >= int(value_of("channeling_min_shots")):
        ratio_limit = value_of("channeling_variance_ratio")
        for pivot in measured:
            if pivot.grind_clicks is None:
                continue
            fine: list[float] = []
            coarse: list[float] = []
            for s in measured:
                if s.grind_clicks is None:
                    continue
                tr = normalised_time(s)
                if tr is None or tr <= 0:
                    continue
                bucket = (
                    fine
                    if not is_finer(pivot.grind_clicks, s.grind_clicks, caps)
                    else coarse
                )
                bucket.append(math.log(tr))
            if len(fine) >= 3 and len(coarse) >= 3:
                var_fine = statistics.pvariance(fine)
                var_coarse = statistics.pvariance(coarse)
                if var_coarse > 0 and var_fine / var_coarse > ratio_limit:
                    candidates.append(
                        (
                            pivot.grind_clicks,
                            "shots at and below this setting vary far more than "
                            "the coarser ones, which is what channeling looks "
                            "like in the data",
                        )
                    )

    # 3. Long *and* sour: the bypass signature. Water spent a long time in the
    #    basket and still under-extracted, so it was not passing through the
    #    coffee. Going finer here makes it worse.
    if target is not None and target.tr_hi is not None:
        for s in measured:
            tr = normalised_time(s)
            if s.grind_clicks is None or tr is None:
                continue
            if tr > target.tr_hi and s.taste_axis in ("sour", "very_sour"):
                candidates.append(
                    (
                        s.grind_clicks,
                        f"{s.grind_clicks:g} produced a long shot that still "
                        f"tasted sour -- the water is channeling, so finer "
                        f"would make it worse",
                    )
                )

    # (The hardware end-stop is deliberately *not* a trigger here. It is a
    # different kind of limit and apply_guardrails applies it separately, so
    # that "your grinder won't go finer" is never mislabelled to the user as
    # "your shots are channeling".)

    # 4. Never leap far below the finest setting that has actually worked.
    acceptable = [
        s.grind_clicks
        for s in history
        if s.grind_clicks is not None
        and ((s.rating is not None and s.rating >= 4) or s.taste_axis == "balanced")
    ]
    if acceptable:
        finest_good = min(acceptable) if caps.finer_sign < 0 else max(acceptable)
        candidates.append(
            (
                finer_by(finest_good, value_of("max_steps_finer_than_best"), caps),
                "more than a couple of steps finer than anything that has "
                "worked before is a guess, not a correction",
            )
        )

    if not candidates:
        return FinenessLimit(None, None)

    # The binding limit is the coarsest of the candidate floors.
    coarsest = candidates[0]
    for candidate in candidates[1:]:
        if is_finer(coarsest[0], candidate[0], caps):
            coarsest = candidate

    limit, reason = coarsest

    # A consistently pre-infused, rested puck saturates evenly before full
    # pressure arrives, which is the standard channeling mitigation. Where the
    # user does that every time, the floor genuinely sits finer than it would
    # otherwise -- so give back a step rather than holding them at a limit
    # measured under worse conditions.
    if _preinfuses_consistently(measured):
        limit = finer_by(limit, value_of("preinfusion_channeling_relief"), caps)
        reason = (
            f"{reason}. Your pre-infusion is consistent, which lets the puck "
            f"take a slightly finer grind than it otherwise would"
        )

    return FinenessLimit(limit, reason)


def _preinfuses_consistently(shots: Sequence[ShotRecord]) -> bool:
    """True when every recorded shot used a real and similar pre-infusion."""
    values = [s.preinfusion_s for s in shots if s.preinfusion_s is not None]
    if len(values) < 2 or len(values) < len(shots):
        return False
    if min(values) < value_of("preinfusion_min_for_relief_s"):
        return False
    return (max(values) - min(values)) <= value_of("prep_tolerance_s")


# --------------------------------------------------------------------------
# Recipe and guardrails
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Recipe:
    """What the engine recommends. Every number here is arithmetic, not prose."""

    method: Method
    dose_g: float
    grind_clicks: float | None = None
    yield_g: float | None = None
    water_g: float | None = None
    brew_temp_c: float | None = None
    target_time_s: float | None = None
    # Suggested preparation. Echoes the user's own consistent routine until
    # there is enough variation to say whether changing it helps.
    preinfusion_s: float | None = None
    pause_s: float | None = None
    # Where the numbers came from. "history" and "calibrated" mean a
    # correction to this coffee's own last shot; "setup_law" means the coffee
    # is new and the dial was solved from the grinder's fitted law instead.
    basis: Literal["prior", "history", "calibrated", "setup_law"] = "prior"
    confidence: float = 0.0
    guardrails_hit: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def numeric_tokens(self) -> set[str]:
        """Every number this recipe legitimately contains.

        The rationale writer's output is checked against this set, so the LLM
        cannot introduce a number the engine did not produce.
        """
        tokens: set[str] = set()
        for value in (
            self.dose_g,
            self.grind_clicks,
            self.yield_g,
            self.water_g,
            self.brew_temp_c,
            self.target_time_s,
            self.preinfusion_s,
            self.pause_s,
        ):
            if value is None:
                continue
            tokens.add(f"{value:g}")
            tokens.add(f"{value:.1f}")
            tokens.add(f"{round(value)}")
        return tokens


def correct(
    last: ShotRecord,
    target: Target,
    beta: float | None,
    grinder: GrinderCaps,
    machine: MachineCaps,
    days_since_roast: int | None = None,
    roast_level_ord: int | None = None,
    dose_g: float | None = None,
) -> Recipe:
    """Propose the next recipe from the last measured shot.

    One lever at a time, in priority order: the first rule that fires decides
    the change, and the rest are recorded as what to try next. Changing two
    things at once means learning nothing from the result.

    ``dose_g`` is the dose the user asked for. Left out, the next shot keeps
    the anchor's dose -- the dose they actually use for this coffee.
    """
    notes: list[str] = []
    dose = last.dose_g if dose_g is None else dose_g
    if abs(dose - last.dose_g) >= 0.5:
        # The grind law has no dose term yet (docs/science.md#beta-law), so the
        # setting below is still solved for the anchor's dose. Say so rather
        # than let the time move without warning.
        notes.append(
            "you changed the dose from your last shot on this coffee, and the "
            "grind is still worked out from that shot -- a heavier dose runs "
            "slower and a lighter one faster, so watch the time"
        )
    ratio = brew_ratio(last)
    tr = normalised_time(last)
    grind = last.grind_clicks
    temp_lo, temp_hi = temp_band_for_roast(roast_level_ord)
    temp = (
        min(max(last.brew_temp_c or (temp_lo + temp_hi) / 2, temp_lo), temp_hi)
        if machine.temp_controllable
        else None
    )

    fresh = days_since_roast is not None and days_since_roast < value_of(
        "degas_rest_days"
    )
    if fresh:
        notes.append(
            f"this coffee is {days_since_roast} days off roast; it is still "
            f"releasing CO2, so flow will be erratic and the target will move "
            f"until about day {value_of('degas_rest_days'):.0f}"
        )

    def build(**overrides: object) -> Recipe:
        base: dict[str, object] = {
            "method": last.method,
            "dose_g": dose,
            "grind_clicks": grind,
            "yield_g": round(target.ratio_aim * dose, 1)
            if last.method == "espresso"
            else None,
            "water_g": round(target.ratio_aim * dose, 1)
            if last.method != "espresso"
            else None,
            "brew_temp_c": temp,
            "target_time_s": target.time_hi,
            "notes": tuple(notes),
        }
        base.update(overrides)
        return Recipe(**base)  # type: ignore[arg-type]

    # 1. Ratio first: it is measured, not inferred, and T_r normalises it out
    #    of the time comparison anyway.
    if ratio is not None and not (target.ratio_lo <= ratio <= target.ratio_hi):
        notes.append(
            f"your ratio was 1:{ratio:.1f}; aiming for 1:{target.ratio_aim:g} "
            f"first, since that is the number you measured directly"
        )
        return build()

    # 2. Time out of band -> grind is the lever. Espresso and pour-over only:
    #    for moka, brew time is stove heat, not grind.
    if beta is not None and tr is not None and target.tr_lo is not None:
        tr_lo, tr_hi = target.tr_lo, target.tr_hi
        assert tr_hi is not None
        if fresh:
            widen = value_of("fresh_band_widening")
            centre = (tr_lo + tr_hi) / 2
            tr_lo = centre - (centre - tr_lo) * widen
            tr_hi = centre + (tr_hi - centre) * widen
        if grind is not None and not (tr_lo <= tr <= tr_hi):
            tr_aim = (tr_lo + tr_hi) / 2
            proposed = solve_grind(grind, tr, tr_aim, beta)
            move = proposed - grind
            cap = value_of("max_move_fraction") * abs(1.0 / beta)
            if abs(move) > cap:
                move = math.copysign(cap, move)
                notes.append(
                    "moving in a smaller step than the maths suggests, because "
                    "a big jump teaches you nothing about which way to go next"
                )
            if fresh:
                move *= value_of("fresh_correction_damping")
            direction = "finer" if is_finer(grind + move, grind, grinder) else "coarser"
            notes.append(
                f"your shot ran {'long' if tr > tr_hi else 'fast'} for the "
                f"ratio, so go {direction}"
            )
            return build(grind_clicks=snap_to_step(grind + move, grinder))

    # 3. Time is fine but it does not taste right.
    offset = taste_offset(last.taste_axis)
    if offset:
        if offset < 0:  # sour: under-extracted
            if machine.temp_controllable and temp is not None and temp < temp_hi:
                notes.append("tasted sour, so extract a little harder: up 1 C")
                return build(brew_temp_c=min(temp + 1.0, temp_hi))
            longer = min(target.ratio_aim * 1.15, target.ratio_hi)
            notes.append(
                "tasted sour with the timing on target, so let it run a little "
                "longer rather than changing the grind"
            )
            return build(
                yield_g=round(longer * dose, 1) if last.method == "espresso" else None,
                water_g=round(longer * dose, 1) if last.method != "espresso" else None,
            )
        # bitter
        if not last.astringent:
            # Bitter without astringency is usually roast character, not
            # over-extraction. Moving the grind here is the most common false
            # correction in dial-in advice. See docs/science.md#taste-mapping.
            shorter = max(target.ratio_aim * 0.9, target.ratio_lo)
            notes.append(
                "bitter but not drying, which usually means roast character "
                "rather than over-extraction -- shortening the shot instead of "
                "touching the grind"
            )
            return build(
                yield_g=round(shorter * dose, 1) if last.method == "espresso" else None,
                water_g=round(shorter * dose, 1) if last.method != "espresso" else None,
            )
        if machine.temp_controllable and temp is not None and temp > temp_lo:
            notes.append("drying and bitter: over-extracted, so down 1 C")
            return build(brew_temp_c=max(temp - 1.0, temp_lo))
        if grind is not None:
            notes.append(
                "drying and bitter with the timing on target: one step coarser"
            )
            return build(
                grind_clicks=snap_to_step(finer_by(grind, -1, grinder), grinder)
            )

    notes.append("this one looks on target -- keep it the same and repeat it")
    return build()


def propose_dose_reduction(dose_g: float) -> tuple[float, str]:
    """The Cameron reproducibility move. docs/science.md#cameron-reproducibility.

    When channeling keeps recurring, stop chasing the grind: use less coffee
    and grind coarser. A shallower bed drops less pressure and channels less,
    and it uses a fifth less coffee for a better, more repeatable shot.
    """
    reduced = round(dose_g * (1.0 - value_of("cameron_dose_reduction")), 1)
    return (
        reduced,
        f"channeling keeps recurring at this dose. Rather than chasing it with "
        f"the grinder, try {reduced:g} g instead of {dose_g:g} g and grind a "
        f"little coarser -- a shallower puck channels less, and you use less "
        f"coffee for a better shot",
    )


def resistance_disagreement(
    shot: ShotRecord, reference: Sequence[ShotRecord]
) -> str | None:
    """Check the pull time against the time it took pressure to build.

    Time from pump-on to the gauge first moving is a second, independent
    reading of how hard the puck is to push water through -- taken before the
    shot even runs. Grind moves both readings together: a finer puck is slower
    to pressurise *and* slower to pull.

    When they disagree -- normal time-to-pressure but a long pull, or the
    reverse -- the bed's resistance changed after it was wetted, which points
    at distribution, tamp or channeling rather than at the grinder. Returns a
    plain-language note, or None when the two agree or there is nothing to
    compare against.
    """
    if shot.preinfusion_s is None or shot.preinfusion_s <= 0:
        return None
    tr = normalised_time(shot)
    if tr is None:
        return None

    peers = [
        s
        for s in reference
        if s is not shot
        and s.preinfusion_s is not None
        and s.preinfusion_s > 0
        and normalised_time(s) is not None
        and s.grind_clicks == shot.grind_clicks
    ]
    if not peers:
        return None

    baseline_pi = statistics.median(
        [s.preinfusion_s for s in peers if s.preinfusion_s is not None]
    )
    baseline_tr = statistics.median(
        [t for t in (normalised_time(s) for s in peers) if t is not None]
    )
    if baseline_pi <= 0 or baseline_tr <= 0:
        return None

    pressure_ratio = shot.preinfusion_s / baseline_pi
    pull_ratio = tr / baseline_tr
    threshold = value_of("resistance_disagreement_ratio")

    # Grind moves both readings together, so it is the *gap* between them that
    # carries information -- not either one on its own.
    if pull_ratio > threshold * pressure_ratio:
        return (
            "the puck took the usual time to come up to pressure but then "
            "pulled slowly, so the resistance appeared after it was wetted -- "
            "that points at distribution or tamp rather than the grind"
        )
    if pressure_ratio > threshold * pull_ratio:
        return (
            "pressure took much longer to build than usual but the shot then "
            "ran normally, which usually means the puck was denser at the top "
            "than through its depth"
        )
    return None


def prep_advice(
    shots: Sequence[ShotRecord],
) -> tuple[float | None, float | None, str]:
    """Suggest pre-infusion and pause durations, or explain why it can't yet.

    Gated on data like every other learned quantity. Below the threshold this
    reports back the user's own most consistent routine, which is genuinely
    useful -- keeping preparation identical is what makes the grind evidence
    readable -- without pretending to know an optimum it has not measured.
    """
    recorded = [s for s in shots if s.preinfusion_s is not None and s.preinfusion_s > 0]
    if not recorded:
        return (
            None,
            None,
            (
                "Pre-infusion is not recorded yet. Timing it is what stops a "
                "preparation difference being mistaken for a grind difference."
            ),
        )

    pi = statistics.median([s.preinfusion_s for s in recorded if s.preinfusion_s])
    pauses = [s.pause_s for s in recorded if s.pause_s is not None]
    pause = statistics.median(pauses) if pauses else None

    if len(recorded) < value_of("min_shots_for_prep_advice"):
        return (
            pi,
            pause,
            (
                f"Keeping pre-infusion at about your usual {pi:g} s keeps these "
                f"shots comparable. Once there are more of them, and at more than "
                f"one duration, the engine can start telling you whether changing "
                f"it actually helps."
            ),
        )

    distinct = {round(s.preinfusion_s) for s in recorded if s.preinfusion_s}
    if len(distinct) < 2:
        return (
            pi,
            pause,
            (
                f"You have always pre-infused for about {pi:g} s, so there is "
                f"nothing to compare it against. Trying a longer one on a few "
                f"shots would tell us whether it helps this coffee."
            ),
        )

    best = max(
        recorded,
        key=lambda s: (
            (s.rating or 0),
            -abs(TASTE_SCALE.get(s.taste_axis or "balanced", 0)),
        ),
    )
    return (
        best.preinfusion_s,
        best.pause_s,
        (
            f"Your best-rated shots pre-infuse for about {best.preinfusion_s:g} s"
            + (f" with a {best.pause_s:g} s rest" if best.pause_s else "")
            + "."
        ),
    )


def temp_band_for_roast(roast_level_ord: int | None) -> tuple[float, float]:
    """Brew temperature window by roast level. docs/science.md#temp-by-roast."""
    if roast_level_ord is not None and roast_level_ord <= 2:
        return value_of("temp_light_lo"), value_of("temp_light_hi")
    if roast_level_ord is not None and roast_level_ord >= 4:
        return value_of("temp_dark_lo"), value_of("temp_dark_hi")
    return value_of("temp_medium_lo"), value_of("temp_medium_hi")


def apply_guardrails(
    recipe: Recipe,
    grinder: GrinderCaps,
    machine: MachineCaps,
    history: Sequence[ShotRecord] = (),
    target: Target | None = None,
) -> Recipe:
    """Clamp every field to what the hardware and the user's history allow.

    Runs on numbers, before any language model sees them. Every clamp is
    recorded in guardrails_hit so the UI can show it rather than silently
    changing what the user asked for.
    """
    hits = list(recipe.guardrails_hit)
    notes = list(recipe.notes)
    grind = recipe.grind_clicks
    dose = recipe.dose_g
    temp = recipe.brew_temp_c
    yield_g = recipe.yield_g

    # --- grind ---------------------------------------------------------
    if grind is not None:
        limit = finest_useful_clicks(history, grinder, target)
        if limit.clicks is not None and is_finer(grind, limit.clicks, grinder):
            grind = limit.clicks
            hits.append("grind_channeling_floor")
            if limit.reason:
                notes.append(limit.reason)

        if grinder.min_clicks is not None and grind < grinder.min_clicks:
            grind = grinder.min_clicks
            hits.append("grind_hardware_min")
        if grinder.max_clicks is not None and grind > grinder.max_clicks:
            grind = grinder.max_clicks
            hits.append("grind_hardware_max")

        snapped = snap_to_step(grind, grinder)
        if snapped != grind:
            hits.append("grind_snapped_to_step")
            grind = snapped

    # --- dose ----------------------------------------------------------
    asked_dose = dose
    if machine.basket_size_g is not None:
        lo = machine.basket_size_g * value_of("basket_fill_lo")
        hi = machine.basket_size_g * value_of("basket_fill_hi")
        if dose < lo or dose > hi:
            dose = min(max(dose, lo), hi)
            hits.append("dose_basket_capacity")
            notes.append(f"your basket holds about {machine.basket_size_g:g} g")
    elif recipe.method == "espresso":
        # An espresso basket range. A dripper or a moka funnel of unknown size
        # has no such bound, and clamping a 30 g pour-over to 22 g is wrong.
        lo, hi = value_of("dose_min_g"), value_of("dose_max_g")
        if dose < lo or dose > hi:
            dose = min(max(dose, lo), hi)
            hits.append("dose_plausible_range")
    water_g = recipe.water_g
    if dose != asked_dose and asked_dose > 0:
        # Keep the ratio: the output was sized for the dose that was asked for.
        scale = dose / asked_dose
        if yield_g is not None:
            yield_g = round(yield_g * scale, 1)
        if water_g is not None:
            water_g = round(water_g * scale, 1)

    # --- ratio / yield -------------------------------------------------
    if target is not None and yield_g is not None and dose > 0:
        ratio = yield_g / dose
        if ratio < target.ratio_lo or ratio > target.ratio_hi:
            ratio = min(max(ratio, target.ratio_lo), target.ratio_hi)
            yield_g = round(ratio * dose, 1)
            hits.append("ratio_out_of_band")
    if yield_g is not None and yield_g <= dose:
        # Not a preference: a beverage lighter than the dry coffee is a
        # logging error, not a recipe.
        yield_g = None
        hits.append("yield_below_dose_rejected")

    # --- temperature ---------------------------------------------------
    if temp is not None and not machine.temp_controllable:
        # Telling someone with a fixed-temperature machine to change the
        # temperature is noise.
        temp = None
        hits.append("temp_not_controllable")
    elif temp is not None:
        lo = machine.temp_min_c if machine.temp_min_c is not None else temp
        hi = machine.temp_max_c if machine.temp_max_c is not None else temp
        clamped = min(max(temp, lo), hi)
        if clamped != temp:
            temp = clamped
            hits.append("temp_machine_range")

    return Recipe(
        method=recipe.method,
        dose_g=round(dose, 1),
        grind_clicks=grind,
        yield_g=yield_g,
        water_g=water_g,
        brew_temp_c=temp,
        target_time_s=recipe.target_time_s,
        basis=recipe.basis,
        confidence=recipe.confidence,
        guardrails_hit=tuple(hits),
        notes=tuple(notes),
    )
