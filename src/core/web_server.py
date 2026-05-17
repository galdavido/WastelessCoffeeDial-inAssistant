import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from core.optional_deps import load_dotenv_if_available

from core.web_helpers import init_db, seed_db
from core.web_routes import register_routes

load_dotenv_if_available()

_static_dir = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "web", "static")
)


# Startup bootstrap: initialize DB and static assets once.
init_db()
seed_db()

app = FastAPI(title="WCDA Web")
app.mount("/static", StaticFiles(directory=_static_dir), name="static")
register_routes(app, _static_dir)


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("WEB_PORT", "8080"))
    uvicorn.run("core.web_server:app", host="0.0.0.0", port=port, reload=False)
