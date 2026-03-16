from database import engine, Base
# Important: we need to import the models so that SQLAlchemy 'sees' them before issuing the table generation command!
import models  # noqa: F401  # type: ignore[reportUnusedImport]

print("Database table creation in progress...")

# This command looks at the classes inheriting from Base (Bean, Equipment, DialInLog), and creates them in Postgres if they don't exist.
Base.metadata.create_all(bind=engine)

print("Successful initialization! The tables have been created in PostgreSQL.")
