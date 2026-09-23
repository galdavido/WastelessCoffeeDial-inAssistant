"""The app shell, and the routes that answer "what is running, and for whom?"."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from ..auth import auth_mode, get_owner
from ..engine import ENGINE_VERSION
from ..web_helpers import read_asset_version
from .common import STATIC_DIR

router = APIRouter()

# Parsed once at startup: the prod container is read-only, so the file cannot
# change under a running process, and this keeps it off the request path.
_ASSET_VERSION = read_asset_version(str(STATIC_DIR))


@router.get("/", include_in_schema=False)
def root() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@router.get("/healthz", include_in_schema=False)
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/sw.js", include_in_schema=False)
def service_worker() -> FileResponse:
    return FileResponse(
        STATIC_DIR / "sw.js",
        media_type="application/javascript",
        headers={
            "Service-Worker-Allowed": "/",
            "Cache-Control": "no-cache, no-store, must-revalidate",
        },
    )


@router.get("/api/version")
def get_version() -> dict[str, Any]:
    """What the server is currently serving.

    The client compares this against the version its own bundle was loaded
    with, so the user can tell whether a deploy actually reached their phone
    or they are looking at a cached one.
    """
    return {"asset_version": _ASSET_VERSION, "engine_version": ENGINE_VERSION}


@router.get("/api/whoami")
def whoami(owner: str = Depends(get_owner)) -> dict[str, str]:
    """Who the server thinks you are, and how it decided.

    Deliberately the one user-scoped route that touches no database: when a
    friend reports "it says I'm not signed in", this separates a Tailscale
    identity problem (401 here) from an app problem (200 here, trouble
    elsewhere) in a single request.
    """
    return {"owner": owner, "auth_mode": auth_mode()}
