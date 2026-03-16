from .database import SessionLocal
from .models import Equipment, Bean, DialInLog

def seed_data():
    # Open a session to the database
    db = SessionLocal()

    try:
        print("Data loading starting...")

        # 1. ADD EQUIPMENT
        machine = Equipment(type="espresso_machine", brand="AVX", model="Hero Plus 2024")
        grinder = Equipment(type="grinder", brand="Kingrinder", model="K6")
        
        db.add(machine)
        db.add(grinder)
        db.commit() # Save so they get IDs
        
        # Refresh the objects so we can use their IDs
        db.refresh(machine)
        db.refresh(grinder)

        # 2. ADD COFFEES (Some examples from your notes)
        bean_nensebo = Bean(name="Nensebo", origin="Ethiopia", process="Washed", roast_level="Medium-Light")
        bean_santos = Bean(name="Brasil Santos", origin="Brazil", process="Natural", roast_level="Medium")
        bean_daisuke = Bean(name="Daisuke Ronaldinho", origin="Brazil", process="Natural", roast_level="Medium")
        
        db.add_all([bean_nensebo, bean_santos, bean_daisuke])
        db.commit()

        # 3. ADD SHOT LOGS (Dial-in results)
        # I translated the 3 checkmarks (✅✅✅) to a 5 (perfect) rating!
        
        log1 = DialInLog(
            bean_id=bean_nensebo.id,
            grinder_id=grinder.id,
            machine_id=machine.id,
            grind_setting="36", # 36 clicks on K6
            dose_g=16.0,
            rating=5,
            tasting_notes="Perfect, 3 checkmarks based on notes."
        )

        log2 = DialInLog(
            bean_id=bean_santos.id,
            grinder_id=grinder.id,
            machine_id=machine.id,
            grind_setting="39",
            dose_g=16.0,
            rating=5,
            tasting_notes="Perfect, 3 checkmarks based on notes."
        )
        
        log3 = DialInLog(
            bean_id=bean_daisuke.id,
            grinder_id=grinder.id,
            machine_id=machine.id,
            grind_setting="39",
            dose_g=16.0,
            rating=5,
            tasting_notes="Perfect, 3 checkmarks based on notes."
        )

        db.add_all([log1, log2, log3])
        db.commit()

        print("Success! The equipment, coffees and settings have been added to the database.")

    except Exception as e:
        print(f"Error occurred: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    seed_data()
