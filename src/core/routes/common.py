"""What every router shares: paths, the per-request setup, error handling."""

from __future__ import annotations

import logging
import os
import tempfile
from functools import cache
from pathlib import Path

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from database.models import BrewSetup

from ..auth import get_owner
from ..db_session import get_db
from ..web_helpers import get_active_setup

logger = logging.getLogger("wcda.routes")

STATIC_DIR = Path(__file__).resolve().parents[2] / "web" / "static"


@cache
def uploads_dir() -> Path | None:
    """Where bag photos are kept, or None when nowhere is writable.

    Resolved once, on first use: LOG_IMAGES_DIR if set, else data/log_images
    in the repo, else a temp directory. The prod container is read-only apart
    from its mounted volume, so this has to cope with a path it cannot create.
    """
    configured = os.getenv("LOG_IMAGES_DIR")
    default = Path(__file__).resolve().parents[3] / "data" / "log_images"
    fallback = Path(tempfile.gettempdir()) / "wcda_log_images"
    for candidate in (Path(configured) if configured else default, fallback):
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except OSError:
            continue
    return None


def active_setup(
    db: Session = Depends(get_db), owner: str = Depends(get_owner)
) -> BrewSetup:
    """The request's active setup, looked up once however many things need it."""
    return get_active_setup(db, owner)


def server_error(exc: Exception, action: str) -> HTTPException:
    """Log the real error server-side, return a generic message to the client."""
    logger.exception("Error while %s: %s", action, exc)
    return HTTPException(status_code=500, detail=f"Could not {action}.")
