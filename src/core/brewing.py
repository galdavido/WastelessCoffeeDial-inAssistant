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


def snap_to_step(clicks: float, caps: GrinderCaps) -> float:
    """Round to something the grinder can actually be set to."""
    step = caps.step_clicks or 1.0
    if step <= 0:
        return clicks
    return round(clicks / step) * step
