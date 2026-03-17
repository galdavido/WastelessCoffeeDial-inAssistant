import sys
from pathlib import Path
from typing import List, cast

try:
    from .database import SessionLocal
    from .models import ScrapedEquipment
except ImportError:
    # Allow running as a script: `python src/database/view_db.py`
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from database.database import SessionLocal
    from database.models import ScrapedEquipment
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


def display_database_contents() -> None:
    """
    Connects to the pgvector database, retrieves all scraped equipment,
    and prints a clean, formatted preview of the data and its vectors.
    """
    print("\n🗄️ Connecting to the Vector Database...\n" + "=" * 60)

    db = SessionLocal()
    try:
        # Strictly type the expected return as a List of our SQLAlchemy model
        records: List[ScrapedEquipment] = db.query(ScrapedEquipment).all()

        if not records:
            print("📭 The database is currently empty.")
            return

        total_records: int = len(records)
        print(f"📦 Found {total_records} equipment entries in the database:\n")

        for index, item in enumerate(records, start=1):
            # Explicitly cast text fields to strings to satisfy Pylance
            brand: str = str(item.brand or "Unknown Brand")
            model: str = str(item.model or "Unknown Model")
            eq_type: str = str(item.equipment_type or "Unknown Type")

            # The embedding is returned as a list or NumPy array of floats.
            # We use Any here before verifying its structure dynamically.
            raw_embedding = cast(List[float], item.embedding)  # type: ignore

            # Safely format a preview of the vector (just the first 3 dimensions)
            if len(raw_embedding) >= 3:
                # Format floats to 4 decimal places for readability
                dim_1: float = float(raw_embedding[0])
                dim_2: float = float(raw_embedding[1])
                dim_3: float = float(raw_embedding[2])
                vector_preview: str = (
                    f"[{dim_1:.4f}, {dim_2:.4f}, {dim_3:.4f}, ... (768 dimensions)]"
                )
            else:
                vector_preview = "❌ No valid vector data found"

            # Print the formatted output
            print(f"{index}. {brand} {model} ({eq_type})")
            print(f"   ↳ Vector: {vector_preview}")

    except Exception as e:
        print(f"❌ Database connection or query error: {str(e)}")
    finally:
        db.close()
        print("=" * 60 + "\n✅ Database connection closed.")


if __name__ == "__main__":
    display_database_contents()
