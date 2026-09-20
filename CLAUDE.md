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

- `src/core/` — FastAPI app (`web_server.py` entry, `web_routes.py` routes,
  `web_helpers.py`, `web_schemas.py`), DB bootstrap/session.
- `src/ai/` — Gemini calls (`vision.py` bag OCR, `rag.py` recommendation).
- `src/database/` — SQLAlchemy 2.0 models + engine.
- `src/web/static/` — the PWA: `index.html`, `app.js`, `style.css`, `sw.js`.
- `migrations/` — Alembic. `tests/` — pytest.
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
- **Public (native clients):** `docker compose -f compose.public.yaml
  --env-file .env.public up -d --build` (compose.public.yaml, project
  `wcda-public`).
  `WCDA_AUTH_MODE=apple`: identity comes from a session token this server
  issues after verifying a Sign in with Apple identity token, so it rests on
  a signature rather than on the network boundary. Bound to
  `127.0.0.1:8083`, fronted by Caddy on the host for TLS. **It refuses to
  start without `WCDA_SESSION_SECRET` and `WCDA_APPLE_BUNDLE_ID`** — either
  one missing means forged sessions would be accepted. Owners look like
  `apple:<sub>`; the prefix keeps the identity source visible and makes a
  collision with a Tailscale login impossible. Full setup:
  **`docs/public-deploy.md`**.
- `GET /api/version` reports `auth_mode` unauthenticated, which is how a
  client knows whether to show a sign-in button before making a call that
  would come back 401.
- `DELETE /api/account` erases everything an owner has, including their bag
  photos on disk. Refused in `single` mode, where "the account" is the whole
  instance.
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

- **PostgreSQL with the `vector` extension** — the schema has
  `scraped_equipment.embedding vector(768)`. The compose DB image is
  `pgvector/pgvector:pg16`; **plain `postgres:*` will not work.**
- SQLAlchemy 2.0 + Alembic. `run_migrations()` runs on startup (lifespan):
  `alembic upgrade head`, or stamps the initial revision if a pre-Alembic
  schema is detected.
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

- `pytest` — config in `pyproject.toml`, `pythonpath = ["src"]`.
  `tests/test_web_app.py` are DB-free smoke tests (TestClient without the
  lifespan). The rest need a live Postgres + `DATABASE_URL` (see CI).
- `ruff check .` and `ruff format --check .`; `mypy src`.
- Dev install: `pip install -e '.[dev]'` (or run the checks in a throwaway
  `python:3.14-slim` container with the repo mounted).
- **The agent container's default `python3` is 3.11, which cannot even parse
  this code** — `model_selection.py` uses PEP 695 generics (`def f[T](...)`),
  which need 3.12+. `python3.13` *is* installed, so the whole suite runs
  locally with `uv venv --python 3.13 .venv && uv pip install -e '.[dev]'`.
  Do that rather than concluding the tests cannot run here.
- CI: `.github/workflows/ci.yml` (quality / test / docker-build). **CI's
  Postgres service is plain `postgres:16-alpine`** — a migration that runs
  `CREATE EXTENSION vector` would fail CI; add pgvector to the CI service if
  that ever happens.

## AI cost and quotas

The Gemini key is one shared credential with a daily ceiling, so every
billable call is counted per owner per calendar month (`src/core/quota.py`,
`ai_usage` table). Before this existed nothing counted what the app spent,
and a single enthusiastic user could exhaust the key for everyone.

- **The two call kinds fail differently, deliberately.** A bag scan
  (`vision`) has no non-AI fallback, so over quota `/api/analyze` returns
  **429**. The prose around a recipe (`rationale`) has a deterministic
  template, so over quota it **degrades silently** — and the numbers are
  identical either way, because the engine fixes every one of them and
  `scrub_numerals` rejects any figure the model invents. A free-tier user
  loses the phrasing, not the recipe.
- **Vision is consumed before the call, and committed on its own.** Charging
  only for successes would make an image that always fails an unlimited
  supply of Gemini calls; leaving the counter in the request transaction
  would let a later error roll it back. Both are the same hole.
- **`single` mode is never metered.** That instance is the owner's own
  machine using the owner's own key.
- `core.prose.rationale_for` is the only path to the prose model. It answers
  three questions in order: already written (`rationale_cache`, keyed on a
  hash of the *prompt*), allowed, then what the model says. Never call
  `write_rationale` directly from a request path.
- Entitlement is an env allowlist (`WCDA_ENTITLED_OWNERS`) — the seam a real
  subscription lookup replaces. **Shipping this to the friends instance drops
  everyone not listed to the free tier.**

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
  `tests/test_web_app.py` asserts they agree. The service worker is network-first
  for the app shell (HTML/JS/CSS), cache-only as an offline fallback.
- Over plain HTTP on a bare IP the service worker does not register (not a
  secure context); Add-to-Home-Screen still works.

## Gotchas

- **FastAPI matches routes in definition order.** Declare literal paths before
  parameterised siblings — e.g. `PUT /api/setups/active` must come before
  `PUT /api/setups/{setup_id}`, or `"active"` is parsed as a setup id.
- `git commit` trailer: `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`.
