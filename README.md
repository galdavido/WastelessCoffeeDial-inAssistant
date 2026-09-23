# Wasteless Coffee Dial-in Assistant (WCDA)

An espresso (and pour-over, and moka) dial-in helper. Photograph a coffee bag,
and the app reads it with Gemini and gives you a starting recipe — grind, dose,
yield, temperature — worked out from your own logged shots on your own
grinder. Log how each shot ran and tasted, and the next recipe is corrected
from it.

Every number comes from a deterministic engine (`src/core/brewing.py`,
`calibration.py`, `engine.py`), grounded in [`docs/science.md`](docs/science.md).
The language model only reads the bag and writes the explanation, and a
numeric allow-list rejects any figure it tries to add.

FastAPI + SQLAlchemy + PostgreSQL, with a vanilla-JS PWA front end (no build
step).

## Two instances

| | Dev (daily driver) | Prod (friends) |
|---|---|---|
| Compose file | `compose.yaml` (project `wcda`) | `compose.prod.yaml` (project `wcda-prod`) |
| Web | `0.0.0.0:8082` — on the LAN | `127.0.0.1:8081` — behind `tailscale serve` |
| Identity | `WCDA_AUTH_MODE=single`: one implicit owner | `WCDA_AUTH_MODE=tailscale`: the `Tailscale-User-Login` header |
| Postgres | `127.0.0.1:5434` | internal only |

Both hold real data and both back themselves up nightly (`db-backup`). Tailscale
setup, inviting friends and moving data between identities are in
[`docs/tailscale-setup.md`](docs/tailscale-setup.md).

## Configuration

```bash
cp .env.example .env    # then set POSTGRES_PASSWORD and GEMINI_API_KEY
```

`.env` is git-ignored and excluded from the Docker build context.

| Variable | Purpose | Default |
|---|---|---|
| `DATABASE_URL` | SQLAlchemy/Alembic connection string (compose sets it) | — |
| `GEMINI_API_KEY` | Google Gemini key. Without it scans fail and explanations fall back to a template | — |
| `WCDA_AUTH_MODE` | `single` or `tailscale` (see above) | `single` |
| `WCDA_SINGLE_USER` | The owner every request maps to in `single` mode | `owner` |
| `WCDA_HOST` / `WEB_PORT` | Bind address and port when run directly | `127.0.0.1` / `8080` |
| `LOG_IMAGES_DIR` | Where bag photos are stored | `./data/log_images` |
| `WCDA_GEMINI_MODELS` | Comma-separated model fallback list | see `ai/model_selection.py` |
| `WCDA_GEMINI_THINKING` | `low`, `high` or `off` for Gemini 3.x | `low` |
| `WCDA_ADMIN_DATABASE_URL`, `WCDA_ADMIN_TOKEN` | Dev only: the `/admin` usage dashboard over the prod database | unset |

## Run it

```bash
docker compose up -d --build                                           # dev
docker compose -f compose.prod.yaml --env-file .env up -d --build      # prod
docker compose -f compose.yaml -f compose.admin.yaml up -d --build     # dev + /admin
```

Bring a stack up without naming a service: `up web` starts `web` and its
dependencies but not `db-backup`, and the nightly dump quietly stops.

Without Docker:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
export DATABASE_URL=postgresql+psycopg2://barista:pw@localhost:5434/barista_db
python -m core.web_server        # http://127.0.0.1:8080, migrates on startup
```

`wcda-backtest` (or `python -m core.backtest_cli` inside the container) measures
the engine against your logged shots; it is read-only.

## Database

PostgreSQL 16, schema managed by Alembic in `migrations/`. The app runs
`alembic upgrade head` on startup. Migrations are hand-written — do not
autogenerate them. Nightly dumps land in `backups/` (git-ignored); despite the
`.sql.gz` name they are plain SQL, so restore with a straight redirect into
`psql`.

## Tests and checks

```bash
pytest                            # needs DATABASE_URL for the API tests
ruff check . && ruff format --check .
mypy src
```

Most tests are pure and need nothing. `tests/test_api_flows.py` drives the
HTTP API against a real Postgres (Gemini stubbed): it skips locally when no
database is reachable, and fails in CI instead. CI runs all of it on pushes to
`main` and on pull requests: lint, format, mypy, migrations, tests and a
Docker build.

## Project layout

```text
src/
  ai/          vision.py (bag OCR), rationale.py (explanation), model_selection.py
  core/
    routes/    meta, recipe, coffees, gear -- the HTTP API
    engine.py  one recommendation: retrieve, calibrate, correct, guard, explain
    brewing.py, calibration.py, retrieval.py   the deterministic engine
    eval_harness.py, backtest_cli.py           measuring the engine
    auth.py, web_helpers.py, web_schemas.py, db_bootstrap.py, web_server.py
    admin_*.py the dev-only usage dashboard
  database/    models and engine
  web/static/  index.html, app.js, style.css, sw.js, admin.*
migrations/    Alembic
tests/         pytest; _sim.py is the physics simulator the engine tests use
docs/          science.md (every constant's source), tailscale-setup.md,
               open-decisions.md (what is waiting on the owner)
```

## Security model

- **Identity.** In `tailscale` mode the app trusts the `Tailscale-User-Login`
  header, which `tailscale serve` sets from the authenticated tailnet user.
  That is only safe while the app is reachable solely through Serve, so prod
  binds to loopback. `single` mode has no identity at all and belongs on a
  trusted network only.
- **Isolation.** Every coffee, shot, setup, recommendation and setting is
  scoped to its owner. Equipment is a shared catalogue: anyone can use an
  entry, but only whoever added it can change it, and the seeded entries are
  read-only.
- **Uploads** are limited to 8 MB of JPEG, PNG or WebP, and decoded locally
  before anything is sent to Gemini.
- **Browser.** A strict CSP (`default-src 'self'`) with no inline scripts or
  styles, and fonts self-hosted.
- **Secrets** live in `.env`, never in the image. Server errors are logged in
  full and returned to the client as generic messages.
