"""FastAPI dependency that hands out a scoped SQLAlchemy session."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy.orm import Session

from database.database import SessionLocal


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
