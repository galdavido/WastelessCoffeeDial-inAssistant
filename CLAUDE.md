# CLAUDE.md

Guidance for working in this repo.

## What this is

**Wasteless Coffee Dial-in Assistant** — a FastAPI + Google Gemini espresso
dial-in helper with a vanilla-JS PWA frontend. Scan a coffee bag, get a
grind/dose/temperature recipe informed by your own past logs (RAG over a
Postgres history).

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
- Identity headers are populated for tailnet users, **including external users
  who accepted a node share** — that is what lets friends in — but never for
  *tagged* devices, which is the usual cause of an unexpected 401.
  `GET /api/whoami` reports the resolved owner and mode, and touches no DB.
- Host-side Tailscale setup (Serve, the ACL that keeps shared friends off this
  box's other services, inviting people, claiming pre-multi-user rows):
  **`docs/tailscale-setup.md`**.
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
  Restore: `gunzip -c backups/db/last/<file>.sql.gz | docker compose -f
  compose.prod.yaml exec -T db psql -U barista -d barista_db`.
  **`docker compose up -d --build web` starts only `web` and its `depends_on`,
  never `db-backup`** — bring the stack up without naming a service, or the
  nightly dump quietly never runs.
- **Volume names follow the compose project name, so renaming a project
  orphans its data.** Adding `name: wcda` / `name: wcda-prod` in 2026-08 detached
  the original `wastelesscoffeedial-inassistant_postgres_data` (the real history,
  on PG **15**) and `..._log_images`; both stacks then came up on new, empty
  volumes and the data looked lost. Those volumes still exist as
  `dangling=true`, so **never run `docker volume prune` or `docker system prune
  --volumes` on this host.** Check `docker volume ls` for orphans before
  assuming a fresh start is safe, and note a PG 15 data dir cannot be opened by
  the PG 16 image — dump it with a `pgvector/pgvector:pg15` container first.

## Tests, lint, types

- `pytest` — config in `pyproject.toml`, `pythonpath = ["src"]`.
  `tests/test_web_app.py` are DB-free smoke tests (TestClient without the
  lifespan). The rest need a live Postgres + `DATABASE_URL` (see CI).
- `ruff check .` and `ruff format --check .`; `mypy src`.
- Dev install: `pip install -e '.[dev]'` (or run the checks in a throwaway
  `python:3.14-slim` container with the repo mounted).
- CI: `.github/workflows/ci.yml` (quality / test / docker-build). **CI's
  Postgres service is plain `postgres:16-alpine`** — a migration that runs
  `CREATE EXTENSION vector` would fail CI; add pgvector to the CI service if
  that ever happens.

## Frontend conventions

- No build step, no framework. Edit the files in `src/web/static/` directly.
- **`sw.js` has `const CACHE = 'wcda-vN'` — bump N on every change to a static
  asset** so clients fetch the new bundle. The service worker is network-first
  for the app shell (HTML/JS/CSS), cache-only as an offline fallback.
- Over plain HTTP on a bare IP the service worker does not register (not a
  secure context); Add-to-Home-Screen still works.

## Gotchas

- **FastAPI matches routes in definition order.** Declare literal paths before
  parameterised siblings — e.g. `PUT /api/setups/active` must come before
  `PUT /api/setups/{setup_id}`, or `"active"` is parsed as a setup id.
- `git commit` trailer: `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`.
