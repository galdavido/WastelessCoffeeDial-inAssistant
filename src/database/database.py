from __future__ import annotations

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

# The one place .env is loaded. Everything that reads configuration imports
# this module first (it is what needs DATABASE_URL), so this runs before any
# of it is read.
load_dotenv()

SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL")
if SQLALCHEMY_DATABASE_URL is None:
    raise RuntimeError("DATABASE_URL is not set")

# pool_pre_ping recycles connections dropped by the DB / a restart between requests.
engine = create_engine(SQLALCHEMY_DATABASE_URL, pool_pre_ping=True)

SessionLocal: sessionmaker[Session] = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    class_=Session,
)

Base = declarative_base()
