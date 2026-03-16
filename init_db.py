from database import engine, Base
from sqlalchemy import text  # This is needed to run raw SQL commands
import models  # pyright: ignore[reportUnusedImport] # noqa: F401  # Import to register models 

print("Checking extensions and creating database tables in progress...")

# 1. Enable the pgvector extension in the database
with engine.connect() as conn:
    conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
    conn.commit()
    print("✅ pgvector extension activated!")

# 2. Create tables based on the models (now it knows the Vector type too)
Base.metadata.create_all(bind=engine)

print("🎉 Successful initialization! All tables created in PostgreSQL.")
