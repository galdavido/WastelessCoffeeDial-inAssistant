# API Response Schemas Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every JSON route a strict Pydantic response model, turn off runtime OpenAPI/docs, and commit the generated schema as `docs/openapi.json`, guarded by a freshness test.

**Architecture:** Response models live in a new `src/core/api_schemas.py` and are attached with `response_model=` in each route decorator; route bodies and serializers do not change. `extra="forbid"` + required fields make any serializer/model mismatch a 500 that tests catch. `src/core/openapi_export.py` renders `app.openapi()` deterministically; a test compares it to the committed file.

**Tech Stack:** FastAPI 0.135, Pydantic 2.12, pytest/unittest, Docker for the test runner.

**Spec:** `docs/superpowers/specs/2026-10-11-api-response-schemas-design.md`

## Global Constraints

- Do not change any serializer's output or any route's logic; only add `response_model=`, models, export, tests, docs.
- Every response model: `model_config = ConfigDict(extra="forbid")`, every field required with no default, nullable fields typed `X | None`. **Only exception:** `CoffeeDataOut` (`extra="allow"`; only `preferred_dose_g: float` and `dose_from_roast: bool` required; `bean_id`, `image_name`, `name`, `roaster`, `origin`, `process`, `roast_level`, `roast_date` default to `None`).
- Timestamps/dates are `str` (never `datetime`/`date`). Measurements are `float`; ids and counts are `int`. Take nullability and int-vs-float from the source: the dataclass (`Recipe`, `ShotRecord`, `DoseReduction`, `GrinderCaps`, `Target` in `core/brewing.py`; `Calibration` in `core/calibration.py`) or the SQLAlchemy column in `src/database/models.py`. A value passed through `as_float()` is `float | None`.
- `Literal` only for closed sets: reuse `Method` and `Basis` from `core.brewing`; `band: Literal["in", "fast", "long"] | None`; `direction: Literal["finer", "coarser"] | None`. Everything else whose values are not closed in code is `str`.
- Route functions keep their `-> dict[str, Any]` annotations.
- Commits need pre-commit on PATH: prefix with `export PATH="/c/Users/galda/AppData/Roaming/Python/Python314/Scripts:$PATH" &&`. End each message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Work on branch `feat/api-response-schemas`.
- **Test runner** (the host has no Python deps). Set once per shell:
  `T="docker exec -e DATABASE_URL=postgresql+psycopg2://wcda:wcda@wcda-test-pg:5432/wcda_test wcda-test"`, then run commands as `$T pytest -q`.
  Lint/types: `$T ruff check . && $T ruff format --check . && $T mypy src` (run each with `$T`).

## Review Focus

1. **A new bag with no library match** (`/api/analyze`, transient bean): `recommendation_id` is `None` and `coffee_data` has no `bean_id`. It must validate, not 500. Test: Task 2 `test_transient_bean_payload_validates`.
2. **A client sending a sparse `coffee_data`** to `/api/recommendation` (e.g. only `name`): the echo must validate, and unknown keys must survive in the response. Test: Task 2 `test_coffee_data_keeps_unknown_keys_and_tolerates_missing_ones`.
3. **Integral values in int fields arriving as floats** (`Numeric` columns, `grind_clicks` 29.0): a field mis-typed `int` would 500 on 29.5. Covered by the typing rule above and by Task 3's serializer tests with real `ShotRecord`s. Reviewer: check each `int` field against its source column.
4. **The fit view's conditional branches**: `suggestion` set, `warning` populated, empty history. Tests: Tasks 2 and 3.
5. **Windows checkout of `docs/openapi.json`**: `.gitattributes` forces LF and `Path.read_text()` normalises newlines, so the freshness test must compare `read_text()` output, never raw bytes. Test: Task 5 `test_committed_schema_is_fresh`.

---

### Task 1: Test runner, shared and gear/meta models

**Files:**
- Create: `src/core/api_schemas.py`
- Create: `tests/test_api_schemas.py`
- Modify: `src/core/routes/gear.py` (decorators at lines 151, 160, 180, 198, 226, 250, 268, 294, 305, 327, 366, 373)
- Modify: `src/core/routes/meta.py` (decorators at lines 64, 75)

**Interfaces:**
- Produces in `core.api_schemas`: `StatusOut(status: str)`, `EquipmentOut` (the 17 keys of `setups.serialize_equipment`, in its order), `SetupOut(id, name, method: str, grinder: EquipmentOut, machine: EquipmentOut)`, `EquipmentNameOut(brand, model)`, `ActiveEquipmentOut(grinder, machine: EquipmentNameOut)`, `EquipmentLibraryOut(grinders, machines: list[EquipmentOut])`, `EquipmentSavedOut(status, equipment: EquipmentOut)`, `SetupsOut(active_setup_id: int, setups: list[SetupOut])`, `SetupSavedOut(status, setup: SetupOut)`, `SetupSelectedOut(status, setup_id: int)`, `DoseOut(dose_g: float)`, `DoseSavedOut(status, dose_g: float)`, `VersionOut(asset_version: int | None, engine_version: <type of ENGINE_VERSION>)`, `WhoamiOut(owner: str, auth_mode: str)`, and a private base `_Strict(BaseModel)` carrying `ConfigDict(extra="forbid")` that every strict model subclasses.

- [ ] **Step 1: Start the test containers (once per session)**

```bash
cd "C:/Users/galda/OneDrive/code/BaristAI"
docker network create wcda-test-net
docker run -d --rm --name wcda-test-pg --network wcda-test-net -e POSTGRES_USER=wcda -e POSTGRES_PASSWORD=wcda -e POSTGRES_DB=wcda_test postgres:16-alpine
MSYS_NO_PATHCONV=1 docker run -d --rm --name wcda-test --network wcda-test-net -v "C:/Users/galda/OneDrive/code/BaristAI:/app" -w /app python:3.14-slim sleep infinity
docker exec wcda-test pip install -q -e '.[dev]'
$T pytest -q
```
Expected: the existing suite passes (baseline). If anything fails here, stop and report it; it is not this plan's regression.

- [ ] **Step 2: Write the failing tests** in `tests/test_api_schemas.py` (unittest style like `tests/test_fit_view.py`):
  - `test_equipment_serializer_matches_model`: build an unsaved `Equipment(...)` with every column set, then `EquipmentOut.model_validate(serialize_equipment(item, "me"))`; also with all nullable capability columns `None`.
  - `test_setup_serializer_matches_model`: an unsaved `BrewSetup` with `grinder`/`machine` relationships set to unsaved `Equipment` rows; `SetupOut.model_validate(serialize_setup(setup))`.
  - `test_strict_models_reject_unknown_keys`: `EquipmentOut.model_validate({**valid, "surprise": 1})` raises `ValidationError`.
  - `test_strict_models_reject_missing_keys`: dropping `"spec_source"` from a valid dict raises `ValidationError`.

- [ ] **Step 3: Run to verify they fail**

Run: `$T pytest -q tests/test_api_schemas.py`
Expected: FAIL, `ModuleNotFoundError: No module named 'core.api_schemas'`.

- [ ] **Step 4: Create `src/core/api_schemas.py`** with the models listed under Interfaces. Module docstring: responses live here, requests in `web_schemas.py`, and why `extra="forbid"` (an unmodelled key is a 500, not a silently dropped field).

- [ ] **Step 5: Run to verify they pass**

Run: `$T pytest -q tests/test_api_schemas.py`
Expected: PASS.

- [ ] **Step 6: Wire the routes.** Add `response_model=` to each gear and meta decorator:

| Route | Model |
|---|---|
| `GET /api/equipment` | `ActiveEquipmentOut` |
| `GET /api/equipment/library` | `EquipmentLibraryOut` |
| `POST`/`PUT /api/equipment/library…` | `EquipmentSavedOut` |
| `DELETE /api/equipment/library/{id}`, `DELETE /api/setups/{id}` | `StatusOut` |
| `GET /api/setups` | `SetupsOut` |
| `POST /api/setups`, `PUT /api/setups/{id}` | `SetupSavedOut` |
| `PUT /api/setups/active` | `SetupSelectedOut` |
| `GET /api/settings` | `DoseOut` |
| `PUT /api/settings/dose` | `DoseSavedOut` |
| `GET /api/version` | `VersionOut` |
| `GET /api/whoami` | `WhoamiOut` |

- [ ] **Step 7: Run the full suite, including the API flows**

Run: `$T pytest -q`
Expected: PASS, with `tests/test_api_flows.py` *running* (not skipped). A `ResponseValidationError` names the field and route to fix in the model.

- [ ] **Step 8: Lint, types, commit**

```bash
git add src/core/api_schemas.py tests/test_api_schemas.py src/core/routes/gear.py src/core/routes/meta.py
git commit -m "feat(api): response models for gear and meta routes"
```

---

### Task 2: Recommendation models

**Files:**
- Modify: `src/core/api_schemas.py`
- Modify: `tests/test_api_schemas.py`
- Modify: `src/core/routes/recipe.py` (decorators at lines 110, 155, 247)

**Interfaces:**
- Consumes: `_Strict` from Task 1.
- Produces: `RecipeOut` (the 13 keys of `serialize_result()["recipe"]`; `method: Method`, `basis: Basis`, `guardrails_hit: list[str]`), `RationaleOut(headline, why, what_to_watch: str)`, `SuggestionOut(kind: Literal["use_less_coffee"], dose_g: float, yield_g: float | None, grind_clicks: float | None, channeled_shots: int, note: str)`, `CoffeeDataOut` (see Global Constraints), `RecommendationOut(coffee_data: CoffeeDataOut, recommendation_id: int | None, recipe: RecipeOut, rationale: RationaleOut, confidence_label: str, tier: str, protocol: str | None, suggestion: SuggestionOut | None)`, `BeanSavedOut(status: str, bean_id: int)`.

- [ ] **Step 1: Write the failing tests.** Build an `EngineResult` the way `tests/test_fit_view.py::_result` does (import the helper's pattern, not the module), then:
  - `test_recommendation_payload_validates`: `RecommendationOut.model_validate({"coffee_data": {"preferred_dose_g": 18.0, "dose_from_roast": False, "bean_id": 7}, "recommendation_id": 3, **serialize_result(result)})`.
  - `test_suggestion_branch_validates`: the same with `dataclasses.replace(result, suggestion=DoseReduction(dose_g=16.0, yield_g=32.0, grind_clicks=31.0, channeled_shots=2, note="n"))`; assert `payload.suggestion.kind == "use_less_coffee"`.
  - `test_transient_bean_payload_validates`: `recommendation_id=None`, `coffee_data` without `bean_id`.
  - `test_coffee_data_keeps_unknown_keys_and_tolerates_missing_ones`: `CoffeeDataOut.model_validate({"preferred_dose_g": 18.0, "dose_from_roast": True, "name": "X", "varietal": "Bourbon"}).model_dump()` contains `"varietal": "Bourbon"` and `"origin": None`; and omitting `preferred_dose_g` raises `ValidationError`.

- [ ] **Step 2: Run to verify they fail**

Run: `$T pytest -q tests/test_api_schemas.py`
Expected: FAIL with `ImportError` on `RecommendationOut`.

- [ ] **Step 3: Add the models** listed under Interfaces to `api_schemas.py`. `CoffeeDataOut` docstring says why it is loose: `/api/recommendation` echoes the client's `coffee_data`, and OCR output is not fixed.

- [ ] **Step 4: Run to verify they pass**

Run: `$T pytest -q tests/test_api_schemas.py`
Expected: PASS.

- [ ] **Step 5: Wire** `POST /api/analyze` and `POST /api/recommendation` → `RecommendationOut`; `POST /api/feedback` → `BeanSavedOut`.

- [ ] **Step 6: Run the full suite**

Run: `$T pytest -q`
Expected: PASS, API flows running.

- [ ] **Step 7: Lint, types, commit**

```bash
git add src/core/api_schemas.py tests/test_api_schemas.py src/core/routes/recipe.py
git commit -m "feat(api): response models for the recommendation routes"
```

---

### Task 3: Fit view model

**Files:**
- Modify: `src/core/api_schemas.py`
- Modify: `tests/test_api_schemas.py`
- Modify: `src/core/routes/recipe.py` (decorator at line 195)

**Interfaces:**
- Consumes: `_Strict`.
- Produces: `TargetOut(tr_lo, tr_hi, time_lo, time_hi, ratio_aim)` (types from `brewing.Target`; reused by Task 4), `LawOut` (the 19 keys of `serialize_fit()["law"]`), `FitBeanOut(id: int, name: str, delta_bean: float, is_current: bool)`, `FitShotOut` (the 17 keys per shot), `PairOut(slope: float | None, a_index: int, b_index: int, bean_id: int | None)`, `RejectedPairOut(a_index, b_index: int, bean_id, other_bean_id: int | None, reason: str)`, `ClicksReasonOut(clicks: float | None, reason: str | None)` (both `floor` and `warning`), `GrinderCapsOut` (the 5 keys of `serialize_fit()["grinder"]`), `FitRecipeOut(grind_clicks: float | None, basis: Basis, guardrails_hit: list[str])`, `FitOut(law, beans, shots, pairs, pairs_rejected, pairs_rejected_by_reason: dict[str, int], target, floor, warning, grinder, recipe)`.

- [ ] **Step 1: Write the failing tests**, reusing the `HISTORY`/`_result` fixture pattern of `tests/test_fit_view.py` (copy the minimal fixture; do not import a test module):
  - `test_fit_payload_validates`: `FitOut.model_validate(serialize_fit(_result(), NAMES, RWANDA))`.
  - `test_fit_payload_with_an_excluded_shot_validates`: the history plus the 88 °C lonely shot from `test_an_excluded_shot_says_why_and_the_reason_holds`; assert some `shots[i].excluded_reason` is a non-empty string.
  - `test_empty_history_fit_validates`: the empty-history `EngineResult` from `TestItStaysHonestWithNothingToShow`.
  - `test_populated_warning_validates`: take the first payload, set `payload["warning"] = {"clicks": 27.0, "reason": "one channeling sign"}`, validate.

- [ ] **Step 2: Run to verify they fail**

Run: `$T pytest -q tests/test_api_schemas.py`
Expected: FAIL with `ImportError` on `FitOut`.

- [ ] **Step 3: Add the models.**

- [ ] **Step 4: Run to verify they pass**

Run: `$T pytest -q tests/test_api_schemas.py`
Expected: PASS.

- [ ] **Step 5: Wire** `GET /api/fit` → `FitOut`.

- [ ] **Step 6: Run the full suite**

Run: `$T pytest -q`
Expected: PASS.

- [ ] **Step 7: Lint, types, commit**

```bash
git add src/core/api_schemas.py tests/test_api_schemas.py src/core/routes/recipe.py
git commit -m "feat(api): response model for the fit view"
```

---

### Task 4: Coffee library models

**Files:**
- Modify: `src/core/api_schemas.py`
- Modify: `tests/test_api_schemas.py`
- Modify: `src/core/routes/coffees.py` (decorators at lines 53, 122, 240, 263, 304)

**Interfaces:**
- Consumes: `_Strict`, `TargetOut` (Task 3), `BeanSavedOut` and `StatusOut` (Tasks 1–2).
- Produces: `LatestLogOut` (the 12 keys of `latest_log` in `list_coffees`), `CoffeeEntryOut` (its 10 keys; `latest_log: LatestLogOut | None`), `CoffeeListOut(entries: list[CoffeeEntryOut])`, `BeanRefOut(id: int, name: str, roaster: str | None)`, `BeanShotOut` (the 21 keys per shot in `get_bean_shots`; `band`/`direction` Literals per Global Constraints), `BeanShotsOut(bean: BeanRefOut, target: TargetOut, shots: list[BeanShotOut])`.

These dicts are built inline in the routes, so their check is end-to-end through `tests/test_api_flows.py`; the unit tests only pin the loose ends.

- [ ] **Step 1: Write the failing tests:**
  - `test_coffee_entry_without_shots_validates`: a `CoffeeEntryOut` dict with `last_brewed_at=None`, `logs_count=0`, `latest_log=None`.
  - `test_bean_shot_rejects_an_unknown_band`: a valid `BeanShotOut` dict validates; the same with `band="slow"` raises `ValidationError`.

- [ ] **Step 2: Run to verify they fail**

Run: `$T pytest -q tests/test_api_schemas.py`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Add the models.**

- [ ] **Step 4: Run to verify they pass**

Run: `$T pytest -q tests/test_api_schemas.py`
Expected: PASS.

- [ ] **Step 5: Wire:** `GET /api/logs` → `CoffeeListOut`; `GET /api/beans/{bean_id}/shots` → `BeanShotsOut`; `POST /api/logs/manual`, `PUT /api/logs/{bean_id}` → `BeanSavedOut`; `DELETE /api/logs/{bean_id}` → `StatusOut`.

- [ ] **Step 6: Run the full suite**

Run: `$T pytest -q`
Expected: PASS, API flows running. Confirm that `test_api_flows.py` calls both `GET /api/logs` and `GET /api/beans/{id}/shots` with at least one logged shot; if either is never called, add one flow test that is (CLAUDE.md: new API behaviour gets a test there).

- [ ] **Step 7: Lint, types, commit**

```bash
git add src/core/api_schemas.py tests/test_api_schemas.py src/core/routes/coffees.py tests/test_api_flows.py
git commit -m "feat(api): response models for the coffee library"
```

---

### Task 5: Close runtime docs, export the schema, guard it

**Files:**
- Modify: `src/core/web_server.py:74`
- Modify: `src/core/admin_routes.py` (the `/api/admin/stats` decorator)
- Create: `src/core/openapi_export.py`
- Create: `docs/openapi.json` (generated)
- Create: `tests/test_openapi.py`
- Modify: `README.md` ("Tests and checks"), `CLAUDE.md` ("Layout", "Tests, lint, types", "Gotchas")

**Interfaces:**
- Consumes: all routes wired in Tasks 1–4.
- Produces: `core.openapi_export.SCHEMA_PATH: Path` (`<repo>/docs/openapi.json`, from `Path(__file__).resolve().parents[2]`), `render() -> str` (`json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"`), `main() -> None` (writes `render()` to `SCHEMA_PATH` with `newline="\n"`, encoding utf-8, and prints the path), runnable as `python -m core.openapi_export`.

- [ ] **Step 1: Write the failing tests** in `tests/test_openapi.py` (DB-free; `TestClient(app)` without the context manager, as in `tests/test_web_app.py`):
  - `test_runtime_docs_are_closed`: `GET /openapi.json`, `/docs`, `/redoc` each return 404.
  - `test_every_api_route_has_a_response_schema`: for every path starting with `/api/` and every method in `app.openapi()["paths"]`, `responses["200"]["content"]["application/json"]["schema"]` contains a `$ref`, except `GET /api/log-images/{image_name}`. Collect all offenders and assert the list is empty, so the message names them all.
  - `test_admin_route_is_not_in_the_schema`: `"/api/admin/stats" not in app.openapi()["paths"]` with the admin env vars set (patch `os.environ`, build a fresh `FastAPI` app, call `register_admin_routes(app, ...)`, then check its `openapi()["paths"]`).
  - `test_committed_schema_is_fresh`: `SCHEMA_PATH.read_text(encoding="utf-8") == render()`, failure message: `"docs/openapi.json is stale: run `python -m core.openapi_export` and commit it"`.

- [ ] **Step 2: Run to verify they fail**

Run: `$T pytest -q tests/test_openapi.py`
Expected: FAIL: docs routes answer 200, `core.openapi_export` missing.

- [ ] **Step 3: Implement:** `openapi_url=None` in the `FastAPI(...)` call (one comment: no runtime schema or docs UI; the contract is `docs/openapi.json`); `include_in_schema=False` on the admin stats route (one comment: keeps the generated schema independent of the generating machine's env); create `openapi_export.py` per Interfaces.

- [ ] **Step 4: Generate the schema**

Run: `$T python -m core.openapi_export`
Expected: prints the path; `docs/openapi.json` exists and `git diff --stat` shows it as new.

- [ ] **Step 5: Run to verify they pass**

Run: `$T pytest -q tests/test_openapi.py`
Expected: PASS.

- [ ] **Step 6: Docs.**
  - README "Tests and checks": after the lint block, the line `python -m core.openapi_export   # regenerate docs/openapi.json after changing a response` and one sentence that `tests/test_openapi.py` fails until it is regenerated; mention `docs/openapi.json` in "Project layout".
  - CLAUDE.md "Layout": `api_schemas.py` (response models) beside `web_schemas.py` (request models); `openapi_export.py` writes `docs/openapi.json`.
  - CLAUDE.md "Tests, lint, types": changing a response shape means updating its model in `api_schemas.py` and regenerating `docs/openapi.json`; there is no runtime `/openapi.json` or `/docs`.
  - CLAUDE.md "Gotchas": response models are `extra="forbid"` with required fields, so a serializer key missing from its model is a 500 (`ResponseValidationError` names the field), by design; `CoffeeDataOut` is the one loose model.

- [ ] **Step 7: Full verification**

Run: `$T pytest -q`, then `$T ruff check .`, `$T ruff format --check .`, `$T mypy src`
Expected: all pass, API flows running.

- [ ] **Step 8: Commit**

```bash
git add src/core/web_server.py src/core/admin_routes.py src/core/openapi_export.py docs/openapi.json tests/test_openapi.py README.md CLAUDE.md
git commit -m "feat(api): commit the OpenAPI schema and close runtime docs"
```

- [ ] **Step 9: Clean up the test containers**

```bash
docker rm -f wcda-test wcda-test-pg && docker network rm wcda-test-net
```
