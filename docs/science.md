# The science behind the recommendations

Every number the engine uses is declared in `src/core/brewing.py::CONSTANTS`
and carries an `anchor` pointing at a heading in this file. `tests/test_science_doc.py`
fails the build if a constant cites a heading that doesn't exist, or if a
heading here has no constant referring to it. The point is that no magic
number survives review without a source or an explicit admission that it's
a guess.

Constants are labelled by kind:

| kind | means |
|---|---|
| `PHYSICS` | derived from a physical law; not up for debate, though its *applicability* may be |
| `LITERATURE` | published measurement or an established industry standard, cited below |
| `CALIBRATED` | a reference value chosen to make a model fit; defensible but not universal |
| `HEURISTIC` | our own judgement. No source. Change freely if the data disagrees |

---

## 1. Scope and honest limits {#limits}

This app has **no refractometer**. It records dose, beverage/water mass, time,
a taste axis, and (optionally) temperature. That bounds what can honestly be
claimed.

**Cannot be computed at all:**

- **Extraction yield.** `EY% = (beverage_g × TDS%) / dose_g` needs TDS, which
  needs a refractometer. Two of the three terms are known and the third is not,
  so the app must **never print an EY figure** or place a shot on the SCA
  18–22% scale. See [#ey-formula](#ey-formula).
- **Strength versus extraction, separated.** TDS and EY are independent axes.
  "Too weak" may be under-extraction *or* an over-long ratio, and taste alone
  cannot decompose them. The engine's policy of fixing the *measured* ratio
  before touching the *inferred* grind is a pragmatic ordering, not a
  measurement.
- **Which side of the extraction peak you are on**, directly. The peak is
  defined on an EY axis. The engine infers it from broken time-monotonicity and
  a long-and-sour taste signature — a genuine proxy, but a proxy, and one that
  needs at least two shots at different settings before it can fire.

**Structurally unobservable, whatever instrumentation is added, because the app
does not record it:**

- **Puck preparation** — distribution, tamp, WDT, basket wear. This dominates
  channeling variance. A shot that ran long because of a poor tamp is
  indistinguishable, to this system, from one that ran long because the grind
  was too fine. **This is the single largest error source and better maths
  cannot fix it.**
- **Actual brew temperature** without a PID or a Scace device: `brew_temp_c` is
  what the user set or believes, not what reached the coffee.
- **Pour schedule and agitation** for pour-over — the dominant lever, entirely
  uncaptured, which is why pour-over confidence is capped.
- **Stove power and heat-cut timing** for moka — likewise dominant, likewise
  uncaptured.
- **Grinder retention and burr drift** — retained grounds and slow wear mean
  the same click number means slightly different things months apart.

What the engine can honestly say: *given your grinder, your machine and what
you actually measured, here is the setting that should land your time and ratio
in the target band.*

---

## 2. Physics {#physics}

### 2.1 Darcy's law {#darcy}

Flow through a packed bed:

```
Q = k · A · ΔP / (µ · L)
```

`Q` volumetric flow, `k` permeability, `A` bed cross-section, `ΔP` pressure
drop, `µ` dynamic viscosity, `L` bed depth. Measured coffee-puck permeabilities
are of order 10⁻¹³–10⁻¹⁴ m².

### 2.2 Kozeny–Carman, and where it breaks {#kozeny}

```
k = d² · ε³ / (180 · (1 − ε)²)
```

for particle diameter `d` and porosity `ε`; so **`k ∝ d²`** at fixed packing.

**Caveat, and it matters:** Kozeny–Carman is known to degrade near clogging,
where percolation-type models fit better. We therefore use `k ∝ d²` only for
the *local slope* of the grind law — a linearisation around the current
setting — and never for absolute prediction. The regime where it fails is
precisely the channeling regime, which [#cameron](#cameron) hands over to a
separate guardrail. The two limits coincide, which is reassuring.

### 2.3 Normalised shot time {#normalised-time}

```
T_r = time_s / brew_ratio
```

Shot time alone is not comparable across different ratios; `T_r` (seconds per
unit of brew ratio) is. 18 g → 36 g in 28 s gives `R = 2.0`, `T_r = 14.0`.

### 2.4 The grind law {#beta-law}

Combining 2.1–2.3 at fixed dose, geometry and pressure gives `T_r ∝ d⁻²`. With
a linear grinder dial (`d = d₀ + u·(c − c₀)`, `u` µm per click):

```
ln T_r = α_setup + δ_bean + β_setup · c        β = −2u / d_ref
```

`α` is the setup's intercept, `δ_bean` a per-bean offset. Both are fitted; `β`
starts from the physical prior in [#beta-prior](#beta-prior) and is shrunk
toward the fitted value as data arrives ([#shrinkage](#shrinkage)).

**Which term the engine uses depends on whether it has brewed this coffee.**

*Shots on this coffee.* The law is used in **differential** form — the one
correction the engine makes — anchored on this coffee's own most recent
measured shot:

```
c* = c + (ln T_r_target − ln T_r_observed) / β
```

`α` and `δ_bean` cancel, which is why they need not be known accurately. The
anchor must be a shot of the *same* coffee: `δ_bean` is precisely the
statement that `c` and `T_r` from a different bag do not belong on this
coffee's curve. Dose, brew temperature, ratio and taste are also read off that
anchor, so a foreign anchor gets all of them wrong too.

The same restriction applies to the anti-channeling floor
([#cameron](#cameron)): its triggers compare normalised times against one
another and read the finest setting that has *tasted* right, and neither
comparison survives a change of coffee.

**And to the pairs the slope is fitted from. Recorded 2026-09-14.** `β` is a
property of the grinder, so it is fitted across every bag on the setup — but
by pooling each coffee's own *pairs* into one median, never by pairing one
coffee's shot against another's. A cross-bean pair's rise is `β·Δc` plus
`δ_bean_a − δ_bean_b`; the second term is not a grind effect, and where it
dominates the fitted slope comes back too shallow or with the **wrong sign**,
which `fit_setup` then reads as the channeling signature and discards, falling
back to the prior at zero confidence.

On the reference history this was **latent, not active**: the two bags were
brewed in different temperature bands (94–96 °C and 91–92 °C), so
[#temp-covariate](#temp-covariate) already dropped every cross-bean pair for
an unrelated reason — 0 of the 14 surviving pairs crossed bags, and the fit
was correct by luck. Hold that history at one temperature and 24 of 42 pairs
cross, dragging the median from **−0.150** to **−0.050**: three times too
shallow, so a correction three times too large, with `max_move_fraction`'s
cap — itself `0.25·|1/β|` — widening in step instead of catching it. Being
saved by a covariate filter aimed at something else is not a safeguard, and
it disappears as soon as two bags are brewed at the same temperature.

*No shots on this coffee.* Nothing to correct from, so the law is used in
**absolute** form and solved for the dial:

```
c = (ln T_r_target − α − δ̂_bean) / β
```

`δ̂_bean` is borrowed from the coffees this one resembles, weighted by the
similarity score ([#similarity](#similarity)); with nothing similar enough it
is 0, i.e. the setup's average bean. Falling back to another coffee's last
shot instead is the failure this replaced: every bean on a setup came back
with the same number.

*Neither.* No fitted `α` — a new grinder, or moka, which has no grind law at
all — so the dial cannot be located from history and the engine falls back to
the cold start in [#cold-start](#cold-start).

**Missing term: dose. Recorded 2026-09-13.** The law has no dose term, and it
should. Cameron et al. state it plainly: when the coffee mass changes *"the
only parameter that needs to be altered is the bed depth, L"*, and bed depth is
**directly proportional to the dose**. Darcy (§2.1) then makes the pressure
drop — and so the shot time — scale with `L`. A dose change is therefore a
first-order effect on `T_r` that the engine currently attributes to something
else.

That something else is `δ_bean`, and on the reference history the two are
**completely confounded**: one coffee was always dosed 18 g and the other
always 16 g, so the fitted offsets (−0.043 and +0.142, a gap worth about two
clicks) cannot distinguish "this bean grinds differently" from "this bean was
dosed 2 g lighter". [#similarity](#similarity) notes that origin and process
have no published effect on how a coffee grinds, which makes the dose reading
the more likely one. The fix is to put `+ γ·ln(dose)` in the law and re-fit,
leaving `δ_bean` to carry only what is genuinely the coffee — until then,
`δ_bean` should be read as "this bag, at the dose you use for it".

### 2.5 Extraction yield {#ey-formula}

```
EY% = (beverage_g × TDS%) / dose_g
```

Documented for completeness and for the day a refractometer appears. **Not
computable here** — see [#limits](#limits).

---

## 3. Literature constants {#literature}

### 3.1 SCA extraction and strength bands {#sca-bands}

Extraction yield **18–22%** is the long-standing target band, originating in
Lockhart's Coffee Brewing Institute work at MIT in the 1950s and retained by
the SCA. Espresso TDS runs **8–12%**. Below 18% reads as under-extracted
(bright, sour, tea-like); above 22% as over-extracted.

TDS is approximately inversely proportional to the brew ratio, while extraction
yield is approximately independent of it — which is why ratio is treated as a
strength/texture lever rather than an extraction lever.

### 3.2 Espresso ratio, time and temperature {#ratio-espresso}

Normale **1:2** (band 1:1.8–1:2.5), **25–30 s**, brew temperature
**90.5–96 °C**.

**The time half of this band is contested by our own load-bearing source.**
Cameron et al. name it directly: *"The Specialty Coffee Association espresso
parameters mandate that the extraction should take 20–30 s; we speculate that
this might be partially responsible for the prevailing empirical truth that
most coffee is brewed using grind settings that cause partially
clogged/inhomogeneous flow."* Their own reproducibility route
([#cameron-reproducibility](#cameron-reproducibility)) explicitly produces
**shots under 15 s** and calls that a success, not a fault.

So a band of 25–30 s is a *taste convention*, not a physical optimum, and an
engine that treats it as a target will drive every coffee finer until it hits
the clogged regime and then report that it is stuck. Treat a persistently fast
shot that tastes balanced as a valid operating point rather than an error to
be corrected. See [#target-reachability](#target-reachability).

### 3.3 Pressure, and whether the band is reachable {#target-reachability}

Cameron et al. give the pressure dependence explicitly: increasing the pump
overpressure increases the Darcy flux in direct proportion, so **shot time
falls inversely with pressure**. Pressure therefore moves `α` in
[#beta-law](#beta-law), not `β` — it shifts the whole curve rather than
changing its slope.

It also moves the clogging onset. They ran at **9 bar first and could not use
fine settings at all** — it clogged — and dropped to **6 bar** specifically to
open up the grind range. So a machine at higher pressure reaches the
inhomogeneous regime at a *coarser* setting than one at lower pressure.

The practical consequence for this app: on a fixed, unregulated machine the
25–30 s band may simply be unreachable, and the honest output is to say so
rather than to keep recommending finer. A target band is only meaningful
relative to the pressure the machine actually delivers, which we cannot
measure.

### 3.4 Ristretto {#ratio-ristretto}

**1:1–1:1.5**, aim 1:1.25, 20–28 s. Same temperature band.

### 3.5 Lungo {#ratio-lungo}

**1:2.5–1:3**, aim 1:2.75, 28–36 s. Same temperature band.

### 3.6 Pour-over, V60 {#ratio-pourover}

Golden ratio **1:16** (≈60 g/L), band 1:15–1:17; water **92–96 °C**; total
drawdown **2:45–3:15** for a ~15 g single; medium-fine grind, ~600–800 µm.

The dominant levers — pour schedule, agitation, bloom, pour height — are not
recorded by this app. See [#method-levers](#method-levers).

### 3.7 Moka pot {#ratio-moka}

Steam pressure **1–2 bar**, ratio **1:7–1:10** (aim 1:8), grind
**360–660 µm**, water reaching the bed at roughly **93 °C** and *rising through
the brew*.

Brew time is set by stove heat input, not by bed permeability, so the engine
does not solve grind from time for this method and does not state a target
time it cannot control.

### 3.8 Degassing {#degassing}

Coffee released **5–14 days** post-roast is the commonly cited window. Fresher
coffee releases CO₂ during extraction, causing faster and more erratic flow,
early blonding and a raised channeling risk. Qualitatively well established;
the specific magnitudes we apply are heuristic
([#fresh-band](#fresh-band)).

### 3.9 The extraction peak is not monotonic {#cameron}

Cameron et al., *Matter* 2020, is the load-bearing citation for this project.
A mathematical model assuming homogeneous flow predicts extraction yield
falling monotonically as grind coarsens. Experiment disagrees: measured yield
**peaks and then declines at fine settings**, because flow becomes
inhomogeneous — channeling — which both wastes coffee and destroys
reproducibility.

The practical consequence is that **"the shot ran long, grind finer" is wrong
past the peak**, and grinding finer there makes extraction *worse* and less
repeatable. That reflex was hardcoded into this app's previous prompt. The
engine now refuses to cross an empirically detected floor.

The onset setting is device-specific (their instrument showed it below ~1.7 on
its own dial), which is why the engine detects it from the user's own data
rather than hardcoding a number. They quantify the cost of crossing it: at
grind settings of 1.5, 1.3 and 1.1 the measured yield falls **2.6%, 6.1% and
13.1%** below the homogeneous-flow prediction.

**What clogging does *not* do is stop the shot getting slower.** In their
Figure 4A shot time stays inversely proportional to grind setting with
**R² = 0.995 across both regimes** — the clogged points sit on the same line.
Extraction yield turns over at the onset; shot time does not. A time-based
plateau is therefore *not* a literature signature of channeling, and
[#channeling-detection](#channeling-detection) should not be read as if it
were. The signatures the paper does offer are a **falling extraction yield
while time keeps rising** (needs a refractometer) and a cup that reads as
**bitter and sour at the same time** — under- and over-extracted regions
brewed together, which a single sour↔bitter axis cannot represent.

Tamp force is not one of the signatures: they varied it deliberately and
**observed no appreciable variation in shot time or yield**, standardising at
98 N only for convenience.

### 3.10 The reproducibility recipe {#cameron-reproducibility}

The same paper's affirmative recommendation: **reduce the dry dose and grind
coarser** — 20 g → 15 g in their protocol, up to **25% less coffee** — which
raised extraction yield *and* improved shot-to-shot reproducibility. Validated
in production at a roastery across **27,850 beverages** over roughly a year.

Lower bed depth `L` reduces the pressure drop (2.1), which reduces the
channeling that (3.9) describes. For an app named "Wasteless", using a quarter
less coffee for a better shot is the headline move.

### 3.11 Temperature by roast level {#temp-by-roast}

Within the SCA band, lighter roasts are conventionally brewed hotter (more
soluble material, denser cell structure), darker roasts cooler (more soluble,
more prone to harsh extraction): light 94–96 °C, medium 92–94 °C,
dark 90.5–92.5 °C. The band edges are literature; the split points are our
interpolation.

### 3.12 Sour/bitter is not a reliable extraction readout {#taste-mapping}

"Sour means under-extracted, bitter means over-extracted" is the industry
default and is **not** dependable:

- Dark roasts taste bitter at *correct* extraction — that is roast character.
- Severe channeling produces shots that are simultaneously sour **and** bitter,
  because some coffee is over-extracted while bypassed coffee is barely
  extracted at all.

**Astringency** — a drying, mouth-puckering tactile sensation, distinct from
bitter taste — is the more specific over-extraction marker. Hence the separate
`astringent` flag, and hence the rule that *bitter without astringency does not
move the grind*.

---

## 4. Calibrated priors {#calibrated}

### 4.1 Reference particle diameter and β {#beta-prior}

`β = −2u / d_ref` from [#beta-law](#beta-law) needs a reference diameter.
We take `d_ref = 300 µm` for espresso and `700 µm` for pour-over, mid-range
values consistent with the published grind-size ranges in §3. These are
**calibrated**, not measured: they set the scale of the correction, and the
fitted `β` supersedes them as soon as there is data.

For a grinder with `u = 16 µm/click` this gives `β ≈ −0.107` per click, i.e.
roughly a **10% change in shot time per click** — the right order of magnitude
against common experience with hand grinders.

Where `u` is unknown, `β_prior = −0.06` per click is used, confidence is capped
low, and the prior variance is widened.

### 4.2 Locating the dial on an unmeasured grinder {#cold-start}

With no measured shot there is no intercept `α`, so the grind law cannot be
solved. But most hand grinders are zeroed at burr contact, which makes the dial
read out roughly linearly in particle diameter:

```
clicks ≈ d / (µm per click)
```

For a 16 µm/click grinder, espresso's 300 µm reference lands at ~19 clicks —
inside the published espresso range for such grinders, and derived rather than
guessed.

**Why not the midpoint of the hardware range?** Because that range spans
espresso to French press. On a K6 (0–180) the midpoint is 90 clicks, roughly
1.4 mm particles — French press territory, and a genuinely bad first shot. The
midpoint looks like a reasonable default and is not one.

**Assumption:** the dial's zero is burr contact and the scale is linear from
there. True for zero-set hand grinders; not necessarily true of stepped
electric grinders with an arbitrary origin. Where `µm per click` is unknown the
dial cannot be located at all, and the engine abstains (tier E) rather than
guessing.

### 4.3 Kingrinder K6 {#k6-caps}

**60 clicks per rotation, 16 µm per click.**

Published *espresso* ranges for this grinder disagree wildly across sources —
manufacturer guidance around 15–25, one review 22–45, others 30–60 "start at
45". That spread is the argument for storing capability per unit, with a
`spec_source` citation, rather than hardcoding a range in application code.

---

## 5. Heuristics — our own judgement, no source {#heuristics}

### 5.1 Shrinkage constants {#shrinkage}

`w = n_eff / (n_eff + κ)` with `κ = 4.0` espresso, `8.0` pour-over, and
`κ_bean = 2.0` for the per-bean offset. `n_eff` counts **distinct grind
settings**, not shots: ten shots at one setting carry no slope information.
Chosen so that roughly four distinct settings gets you halfway from prior to
fitted. Pure guess, easily revised.

### 5.2 Similarity weights {#similarity}

same setup 0.40, roast level 0.25, process 0.15, origin 0.10, freshness 0.10;
match floor 0.45; recency multiplier `0.97^weeks_ago`. Setup dominates because
a click number from a different grinder is close to meaningless.

**Caveat on the bean terms, recorded 2026-09-13.** Uman et al. (*Sci Rep*
2016) found particle size distribution to be **independent of bean origin and
processing method** — the two terms carrying 0.15 and 0.10 here. Roast level
and grinding temperature did matter. So origin and process are defensible as
*taste* neighbours for retrieving exemplars, but they have no published basis
as predictors of how a coffee grinds, and `δ_bean` should not be justified by
them. See the confound noted in [#beta-law](#beta-law).

**Bean-offset floor 0.25.** When seeding `δ̂_bean` for a coffee with no shots
([#beta-law](#beta-law)), every candidate is already on this setup, so the
0.40 setup term is excluded — it would add the same amount to all of them and
flatten the only comparison that carries information. That puts the ceiling at
0.60, so 0.25 asks for roughly a close roast match plus one of process or
origin. Below it, borrowing an offset is worse than assuming the setup's
average bean. Another pure guess.

### 5.3 Roast-level time modifier {#roast-time-modifier}

±1 s on the target `T_r`: lighter roasts a touch longer, darker a touch
shorter. Small enough to be nearly cosmetic; retained because it matches
common practice.

### 5.4 Fresh-coffee band widening {#fresh-band}

Under 7 days off roast, acceptance bands are doubled and correction magnitudes
halved, and the user is told the target is moving. Rationale in
[#degassing](#degassing); the factors themselves are guesses.

### 5.5 Pre-infusion and the rest before the pull {#preinfusion}

Pre-infusion wets the puck at low pressure so it swells and settles before
full pressure arrives; the pause afterwards lets water finish distributing by
capillary action and lets CO₂ escape. Both exist to make the bed uniformly
saturated, and an evenly saturated bed is the standard mitigation for
channeling — the same failure mode as [#cameron](#cameron).

This is well-established practice rather than peer-reviewed measurement. The
mechanism is not in dispute; the magnitudes below are ours.

**Why pre-infusion time is deliberately excluded from `T_r`.** The grind law
([#beta-law](#beta-law)) is Darcy's law, which describes *pressurised* flow.
`T_r` must therefore be the pressurised pull only. Folding pre-infusion
seconds into it would put a non-Darcy phase inside a Darcy model and corrupt
β. Machines that restart their timer when the pull begins are, for this
purpose, doing the right thing.

**Why it must still be recorded.** A shot with longer pre-infusion reaches
full pressure with the bed already wet, so it pulls *faster*. Unrecorded, that
is indistinguishable from — and will be attributed to — a coarser grind. Worse,
a finer shot that ran faster is precisely trigger 1 of
[#channeling-detection](#channeling-detection), so an unrecorded pre-infusion
difference can **fake the channeling signature** and stop the engine going
finer when nothing is wrong. Pairs whose pre-infusion or pause differ by more
than `prep_tolerance_s` are therefore excluded from the Theil–Sen slope and
from channeling detection. Because Theil–Sen is built from pairwise slopes,
dropping an incomparable pair is one term removed and nothing else changes.

**Time to first pressure as a second resistance reading.** On a machine with a
gauge, the interval between the pump starting and the needle first moving is
how long it takes to fill the headspace and saturate the bed — a measurement
of puck resistance taken *before* the shot runs. Grind moves it and the pull
time together. When they disagree by more than
`resistance_disagreement_ratio`, the bed's resistance changed after it was
wetted, which points at distribution, tamp or channeling rather than at the
grinder — a distinction the pull time alone cannot make.

**Fineness relief.** Where pre-infusion is used consistently and is long
enough to matter, the channeling floor is relaxed by
`preinfusion_channeling_relief` of one grinder step, because a properly
saturated puck tolerates a finer grind than a dry one. Consistency is required
before the relief applies: an inconsistent routine provides no such protection.

**Advice is gated.** Below `min_shots_for_prep_advice`, or with only one
pre-infusion duration ever recorded, the engine reports back the user's own
routine and says that keeping it constant is what makes the grind evidence
readable. It does not propose an optimum it has not measured.

### 5.6 Brew temperature as a covariate {#temp-covariate}

Hotter water is less viscous and extracts faster, so raising the brew
temperature shortens the shot and moves the taste toward the bitter end
without the grind changing at all. Two shots pulled at different temperatures
are therefore not clean evidence about the grinder, for the same reason two
shots with different pre-infusion are not ([#preinfusion](#preinfusion)).

Shots whose recorded temperatures differ by more than `temp_tolerance_c` are
excluded from each other's pairwise comparison in the Theil–Sen slope and in
channeling detection. As with pre-infusion, an unknown temperature on either
side counts as comparable — otherwise nothing would compare for a user who
does not record it.

The tolerance is deliberately loose. On a machine without a PID the recorded
figure is what the user set or believes, not what reached the coffee
([#limits](#limits)), so treating small differences as meaningful would be
false precision.

Temperature only becomes a *lever* the engine will move when the machine is
marked temperature-controllable; otherwise it is recorded and used for
comparability but never recommended, because advising a change you cannot make
is noise.

### 5.7 Channeling detection thresholds {#channeling-detection}

Variance ratio 2.0 between fine and coarse subsets (n ≥ 6 before it may fire);
never suggest more than 2 steps finer than the finest historically acceptable
setting; maximum single move 25% of |1/β|. All judgement calls, tuned to fail
safe — the cost of refusing to go finer when you could have is one extra
iteration, while the cost of chasing the channeling regime is wasted coffee and
an undiagnosable shot.

**Known weakness, recorded 2026-09-13.** The trigger "a finer setting ran no
slower, so the water is channeling" is *our* inference, not a literature
result, and [#cameron](#cameron) points the other way: shot time stayed
monotonic in grind setting through the clogged regime at R² = 0.995. What
turns over at the onset is extraction yield, which we cannot see without a
refractometer.

Worse, at realistic sample sizes the trigger cannot tell a plateau from noise.
On the reference history (10 shots) the pooled within-setting spread of
`ln T_r` was **0.395** — one bean gave `T_r` 4.17 and 10.11 at the *same*
setting — against **0.084–0.168 per click**. A single shot therefore carries
**2.4–4.7 clicks** of noise, so a three-point "plateau" is indistinguishable
from a flat line drawn through scatter. The floor fired on both beans there
and pinned the recommendation at a setting no finer than the one already used,
while the prose still said "go finer". Failing safe is the right instinct, but
a detector with no noise model fails safe *always*, which is its own failure.

Until this is replaced, treat the floor as a soft warning rather than a hard
clamp, and see [#deadband](#deadband) for the minimum move that is worth
naming at all.

### 5.8 The deadband: when not to change anything {#deadband}

There is currently **no deadband** — the engine will name a new click number
for a difference far below what a single shot can resolve. Nothing in the
literature gives a shot-time variance directly, but three independent
anchors bound it:

- Cameron et al. collected data in **pentaplicate** (n = 5 per point, n = 20
  for calibration) under tight control — ±0.5 g dose, ±1 g beverage mass
  (shots outside it discarded), fixed 92 °C, automated tamping to ±3 N. Five
  replicates is what a controlled rig needed for one usable point.
- The Espresso Protocol, a professional sensory standard, tolerates
  **25 s ± 3 s** as "the same shot" — an accepted band, not a measured sigma.
- Practitioner reports put fixed-setting shot time at roughly **±3–5 s**, and
  our own reference history gives 2.4–4.7 clicks (above).

None of these is a peer-reviewed sigma, so any threshold built on them is a
`HEURISTIC`. The defensible shape is: require the solved move to exceed the
observed within-setting spread before naming a new number, and otherwise say
"pull the same shot again" — which is also how you buy the replicate the
estimate needs.

---

## 6. Method levers, and what we cannot see {#method-levers}

| | espresso | pour-over | moka |
|---|---|---|---|
| driving force | pump, ~9 bar | gravity, ~2 kPa | steam, 1–2 bar |
| ratio denominator | beverage out | water in | water in |
| grind ↔ time coupling | **strong** | moderate | **weak** |
| levers we can move | grind, dose, ratio, temp\* | grind, dose, ratio | grind, dose, ratio |
| levers we cannot see | puck prep, distribution, tamp | pour schedule, agitation, bloom | stove power, heat-cut timing |
| confidence cap | 1.0 | 0.6 | 0.4 |

\* temperature only when the machine reports it as controllable.

Espresso is the only method where the physics model is load-bearing. For moka
the grind law is disabled outright (`β_prior = None`).

---

## 7. The simulator {#simulator}

`src/core/sim.py` implements Darcy + Kozeny–Carman plus a logistic bypass term
so that a fraction of flow short-circuits through a low-resistance channel as
particle size falls below an onset diameter. This reproduces the non-monotonic
yield curve of [#cameron](#cameron) from first principles, which lets the
correction policy be tested before any real shots exist.

It is a **test fixture only**. Its taste mapping in particular is crude. No
production module may import it, and a convention test enforces that.

---

## 8. Bibliography

- Cameron, M. I. et al. "Systematically Improving Espresso: Insights from
  Mathematical Modeling and Experiment." *Matter* 2(3), 631–648, 2020.
  <https://www.cell.com/matter/fulltext/S2590-2385(19)30410-2>
  — non-monotonic extraction yield; the 20 g → 15 g reproducibility protocol;
  27,850-beverage validation. Also: shot time linear in grind setting at
  R² = 0.995 *across both flow regimes*; clogging costs 2.6 / 6.1 / 13.1 % of
  yield at GS 1.5 / 1.3 / 1.1; tamp force does not measurably affect shot time
  or yield; pressure raised to 9 bar clogged fine settings, so the study ran at
  6 bar; shot time inversely proportional to pressure; bed depth proportional
  to dose; and the explicit criticism of the SCA 20–30 s mandate. Full text:
  <https://pages.uoregon.edu/chendon/publications/2020/74.%20Matter,%20Espresso%20extraction.pdf>
  Summary coverage:
  <https://www.sciencedaily.com/releases/2020/01/200122110447.htm>
- Uman, E. et al. "The effect of bean origin and temperature on grinding
  roasted coffee." *Scientific Reports* 6, 24483, 2016.
  <https://www.nature.com/articles/srep24483>
  — particle size distribution is **independent of origin and processing
  method**; grinding colder narrows the distribution and lowers mean particle
  size. The basis for the caveat in [#similarity](#similarity).
- "Cross-Cultural Comparison of the Espresso Protocol Repeatability", 2025.
  <https://pmc.ncbi.nlm.nih.gov/articles/PMC11854300/>
  — a professional sensory protocol's own extraction tolerance, 25 s ± 3 s at
  9 bar, 92–94 °C, 15–17 g ± 1 g. Used only as a tolerance anchor in
  [#deadband](#deadband); it reports no shot-time variance of its own.
- Wadsworth, F. B. et al. "A model for the permeability of coffee pucks
  validated using X-ray computed micro-tomography." *Royal Society Open
  Science* 13(4), 252031, 2026. <https://doi.org/10.1098/rsos.252031>
  — permeability from pore volume fraction and specific surface area,
  validated against lattice-Boltzmann simulation on XCT scans of real pucks at
  eleven grind settings; introduces a Forchheimer number for the onset of
  inertial flow. (Full text not retrieved — abstract only.)
- SCA Brewing Control Chart / Coffee Brewing Institute (Lockhart, MIT, 1950s) —
  extraction 18–22%, espresso TDS 8–12%.
  <https://www.baristainstitute.com/blog/jori-korhonen/january-2019/how-measure-extraction-coffee>
  and <https://www.baristahustle.com/towards-a-common-coffee-control-chart/>
- Corrochano, B. R. et al. "A new methodology to estimate the steady-state
  permeability of roast and ground coffee in packed beds." *Journal of Food
  Engineering*, 2015 — Darcy/Kozeny–Carman applied to coffee; measured
  permeabilities.
- "A model for the permeability of coffee pucks validated using X-ray computed
  micro-tomography." *Royal Society Open Science*, 2026 — Kozeny–Carman
  breakdown near clogging.
  <https://royalsocietypublishing.org/rsos/article/13/4/252031/481206/>
- Espresso brew ratios and basket sizes — Clive Coffee.
  <https://clivecoffee.com/blogs/learn/brew-ratios-basket-sizes-and-the-confusion-over-a-double-shot>
- Hario V60 brew guide — Stumptown.
  <https://www.stumptowncoffee.com/pages/brew-guide-hario-v60>
- Moka pot grind size and extraction — CoffeeGearHub.
  <https://www.coffeegearhub.com/moka-pot-grind-size/>
- Coffee degassing and the rest window — Podium Coffee Club.
  <https://podiumcoffeeclub.com/blogs/blog/coffee-degassing>
- KINGrinder K6 grind settings: 60 clicks/rotation, 16 µm/click — Honest Coffee
  Guide. <https://honestcoffeeguide.com/kingrinder-k6-grind-settings/>
- Coffee extraction and how to taste it — Barista Hustle.
  <https://www.baristahustle.com/coffee-extraction-and-how-to-taste-it/>
  — the limits of the sour/bitter mapping; astringency as a distinct sensation.
