from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from core.db_bootstrap import run_migrations, seed_baseline_equipment
from core.optional_deps import load_dotenv_if_available
from core.web_routes import register_routes

load_dotenv_if_available()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("wcda")

_STATIC_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "web", "static")
)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    run_migrations()
    seed_baseline_equipment()
    logger.info("Startup complete.")
    yield


_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(self), microphone=(), geolocation=()",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; object-src 'none'; "
        "base-uri 'self'; frame-ancestors 'none'"
    ),
}


# Paths whose responses must be revalidated on every load. Without this the
# browser applies heuristic caching to /static/*, which can hand the service
# worker a stale app.js while style.css is fresh - a torn cache that renders
# the app incorrectly. "no-cache" still stores the file; the ETag makes the
# revalidation a cheap 304.
_REVALIDATE_PATHS = ("/", "/mobile", "/desktop")


def _must_revalidate(path: str) -> bool:
    return path in _REVALIDATE_PATHS or path.startswith("/static/")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        for header, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        if _must_revalidate(request.url.path):
            response.headers["Cache-Control"] = "no-cache"
        return response


app = FastAPI(title="Wasteless Coffee Dial-in Assistant", lifespan=lifespan)
app.add_middleware(SecurityHeadersMiddleware)
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
register_routes(app, _STATIC_DIR)


def main() -> None:
    import uvicorn

    host = os.getenv("WCDA_HOST", "127.0.0.1")
    port = int(os.getenv("WEB_PORT", "8080"))
    logger.info("Serving on http://%s:%d", host, port)
    uvicorn.run("core.web_server:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
