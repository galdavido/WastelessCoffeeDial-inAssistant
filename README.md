# Barista AI

Web-based coffee dial-in assistant powered by FastAPI + Gemini. Upload or scan coffee bag photos, get grind recommendations, and track bean logs with setup-aware equipment management.

## What This Project Includes

- Web server and UI (mobile + desktop templates)
- AI image analysis and recommendation pipeline
- PostgreSQL-backed bean logs and settings
- Equipment library + setup management (active setup aware)

## What Was Removed

This repository no longer includes:

- Discord bot runtime
- Web scraping pipeline for equipment ingestion
- Vector-search utility for scraped equipment

## Project Structure

```text
src/
  ai/
    rag.py
    vision.py
    model_selection.py
  core/
    web_server.py
    web_routes.py
    web_helpers.py
    web_schemas.py
    main.py
  database/
    database.py
    models.py
    init_db.py
    seed.py
  web/
    static/
      index.html
      desktop.html
      app.js
      style.css
```

## Environment

Create `.env` in project root:

```env
POSTGRES_USER=barista
POSTGRES_PASSWORD=supersecret
POSTGRES_DB=barista_db
DATABASE_URL=postgresql://barista:supersecret@localhost:5434/barista_db
GEMINI_API_KEY=your_gemini_api_key_here
```

Inside the dev container / compose network, use:

```env
DATABASE_URL=postgresql://barista:supersecret@db:5432/barista_db
```

## Run with Docker Compose

```bash
docker-compose up --build -d
```

Services:

- `db` on `5434`
- `wcda-web` on `8081`

## Run Locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH=src:$PYTHONPATH
python -m core.web_server
```

App URL: `http://localhost:8080` (or `http://localhost:8081` when running via compose port mapping).

When working inside a VS Code dev container, open the forwarded `8081` port in the host browser from the **Ports** panel.

## Tests

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

## Notes

- The web app uses active setup selection to decide which grinder/machine are attached to new logs.
- Equipment CRUD is managed through the equipment library UI.
- Setup CRUD links existing equipment only.
