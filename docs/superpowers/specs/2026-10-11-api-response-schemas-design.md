# API response schemas and a committed OpenAPI contract

Date: 2026-10-11 · Status: approved design, not yet implemented

## Goal

The HTTP API between the PWA (`app.js`) and FastAPI is documented only by its
request models. Responses are hand-built `dict`s, so `/openapi.json` has empty
response schemas. We want:

1. **Browsable documentation** of every request *and* response.
2. **A tested contract**: a change to any response field is visible in review
   and cannot silently drop a field the frontend reads.

Nothing is served at runtime: the schema lives in the repo as
`docs/openapi.json`, kept fresh by a test.

## Non-goals

- Changing any response shape or any serializer's logic.
- Serving Swagger UI / ReDoc anywhere (dev or prod).
- Checking `app.js` field usage against the schema automatically.
- Documenting the dev-only admin dashboard API.

## Design

### Response models — `src/core/api_schemas.py` (new)

Request models stay in `web_schemas.py`; response models go in a new
`api_schemas.py`, one class per JSON object the API returns.

Shared pieces:

- `EquipmentOut` — the 17 fields of `setups.serialize_equipment`.
- `SetupOut` — `serialize_setup` (`grinder`/`machine` are `EquipmentOut`).
- `TargetOut` — `tr_lo`, `tr_hi`, `time_lo`, `time_hi`, `ratio_aim`; used by
  `/api/fit` and `/api/beans/{id}/shots`.
- `StatusOut` — `{"status": str}` for the delete routes.

Per area:

- Recipe: `RecipeOut`, `RationaleOut`, `SuggestionOut`, `RecommendationOut`
  (`coffee_data`, `recommendation_id`, plus `engine.serialize_result`'s keys),
  returned by `POST /api/analyze` and `POST /api/recommendation`.
- `CoffeeDataOut` — the bean fields from `beans.bean_coffee_data` plus
  `preferred_dose_g`, `dose_from_roast`, and the optional `bean_id`,
  `image_name`. **`extra="allow"`**: it carries whatever the vision OCR
  returned, which is not fixed.
- Fit (`GET /api/fit`, `engine.serialize_fit`): `FitOut` with `LawOut`,
  `FitBeanOut`, `FitShotOut`, `PairOut`, `RejectedPairOut`, `TargetOut`,
  `ClicksReasonOut` (floor and warning), `GrinderCapsOut`, `FitRecipeOut`;
  `pairs_rejected_by_reason` is `dict[str, int]`.
- Library: `CoffeeListOut` / `CoffeeEntryOut` / `LatestLogOut`
  (`GET /api/logs`), `BeanShotsOut` / `BeanRefOut` / `BeanShotOut`
  (`GET /api/beans/{id}/shots`), `BeanSavedOut` (`status`, `bean_id`: manual
  create, update, feedback).
- Gear: `ActiveEquipmentOut`, `EquipmentLibraryOut`, `EquipmentSavedOut`,
  `SetupsOut`, `SetupSavedOut`, `SetupSelectedOut`, `DoseOut`,
  `DoseSavedOut`.
- Meta: `VersionOut`, `WhoamiOut`.

The exact class list may merge or split during implementation; the rules
below are what matters.

### Strictness rules (the contract)

1. **`model_config = ConfigDict(extra="forbid")`** on every model except
   `CoffeeDataOut`. FastAPI validates the returned dict against the model; an
   unknown key raises `ResponseValidationError` (HTTP 500) instead of being
   silently filtered out. A field added to a serializer but not to its model
   therefore fails tests rather than vanishing from the response.
2. **Every field is required, with no default.** Nullable fields are typed
   `X | None` but must still be present. A missing key is an error too.
   Exception: `CoffeeDataOut`. `POST /api/recommendation` echoes back whatever
   `coffee_data` the client sent, so only the two keys the server always sets
   (`preferred_dose_g`, `dose_from_roast`) are required; the bean fields
   (`name`, `roaster`, `origin`, `process`, `roast_level`, `roast_date`),
   `bean_id` and `image_name` default to `None`, and this is documented on the
   model.
3. **Types describe today's JSON, not a richer one.** Timestamps and dates are
   `str` (the code sends `isoformat()`; typing them `datetime` would make
   FastAPI reformat them). Numbers are `float` (or `int` where the source is an
   integer id/count). The only visible wire change allowed: an integral float
   may serialise as `18.0` instead of `18`.
4. **`Literal` only where the value set is closed in code** (`band`:
   `"in" | "fast" | "long"`, `direction`: `"finer" | "coarser"`). Anything
   whose value set cannot be read off the code stays `str`.

### Routes

Every JSON route gets `response_model=<Model>` in its decorator. Function
bodies, the `-> dict[str, Any]` annotations and the serializers are unchanged.
Routes returning `FileResponse` (`/`, `/sw.js`, `/api/log-images/{name}`) and
`/healthz` are left as they are. `GET /api/admin/stats` gets
`include_in_schema=False` so the generated schema does not depend on whether
the admin variables are set on the machine generating it.

### Runtime

`FastAPI(..., openapi_url=None)` — this removes `/openapi.json`, `/docs` and
`/redoc` from both instances (today all three are reachable; the UIs render
blank under the CSP). `app.openapi()` still works in-process.

### Export — `src/core/openapi_export.py` (new)

- `render() -> str`: `json.dumps(app.openapi(), indent=2, sort_keys=True,
  ensure_ascii=False) + "\n"`.
- `main()`: writes `render()` to `docs/openapi.json`.
- Run: `python -m core.openapi_export`. Needs no database (importing the app
  creates the SQLAlchemy engine lazily; no connection is opened).
- `docs/openapi.json` is committed, so every contract change shows as a diff.
- Browsing: open `docs/openapi.json` in an OpenAPI preview extension or any
  local viewer.

## Testing — `tests/test_openapi.py` (new, no database)

1. **Freshness:** `render()` equals the committed `docs/openapi.json`; the
   failure message names the regeneration command.
2. **Coverage:** every `/api/*` operation in the schema has a `200` response
   with a `$ref` schema (not the empty default), so a new route cannot skip
   the contract.
3. **Closed:** `GET /openapi.json`, `/docs`, `/redoc` return 404.
4. **Serializer vs. model:** the outputs of `serialize_result`,
   `serialize_fit`, `serialize_equipment` and `serialize_setup` validate
   against their models, covering both branches of each conditional field
   (`suggestion` `None` and set; `warning` empty and set).

`tests/test_api_flows.py` needs no changes: with `extra="forbid"` and required
fields it becomes the end-to-end contract check, since any mismatch is a 500.

## Documentation

- README "Tests and checks": the regeneration command.
- CLAUDE.md:
  - Layout: `api_schemas.py` (responses) beside `web_schemas.py` (requests);
    `docs/openapi.json` and `openapi_export.py`.
  - Rule: changing a response shape means updating its model in
    `api_schemas.py` and regenerating `docs/openapi.json`.
  - Gotcha: a serializer key missing from its model is a 500, by design.

## Risks and rollout

- **Main risk:** a response branch no test reaches returns a dict that does
  not match its model and 500s in production. Mitigated by the per-branch
  serializer tests and `test_api_flows.py`; if it happens, `docker logs` names
  the exact field.
- No static asset changes, so no `sw.js` cache bump.
- Shipping to prod uses the `deploy` skill, when the owner asks.
