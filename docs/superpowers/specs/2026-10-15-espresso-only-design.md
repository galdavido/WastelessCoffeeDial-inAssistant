# Espresso only

Date: 2026-10-15 · Status: approved design, not yet implemented

## Goal

Narrow the app to one brew method and one style: **espresso**, at the
standard ratio and time band. Pour-over, moka, ristretto and lungo leave the
engine, the API, the database, the PWA and the admin dashboard. The research
behind them is kept, out of the engine's path, in an appendix of
`docs/science.md`.

The point is a smaller engine with fewer forks. Every espresso number the
engine produces today must come out identical afterwards.

## Facts this rests on

- The owner confirmed there are **no pour-over or moka setups or shots** on
  dev or prod. The migration checks this instead of trusting it.
- **Espresso style is already unreachable**: `engine.recommend` takes
  `style`, but no route passes one. Removing ristretto and lungo changes
  nothing a user can see.
- The PWA always posts `yield_g`, never `water_g`. `water_g` (water in) only
  means something for pour-over and moka.
- Request models ignore unknown keys, so an old cached client that still
  sends `method` or `water_g` is not rejected.
- Bootstrap seeds only a `grinder` and an `espresso_machine`. The
  equipment types `filter` and `other` appear only in the equipment form.

## Non-goals

- Changing any espresso number, band, constant value or correction rule.
- A dedicated moka or pour-over flow (the "Decided, don't reopen" entry in
  CLAUDE.md covers this).
- Renaming `/api/logs/*`.
- Deploying. That happens later, on request, dev first (see Deploy).

## Design

### 1. Database — migration `0010_espresso_only` (hand-written)

#### Upgrade

1. **Guard.** Count the rows that would lose information:
   - `brew_setups.method NOT IN ('espresso')` (NULL is fine),
   - `dial_in_logs.brew_method NOT IN ('espresso')` (NULL is fine),
   - `recommendations.method NOT IN ('espresso')` (NULL is fine),
   - `dial_in_logs.water_g IS NOT NULL`,
   - `recommendations.water_g IS NOT NULL`,
   - `equipment.type NOT IN ('grinder', 'espresso_machine')`.

   If any count is non-zero, raise a `RuntimeError` that names each non-zero
   count, before any DDL. Nothing is changed.
2. Drop the columns `brew_setups.method`, `dial_in_logs.brew_method`,
   `dial_in_logs.water_g`, `recommendations.method` and
   `recommendations.water_g`. First drop, explicitly, the two CHECK
   constraints that 0002 created on them: `ck_brew_setups_method` and
   `ck_dial_in_logs_brew_method`.

**Downgrade** re-adds the five columns as nullable, with the 0002 CHECK
constraints. It does not restore data: there was none to restore.

`src/database/models.py` loses the five attributes. The models do not get a
CHECK on `equipment.type`: the request schema is the gate, and the guard has
already shown that the live data conforms.

### 2. API

#### Requests (`web_schemas.py`)

- `SetupInput` loses `method`.
- The feedback/shot input loses `water_g`.
- `EquipmentInput.type` becomes `Literal["grinder", "espresso_machine"]`.

#### Responses (`api_schemas.py`)

- `RecipeOut` (and every other response model that carries them) loses
  `method` and `water_g`. The `Method` alias goes.
- The admin stats response loses its per-method breakdown.

#### Routes

- `routes/gear.py`: `_infer_method`, `_POUROVER_MODELS` and `_MOKA_MODELS`
  go. The machine list returns `espresso_machine` rows only. Creating or
  editing a setup returns 400 unless `machine_id` is an `espresso_machine`,
  the same check the grinder already gets.
- `routes/coffees.py`: no method or `water_g` in the shot history or the
  latest log.
- `shots.py`: `brew_method` is no longer written. `classify_data_quality`
  requires `yield_g` for "measured", with no `water_g` alternative.
- `admin_stats.py`: the method count query goes.

`docs/openapi.json` is regenerated with `python -m core.openapi_export`.

### 3. Engine

#### `brewing.py`

- Remove the `Method` literal, `ShotRecord.method`, `ShotRecord.water_g`,
  `Recipe.method` and `Recipe.water_g`.
- Remove the constants `pourover_*`, `moka_*`, `ristretto_*`, `lungo_*`,
  `d_ref_pourover_um`, `kappa_pourover`, `confidence_cap_pourover` and
  `confidence_cap_moka`.
- Rename where the prefix only told methods apart. The values do not change:

  | old | new |
  | --- | --- |
  | `espresso_ratio_aim` / `_lo` / `_hi` | `ratio_aim` / `ratio_lo` / `ratio_hi` |
  | `espresso_time_lo` / `_hi` | `time_lo` / `time_hi` |
  | `espresso_temp_lo` / `_hi` | `temp_lo` / `temp_hi` |
  | `d_ref_espresso_um` | `d_ref_um` |
  | `kappa_espresso` | `kappa` |

  If a new name collides with an existing constant or local identifier,
  keep the old name for that one and record it in the plan.
- `TARGETS` and `target_for(method, style, roast)` become one module-level
  espresso `Target` and `target_for(roast_level_ord)`, which applies
  `for_roast`.
- `brew_ratio(shot)` is `yield_g / dose_g` (None when either is missing or
  non-positive).
- `beta_prior(caps)` and `cold_start_clicks(caps)` lose `method` and the moka
  branch. They still return None when microns per click are unknown.
- The correction policy, the pre-infusion experiment and the dose-reduction
  suggestion lose every `method == "espresso"` / `!= "espresso"` fork and
  keep the espresso branch. The dose bound is always the basket-relative
  range, or 12–22 g without a basket size.

**`calibration.py`**: the dose exponent always starts from
`dose_exponent_prior`. Shrinkage uses `kappa`. The method confidence cap
goes.

**`retrieval.py`**: `get_active_setup_method` goes. `to_shot_record` and the
history query drop the `method` parameter and stop filtering on method.
`calibration_protocol` loses the moka branch.

**`engine.py`**: `recommend` loses `method` and `style`. The recipe always
sets `yield_g`.

**`ai/rationale.py`**: the `water_g` prompt branch goes.

**`eval_harness.py` / `backtest_cli.py`**: the `method` parameters and any
`--method` option go.

### 4. Frontend

#### PWA (`index.html`, `app.js`, `style.css`)

- Setup form:
  - the "Brew method" select and its hint go;
  - "Machine / brewer" becomes "Espresso machine";
  - the name placeholder drops "V60";
  - the machine select lists espresso machines only.
- Equipment form: the type select offers Grinder and Espresso machine only.
  `EQUIPMENT_TYPE_LABELS` loses `filter` and `other`.
- Remove `METHOD_LABELS`, `activeSetupMethod`, the setup chip's method span,
  the setup list's method label, and the CSS for `.setup-chip-method` and
  `.setup-item-method`.
- Shot wizard: the yield label is always "Out (g)". The moka branch that
  skipped straight to the pull and hid "skip" goes.
- Recipe card: shows `yield_g` only, without the "· method" suffix.

**Admin (`admin.html`, `admin.js`, `admin.css`)**: the "Method mix" chart,
`renderMethods` and their CSS go.

**Cache**: `sw.js` `CACHE` goes from `wcda-v49` to `wcda-v50`. The `?v=` tags
on CSS and JS move to match in `index.html` and `admin.html`.

### 5. Docs

#### `docs/science.md`

- §1 opens with the scope: espresso only, at one style. Removed from §1: the
  "pour schedule / stove power" bullet and the pour-over/moka dose-bound
  sentence.
- §3.4 Ristretto, §3.5 Lungo, §3.6 Pour-over, §3.7 Moka and the §6
  method-levers table move to a new **Appendix A — Not implemented: other
  methods and styles**, placed before §9 Bibliography and headed with a note
  that the engine does not use it. The anchors `#ratio-ristretto`,
  `#ratio-lungo`, `#ratio-pourover`, `#ratio-moka` and `#method-levers`
  stay, on the appendix headings. §7 and §8 renumber to §6 and §7.
- The moka row of the "literature disagrees" table stays, with its status
  changed to "Out of scope: espresso only; research kept in Appendix A".
  Navarini 2009 stays, because the appendix cites it.
- Every reference to a renamed constant is updated.
- The owner's uncommitted re-wrap of §5.4 and §5.5 is kept and goes in with
  the docs commit.

**`tests/test_science_doc.py`**: the §5 end marker becomes `{#simulator}`. The
five appendix anchors join the narrative allowlist, and `method-levers` leaves
the heuristic-anchor exemption.

**`CLAUDE.md`**: the "Moka stays as it is for now" entry under "Decided,
don't reopen" becomes an "Espresso only" entry, dated 2026-10-15. It points
to Appendix A and keeps the Navarini heat-cut reasoning for when a moka flow
is revisited. All other mentions of method in CLAUDE.md are updated to match.

**`README.md`**: the tagline and any other mention of pour-over or moka.

## Testing

- **No-change baseline.** `backtest_cli` reads the real database, so it can't
  be the baseline. Instead, before any engine edit, a throwaway script in the
  scratchpad (not committed) builds a deterministic grid of espresso shot
  histories with `tests/_sim.py` and `tests/_fixtures.py`. It runs
  `target_for`, `beta_prior`, `cold_start_clicks`, the calibration fit, the
  correction policy and `eval_harness.backtest` over that grid and dumps JSON.
  After the change, only its call sites are adapted to the new signatures,
  and the output must match the baseline byte for byte. Any difference is a
  bug, not an update.
- **Deleted tests.** Tests that exist only for pour-over, moka, ristretto or
  lungo are removed. The others move to the new signatures without changing
  their expected numbers.
- **New tests in `tests/test_api_flows.py`:**
  - creating a setup whose machine is a grinder returns 400;
  - posting equipment with `type: "filter"` or `"other"` returns 422;
  - a setup body that still carries `method` is accepted and ignored.
- **Migration.** Upgrade and downgrade run on a disposable Postgres. A test
  seeds one non-conforming row (for example `water_g` set) and confirms the
  upgrade raises and leaves the schema unchanged.
- **Whole suite.** The full suite, ruff and the type checker pass, as do
  `test_openapi.py`, `test_science_doc.py` and the `test_web_app.py` checks
  on the cache version and inline styles.
- **Leftovers.** `grep -rniE "pourover|pour-over|moka|ristretto|lungo|water_g|brew_method"`
  over `src/` and `tests/` returns nothing. Migrations 0002–0009 are exempt.

## Deploy (later, on request)

Dev's `/admin` reads the prod database. If prod were migrated first, dev's
old admin code would query a dropped column, so: **deploy dev first, then
prod, or both together.** Take a dump before each migration, as for 0009.

## Commits on `espresso-only`

1. This spec.
2. The engine (`brewing`, `calibration`, `retrieval`, `engine`, `rationale`,
   eval and backtest) and its tests.
3. The API, models, migration 0010, the routes, admin stats,
   `openapi.json` and the API tests.
4. The PWA and admin frontend, and the cache bump.
5. `science.md`, `test_science_doc.py`, CLAUDE.md and README.

Each commit leaves the suite green. Where the API and the engine cannot be
split cleanly, commits 2 and 3 merge into one.
