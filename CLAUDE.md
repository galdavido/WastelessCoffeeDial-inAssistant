# CLAUDE.md

Guidance for working in this repo.

## What this is

**Wasteless Coffee Dial-in Assistant** — a FastAPI + Google Gemini espresso
dial-in helper with a vanilla-JS PWA frontend. Scan a coffee bag, get a
grind/dose/temperature recipe informed by your own past logs (RAG over a
Postgres history).

## Session state — read this first

`docs/SESSION-STATE.md` is the working memory for whatever task is in flight,
so it survives a disconnect or a context reset. It is deliberately separate
from the three things that already exist: this file is durable repo truth,
auto-memory holds cross-session lessons, and `git log` is what shipped —
none of them hold "where are we in this job."

- **First action of every ask:** read `docs/SESSION-STATE.md`.
- **Update it after any meaningful step**, and *always before* a long or
  risky operation (deploy, migration, container rebuild) so an interruption
  mid-op is recoverable.
- **On task completion:** move `Now` into `Done this thread`, clear
  `Next steps`, promote anything under `System notes discovered` into this
  file or auto-memory, and trim `Done this thread` back to ~10 lines.
- Keep every section short — it is working memory, not a changelog.
- **Commit discipline:** fold the state update into the task's own commit;
  if a task produces no code commit, a standalone `docs: session state`
  commit is fine.

## Layout

- `src/core/routes/` — the HTTP API, one `APIRouter` per area: `meta` (shell,
  health, version, whoami), `recipe` (scan, recommendation, feedback, photos),
  `coffees` (library + shot history), `gear` (equipment, setups, settings).
  `common.py` holds `STATIC_DIR`, `uploads_dir()` and the request-scoped
  `active_setup` dependency.
- `src/core/` — `web_server.py` (entry), `web_helpers.py`, `web_schemas.py`,
  `auth.py`, DB bootstrap/session, and the engine: `engine.py` orchestrates
  `retrieval.py` → `calibration.py` → `brewing.py` (pure, no DB) → rationale.
  `eval_harness.py` + `backtest_cli.py` measure it. `admin_*.py` is the
  dev-only dashboard.
- `src/ai/` — the two Gemini calls: `vision.py` (bag OCR), `rationale.py`
  (prose around numbers the engine already fixed); `model_selection.py` holds
  the model fallback chain and the shared `json_config()`.
- `src/database/` — SQLAlchemy 2.0 models + engine (the one place `.env` is
  loaded).
- `src/web/static/` — the PWA: `index.html`, `app.js`, `style.css`, `sw.js`.
- `migrations/` — Alembic. `tests/` — pytest; `_sim.py` (physics simulator,
  a test fixture) and `_db.py` (real-Postgres test support) live there.
- Package layout: code lives under `src/` (`pyproject.toml` `package-dir`).

## Running it

The two stacks run side by side on one host, so they must not share a port:
**dev owns `8082`, prod owns `8081`.**

- **Dev:** `docker compose up --build` (compose.yaml, project `wcda`).
  Single-user (`WCDA_AUTH_MODE=single`). Web published on all interfaces at
  port `8082` → reachable on the LAN at `http://192.168.50.202:8082`, Postgres
  on `127.0.0.1:5434`. Despite the name this is **not** a scratch instance —
  it is the one used day to day, and its DB holds the real bean/shot history.
  Treat its data like production data; it has its own nightly `db-backup`.
- **Prod (friends):** `docker compose -f compose.prod.yaml --env-file .env up
  -d --build` (compose.prod.yaml, project `wcda-prod`). Multi-user
  (`WCDA_AUTH_MODE=tailscale`): per-user data keyed on the `Tailscale-User-Login`
  header. The web port is bound to **loopback only** (`127.0.0.1:8081`) and
  fronted on the host by:
  ```
  sudo tailscale serve --bg --https=443 http://127.0.0.1:8081
  ```
  Friends reach it at the tailnet HTTPS URL, not on the LAN. `WCDA_PROD_BIND`
  can widen that bind address, but **only** together with
  `WCDA_AUTH_MODE=single` — publishing on `0.0.0.0` while in `tailscale` mode
  lets anyone on the LAN forge the identity header. DB is internal-only; the
  web container is `read_only` with `cap_drop: ALL`.
- Identity headers are populated for tailnet users, **including external users
  who accepted a node share** — that is what lets friends in — but never for
  *tagged* devices, which is the usual cause of an unexpected 401.
  `GET /api/whoami` reports the resolved owner and mode, and touches no DB.
- Host-side Tailscale setup (Serve, the ACL that keeps shared friends off this
  box's other services, inviting people, claiming pre-multi-user rows):
  **`docs/tailscale-setup.md`**.
- **Admin dashboard (dev only):** `/admin` on 8082 shows how much the friends
  instance is used and how, read live from the **prod** database through a
  `SELECT`-only role. It is mounted only when both `WCDA_ADMIN_DATABASE_URL`
  and `WCDA_ADMIN_TOKEN` are set -- that is the dev instance and never prod, so
  prod's attack surface is unchanged. Bring it up with the overlay:
  `docker compose -f compose.yaml -f compose.admin.yaml up -d --build`.
  The overlay is separate because it joins `wcda-prod_backend`, and a missing
  external network is a hard startup failure: folding it into `compose.yaml`
  would stop the daily driver whenever the prod stack is down. Create the role
  once with `scripts/create_readonly_role.sql`.
- **A container on two compose networks resolves a bare service name to
  whichever stack answers first.** Both projects have a service called `db`, so
  once the overlay put the dev web container on `wcda-prod_backend` its plain
  `db` started resolving to the *prod* database: the dev app read the friends'
  rows for half a day and showed an empty list, because the dev owner owns
  nothing there. Nothing was written, but only by luck. So: the dev database is
  addressed **only** as `wcda-dev-db` (a network alias that exists on one
  network), the admin URL uses the **container** name `wcda-prod-db-1`, and
  `tests/test_admin.py` fails if a bare `db` comes back. The app logs
  `Database: ...` at startup — check it in `docker logs` when data looks
  missing.
- To ship a change to the running prod app, use the **`deploy` skill**.
- App process: `python -m core.web_server`; honours `WCDA_HOST` / `WEB_PORT`.

## Database

- **PostgreSQL 16.** No migration uses the `vector` extension (the
  `scraped_equipment.embedding` table this note used to warn about lived in
  the pre-Alembic database discarded on 2026-09-08), and CI and the tests run
  on plain `postgres:16`. The compose stacks still use `pgvector/pgvector:pg16`:
  leave that alone — swapping the image under a live volume is risk for no
  gain. To confirm on the host: `\dx` and `\dt scraped_equipment` in `psql`.
- SQLAlchemy 2.0 + Alembic. `run_migrations()` runs `alembic upgrade head` on
  startup (lifespan), retrying while the DB comes up. Migrations are
  hand-written; never autogenerate.
- **Equipment is shared but owned.** Everyone can pick any entry for a setup;
  only `equipment.owner` may edit or delete it, and owner-NULL rows (the
  seeded hardware) are read-only. Migration 0007 backfilled owners — see
  `docs/tailscale-setup.md` for reassigning a row.
- Env comes from `.env` (gitignored): `POSTGRES_USER/PASSWORD/DB`,
  `DATABASE_URL`, `GEMINI_API_KEY`. Template: `.env.example`.
- Daily dumps land in `./backups/db/` (prod) and `./backups/dev-db/` (dev) via
  the `db-backup` compose service in each stack (`backups/` is gitignored).
  **Despite the `.sql.gz` name these dumps are plain, uncompressed SQL**, so
  the restore is a straight redirect — piping them through `gunzip` fails with
  "not in gzip format":
  `docker compose -f compose.prod.yaml exec -T db psql -U barista -d
  barista_db < backups/db/last/<file>.sql.gz`.
  **`docker compose up -d --build web` starts only `web` and its `depends_on`,
  never `db-backup`** — bring the stack up without naming a service, or the
  nightly dump quietly never runs.
- **Volume names follow the compose project name, so renaming a project
  orphans its data.** Adding `name: wcda` / `name: wcda-prod` in 2026-08 detached
  the original `wastelesscoffeedial-inassistant_postgres_data` (PG **15**) and
  `..._log_images`; both stacks then came up on new, empty volumes. **That old
  database was deliberately discarded on 2026-09-08** — the owner confirmed the
  history in it was not wanted — and the volume plus its `wcda_rescue_pg15` copy
  were deleted. Do not go looking for it again: the live data is
  `wcda_postgres_data` (dev) and `wcda-prod_postgres_data` (prod), and dev's
  history starts 2026-09-06. `wastelesscoffeedial-inassistant_log_images` is
  still dangling.
- Still **never run `docker volume prune` or `docker system prune --volumes`**
  here: the two stacks' live volumes are only ever attached while their
  containers exist, and a stopped stack's data would go with it. Check
  `docker volume ls` before assuming a fresh start is safe.

## Tests, lint, types

- `pytest` — config in `pyproject.toml`, `pythonpath = ["src"]`. Almost
  everything is DB-free. `tests/test_api_flows.py` drives the real routes,
  engine and Postgres with only the Gemini calls stubbed, one fresh
  Tailscale user per test; it needs `DATABASE_URL` pointing at a disposable
  database, skips when none is reachable, and **fails** instead when `CI` is
  set. New API behaviour gets a test there.
- `ruff check .` and `ruff format --check .`; `mypy src`.
- Dev install: `pip install -e '.[dev]'` (or run the checks in a throwaway
  `python:3.14-slim` container with the repo mounted).
- CI: `.github/workflows/ci.yml` (quality / test / docker-build). **CI's
  Postgres service is plain `postgres:16-alpine`** — a migration that runs
  `CREATE EXTENSION vector` would fail CI; add pgvector to the CI service if
  that ever happens.

## Frontend conventions

- No build step, no framework. Edit the files in `src/web/static/` directly.
- **Type and colour live in `:root` in `style.css`.** Instrument Serif sets
  headings, the shot clock and filled buttons; Hanken Grotesk does the rest.
  Both are **self-hosted** in `static/fonts/` and precached by `sw.js` — they
  have to be, because the CSP is `default-src 'self'` with no `font-src`, so
  Google Fonts is blocked outright.
- **The CSP also blocks inline styles**: no `<style>` blocks, and no `style=""`
  inside an `innerHTML` template. Dynamic values go through
  `element.style.setProperty()` (CSSOM, which is not blocked) or a data
  attribute the stylesheet reads.
- The look is warm and muted, never neon, and controls are printed rather than
  glossy — flat fills with a letterpress keyline, no gradients or white inner
  highlights. Chart series in `admin.css` are three separate hues, not three
  shades of clay, because muted earth tones alone fail colour-blind separation.
- **`sw.js` has `const CACHE = 'wcda-vN'` — bump N on every change to a static
  asset** so clients fetch the new bundle, and move the `?v=` on the CSS/JS
  tags in **every** page (`index.html` and `admin.html`) to match;
  `tests/test_web_app.py` asserts they agree, and that neither page carries
  an inline style. The service worker is network-first
  for the app shell (HTML/JS/CSS), cache-only as an offline fallback.
- Over plain HTTP on a bare IP the service worker does not register (not a
  secure context); Add-to-Home-Screen still works.

## Gotchas

- **FastAPI matches routes in definition order.** Declare literal paths before
  parameterised siblings — e.g. `PUT /api/setups/active` must come before
  `PUT /api/setups/{setup_id}` in `routes/gear.py`, or `"active"` is parsed
  as a setup id.
- **Every number comes from the engine.** Doses, grinds, yields and
  temperatures are decided in `core/` and returned as `recipe`; the browser
  only displays them, and Gemini's prose is checked against them
  (`ai/rationale.scrub_numerals`). Don't compute a recipe number in `app.js`.
- **The Gemini chain is bounded by a wall-clock budget, not by the API's
  mood.** `try_model_candidates` takes `budget_s` (4s for the rationale, 20s
  for bag OCR) and enforces it client-side in a worker thread, because the SDK
  cannot: `HttpOptions.timeout` also populates `X-Server-Timeout`, which the
  API rejects below 10s, and the SDK passes `timeout=None` on each request,
  overriding any `client_args` timeout. An over-budget attempt is *abandoned*,
  not cancelled — hence `shutdown(wait=False)`, since the executor's `__exit__`
  would join exactly the thread being abandoned.
- **Model availability must be checked by calling, not by `models.list`.**
  `gemini-2.5-flash-lite` was still listed while returning 404 "no longer
  available" on every call. A 404 or a 503 now *skips* to the next candidate;
  only a chain-wide fault (bad API key, permission denied) stops it.
- **The rationale's numeral allow-list covers the whole engine-authored
  prompt**, not just `recipe.numeric_tokens()`. The engine's notes and
  confidence label name past grind settings and shot counts, and the prompt
  invites the model to explain them — scoping the list to the recipe alone
  rejected good answers for quoting the engine back.
- `git commit` trailer: `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`.
