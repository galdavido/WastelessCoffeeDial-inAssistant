from database import engine, Base
# Fontos: be kell importálnunk a modelleket, hogy az SQLAlchemy "lássa" őket, 
# mielőtt kiadja a táblageneráló parancsot!
import models  # noqa: F401  # type: ignore[reportUnusedImport]

print("Adatbázis táblák létrehozása folyamatban...")

# Ez a parancs nézi meg a Base-ből öröklődő osztályokat (Bean, Equipment, DialInLog),
# és létrehozza őket a Postgresben, ha még nem léteznek.
Base.metadata.create_all(bind=engine)

print("Sikeres inicializálás! A táblák létrejöttek a PostgreSQL-ben.")
