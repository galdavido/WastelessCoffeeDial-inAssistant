"""A second, read-only engine: the friends database, seen from the dev instance.

Only the admin dashboard uses this. It is deliberately kept apart from
``database.database.engine`` -- Alembic, ``get_db`` and every ordinary route
stay bound to *this* instance's own database, so nothing but the dashboard can
reach across the stacks.

The connection is expected to use a Postgres role that has ``SELECT`` and
nothing else (``scripts/create_readonly_role.sql``). The separation here is
organisational; the role is what actually makes it read-only.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger("wcda.admin")

_engine: Engine | None = None
_factory: sessionmaker[Session] | None = None


def admin_database_url() -> str | None:
    """The friends database, or ``None`` when this instance has no admin view."""
    return (os.getenv("WCDA_ADMIN_DATABASE_URL") or "").strip() or None


def admin_token() -> str | None:
    return (os.getenv("WCDA_ADMIN_TOKEN") or "").strip() or None


def admin_enabled() -> bool:
    """Whether the dashboard should be mounted at all.

    Both halves are required. The dev instance runs ``WCDA_AUTH_MODE=single``
    and is published on the LAN with no identity of any kind, so a dashboard of
    other people's usage with no token in front of it would be readable by
    every device on the network. Missing token means the routes simply do not
    exist -- failing closed rather than open.
    """
    return admin_database_url() is not None and admin_token() is not None


def warn_if_half_configured() -> None:
    if admin_database_url() is not None and admin_token() is None:
        logger.warning(
            "WCDA_ADMIN_DATABASE_URL is set but WCDA_ADMIN_TOKEN is empty: the "
            "admin dashboard stays unmounted. Set a token to enable it."
        )


def _session_factory() -> sessionmaker[Session]:
    global _engine, _factory
    if _factory is None:
        url = admin_database_url()
        if url is None:  # pragma: no cover - guarded by admin_enabled()
            raise RuntimeError("WCDA_ADMIN_DATABASE_URL is not set")
        # A small pool: the dashboard is one person hitting refresh, and the
        # connections are crossing into another stack's database.
        _engine = create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=2)
        _factory = sessionmaker(
            autocommit=False, autoflush=False, bind=_engine, class_=Session
        )
    return _factory


def get_admin_db() -> Iterator[Session]:
    """FastAPI dependency: a session on the friends database."""
    db = _session_factory()()
    try:
        yield db
    finally:
        db.close()
