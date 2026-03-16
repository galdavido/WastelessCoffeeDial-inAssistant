import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

# Load the variables from the .env file
load_dotenv()

# Get the connection URL from environment variables
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL")
if SQLALCHEMY_DATABASE_URL is None:
    raise RuntimeError("DATABASE_URL is not set")

# Create the engine (this is the engine that physically communicates with Postgres)
engine = create_engine(SQLALCHEMY_DATABASE_URL)

# Create a Session class with which we can write/read data
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# This is the base class from which our tables (Beans, Equipment) will inherit
Base = declarative_base()
