import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

# Betöltjük a .env fájlban lévő változókat
load_dotenv()

# Lekérjük a kapcsolati URL-t a környezeti változókból
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL")
if SQLALCHEMY_DATABASE_URL is None:
    raise RuntimeError("DATABASE_URL is not set")

# Létrehozzuk az engine-t (ez a motor, ami fizikailag kommunikál a Postgres-szel)
engine = create_engine(SQLALCHEMY_DATABASE_URL)

# Létrehozunk egy Session osztályt, amivel majd adatokat tudunk írni/olvasni
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Ez az az alaposztály, amiből majd a mi tábláink (Beans, Equipment) öröklődnek
Base = declarative_base()
