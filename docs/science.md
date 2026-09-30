# The science behind the recommendations

Every number the engine uses is declared in `src/core/brewing.py::CONSTANTS`
with an `anchor` pointing at a heading here. `tests/test_science_doc.py` fails
the build if a constant cites a missing heading, or a heading has no constant
(narrative sections are allow-listed). No magic number survives review without
a source or an explicit admission that it is a guess.

| kind | means |
| --- | --- |
| `PHYSICS` | derived from a physical law; its *applicability* may still be in question |
| `LITERATURE` | a published measurement or an established industry standard, cited below |
| `CALIBRATED` | a reference value chosen to make a model fit; defensible, not universal |
| `HEURISTIC` | our own judgement, no source; change freely if the data disagrees |

Citations are short-form, e.g. (Cameron 2020); full entries are in §9. Peer-
reviewed papers and practitioner sources are listed separately there, so it is
visible which `LITERATURE` claims rest on which.

---

## 1. Scope and honest limits {#limits}

The app has **no refractometer**. It records dose, beverage/water mass, time, a
taste axis and (optionally) temperature and pre-infusion.

**Cannot be computed:**

- **Extraction yield.** `EY% = beverage_g × TDS% / dose_g` needs TDS. The app
  must **never print an EY figure** or place a shot on the 18–22% scale
  ([#ey-formula](#ey-formula)).
- **Strength versus extraction, separated.** TDS and EY are independent axes,
  and taste alone cannot decompose them — the sensory panels in
  [#taste-mapping](#taste-mapping) show sour, bitter and astringent all rising
  with *strength* as well as with extraction. Fixing the measured ratio before
  the inferred grind is a pragmatic ordering, not a measurement.
- **Which side of the extraction peak a shot is on**, directly. The peak lives
  on an EY axis; the engine infers it from proxies ([#cameron](#cameron)).

**Unobservable, because the app does not record it:**

- **Puck preparation** — distribution, WDT, basket wear, clumping. This
  dominates channeling variance, and a shot that ran long from poor prep is
  indistinguishable from one ground too fine. **The single largest error
  source; better maths cannot fix it.**
- **Static and clumping at the grinder.** Charge depends on the bean's internal
  moisture and roast, and a drop of water on the beans (RDT) suppresses both
  charge and clumping, letting the bed pack denser and changing espresso flow
  (Harper 2024). Whether a user sprays their beans shifts the whole curve.
- **Fines fraction.** Adding particles below 100 µm lowers bed permeability and
  lengthens the shot at an unchanged grind setting (Smrke 2024) — so burr wear,
  alignment and grinder model move `α` in ways the dial number hides.
- **Water chemistry.** Na⁺, Mg²⁺ and Ca²⁺ bind flavour acids and change both
  rate and composition of extraction; Mg-rich water extracts most (Hendon 2014).
  A change of water is a change of recipe the app cannot see.
- **Actual brew temperature** without a PID or Scace: `brew_temp_c` is what the
  user set or believes.
- **Pour schedule and agitation** (pour-over) and **stove power** (moka) — the
  dominant levers for those methods, hence their confidence caps
  ([#method-levers](#method-levers)).
- **Grinder retention and burr drift** — the same click means slightly different
  things months apart.

What the engine can honestly say: *given your grinder, your machine and what
you measured, here is the setting that should land your time and ratio in the
target band.*

**Dose bounds.** With a basket size recorded, the dose is held to 75–105% of
it; without one, an espresso dose is held to 12–22 g (single to triple
baskets). Pour-over and moka get no default bound. A clamped dose scales the
yield or water with it, so the ratio survives.

---

## 2. Physics {#physics}

### 2.1 Darcy's law {#darcy}

```text
Q = k · A · ΔP / (µ · L)
```

`Q` flow, `k` permeability, `A` bed area, `ΔP` pressure drop, `µ` viscosity,
`L` bed depth. Measured coffee-bed permeabilities are of order
10⁻¹³–10⁻¹⁴ m² (Corrochano 2015).

**Darcy holds only at low pressure.** Brewing 60 shots at 11 basket pressures
from ~1 to 12 bar, Waszkiewicz 2026 found flow linear in pressure below
**~5 bar** and **saturating** above it — at the working pressure of an espresso
machine, more pressure buys little or no more flow, and past a threshold the
flow fell again. Their explanation is poroelastic: the pressure gradient
compacts the bed, cutting its permeability. The grind law below uses Darcy only
at fixed pressure and only for its local slope, which this does not break; it
does break any claim that time scales with pressure (see
[#target-reachability](#target-reachability)).

### 2.2 Kozeny–Carman, and where it breaks {#kozeny}

```text
k = d² · ε³ / (180 · (1 − ε)²)
```

for particle diameter `d` and porosity `ε`: **`k ∝ d²`** at fixed packing.

Coffee is not the monodisperse bed Kozeny–Carman assumes. Grounds are bimodal —
fines around 50 µm alongside 100–200 µm "boulders" (Waszkiewicz 2026) — and
X-ray micro-tomography of real pucks at eleven grind settings is better fitted
by a percolation model built on pore fraction and specific surface area than by
a single diameter (Wadsworth 2026). Fines alone measurably cut permeability at
an unchanged grinder setting (Smrke 2024).

So `k ∝ d²` is used only for the **local slope** of the grind law — a
linearisation around the current setting — never for absolute prediction, and
the fitted `β` replaces it as data arrives. The regime where it fails worst is
the clogged, channeling regime, which [#cameron](#cameron) hands to a separate
guardrail.

### 2.3 Normalised shot time {#normalised-time}

```text
T_r = time_s / brew_ratio
```

Shot time is not comparable across ratios; `T_r` is. 18 g → 36 g in 28 s gives
`R = 2.0`, `T_r = 14.0`.

### 2.4 The grind law {#beta-law}

2.1–2.3 at fixed dose, geometry and pressure give `T_r ∝ d⁻²`. With a linear
dial (`d = d₀ + u·(c − c₀)`, `u` µm per click):

```text
ln T_r = α_setup + δ_bean + β_setup · c        β = −2u / d_ref
```

`α` is the setup's intercept, `δ_bean` a per-bean offset; both are fitted. `β`
starts from the prior in [#beta-prior](#beta-prior) and shrinks toward the
fitted value as data arrives ([#shrinkage](#shrinkage)). Cameron 2020 found shot
time linear in the inverse grind setting at R² = 0.995, so a single slope is a
fair description across the working range.

**Shots on this coffee** — the law is used in **differential** form, anchored
on this coffee's most recent shot:

```text
c* = c + (ln T_r_target − ln T_r_observed) / β
```

`α` and `δ_bean` cancel. The anchor must be the *same* coffee: `δ_bean` says
precisely that another bag's `c` and `T_r` are not on this curve, and dose,
temperature, ratio and taste are read off the anchor too. The anti-channeling
floor ([#cameron](#cameron)) has the same restriction.

**Fitting `β`.** `β` is a property of the grinder, so it is fitted across every
bag on the setup — but by pooling each coffee's *own* pairs into one Theil–Sen
median, never by pairing one coffee against another. A cross-bean pair's rise is
`β·Δc + (δ_a − δ_b)`; on the reference history, pairing across bags would have
dragged the median from −0.150 to −0.050, a correction three times too large.
With no same-coffee pair at two settings, there is no fit and `β` stays at the
prior.

**No shots on this coffee** — the law is solved in **absolute** form:

```text
c = (ln T_r_target − α − δ̂_bean) / β
```

`δ̂_bean` is borrowed from similar coffees on this setup
([#similarity](#similarity)), or 0 (the setup's average bean) if none is
similar enough. With no fitted `α` at all — a new grinder, or moka — the engine
falls back to [#cold-start](#cold-start).

**Dose.** For espresso the law also carries a dose term, `+ γ·ln D`, where
`D` is the bed depth; see [#dose-term](#dose-term). On the reference history
one coffee was always dosed 18 g and the other almost always 16 g, so dose and
bean looked confounded — but the darker coffee is dosed lighter *because* a
dark roast is less dense, and the two fill the basket to about the same depth.
So dose explains none of the gap between their offsets; the darker coffee runs
slower at a given setting because of its roast, which is what `δ_bean` is for.
That is why the term measures **depth**, not grams.

### 2.5 Extraction yield {#ey-formula}

```text
EY% = (beverage_g × TDS%) / dose_g
```

Documented for the day a refractometer appears. **Not computable here.**

### 2.6 The dose term {#dose-term}

For espresso:

```text
ln T_r = α_setup + δ_bean + β_setup · c + γ · ln D + ln fill(roast)
D = dose / (18 g × fill(roast))
```

`D` is the **bed depth** relative to a full reference basket. Darcy's `L` is a
depth and grams only a proxy for it: a darker roast has expanded more and is
less dense (Schenker 2000), so the same depth weighs less. `fill(roast)` is the
starting-dose table ([#starting-dose](#starting-dose)): 1.03 light, 0.97
medium, 0.94 medium-dark, 0.92 dark, 1 when unknown. A light coffee at 18.5 g
and a dark one at 16.5 g are the same bed. Within one coffee `D` is simply
proportional to grams, so the fit of `γ` is unaffected; the roast correction
matters wherever coffees are compared — bean offsets, the solve for a new
coffee, the fit chart.

**Why `ln fill(roast)` too.** `T_r = t / R` and `t = beverage / Q`, so
`T_r = dose / Q`: at a fixed ratio a smaller dose is a smaller drink, which
takes less time even at the same depth. That factor is kinematics, exponent 1.
Depth enters through Darcy's `Q`. Within one coffee both scale with grams (total
`γ = 2`); across roasts only the depth part is density-corrected, and the
drink-size part leaves `ln fill(roast)`, a per-coffee constant that cancels
whenever two shots of one coffee are compared.

**Why γ = 2.** Bed depth is proportional to dose (Cameron 2020). At fixed
pressure Darcy gives `Q ∝ 1/L ∝ 1/dose`; the beverage at a fixed ratio is
`R · dose`, so `t ∝ R · dose²` and `T_r ∝ dose²`. The prior is `γ = 2`
(`dose_exponent_prior`, `PHYSICS`): 18 g → 19 g at the same setting and ratio
should slow the shot ~11%, about 3 s on 28 s. **Caveat:** the bed is
poroelastic (Waszkiewicz 2026, [#darcy](#darcy)); a deeper bed sees a gentler
pressure gradient and compacts less, which would make the fitted `γ` come out
somewhat below 2. That is what shrinkage toward data is for.

**Why only espresso.** The derivation needs a fixed pressure drop. Pour-over
drawdown is driven by the pour, and moka has no grind law, so `γ = 0` there:
a requested dose is honoured, but the grind is solved at the last shot's dose
and the recipe says so.

**How it is fitted.** Like `β`, shrunk toward the data:
`γ = w·γ_fitted + (1 − w)·γ_prior`, `w = n/(n + κ_dose)`, `n` counting dose
pairs ([#dose-fit](#dose-fit)). A dose pair is two shots of one coffee,
prepared the same way (the same rules as `β`'s pairs), doses at least
`dose_pair_min_diff_g` apart; its grind difference is removed with `β` first,
`(Δ ln T_r − β·Δc) / Δ ln dose`, and `γ_fitted` is their median. A fit at or
below zero is discarded — no bed runs faster when deeper. `β`'s pairs take the
dose effect out in the same way, and the two are fitted in one round (`β` with
the prior `γ`, `γ` given that `β`, `β` again); they are nearly orthogonal unless
dose and grind always moved together, when no iteration could separate them.

**Where it acts.** The differential correction carries the anchor to the new
dose before comparing it with the target,
`T_r' = T_r · (dose_new / dose_anchor)^γ`, so a heavier dose moves the grind
coarser by what it should do to the time. The absolute solve subtracts
`γ·ln D`; `α` is quoted at a full reference basket.

**Measured on the reference history (2026-09-23).** 15 measured shots and no
dose pair yet, so `γ` is the prior. The two coffees' usual doses sit at nearly
the same depth (`ln D` −0.03 and −0.06). Leave-one-out prediction of `ln T_r`
gives a mean absolute error of **0.260 with no dose term and 0.244 with
γ = 2**; with the term, the darker coffee runs about 1.4× slower than the
lighter at the same setting and depth — the roast.

---

## 3. Literature constants {#literature}

### 3.1 Extraction and strength bands {#sca-bands}

EY **18–22%** is the classic target band, from Lockhart's Coffee Brewing
Institute work in the 1950s, retained by the SCA; espresso TDS runs **8–12%**.

The ratio claim is now peer-reviewed: in full-immersion brewing, **TDS is
approximately inversely proportional to the brew ratio while EY is independent
of it**, holding near 21% across a wide range of ratios (Liang 2021). For
espresso, Schmieder 2023 found brew ratio dominating flow rate, grind and
temperature in how much of each compound reached the cup. Ratio is therefore a
strength lever first and an extraction lever second.

The band itself is a convention, not an optimum. Sensory and consumer work on
drip coffee finds preferences **split into clusters** — one preferring low TDS at
medium extraction, another medium TDS at low *or* high extraction — rather than
converging on one box (Guinard 2023).

### 3.2 Espresso ratio, time and temperature {#ratio-espresso}

Normale **1:2** (band 1:1.8–1:2.5), **25–30 s**, **90.5–96 °C**.

**The time band is a taste convention, not a physical optimum.** Cameron 2020
argue that the SCA's 20–30 s mandate may be *why* most coffee is brewed at
partially clogged settings, and their own reproducibility route
([#cameron-reproducibility](#cameron-reproducibility)) produces shots under
15 s. Smrke 2024 measured the trade: shots under 15 s still reached 17–18% EY,
over 80% of the maximum, while the best sensory scores sat near 30 s at 19–20%.
So a fast shot that tastes balanced is a valid operating point, and an engine
that treats 25 s as a hard target will drive every coffee finer into the
clogged regime ([#target-reachability](#target-reachability)).

On temperature, Andueza 2003 found **92 °C optimal for arabica** espresso (of
88/92/96/98 °C), with 88 °C preferred for a dark torrefacto robusta blend.

### 3.3 Pressure, and whether the band is reachable {#target-reachability}

Pressure sets the whole curve (`α`), not its slope. It also sets the clogging
onset: Cameron 2020 could not use fine settings at 9 bar at all, and dropped to
**6 bar** to open up the grind range.

But more pressure is **not** proportionally more flow. Above ~5 bar flow
saturates (Waszkiewicz 2026, [#darcy](#darcy)), and sensory work places the
optimum around the standard pressure rather than above it: of 7, 9 and 11 atm,
**11 atm gave the worst espresso** (Andueza 2002). So on a fixed, unregulated
machine the time band may simply be unreachable, and turning up the pressure is
not the fix. The honest output is to say so, rather than to keep recommending
finer.

### 3.4 Ristretto {#ratio-ristretto}

**1:1–1:1.5**, aim 1:1.25, 20–28 s. Same temperature band.

### 3.5 Lungo {#ratio-lungo}

**1:2.5–1:3**, aim 1:2.75, 28–36 s. Same temperature band.

### 3.6 Pour-over, V60 {#ratio-pourover}

**1:16** (≈60 g/L), band 1:15–1:17; water **92–96 °C**; drawdown **2:45–3:15**
for a ~15 g single; medium-fine, ~600–800 µm. These are practitioner figures
(§9.2). Liang 2021 supports ratio as the strength lever; Batali 2020 found brew
temperature from 87 to 93 °C made practically no sensory difference once TDS and
EY were held fixed — so the 92–96 °C floor is convention, not requirement.

The dominant levers — pour schedule, agitation, bloom — are not recorded. See
[#method-levers](#method-levers).

### 3.7 Moka pot {#ratio-moka}

Ratio **1:7–1:10** (aim 1:8), grind **360–660 µm**, steam pressure **1–2 bar**,
water **90–96 °C**, and beyond **~8 minutes** the pot is treated as choked.

Measured on a three-cup moka (150 g water, 15 g coffee — 1:10), the water in the
kettle starts flowing at **~69–70 °C** and ends at **117–121 °C**, averaging
**94–98 °C** depending on stove power; the extract leaves the bed much cooler,
averaging **~79–81 °C** (Navarini 2009). The bed's permeability falls during the
brew, stove power exceeds what the last of the water needs so flow accelerates
at the end, and the final sputtering "strombolian" phase extracts the harshest
compounds — the hotter and higher-pressure, the more. So the moka band describes
the *water*, not what the coffee sees, and cutting the heat early matters more
than any grind change.

Brew time is set by heat input, not bed permeability, so the engine does not
solve grind from time for moka.

### 3.8 Degassing {#degassing}

Coffee released **5–14 days** post-roast is the commonly cited window
(practitioner). The kinetics are peer-reviewed: whole-bean CO₂ release fits two
first-order components with time constants of **~38 h and ~183 h** (1.6 and 7.6
days), the slow one carrying ~80% of the gas; release was still measurable at
800 h. On grinding, **up to 75% of the trapped gas escapes within 90 s**
(Smrke 2018). Light-to-medium roasts release more CO₂ as roast darkens; darker
roasts trap more but release no more on grinding.

That CO₂ is what makes fresh coffee flow fast and erratically and raises the
channeling risk. The ~7.6-day time constant is consistent with a ~7-day rest;
the magnitudes we apply to fresh coffee are heuristic ([#fresh-band](#fresh-band)).

### 3.9 The extraction peak is not monotonic {#cameron}

Cameron 2020 is the load-bearing citation. A homogeneous-flow model predicts
EY rising monotonically as grind fines; experiment shows it **peak and then
fall** at fine settings, because flow becomes inhomogeneous. At grind settings
1.5, 1.3 and 1.1 measured yield fell **2.6%, 6.1% and 13.1%** below the
homogeneous prediction. The peak is independently reproduced: Schmieder 2023
found extraction at the finest of three grinds *below* the medium one.

The mechanism now has a model. Lee 2023 reproduce the peak with two parallel
flow paths: dissolution raises the faster path's porosity, which raises its
flow, which speeds its dissolution — **a positive feedback present at every
grind size**. The peak is where the fast path runs out of solubles and can no
longer compensate. Their conclusion for taste: *average EY may be a poor guide at
fine grinds*, because the cup is a blend of over- and under-extracted coffee.

Consequences for the engine:

- **"The shot ran long, grind finer" is wrong past the peak.** The engine
  refuses to cross an empirically detected floor. The onset is
  device-specific (below ~1.7 on Cameron's dial), so it is detected from the
  user's data, not hardcoded.
- **Shot time does not turn over.** Cameron's shot time stayed linear in grind
  across both regimes (R² = 0.995). A time plateau is *not* a literature
  signature of channeling ([#channeling-detection](#channeling-detection)). The
  signatures that are: falling EY while time rises (needs a refractometer), and
  a cup that is **sour and bitter at once**.
- **Tamping is not a lever.** Cameron varied tamp force and saw no appreciable
  change in time or yield; Kuhn 2017 likewise found **no detectable effect of
  tamping pressure** on extraction kinetics, while particle size mattered
  strongly.

### 3.10 The reproducibility recipe {#cameron-reproducibility}

Cameron 2020's affirmative recommendation: **less coffee, ground coarser** —
20 g → 15 g, up to 25% less — which raised EY *and* shot-to-shot
reproducibility, validated over **27,850 beverages** in a roastery. Lower bed
depth cuts the pressure drop and so the channeling of [#cameron](#cameron).
Khamitova 2020 reach the same direction from chemistry: finer particles in a
redesigned basket kept the extracted bioactive compounds up while using less
ground coffee (abstract only).

The engine offers this as a suggestion beside the recipe, never folded into
it; when, is in [#dose-reduction](#dose-reduction).

### 3.11 Temperature by roast level {#temp-by-roast}

Convention within the espresso band: light **94–96 °C**, medium **92–94 °C**,
dark **90.5–92.5 °C**. Band edges are practitioner convention; the split points
are our interpolation. The only direct espresso evidence is Andueza 2003 (92 °C
best for arabica, 88 °C for a dark torrefacto blend), which agrees in direction.

**The effect is smaller than the convention implies.** Schmieder 2023 found **no
measurable influence** of water temperature from 80 to 98 °C on the mass of
caffeine, trigonelline, 5-CQA or TDS in an espresso, alone — only an interaction
that strengthened the flow-rate effect at fine grind and high temperature. For
drip, Batali 2020 held TDS and EY fixed and found 87, 90 and 93 °C sensorially
indistinguishable (one attribute moved by one point on a 100-point scale).
Temperature matters mostly *through* extraction, and grind and ratio move
extraction far more. Hence the engine treats temperature as a covariate and a
last-resort lever ([#temp-covariate](#temp-covariate)).

### 3.12 Sour/bitter is not a reliable extraction readout {#taste-mapping}

"Sour means under-extracted, bitter means over-extracted" is the industry
default and is **not** dependable:

- Dark roasts taste bitter at *correct* extraction — roast character.
- Channeling produces shots that are **sour and bitter at once**, because some
  coffee is over-extracted while bypassed coffee barely is (Lee 2023).
- **Strength confounds it.** In descriptive panels, bitter, sour and astringent
  all rose with TDS, and TDS had the larger sensory effect than extraction
  (Batali 2020; Frost 2020). Guinard 2023 do place sour/fruit at high TDS and
  low EY, and bitter/astringent/roasted at high TDS and high EY — a real but
  two-dimensional mapping that one taste axis cannot represent.

**Astringency** — a drying, tactile sensation distinct from bitter taste — is
the more specific over-extraction marker. Hence the separate `astringent` flag,
and the rule that *bitter without astringency does not move the grind*.

---

## 4. Calibrated priors {#calibrated}

### 4.1 Reference particle diameter and β {#beta-prior}

`β = −2u / d_ref` ([#beta-law](#beta-law)) needs a reference diameter:
`d_ref = 300 µm` for espresso and `700 µm` for pour-over, mid-range values
consistent with §3. **Calibrated**, not measured: they set the scale of the
correction, and the fitted `β` supersedes them. (Real grounds are bimodal —
[#kozeny](#kozeny) — so `d_ref` is an effective diameter, not a median.)

For `u = 16 µm/click` this gives `β ≈ −0.107` per click, roughly a **10% change
in shot time per click**. Where `u` is unknown, `β_prior = −0.06`, confidence is
capped low, and the prior variance widened.

### 4.2 Locating the dial on an unmeasured grinder {#cold-start}

With no measured shot there is no `α`. Most hand grinders are zeroed at burr
contact, so the dial reads roughly linearly in particle size:

```text
clicks ≈ d / (µm per click)
```

For 16 µm/click, espresso's 300 µm lands at ~19 clicks — inside published
espresso ranges for such grinders, and derived rather than guessed. The
midpoint of the hardware range is *not* a safe default: on a K6 (0–180) it is
90 clicks, ~1.4 mm, French-press territory.

**Assumption:** zero is burr contact and the scale is linear. True for zero-set
hand grinders; not for stepped electric grinders with an arbitrary origin. With
`µm per click` unknown, the engine abstains (tier E).

### 4.3 Kingrinder K6 {#k6-caps}

**60 clicks per rotation, 16 µm per click.** Published *espresso* ranges for
this grinder disagree wildly (manufacturer ~15–25; reviews 22–45 and 30–60) —
the argument for storing capability per unit with a `spec_source`, not
hardcoding a range.

---

## 5. Heuristics — our own judgement, no source {#heuristics}

### 5.1 Shrinkage constants {#shrinkage}

`w = n_eff / (n_eff + κ)` with `κ = 4.0` espresso, `8.0` pour-over,
`κ_bean = 2.0` for the per-bean offset. `n_eff` counts **distinct grind
settings**, not shots: ten shots at one setting carry no slope information.
About four distinct settings gets you halfway from prior to fitted. Pure guess.

### 5.2 Similarity weights {#similarity}

Roast level 0.25, process 0.15, origin 0.10 (half for the same region),
freshness 0.10 — a ceiling of 0.60. Used only to choose which of a setup's
coffees a new one borrows `δ̂_bean` from ([#beta-law](#beta-law)).

**The bean terms have weak support.** Particle size distribution is
**independent of origin and processing method**; roast level and grinding
temperature did matter (Uman 2016). Roast also sets internal moisture and so
static and clumping (Harper 2024), and bean volume and porosity (Schenker 2000).
So roast is the defensible term; origin and process are *taste* neighbours with
no published basis as predictors of how a coffee grinds.

**Bean-offset floor 0.25.** Below it, borrowing an offset is worse than
assuming the setup's average bean. Against the 0.60 ceiling, 0.25 asks for
roughly a close roast match plus one of process or origin. Pure guess.

### 5.3 Roast-level time modifier {#roast-time-modifier}

±1 s on the target `T_r`: lighter roasts a touch longer, darker shorter. Nearly
cosmetic; retained because it matches common practice.

### 5.4 Fresh-coffee band widening {#fresh-band}

Under 7 days off roast, acceptance bands are doubled and corrections halved, and
the user is told the target is moving. The 7 days sits near the slow degassing
time constant ([#degassing](#degassing)); the factors are guesses.

### 5.5 Pre-infusion and the rest before the pull {#preinfusion}

Pre-infusion wets the puck at low pressure so it swells and settles before full
pressure; the pause lets water distribute by capillarity and CO₂ escape. Both
aim at a uniformly saturated bed — the standard mitigation for channeling.

The mechanism is supported: on a full-pressure shot the wetting front takes
**~5–10 s** to penetrate the bed and expel air, with the bed swelling as it goes,
before flow settles (Waszkiewicz 2026); and simulations show grain swelling
slightly slows the extraction rate but raises strength considerably at fixed
time or volume (Mo 2022). **No peer-reviewed study we found measures
pre-infusion's effect on espresso yield or channeling** — the magnitudes below
are ours.

**Excluded from `T_r`.** The grind law is Darcy, i.e. *pressurised* flow, so
`T_r` must be the pressurised pull only; folding pre-infusion into it would put
a non-Darcy phase inside a Darcy model and corrupt `β`.

**Still recorded.** A longer pre-infusion reaches full pressure with a wet bed
and pulls *faster*; unrecorded, that reads as a coarser grind — and a finer shot
that ran faster is trigger 1 of [#channeling-detection](#channeling-detection),
so it can **fake the channeling signature**. Pairs whose pre-infusion or pause
differ by more than `prep_tolerance_s` are excluded from the Theil–Sen slope and
from channeling detection (one pairwise term dropped, nothing else changes).

**Time to first pressure** is a second resistance reading, taken before the
shot runs. Grind moves it and the pull time together; when they disagree by
more than `resistance_disagreement_ratio`, the bed changed after wetting — prep
or channeling rather than the grinder.

**Fineness relief.** Where pre-infusion is consistent and long enough to matter,
the channeling floor is relaxed by `preinfusion_channeling_relief` of a grinder
step. An inconsistent routine gets no relief.

**Advice is gated.** Below `min_shots_for_prep_advice`, or with only one
pre-infusion duration recorded, the engine reports the user's own routine and
says keeping it constant makes the grind evidence readable. It does not propose
an optimum it has not measured.

### 5.6 Brew temperature as a covariate {#temp-covariate}

Hotter water is less viscous and extracts faster, so two shots at different
temperatures are not clean evidence about the grinder. Shots whose recorded
temperatures differ by more than `temp_tolerance_c` are excluded from each
other's pairwise comparison in the slope fit and channeling detection; an
unknown temperature on either side counts as comparable.

The tolerance is deliberately loose, for two reasons: on a machine without a PID
the recorded figure is a belief, not a measurement ([#limits](#limits)); and the
measured effect is small — no detectable change in extracted mass over 80–98 °C
for espresso alone (Schmieder 2023; see [#temp-by-roast](#temp-by-roast)).

Temperature becomes a *lever* only when the machine is marked
temperature-controllable; advising a change the user cannot make is noise.

### 5.7 Channeling detection thresholds {#channeling-detection}

Variance ratio 2.0 between fine and coarse subsets (n ≥ 6 before it may fire);
never more than 2 steps finer than the finest historically acceptable setting;
maximum single move 25% of |1/β|. Tuned to fail safe: refusing to go finer costs
one extra iteration, chasing the channeling regime costs coffee and an
undiagnosable shot.

**Known weakness.** The trigger "a finer setting ran no slower, so water is
channeling" is *our* inference. The literature points the other way: shot time
stays monotonic in grind through the clogged regime (Cameron 2020), and uneven
flow is present at every grind, turning over only in EY (Lee 2023) — which we
cannot see.

At realistic sample sizes it also cannot tell a plateau from noise. On the
reference history (10 shots) the pooled within-setting spread of `ln T_r` was
**0.395** — one bean gave `T_r` 4.17 and 10.11 at the same setting — against
**0.084–0.168 per click**, so one shot carries **2.4–4.7 clicks** of noise. The
floor fired on both beans and pinned the recommendation, while the prose said
"go finer". A detector with no noise model fails safe *always*. Treat the floor
as a soft warning, and see [#deadband](#deadband).

### 5.8 The deadband: when not to change anything {#deadband}

There is currently **no deadband**: the engine will name a new click for a
difference far below what one shot resolves. No study we found reports a
shot-time standard deviation directly; four anchors bound it:

- Cameron 2020 needed **pentaplicate** points (n = 5; n = 20 for calibration)
  under tight control — ±0.5 g dose, ±1 g beverage, fixed 92 °C, automated
  tamping to ±3 N.
- Kuhn 2017 and Schmieder 2023 ran triplicates on instrumented rigs.
- The Espresso Protocol, a professional sensory standard, tolerates
  **25 s ± 3 s** as "the same shot" (Espresso Protocol 2025) — an accepted band,
  not a measured sigma.
- Practitioners report ±3–5 s at a fixed setting; our reference history gives
  2.4–4.7 clicks (above).

Any threshold built on these is `HEURISTIC`. The defensible shape: require the
solved move to exceed the observed within-setting spread, otherwise say "pull
the same shot again" — which also buys the replicate the estimate needs.

### 5.9 Starting dose by roast level {#starting-dose}

A coffee with no shots needs a first dose. Roasting expands the bean and opens
its pores — up to ~80% volume increase, more at higher roast temperature
(Schenker 2000; Smrke 2018) — so the same basket holds less mass of a more
expanded bean. The engine starts from a **fill of the basket** by roast:

| Roast | Fill | On an 18 g basket |
| --- | --- | --- |
| light, medium-light | 1.03 | 18.5 g |
| medium | 0.97 | 17.5 g |
| medium-dark | 0.94 | 17 g |
| dark | 0.92 | 16.5 g |

The basket is the recorded `basket_size_g`, or an 18 g reference. Rounded to
half a gram. The fills are practitioner midpoints (dark ~16–17 g, light
~18–19 g in an 18 g basket), not measurements, hence `HEURISTIC`: the direction
is supported, the numbers are not. The basket guardrail
([#limits](#limits)) still applies, and the user's own dose takes over from the
first logged shot. The same fills convert grams to bed depth in the dose term
([#dose-term](#dose-term)).

### 5.10 Fitting the dose term {#dose-fit}

Three choices in [#dose-term](#dose-term) are ours, not physics:

- `kappa_dose = 4` dose pairs — the weight `κ_espresso` gives distinct settings
  for `β`. A handful of pairs should move `γ`, not define it.
- `dose_pair_min_diff_g = 0.5` g — below this, two doses differ by less than an
  ordinary scale-and-basket repeat, so the pair measures noise.
- `dose_reference_g = 18` g — the basket `α` is quoted at, scaled by the roast's
  fill. A centring choice that changes no prediction.

### 5.11 When to suggest less coffee {#dose-reduction}

The engine offers [#cameron-reproducibility](#cameron-reproducibility)'s move —
less coffee, coarser, the same drink — as a **suggestion beside the recipe**.
The shot it describes deliberately runs faster and at a longer ratio than the
recipe's bands; the point is extraction and repeatability, not the clock, and
the guardrails would undo it if it went through them. Every number is still the
engine's. It is offered only when all of these hold:

- **Espresso**, and the **channeling floor has taken the grind lever away**
  (`grind_channeling_floor`). Before that, grinding is the simpler fix.
- **This coffee has channeled repeatedly at this dose**: at least
  `cameron_min_channeled_shots = 2` of its shots within `dose_pair_min_diff_g`
  of the recipe's dose show a channeling sign by the floor's own triggers. Two,
  because one bad puck is not a pattern; one dose, because that keeps the
  comparisons safe without a dose correction.
- **No markedly lighter dose has been tried** on this coffee yet (half the
  reduction or more). After that its own shots are the evidence.
- **The pre-infusion experiment is not running.** One lever at a time.

The suggestion is `cameron_dose_reduction = 20%` less coffee, rounded to half a
gram and never below the basket's fill floor, with the drink the same size and
the grind one step coarser than the floor. Cameron 2020 went 25% on commercial
baskets; home baskets are sized closer to their nominal dose, so this starts at
the conservative end. One step coarser is a direction, not a solved number.

---

## 6. Method levers, and what we cannot see {#method-levers}

| | espresso | pour-over | moka |
| --- | --- | --- | --- |
| driving force | pump, ~9 bar | gravity, ~2 kPa | steam, 1–2 bar |
| ratio denominator | beverage out | water in | water in |
| grind ↔ time coupling | **strong** | moderate | **weak** |
| levers we can move | grind, dose, ratio, temp\* | grind, dose, ratio | grind, dose, ratio |
| levers we cannot see | puck prep, distribution, RDT, water | pour schedule, agitation, bloom, water | stove power, heat-cut timing, water |
| confidence cap | 1.0 | 0.6 | 0.4 |

\* temperature only when the machine reports it as controllable.

Espresso is the only method where the physics model is load-bearing. For moka
the grind law is disabled outright (`β_prior = None`), because its flow is set
by a rising steam pressure and a bed whose permeability falls during the brew
(Navarini 2009).

---

## 7. The simulator {#simulator}

`tests/_sim.py` implements Darcy + Kozeny–Carman plus a logistic bypass term, so
a fraction of flow short-circuits through a low-resistance channel as particle
size falls below an onset diameter. It reproduces the non-monotonic yield curve
of [#cameron](#cameron) — the same two-path picture Lee 2023 analyse — so the
correction policy can be tested before any real shots exist. It is a **test
fixture only**; its taste mapping is crude, which is why it lives under
`tests/`.

---

## 8. Where the literature disagrees with the engine {#open-conflicts}

Findings above that argue for a change we have not made. The `#` column is the
entry in `docs/open-decisions.md`.

| Finding | Engine today | Implication | # |
| --- | --- | --- | --- |
| Brew temperature has little direct effect at fixed extraction (Schmieder 2023; Batali 2020) | Roast-level temperature split (`temp_*`) as a `LITERATURE` recommendation | Keep as a starting point, but relabel its authority and prefer grind/ratio corrections before ever moving temperature | 11 |
| Flow saturates with pressure above ~5 bar (Waszkiewicz 2026) | Doc previously said time falls inversely with pressure | Doc corrected; never advise more pressure to shorten a shot | — |
| Uneven flow exists at all grinds; time is not a channeling signature (Lee 2023; Cameron 2020) | Time-plateau trigger in channeling detection | Replace with a noise-aware test, or demote to a warning | 12 |
| Dose sets bed depth and so time (Cameron 2020) | Built: `γ·ln D` ([#dose-term](#dose-term)) | Resolved | 5 |
| Less coffee, coarser, is more reproducible (Cameron 2020; Khamitova 2020) | Built: a suggestion ([#dose-reduction](#dose-reduction)) | Resolved | 6 |
| Moka extract averages ~80 °C; the final phase extracts harsh compounds (Navarini 2009) | `moka_temp` 90–96 °C | Describe as water temperature; advise cutting the heat before sputtering | 13 |

---

## 9. Bibliography

### 9.1 Peer-reviewed

- **Andueza 2002** — Andueza, S. et al. "Influence of water pressure on the
  final quality of arabica espresso coffee." *J. Agric. Food Chem.* 50(25),
  7426–7431. <https://doi.org/10.1021/jf0206623> — 7/9/11 atm; 11 atm worst.
- **Andueza 2003** — Andueza, S. et al. "Influence of extraction temperature on
  the final quality of espresso coffee." *J. Sci. Food Agric.* 83(3), 240–248.
  <https://doi.org/10.1002/jsfa.1304> — 88–98 °C; 92 °C best for arabica.
- **Batali 2020** — Batali, M. E., Ristenpart, W. D., Guinard, J.-X. "Brew
  temperature, at fixed brew strength and extraction, has little impact on the
  sensory profile of drip brew coffee." *Sci. Rep.* 10, 16450.
  <https://doi.org/10.1038/s41598-020-73341-4> — 87/90/93 °C indistinguishable
  at fixed TDS/EY; TDS drives bitter, sour, astringent.
- **Cameron 2020** — Cameron, M. I. et al. "Systematically improving espresso:
  insights from mathematical modeling and experiment." *Matter* 2(3), 631–648.
  <https://doi.org/10.1016/j.matt.2019.12.019> — non-monotonic EY; 2.6/6.1/13.1%
  yield loss at GS 1.5/1.3/1.1; time linear in grind at R² = 0.995 across both
  regimes; tamp force no effect; 9 bar clogged, study ran at 6 bar; bed depth ∝
  dose; 20 g → 15 g protocol over 27,850 beverages; critique of the 20–30 s
  mandate. Full text:
  <https://pages.uoregon.edu/chendon/publications/2020/74.%20Matter,%20Espresso%20extraction.pdf>
- **Corrochano 2015** — Corrochano, B. R., Melrose, J. R., Bentley, A. C.,
  Fryer, P. J., Bakalis, S. "A new methodology to estimate the steady-state
  permeability of roast and ground coffee in packed beds." *J. Food Eng.* 150,
  106–116. <https://doi.org/10.1016/j.jfoodeng.2014.11.006> — Darcy/Kozeny–Carman
  applied to coffee; measured permeabilities. (Not re-read for this revision.)
- **Frost 2020** — Frost, S. C., Ristenpart, W. D., Guinard, J.-X. "Effects of
  brew strength, brew yield, and roast on the sensory quality of drip brewed
  coffee." *J. Food Sci.* 85(8), 2530–2543.
  <https://doi.org/10.1111/1750-3841.15326> — TDS and EY map to distinct sensory
  attributes. (Abstract only.)
- **Guinard 2023** — Guinard, J.-X. et al. "A new Coffee Brewing Control Chart
  relating sensory properties and consumer liking to brew strength, extraction
  yield, and brew ratio." *J. Food Sci.* 88(5), 2168–2177.
  <https://doi.org/10.1111/1750-3841.16531> — sour/fruit at high TDS–low EY,
  bitter/astringent at high TDS–high EY; consumer liking splits into clusters.
- **Harper 2024** — Méndez Harper, J. et al. "Moisture-controlled
  triboelectrification during coffee grinding." *Matter* 7(1), 266–283.
  <https://doi.org/10.1016/j.matt.2023.11.005> — bean moisture and added water
  control static and clumping, and change espresso flow.
- **Hendon 2014** — Hendon, C. H., Colonna-Dashwood, L., Colonna-Dashwood, M.
  "The role of dissolved cations in coffee extraction." *J. Agric. Food Chem.*
  62(21), 4947–4950. <https://doi.org/10.1021/jf501687c> — Na⁺/Mg²⁺/Ca²⁺ change
  extraction; Mg-rich water extracts most.
- **Khamitova 2020** — Khamitova, G. et al. "Optimization of espresso coffee
  extraction through variation of particle sizes, perforated disk height and
  filter basket aimed at lowering the amount of ground coffee used." *Food
  Chem.* 314, 126220. <https://doi.org/10.1016/j.foodchem.2020.126220> — less
  coffee, finer, redesigned basket. (Abstract only.)
- **Kuhn 2017** — Kuhn, M., Lang, S., Bezold, F., Minceva, M., Briesen, H.
  "Time-resolved extraction of caffeine and trigonelline from finely-ground
  espresso coffee with varying particle sizes and tamping pressures." *J. Food
  Eng.* 206, 37–47. <https://doi.org/10.1016/j.jfoodeng.2017.03.002> — particle
  size matters; tamping pressure has no detectable effect.
- **Lee 2023** — Lee, W. T., Smith, A., Arshad, A. "Uneven extraction in coffee
  brewing." *Phys. Fluids* 35(5), 054110. <https://doi.org/10.1063/5.0138998>
  (preprint <https://arxiv.org/abs/2206.12373>) — two-path dissolution–flow
  feedback reproduces Cameron's peak; unevenness at all grinds; average EY a poor
  taste guide at fine grind.
- **Liang 2021** — Liang, J., Chan, K. C., Ristenpart, W. D. "An equilibrium
  desorption model for the strength and extraction yield of full immersion
  brewed coffee." *Sci. Rep.* 11, 6904.
  <https://doi.org/10.1038/s41598-021-85787-1> — TDS ∝ 1/ratio, EY ≈ 21%
  independent of ratio.
- **Mo 2022** — Mo, C., Navarini, L., Suggi Liverani, F., Ellero, M. "Modeling
  swelling effects during coffee extraction with smoothed particle
  hydrodynamics." *Phys. Fluids* 34(4), 043104.
  <https://doi.org/10.1063/5.0086897> — swelling slows extraction rate slightly,
  raises strength considerably. (Abstract only.)
- **Navarini 2009** — Navarini, L., Nobile, E., Pinto, F., Scheri, A.,
  Suggi-Liverani, F. "Experimental investigation of steam pressure coffee
  extraction in a stove-top coffee maker." *Appl. Therm. Eng.* 29(5–6),
  998–1004. <https://doi.org/10.1016/j.applthermaleng.2008.05.014> — moka water
  69 → 117–121 °C, extract ~80 °C mean; falling bed permeability; strombolian
  phase.
- **Schenker 2000** — Schenker, S., Handschin, S., Frey, B., Perren, R.,
  Escher, F. "Pore structure of coffee beans affected by roasting conditions."
  *J. Food Sci.* 65(3), 452–457.
  <https://doi.org/10.1111/j.1365-2621.2000.tb16026.x> — roasting raises bean
  volume and pore volume. (Abstract only.)
- **Schmieder 2023** — Schmieder, B. K. L., Pannusch, V. B., Vannieuwenhuyse,
  L., Briesen, H., Minceva, M. "Influence of flow rate, particle size, and
  temperature on espresso extraction kinetics." *Foods* 12(15), 2871.
  <https://doi.org/10.3390/foods12152871> — 20 g dose, 1–3 mL/s, 80–98 °C:
  ratio dominates; slower flow ~8% more extract; temperature alone no
  measurable effect; finest grind extracts less than medium.
- **Smrke 2018** — Smrke, S. et al. "Time-resolved gravimetric method to assess
  degassing of roasted coffee." *J. Agric. Food Chem.* 66(21), 5293–5300.
  <https://doi.org/10.1021/acs.jafc.7b03310> — whole-bean time constants ~38 h
  and ~183 h; up to 75% of gas lost within 90 s of grinding.
- **Smrke 2024** — Smrke, S., Eiermann, A., Yeretzian, C. "The role of fines in
  espresso extraction dynamics." *Sci. Rep.* 14, 5612.
  <https://doi.org/10.1038/s41598-024-55831-x> — fines cut permeability and
  lengthen shots; <15 s shots reach 17–18% EY; best sensory near 30 s at 19–20%.
- **Uman 2016** — Uman, E. et al. "The effect of bean origin and temperature on
  grinding roasted coffee." *Sci. Rep.* 6, 24483.
  <https://doi.org/10.1038/srep24483> — particle size distribution independent
  of origin and process; roast and grind temperature matter.
- **Wadsworth 2026** — Wadsworth, F. B. et al. "A model for the permeability of
  coffee pucks validated using X-ray computed micro-tomography." *R. Soc. Open
  Sci.* 13(4), 252031. <https://doi.org/10.1098/rsos.252031> — percolation model
  on pore fraction and specific surface area, validated on XCT of pucks at 11
  grind settings; Forchheimer number for inertial-flow onset. (Abstract only.)
- **Waszkiewicz 2026** — Waszkiewicz, R. et al. "Under pressure: poroelastic
  regulation of flow in espresso brewing." *Phys. Fluids* 38, 063113.
  (preprint <https://arxiv.org/abs/2512.21528>) — Darcy-linear below ~5 bar,
  saturating above; 5–10 s wetting phase; bimodal grounds.
- **Espresso Protocol 2025** — "Cross-cultural comparison of the Espresso
  Protocol repeatability."
  <https://pmc.ncbi.nlm.nih.gov/articles/PMC11854300/> — tolerance 25 s ± 3 s at
  9 bar, 92–94 °C, 15–17 g ± 1 g; no shot-time variance reported.

### 9.2 Practitioner and industry sources

These back the `LITERATURE` numbers no paper above fixes: the ristretto/lungo
bands, the V60 recipe, moka grind and ratio, the 5–14-day rest window, the
roast-level temperature split and the K6 spec.

- SCA Brewing Control Chart / Coffee Brewing Institute (Lockhart, 1950s) —
  <https://www.baristainstitute.com/blog/jori-korhonen/january-2019/how-measure-extraction-coffee>,
  <https://www.baristahustle.com/towards-a-common-coffee-control-chart/>
- Espresso brew ratios and basket sizes — Clive Coffee.
  <https://clivecoffee.com/blogs/learn/brew-ratios-basket-sizes-and-the-confusion-over-a-double-shot>
- Hario V60 brew guide — Stumptown.
  <https://www.stumptowncoffee.com/pages/brew-guide-hario-v60>
- Moka pot grind size — CoffeeGearHub.
  <https://www.coffeegearhub.com/moka-pot-grind-size/>
- Coffee degassing and the rest window — Podium Coffee Club.
  <https://podiumcoffeeclub.com/blogs/blog/coffee-degassing>
- KINGrinder K6: 60 clicks/rotation, 16 µm/click — Honest Coffee Guide.
  <https://honestcoffeeguide.com/kingrinder-k6-grind-settings/>
- Coffee extraction and how to taste it — Barista Hustle.
  <https://www.baristahustle.com/coffee-extraction-and-how-to-taste-it/>
