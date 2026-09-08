"""The admin dashboard: how much the friends instance is being used, and how.

Mounted only when this instance is configured to read another one -- see
``admin_db.admin_enabled()``. On the friends instance itself neither variable
is set, so these routes do not exist there and its attack surface is unchanged.
"""

from __future__ import annotations

import hmac
import logging
import os
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from . import admin_stats
from .admin_db import admin_token, get_admin_db

logger = logging.getLogger("wcda.admin")


def _require_token(x_admin_token: str | None = Header(default=None)) -> None:
    """Gate every data route on a shared token.

    The dev instance has no identity of its own and is published on the LAN, so
    this token is the only thing standing between other people's usage data and
    every device on the network. Compared in constant time.
    """
    expected = admin_token()
    if expected is None:  # pragma: no cover - guarded by admin_enabled()
        raise HTTPException(status_code=404, detail="Not found")
    if x_admin_token is None or not hmac.compare_digest(x_admin_token, expected):
        raise HTTPException(status_code=401, detail="Bad or missing admin token.")


def register_admin_routes(app: FastAPI, static_dir: str) -> None:
    @app.get("/admin", include_in_schema=False)
    def admin_page() -> FileResponse:
        # The shell carries no data; the token is asked for in the page and
        # only ever spent on /api/admin/stats.
        return FileResponse(os.path.join(static_dir, "admin.html"))

    @app.get("/api/admin/stats", dependencies=[Depends(_require_token)])
    def admin_dashboard(
        days: int = 90, db: Session = Depends(get_admin_db)
    ) -> dict[str, Any]:
        """Every number on the dashboard, for a window of ``days``."""
        if days not in (30, 90, 365, 3650):
            raise HTTPException(status_code=400, detail="Unsupported window.")
        return admin_stats.dashboard(db, days)

    logger.info("Admin dashboard mounted at /admin (reading a second database).")
