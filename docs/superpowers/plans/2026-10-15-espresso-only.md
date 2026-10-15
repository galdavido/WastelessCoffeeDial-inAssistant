# Espresso Only Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Narrow the app to espresso at one style. Pour-over, moka, ristretto and lungo leave the engine, API, database, PWA and admin dashboard, and their research moves to an appendix of `docs/science.md`.

**Architecture:** This is a deletion, in four green commits. (1) The engine loses every `method`/`style`/`water_g` fork and the response models lose those fields. (2) Migration 0010 drops the columns behind a refuse-if-data guard, and the request models, gear routes and admin stats follow. (3) The PWA. (4) The docs. Before anything changes, a scratchpad snapshot of the pure engine's output is taken, and it must come back byte-identical after Task 2.

**Tech Stack:** FastAPI, Pydantic 2, SQLAlchemy 2, hand-written Alembic, vanilla-JS PWA, pytest/unittest in Docker.

**Spec:** `docs/superpowers/specs/2026-10-15-espresso-only-design.md`

## Global Constraints

- **No espresso number changes.** Constant values, bands, correction rules and expected numbers in the surviving tests stay as they are. The Task 1 snapshot must match exactly after Task 2.
- Migrations are hand-written; never autogenerate. Do not edit migrations 0001–0009.
- Response models stay strict (`_Strict`, every field required). Any request/response shape change → `python -m core.openapi_export`, and the regenerated `docs/openapi.json` is committed in the same task.
- Equipment types are exactly `grinder` and `espresso_machine`.
- Frontend: no inline styles and no `<style>` (CSP). The cache bump happens once, in Task 4: `wcda-v49` → `wcda-v50`, and `?v=` follows on every CSS/JS tag in `index.html` **and** `admin.html`.
- Constant renames (values unchanged): `espresso_ratio_{aim,lo,hi}` → `ratio_{aim,lo,hi}`, `espresso_time_{lo,hi}` → `time_{lo,hi}`, `espresso_temp_{lo,hi}` → `temp_{lo,hi}`, `d_ref_espresso_um` → `d_ref_um`, `kappa_espresso` → `kappa`.
- Branch `espresso-only`. Commit with pre-commit on PATH: prefix `export PATH="/c/Users/galda/AppData/Roaming/Python/Python314/Scripts:$PATH" &&`. End each message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Never stage `docs/SESSION-STATE.md`. Update it after each task.
- The owner's uncommitted re-wrap of `docs/science.md` §5.4/§5.5 is kept, and is committed only in Task 5.
- **Test runner** (the host has no Python deps). Start Docker Desktop first. Set this once per shell:
  `T="docker exec -e DATABASE_URL=postgresql+psycopg2://wcda:wcda@wcda-test-pg:5432/wcda_test wcda-test"`.
  Run everything as `$T pytest -q`, `$T ruff check .`, `$T ruff format --check .`, `$T mypy src`.

## Review Focus

1. **An old cached PWA** still posts `method` on a setup and `water_g` on feedback. Both must be accepted and ignored, not answered with 422. Test: Task 3 `test_stale_client_fields_are_ignored`.
2. **A shot logged with time but no yield.** It used to count as "measured" if `water_g` was present; now it must be `partial`, so calibration never reads it. Test: Task 3 `test_classify_requires_yield`.
3. **The shared test database still holds rows from before 0010** (`water_g` from deleted pour-over tests). The guard will rightly refuse to migrate it. Task 3 Step 1 recreates the test Postgres, so a refusal there is not misread as a bug.
4. **A setup edited to point at a grinder as its machine.** Today only the grinder is type-checked. Test: Task 3 `test_setup_machine_must_be_espresso_machine` (both create and update).
5. **The Target bands without `None` times.** Moka was the only reason `time_lo`/`time_hi`/`tr_lo`/`tr_hi` could be None. Making them `float` must not change a fit-view or bean-history payload. Covered by the snapshot and by `test_fit_view.py`/`test_api_flows.py` unchanged; the reviewer checks that `TargetOut` fields become `float`.

---

### Task 1: Test runner and the no-change snapshot

**Files:**
- Create (scratchpad, never committed): `C:\Users\galda\AppData\Local\Temp\claude\c--Users-galda-OneDrive-code-BaristAI\2119b146-4122-49e0-900c-19a097a8456b\scratchpad\snapshot.py`. Inside the container it is not visible, so copy it in with `docker cp` before running it.

**Interfaces:**
- Produces: `/tmp/before.json` inside `wcda-test`, which Task 2 compares against.

- [ ] **Step 1: Start the containers and run the baseline suite**

```bash
cd "C:/Users/galda/OneDrive/code/BaristAI"
docker network create wcda-test-net
docker run -d --rm --name wcda-test-pg --network wcda-test-net -e POSTGRES_USER=wcda -e POSTGRES_PASSWORD=wcda -e POSTGRES_DB=wcda_test postgres:16-alpine
MSYS_NO_PATHCONV=1 docker run -d --rm --name wcda-test --network wcda-test-net -v "C:/Users/galda/OneDrive/code/BaristAI:/app" -w /app python:3.14-slim sleep infinity
docker exec wcda-test pip install -q -e '.[dev]'
$T pytest -q
```
Expected: everything passes. If anything fails here, stop and report it: it is not this plan's regression.

- [ ] **Step 2: Write `snapshot.py`**

It imports `tests._sim`, `tests._fixtures` and `core.brewing`, `core.calibration` and `core.eval_harness`, with `sys.path` set to `/app/src` and `/app`. It prints one JSON document (`json.dumps(..., sort_keys=True, indent=1, default=str)`), built deterministically with no randomness:

- `targets`: `target_for("espresso", None, r)` for `r` in `None, 1, 2, 3, 4, 5`, each as `dataclasses.asdict` plus `tr_lo` and `tr_hi`.
- `beta_prior` and `cold_start_clicks` for `K6`, for `GrinderCaps(min_clicks=0, max_clicks=100)`, and for a `higher_is_finer` copy of K6.
- **Histories.** For each dose in `(16.0, 18.0, 20.0)`, each roast in `(None, 2, 4)` and each grind list in `([24, 26, 28, 30], [18, 19, 20], [30, 32, 34, 36, 38])`: simulate each click with `simulate_shot(c, K6, BedParams(dose_g=dose), target_yield_g=2*dose)` and turn each result into `ShotRecord(method="espresso", dose_g=dose, setup_id=1, bean_id=1, grind_clicks=c, yield_g=2*dose, time_s=sim.time_s, taste_axis=sim.taste, roast_level_ord=roast)`. Use the real `SimShot` attribute names. For each history, record:
  - `fit_setup(history, "espresso", K6, beta_prior("espresso", K6), bean_id=1)` as `asdict`;
  - `apply_guardrails(correct(history[-1], target, fit.beta, K6, MACHINE_18G, roast_level_ord=roast, gamma=fit.gamma or 0.0, noise_ln=None), K6, MACHINE_18G, history, target, fit.beta, fit.gamma or 0.0)` as `asdict`, **with the keys `method` and `water_g` deleted**;
  - `dose_reduction(history, guarded, K6, MACHINE_18G, target, fit.beta)` and `preinfusion_experiment(history, "espresso", True)` as `asdict` or `None`;
  - `backtest(history, target, K6, MACHINE_18G).render()`.

Read the real field names of `Calibration` (`core/calibration.py`) and `SimShot` before writing. A small adapter function at the top, `call_target(roast)`, `call_beta(caps)`, `call_cold(caps)`, `call_fit(...)`, `call_prep(...)`, `make_shot(...)`, holds every call whose signature Task 2 changes, so that afterwards only the adapter is edited.

- [ ] **Step 3: Take the baseline**

```bash
docker cp "C:/Users/galda/AppData/Local/Temp/claude/c--Users-galda-OneDrive-code-BaristAI/2119b146-4122-49e0-900c-19a097a8456b/scratchpad/snapshot.py" wcda-test:/tmp/snapshot.py
docker exec wcda-test sh -c 'cd /app && python /tmp/snapshot.py > /tmp/before.json && wc -c /tmp/before.json'
```
Expected: a non-trivial byte count (thousands). No commit in this task.

---

### Task 2: The engine is espresso-only

**Files:**
- Modify: `src/core/brewing.py`, `src/core/calibration.py`, `src/core/eval_harness.py`, `src/core/backtest_cli.py`, `src/core/retrieval.py`, `src/core/engine.py`, `src/ai/rationale.py`, `src/core/routes/coffees.py`, `src/core/routes/recipe.py` (only if it reads `recipe.method`), `src/core/api_schemas.py`, `docs/openapi.json`
- Test: `tests/test_brewing_physics.py`, `tests/test_brewing_correction.py`, `tests/test_brewing_dose_reduction.py`, `tests/test_brewing_dose_term.py`, `tests/test_brewing_preinfusion.py`, `tests/test_bean_scoping.py`, `tests/test_engine.py`, `tests/test_eval_harness.py`, `tests/test_fit_view.py`, `tests/test_api_schemas.py`, `tests/test_retrieval.py`, `tests/test_rationale.py`, `tests/test_api_flows.py`, `tests/test_science_doc.py`

**Interfaces:**
- Consumes: `/tmp/before.json` from Task 1.
- Produces (`core.brewing`):
  - `ShotRecord` with no `method` and no `water_g`; the first field is `dose_g: float`.
  - `Recipe` with no `method` and no `water_g`; the first field is `dose_g: float`.
  - `Target` with `time_lo: float`, `time_hi: float`, and `tr_lo`/`tr_hi -> float`.
  - `ESPRESSO: Target`, and `target_for(roast_level_ord: int | None = None) -> Target`.
  - `beta_prior(caps: GrinderCaps) -> float | None`.
  - `cold_start_clicks(caps: GrinderCaps) -> float | None`.
  - `preinfusion_experiment(shots, grind_is_stuck: bool) -> PrepExperiment | None`.
  - `brew_ratio(shot) -> float | None` (`yield_g / dose_g`).
  - The `Method` alias no longer exists.
- Produces (elsewhere):
  - `fit_setup(shots, caps, beta_prior_value, bean_id=None) -> Calibration`.
  - `to_shot_record(log, bean) -> ShotRecord`.
  - `fetch_calibration_shots(db, owner, setup_id) -> list[ShotRecord]`.
  - `calibration_protocol(dose_g, out_g) -> str`.
  - `recommend(db, owner, setup, bean, dose_g, default_dose_g, explain=True)`.
  - `backtest(shots, target, caps, machine)`.
  - `get_active_setup_method` is deleted.
- Response models: `RecipeOut` and `BeanShotOut` lose `method` and `water_g`. The fit-view shot model loses `water_g`. In `TargetOut`, `tr_lo`, `tr_hi`, `time_lo` and `time_hi` become `float`. `SetupOut.method` stays until Task 3.

- [ ] **Step 1: Rewrite the target tests first**

In `tests/test_brewing_physics.py`:
- Delete `test_pourover_ratio_uses_water_in`, `test_moka_has_no_grind_law`, `test_moka_declares_no_target_time` and `test_moka_still_has_no_time`, plus every ristretto/lungo assertion and subtest.
- Change every `target_for("espresso", …)` to `target_for(…)`.
- Add:

```python
def test_one_espresso_target(self) -> None:
    t = target_for()
    self.assertEqual((t.ratio_lo, t.ratio_aim, t.ratio_hi), (1.8, 2.0, 2.5))
    self.assertEqual((t.time_lo, t.time_hi), (25.0, 30.0))
    self.assertEqual((t.temp_lo, t.temp_hi), (90.5, 96.0))

def test_brew_ratio_is_yield_over_dose(self) -> None:
    self.assertEqual(brew_ratio(ShotRecord(dose_g=18.0, yield_g=36.0)), 2.0)
    self.assertIsNone(brew_ratio(ShotRecord(dose_g=18.0)))
```

- [ ] **Step 2: Run them and watch them fail**

Run: `$T pytest -q tests/test_brewing_physics.py`
Expected: FAIL (`target_for()` is missing `method`; `ShotRecord` requires `method`).

- [ ] **Step 3: Change `brewing.py` to the Produces signatures**

- Delete the constants listed in the spec §3 and rename the rest (Global Constraints). Keep each renamed constant's `kind`, `anchor` and `note`.
- `TARGETS` and the ristretto/lungo/pourover/moka targets become `ESPRESSO = Target(value_of("ratio_lo"), …)`. `for_roast` loses its None-time guard, keeping only `roast_level_ord is None`.
- Every `method == "espresso"` / `!= "espresso"` fork in `correct`, `dose_reduction`, `preinfusion_experiment` and `apply_guardrails` keeps its espresso branch only. The `build()` helper sets `yield_g` and nothing about `water_g`. `apply_guardrails` loses its `water_g` scaling. The `elif recipe.method == "espresso"` dose bound becomes `else`.
- In `correct` step 2, drop `target.tr_lo is not None` and the `assert`. Also simplify the `target.tr_hi is not None` check near line 904.
- `Recipe.numeric_tokens` loses `water_g`.
- Update docstrings that mention moka or pour-over, and the module comment over the literature constants.

- [ ] **Step 4: Run the target tests and watch them pass**

Run: `$T pytest -q tests/test_brewing_physics.py`
Expected: PASS.

- [ ] **Step 5: Ripple through the engine to the Produces signatures**

- `calibration.fit_setup`: drop `method`; `gamma_prior = value_of("dose_exponent_prior")`; `kappa = value_of("kappa")`; drop `cap`, so `confidence = weight * min(1.0, n_eff / 8.0)`. Keep the `beta_prior_value is None` early return, now worded for an unknown slope, not moka.
- `eval_harness`: drop the `method` parameter from `direction_agreement`, `held_out_time_error`, `guardrail_violations`, `cold_start_abstention` and `backtest`. Simplify the `tr_lo is not None` guards in `_improved`.
- `retrieval`: `to_shot_record` stops reading `log.water_g`. The `fetch_calibration_shots` query must not filter on `brew_method`; if it does today, drop that clause. `calibration_protocol` keeps the espresso wording only.
- `engine.py`: drop `style`, `method` and `get_active_setup_method`. The cold-start recipe sets `yield_g = round(dose_g * target.ratio_aim, 1)`. Drop `method` and `water_g` from the `Recommendation(...)` constructor kwargs and from `inputs_json`; the columns stay nullable until Task 3. In `serialize_fit`, the shot dict and the recipe dict drop `water_g` and `method`, and the `tr_lo is not None` guard near line 355 goes. Drop the "this brew method has no grind law to fit" message branch, or reword it to "no slope to fit yet" if it still has a reachable caller.
- `backtest_cli`: drop `method`. The header line becomes `f"{setup.name}  -- {len(shots)} measured shots"`.
- `ai/rationale.py`: drop the `water_g` branch.
- `routes/coffees.py`: drop `active_method` and the per-shot `method`; use `target_for(roast_level_ord=bean.roast_level_ord)` once for every shot, and drop the `"method"` and `"water_g"` keys from the shot dict and from the latest-log response. Keep the setup's `method` column untouched; Task 3 removes it.
- `api_schemas.py`: apply the Interfaces changes and drop the `Method` import.

- [ ] **Step 6: Update the remaining tests to the new signatures**

- **Delete:**
  - `test_pourover_starts_coarser_than_espresso`, `test_moka_never_gets_a_derived_grind`, `test_moka_has_no_grind_law_to_fit`, `test_moka_recipe_declares_no_target_time`, `test_pourover_ratio_uses_water_in`, `test_pourover_and_moka_doses_are_not_clamped_to_an_espresso_basket` and `test_a_basket_clamp_scales_the_water_too` (`test_brewing_correction.py`);
  - `test_not_for_other_methods` (`test_brewing_dose_reduction.py`);
  - `test_pour_over_and_moka_have_no_dose_term` (`test_brewing_dose_term.py`);
  - `test_it_stays_quiet_on_pourover` (`test_brewing_preinfusion.py`);
  - `test_moka_is_told_why_there_is_no_setting` (`test_api_flows.py`).
- **Elsewhere:** remove `method=` from every `ShotRecord`/`Recipe` construction, every `"espresso"` argument to the changed functions, and every `recipe["method"]` assertion (`test_api_flows.py:137`). Expected numbers do not change.
- **`tests/test_science_doc.py`:**
  - Add `ratio-ristretto`, `ratio-lungo`, `ratio-pourover` and `ratio-moka` to the `narrative` allowlist with the comment `# Appendix A: research the engine does not use.`; `method-levers` is already there.
  - Remove `"method-levers"` from the heuristic-anchor exemption.
  - Change the §5 end marker from `{#method-levers}` to `{#simulator}`.
- `test_api_flows.make_setup` and `_setup` still send `method` and may create `filter`/`other` machines. Leave them for Task 3, but make sure no surviving test depends on a non-espresso method's behaviour.

- [ ] **Step 7: Regenerate the contract and run everything**

```bash
$T python -m core.openapi_export
$T pytest -q && $T ruff check . && $T ruff format --check . && $T mypy src
```
Expected: all pass.

- [ ] **Step 8: Check the snapshot**

In `snapshot.py`, edit only the adapter to the new signatures. Drop `method=` from `make_shot`. The key deletion for `method` and `water_g` stays, since those keys are now absent anyway.

```bash
docker cp "C:/Users/galda/AppData/Local/Temp/claude/c--Users-galda-OneDrive-code-BaristAI/2119b146-4122-49e0-900c-19a097a8456b/scratchpad/snapshot.py" wcda-test:/tmp/snapshot.py
docker exec wcda-test sh -c 'cd /app && python /tmp/snapshot.py > /tmp/after.json && cmp /tmp/before.json /tmp/after.json && echo IDENTICAL'
```
Expected: `IDENTICAL`. Any difference is a bug in Steps 3–5, not a snapshot to update.

- [ ] **Step 9: Leftover check, then commit**

Run: `grep -rnE "pourover|pour-over|moka|ristretto|lungo|\bMethod\b|get_active_setup_method|style: str" src/core src/ai --include=*.py`
Expected: nothing about brew methods. `src/core/routes/gear.py`, `setups.py`, `shots.py`, `admin_stats.py`, `web_schemas.py` and `models.py` are still allowed to hit; Task 3 removes those.

```bash
git add src tests docs/openapi.json
git commit -m "refactor(engine): espresso only, one style ..."
```

---

### Task 3: Migration 0010, the request models, gear routes and admin

**Files:**
- Create: `migrations/versions/0010_espresso_only.py`, `tests/test_migration_0010.py`
- Modify: `src/database/models.py`, `src/core/web_schemas.py`, `src/core/api_schemas.py`, `src/core/shots.py`, `src/core/setups.py`, `src/core/routes/gear.py`, `src/core/admin_stats.py`, `src/web/static/admin.html`, `src/web/static/admin.js`, `src/web/static/admin.css`, `docs/openapi.json`
- Test: `tests/_db.py`, `tests/test_api_flows.py`, `tests/test_admin.py`, `tests/test_shots.py`

**Interfaces:**
- Consumes: Task 2's engine. Nothing reads the five columns any more.
- Produces:
  - `EquipmentInput.type: Literal["grinder", "espresso_machine"]`.
  - `SetupInput` with `name`, `grinder_id` and `machine_id` only.
  - `FeedbackRequest` without `water_g`.
  - `classify_data_quality(*, grind_clicks, time_s, yield_g, rating, taste_axis) -> str`.
  - `SetupOut` without `method`.
  - The admin stats payload without `methods`.

- [ ] **Step 1: Recreate the test Postgres**

The old one holds `water_g` rows from deleted tests, and the new guard would rightly refuse it.

```bash
docker stop wcda-test-pg
docker run -d --rm --name wcda-test-pg --network wcda-test-net -e POSTGRES_USER=wcda -e POSTGRES_PASSWORD=wcda -e POSTGRES_DB=wcda_test postgres:16-alpine
```

- [ ] **Step 2: Write the failing migration test** in `tests/test_migration_0010.py`

Use the unittest style. Skip unless `DATABASE_URL` is set, and call `refuse_live_database` on it. Each test:
- creates its own database `wcda_mig_<uuid hex8>` with an `AUTOCOMMIT` connection to the server in `DATABASE_URL`;
- points `os.environ["DATABASE_URL"]` at it for the test's duration, restoring the original in `finally`;
- drives Alembic with `command.upgrade` / `command.downgrade` and `core.db_bootstrap._alembic_config()`;
- drops the database in `tearDown`, after `engine.dispose()`.

The tests:
- `test_refuses_when_non_espresso_data_exists`: upgrade to `"0009"`; insert `equipment(type='filter', brand='x', model='y')`; assert `command.upgrade(cfg, "head")` raises with `"equipment"` in `str(exc)`; assert `brew_setups.method` still exists (`sqlalchemy.inspect`) and the version is still `0009`.
- `test_refuses_on_water_g`: the same, with a `dial_in_logs` row whose `water_g` is set. Insert the minimum the table's NOT NULL columns need: owner, grinder and machine equipment ids, and `data_quality='partial'`. Assert `"water_g"` is in the message.
- `test_upgrade_drops_and_downgrade_restores`: upgrade to head on an empty database. None of `brew_setups.method`, `dial_in_logs.brew_method`, `dial_in_logs.water_g`, `recommendations.method` or `recommendations.water_g` exists. Downgrade to `"0009"`: all five exist and are nullable.

Run: `$T pytest -q tests/test_migration_0010.py`
Expected: FAIL (there is no `0010` revision).

- [ ] **Step 3: Write `migrations/versions/0010_espresso_only.py`**

- Revision `"0010"`, revises `"0009"`.
- The docstring follows 0009's style: what goes, why, "decided by the owner on 2026-10-15", and "take a dump first".
- `upgrade()` runs the six guard counts from the spec §1 with `op.get_bind().execute(sa.text(...)).scalar_one()`, using `IS DISTINCT FROM 'espresso'`-style predicates so NULL passes. If any is non-zero, it raises `RuntimeError("0010 refused: " + ", ".join(f"{name}={n}" for name, n in nonzero))`, where the names are `brew_setups.method`, `dial_in_logs.brew_method`, `recommendations.method`, `dial_in_logs.water_g`, `recommendations.water_g` and `equipment.type`.
- It then drops `ck_brew_setups_method` and `ck_dial_in_logs_brew_method`, then the five columns.
- `downgrade()` re-adds `brew_setups.method String`, `dial_in_logs.brew_method String`, `dial_in_logs.water_g Numeric(6,1)`, `recommendations.method String` and `recommendations.water_g Numeric(6,1)`, all nullable, and recreates both CHECKs with 0002's exact expressions (copy them from `0002_engine_columns.py`).

- [ ] **Step 4: Run the migration tests and watch them pass**

Run: `$T pytest -q tests/test_migration_0010.py`
Expected: PASS.

- [ ] **Step 5: Write the failing API tests** in `tests/test_api_flows.py`

```python
def test_setup_machine_must_be_espresso_machine(self) -> None:
    # A grinder as machine_id: 400 on POST /api/setups and on PUT /api/setups/{id}.

def test_equipment_type_is_grinder_or_espresso_machine(self) -> None:
    # POST /api/equipment/library with type "filter", then "other": 422 each.

def test_stale_client_fields_are_ignored(self) -> None:
    # POST /api/setups with "method": "moka" -> 200, and the setup in the response has no "method" key.
    # POST /api/feedback with "water_g": 250.0 alongside the usual measured fields -> 200.
```
Make `make_setup` and `_setup` stop sending `method` and always create `espresso_machine` machines.

In `tests/test_shots.py`, add `test_classify_requires_yield`: `classify_data_quality(grind_clicks=20, time_s=28, yield_g=None, rating=4, taste_axis="balanced") == "partial"`, and with `yield_g=36.0` it is `"measured"`.

Run: `$T pytest -q tests/test_api_flows.py tests/test_shots.py`
Expected: the new tests FAIL.

- [ ] **Step 6: Implement**

- `models.py`: remove `BrewSetup.method`, `Recommendation.method`, `Recommendation.water_g`, `DialInLog.brew_method` and `DialInLog.water_g`.
- `web_schemas.py`: apply the Produces changes.
- `shots.py`: drop `water_g` and `brew_method` everywhere; `classify_data_quality` requires `yield_g`.
- `setups.serialize_setup`: drop `"method"`.
- `api_schemas.SetupOut`: drop `method`.
- `routes/gear.py`:
  - delete `_infer_method`, `_POUROVER_MODELS` and `_MOKA_MODELS`, and the `method=` assignments in create/update setup;
  - `_setup_equipment` filters the machine on `Equipment.type == "espresso_machine"`;
  - the library's `"machines"` list keeps `item.type == "espresso_machine"`.
- `admin_stats.py`: delete `method_mix` and the `"methods"` key.
- `admin.html`, `admin.js`, `admin.css`: delete `#chart-methods` and its section heading, `renderMethods` and its call, and the CSS used only by them.
- `tests/_db.py`: drop `method="espresso"` and `"brew_method": "espresso"`.
- `tests/test_admin.py`: delete `test_method_mix_counts_each_method_and_names_unspecified`, and any `methods` assertion.
- Regenerate: `$T python -m core.openapi_export`.

- [ ] **Step 7: Run everything**

Run: `$T pytest -q && $T ruff check . && $T ruff format --check . && $T mypy src`
Expected: all pass.

- [ ] **Step 8: Leftover check, then commit**

Run: `grep -rniE "pourover|pour-over|moka|ristretto|lungo|water_g|brew_method|\"filter\"|'filter'|\"other\"" src tests --include=*.py --include=*.js --include=*.html`
Expected: hits only in `src/web/static/app.js` and `index.html` (Task 4), plus unrelated JS `.filter(` calls.

```bash
git add migrations src tests docs/openapi.json
git commit -m "feat(db): migration 0010 drops the brew-method and water columns ..."
```

---

### Task 4: The PWA is espresso-only

**Files:**
- Modify: `src/web/static/index.html` (setup form ~588–606, equipment type select ~629–634, chip ~43), `src/web/static/app.js`, `src/web/static/style.css` (`.setup-chip-method` ~1073, `.setup-item-method` ~1100), `src/web/static/sw.js`, `src/web/static/admin.html` (only the `?v=`)
- Test: `tests/test_web_app.py` (existing assertions, unchanged)

**Interfaces:**
- Consumes: the Task 2 and 3 payloads. Recipes, setups and shots carry no `method` or `water_g`.

- [ ] **Step 1: Make the changes listed in spec §4 "PWA"**

In `app.js`, by name:
- remove `activeSetupMethod`, `METHOD_LABELS`, the `setup-chip-method` text, the `setup-item-method` span in the setup list template, and the `setup-form-method` reads and writes (reset, edit-fill, payload);
- `EQUIPMENT_TYPE_LABELS` keeps `grinder` and `espresso_machine` only;
- the yield label is the constant `'Out (g)'`;
- delete the `currentRecipe?.method === 'moka'` block;
- the recipe card and wizard read `yield_g` only;
- the recipe-for line drops the `· method` suffix.

In `index.html`:
- remove the method `<label>` and the `dialog-hint` under it, and the `setup-chip-method` span;
- relabel "Machine / brewer" to "Espresso machine";
- change the placeholder to `e.g. Home espresso, Work`;
- the equipment type select offers `grinder` and `espresso_machine` only.

The machine select is filled from the library's `machines`, which Task 3 already restricted. Check that no other code path builds it from all equipment. `equipment-machine-caps` toggling (`type === 'grinder'`) stays as it is.

- [ ] **Step 2: Bump the cache**

`sw.js` `CACHE = 'wcda-v50'`. Every `?v=` on CSS/JS tags in `index.html` and `admin.html` moves to the matching value.

- [ ] **Step 3: Verify**

Run: `$T pytest -q tests/test_web_app.py && grep -niE "moka|pour|filter brewer|water_g|\.method\b|METHOD_LABELS|setup-form-method" src/web/static/*.js src/web/static/*.html`
Expected: the tests pass and the grep prints nothing. Request bodies' `method: 'POST'` fetch options do not match `\.method\b`.

- [ ] **Step 4: Commit (no deploy: the owner deploys later, dev first)**

```bash
git add src/web/static
git commit -m "feat(web): espresso-only setup, equipment and shot forms ..."
```

---

### Task 5: Docs

**Files:**
- Modify: `docs/science.md`, `CLAUDE.md`, `README.md`
- Test: `tests/test_science_doc.py` (unchanged since Task 2)

**Interfaces:**
- Consumes: Task 2's constant names and `test_science_doc.py` allowlist.

- [ ] **Step 1: Restructure `docs/science.md` as spec §5 says**

- §1 opens with: "**Scope: espresso only, at one style.** Pour-over, moka, ristretto and lungo were removed on 2026-10-15; their research is kept in [Appendix A](#appendix-other-methods)." The appendix heading carries `{#appendix-other-methods}`.
- Remove the pour schedule / stove power bullet and the "Pour-over and moka get no default bound…" sentence.
- Move §3.4, §3.5, §3.6, §3.7 and the §6 table with its paragraph into `## Appendix A — Not implemented: other methods and styles {#appendix-other-methods}`, before `## 9. Bibliography`. Open the appendix with: "Nothing in this appendix is used by the engine." The subsection headings keep their anchors, renumbered A.1–A.5.
- Renumber §3.8–§3.12 to §3.4–§3.8, and §7/§8 to §6/§7. Do not renumber §9; it is cited as §9.2 in the text.
- In the open-conflicts table, the moka row's middle cells become "Removed: espresso only" and "Research kept in [Appendix A](#appendix-other-methods)".
- Rename every constant name that appears in the prose to its new name. Fix every "§3.x" cross-reference that moved.
- Add `appendix-other-methods` to the `narrative` allowlist in `tests/test_science_doc.py`.

- [ ] **Step 2: `CLAUDE.md` and `README.md`**

- CLAUDE.md, "Decided, don't reopen": replace the Moka bullet with:
  > **Espresso only (2026-10-15).** Pour-over, moka, ristretto and lungo were removed from the engine, API, database (migration 0010) and PWA; equipment is a grinder or an espresso machine. The research is kept in `docs/science.md` Appendix A. When moka returns it needs its own flow: its extract averages ~80 °C and the final sputtering phase extracts the harshest compounds (Navarini 2009), which argues for a heat-cut prompt rather than a grind change.
- Update every other CLAUDE.md line that says "method", "brewer" or "pour-over" in the method sense.
- README: the tagline becomes "An espresso dial-in helper.", plus any other mentions of pour-over or moka.

- [ ] **Step 3: Verify**

Run: `$T pytest -q tests/test_science_doc.py && grep -nE "§3\.(9|1[0-2])|§[78]\b" docs/science.md`
Expected: PASS. Every grep hit must be a renumbered reference that is still correct.

- [ ] **Step 4: Commit (this includes the owner's re-wrap)**

```bash
git add docs/science.md CLAUDE.md README.md tests/test_science_doc.py
git commit -m "docs: espresso only; other methods' research moves to Appendix A ..."
```

- [ ] **Step 5: Final verification across the branch**

```bash
$T pytest -q && $T ruff check . && $T ruff format --check . && $T mypy src
grep -rniE "pourover|pour-over|moka|ristretto|lungo|water_g|brew_method" src tests
```
Expected: all green, and the grep prints nothing. Migrations are outside `src`/`tests`, and Appendix A is in `docs`.

Update `docs/SESSION-STATE.md`: Now = "espresso-only done on branch, not merged/pushed/deployed; deploy dev first, then prod (spec Deploy section)". Do not stage it.
