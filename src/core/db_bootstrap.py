"""Database bootstrap: run Alembic migrations and seed baseline data.

Called once at application startup (see ``core.web_server`` lifespan). Kept
separate from request handling so it can also be invoked from scripts.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from database.database import SessionLocal, engine
from database.models import Equipment

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ALEMBIC_INI = _REPO_ROOT / "alembic.ini"
_MIGRATIONS_DIR = _REPO_ROOT / "migrations"


def _alembic_config() -> Config:
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    return cfg


def run_migrations(retries: int = 10, delay_seconds: float = 2.0) -> None:
    """Bring the database schema up to ``head``.

    Retries while the database is still starting up. Databases created by the
    pre-Alembic ``create_all`` bootstrap are reconciled by stamping the initial
    revision instead of re-creating tables.
    """

    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            with engine.connect() as conn:
                inspector = inspect(conn)
                has_alembic = inspector.has_table("alembic_version")
                has_legacy_schema = inspector.has_table("beans")

                if not has_alembic and has_legacy_schema:
                    logger.warning(
                        "Pre-Alembic schema detected; reconciling before stamping."
                    )
                    conn.execute(
                        text(
                            "ALTER TABLE dial_in_logs "
                            "ADD COLUMN IF NOT EXISTS image_path TEXT"
                        )
                    )
                    conn.commit()

            cfg = _alembic_config()
            if not has_alembic and has_legacy_schema:
                command.stamp(cfg, "head")
            else:
                command.upgrade(cfg, "head")

            logger.info("Database schema is up to date.")
            return
        except Exception as exc:  # noqa: BLE001 - DB may not be ready yet
            last_exc = exc
            logger.warning("Migration attempt %d/%d failed: %s", attempt, retries, exc)
            if attempt < retries:
                time.sleep(delay_seconds)

    raise RuntimeError(
        f"Database migrations failed after {retries} attempts"
    ) from last_exc


def seed_baseline_equipment() -> None:
    """Insert a default grinder + espresso machine on a first run only."""

    db = SessionLocal()
    try:
        if db.query(Equipment).first() is not None:
            return
        db.add_all(
            [
                Equipment(type="espresso_machine", brand="AVX", model="Hero Plus 2024"),
                Equipment(type="grinder", brand="Kingrinder", model="K6"),
            ]
        )
        db.commit()
        logger.info("Seeded baseline equipment.")
    except Exception:
        db.rollback()
        logger.exception("Failed to seed baseline equipment.")
    finally:
        db.close()
