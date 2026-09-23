"""Physics simulator for espresso extraction. TEST FIXTURE ONLY.

Darcy + Kozeny-Carman with a logistic bypass term, so that below an onset
particle diameter a growing fraction of flow short-circuits through a
low-resistance channel. That reproduces the non-monotonic extraction-yield
curve reported in Cameron et al. 2020 (docs/science.md#cameron) from first
principles: as the grind gets finer past the onset, shot time stops rising and
then falls, while yield drops because the bypassed coffee is barely extracted.

This exists so the correction policy can be tested before any real shots have
been logged. It is deliberately crude -- the taste mapping especially -- which
is why it lives under tests/, where no production module can import it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from core.brewing import GrinderCaps, TasteAxis

# Simulator parameters. These are fixture values, not project constants, and
# deliberately live outside brewing.CONSTANTS -- nothing in production reads
# them. See docs/science.md#simulator.
DEFAULT_DP_BAR = 9.0
DEFAULT_POROSITY = 0.35
DEFAULT_BASKET_DIA_MM = 51.0
DEFAULT_BULK_DENSITY_KG_M3 = 330.0

# Kozeny-Carman with a nominal particle diameter overestimates the absolute
# permeability of a real, compressed espresso puck by orders of magnitude --
# fines migrate into the voids and the bed compacts (docs/science.md#kozeny).
# The fixture therefore keeps the k ∝ d^2 *scaling*, which is what sets the
# slope the engine cares about, and pins the absolute scale to an observed
# reference: 36 g in ~28 s at a 300 µm grind.
REFERENCE_D_UM = 300.0
REFERENCE_FLOW_GPS = 1.30

CHANNEL_PERMEABILITY_FACTOR = 8.0
DEFAULT_ONSET_UM = 200.0
DEFAULT_SHARPNESS = 0.08
EY_MAX_PCT = 26.0
EY_RATE_UM_PER_S = 16.0


@dataclass(frozen=True)
class BedParams:
    dose_g: float
    basket_dia_mm: float = DEFAULT_BASKET_DIA_MM
    porosity: float = DEFAULT_POROSITY
    bulk_density_kg_m3: float = DEFAULT_BULK_DENSITY_KG_M3
    dp_bar: float = DEFAULT_DP_BAR

    @property
    def area_m2(self) -> float:
        radius_m = (self.basket_dia_mm / 1000.0) / 2.0
        return math.pi * radius_m**2

    @property
    def depth_m(self) -> float:
        volume_m3 = (self.dose_g / 1000.0) / self.bulk_density_kg_m3
        return volume_m3 / self.area_m2


@dataclass(frozen=True)
class SimShot:
    clicks: float
    particle_um: float
    time_s: float
    yield_g: float
    ey_pct: float
    channel_fraction: float
    taste_axis: TasteAxis


def particle_diameter_um(
    clicks: float, caps: GrinderCaps, d0_um: float, c0_clicks: float
) -> float:
    """Linear dial model: d = d0 + u * (c - c0), floored to stay positive."""
    u = caps.um_per_click if caps.um_per_click is not None else 16.0
    # finer_sign = +1 when a higher number is finer, so the diameter moves the
    # other way.
    delta = (clicks - c0_clicks) * u * (-caps.finer_sign)
    return max(20.0, d0_um + delta)


def permeability_m2(d_um: float, porosity: float = DEFAULT_POROSITY) -> float:
    """Kozeny-Carman. See docs/science.md#kozeny."""
    d_m = d_um * 1e-6
    return (d_m**2 * porosity**3) / (180.0 * (1.0 - porosity) ** 2)


def channel_fraction(
    d_um: float,
    onset_um: float = DEFAULT_ONSET_UM,
    sharpness: float = DEFAULT_SHARPNESS,
) -> float:
    """Fraction of flow bypassing the bed, rising as the grind goes fine.

    Logistic in particle diameter: negligible above the onset, approaching 1
    well below it. This is the mechanism behind the yield peak.
    """
    return 1.0 / (1.0 + math.exp((d_um - onset_um) / (sharpness * onset_um)))


_REFERENCE_BED = BedParams(dose_g=18.0)


def mass_flow_gps(d_um: float, bed: BedParams, f_channel: float) -> float:
    """Darcy flow, expressed relative to the reference shot.

        Q ∝ k · A · ΔP / (µ · L)

    Every factor is carried as a ratio against the reference bed, so the dose
    dependence (a deeper bed flows slower -- the mechanism behind the Cameron
    dose-reduction move) is preserved, while the absolute scale stays
    realistic. The bypass path carries disproportionate flow, which is what
    makes the fine end of the curve turn over.
    """
    k_bed = permeability_m2(d_um, bed.porosity)
    k_ref = permeability_m2(REFERENCE_D_UM, bed.porosity)
    # (1 - f) through the bed + f through a much more permeable channel.
    k_eff_ratio = ((1.0 - f_channel) + f_channel * CHANNEL_PERMEABILITY_FACTOR) * (
        k_bed / k_ref
    )
    geometry = (
        (bed.area_m2 / _REFERENCE_BED.area_m2)
        * (bed.dp_bar / DEFAULT_DP_BAR)
        * (_REFERENCE_BED.depth_m / bed.depth_m)
    )
    return REFERENCE_FLOW_GPS * k_eff_ratio * geometry


def extraction_yield_pct(d_um: float, contact_s: float, f_channel: float) -> float:
    """First-order extraction kinetics, discounted by the bypassed fraction.

    EY = EY_max * (1 - exp(-k * t / d)) * (1 - f)
    """
    if contact_s <= 0:
        return 0.0
    extracted = 1.0 - math.exp(-EY_RATE_UM_PER_S * contact_s / d_um)
    return EY_MAX_PCT * extracted * (1.0 - f_channel)


def taste_from_ey(ey_pct: float) -> TasteAxis:
    """Crude EY -> taste mapping, banded around the SCA 18-22% window.

    Fixture only. Real tasting does not decompose this cleanly -- see
    docs/science.md#taste-mapping -- and nothing in production may rely on it.
    """
    if ey_pct < 16.0:
        return "very_sour"
    if ey_pct < 18.5:
        return "sour"
    if ey_pct <= 21.5:
        return "balanced"
    if ey_pct <= 23.5:
        return "bitter"
    return "very_bitter"


def simulate_shot(
    clicks: float,
    caps: GrinderCaps,
    bed: BedParams,
    target_yield_g: float,
    d0_um: float = 300.0,
    c0_clicks: float = 33.0,
) -> SimShot:
    """Pull a simulated shot at a given grind setting."""
    d_um = particle_diameter_um(clicks, caps, d0_um, c0_clicks)
    f = channel_fraction(d_um)
    flow = mass_flow_gps(d_um, bed, f)
    time_s = target_yield_g / flow if flow > 0 else float("inf")
    ey = extraction_yield_pct(d_um, time_s, f)
    return SimShot(
        clicks=clicks,
        particle_um=d_um,
        time_s=time_s,
        yield_g=target_yield_g,
        ey_pct=ey,
        channel_fraction=f,
        taste_axis=taste_from_ey(ey),
    )
