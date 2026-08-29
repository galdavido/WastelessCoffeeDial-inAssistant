# Wasteless Coffee Dial-in Assistant (WCDA)

Web app that turns a photo of a coffee bag into an espresso starting recipe.
Upload or scan a bag, Gemini extracts the roast details, and a small
retrieval step over your own dial-in logs produces a grind recommendation.
Built with FastAPI + SQLAlchemy + PostgreSQL, with a vanilla-JS PWA front end.

## Features

- Coffee-bag image analysis and recipe recommendation
- PostgreSQL-backed bean logs, equipment library and brew setups
- Active-setup awareness (which grinder/machine a new log is attached to)
- Installable PWA, responsive from phone to desktop

## Requirements

- Python 3.12+ (CI runs 3.14)
- PostgreSQL 16 (a `docker compose` service is provided)
- A Google Gemini API key

## Configuration

```bash
cp .env.example .env
# then edit .env - set a strong POSTGRES_PASSWORD and your GEMINI_API_KEY
```

`.env` is git-ignored and excluded from the Docker build context. Key variables:

| Variable         | Purpose                                             | Default        |
| ---------------- | -------------------------------------------------- | -------------- |
| `DATABASE_URL`   | SQLAlchemy/Alembic connection string               | -              |
| `GEMINI_API_KEY` | Google Gemini key                                  | -              |
| `WCDA_HOST`      | Interface to bind when run directly                | `127.0.0.1`    |
| `WEB_PORT`       | Listen port                                        | `8080`         |
| `LOG_IMAGES_DIR` | Where uploaded bag photos are stored               | `./data/log_images` |

## Run with Docker Compose

```bash
docker compose up --build          # local dev  -> http://127.0.0.1:8081
docker compose -f compose.prod.yaml up -d --build   # hardened production stack
```

Both stacks bind Postgres and the web app to `127.0.0.1` only. Put a reverse
proxy (TLS, and auth if you need it) in front for anything internet-facing.

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'

# start Postgres however you like, then point DATABASE_URL at it, e.g.
export DATABASE_URL=postgresql+psycopg2://barista:pw@localhost:5434/barista_db

alembic upgrade head       # apply migrations
python -m core.web_server  # http://127.0.0.1:8080
```

The CLI (`wcda path/to/bag.jpg`) runs a single analysis in the terminal.

## Database migrations

Schema is managed with Alembic (`migrations/`). The app also runs
`alembic upgrade head` automatically on startup; a database created by an
older build is detected and stamped rather than recreated.

```bash
alembic revision --autogenerate -m "describe change"
alembic upgrade head
```

## Tests & checks

```bash
pytest                 # unit + smoke tests (DB tests need a live Postgres)
ruff check . && ruff format --check .
mypy src
pip-audit
```

## Project layout

```text
src/
  ai/          vision (Gemini), rag (recommendation), model_selection
  core/        web_server, web_routes, web_helpers, web_schemas, db_session,
               db_bootstrap, main (CLI)
  database/    database (engine/session), models
  web/static/  index.html, app.js, style.css, sw.js, manifest.json
migrations/    Alembic environment + versions
```
