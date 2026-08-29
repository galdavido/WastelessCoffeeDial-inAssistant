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

- **Dev:** `docker compose up --build` (compose.yaml, project `wcda`). Web on
  `http://127.0.0.1:8081`, Postgres on `127.0.0.1:5434`.
- **Prod:** `docker compose -f compose.prod.yaml --env-file .env up -d --build`
  (compose.prod.yaml, project `wcda-prod`). Web published on all interfaces at
  port `8081` → reachable at `http://192.168.50.202:8081`. DB is internal-only.
  The web container is `read_only` with `cap_drop: ALL`.
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
- Daily dumps land in `./backups/db/` via the `db-backup` compose service
  (`backups/` is gitignored). Restore: `gunzip -c backups/db/<file>.sql.gz |
  docker compose -f compose.prod.yaml exec -T db psql -U barista -d barista_db`.

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
